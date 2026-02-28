# Phase 2-6 実装状況: 詳細分析と改善提案

**分析日**: 2025-11-09
**対象**: `patchpilot/fl/repograph_utils.py` と `patchpilot/fl/localize.py`

---

## 1. 重大な問題

### 問題 1: Logger統合が不完全（HIGH PRIORITY）

**所在**: `patchpilot/fl/repograph_utils.py` の `retrieve_graph()` 関数

```python
# 251行目
print(f"Retrieving graph for {i}/{len(tags)}")  # ← logger を使用していない

# 271行目
print(f"[DEBUG retrieve_graph] Retrieved {len(one_hop_tags)} one-hop tags for: {search_term}")  # ← logger を使用していない
```

**影響**:
- これらのメッセージは stdout に出力されるため、ログファイルには保存されない
- 本来ログに記録されるべきデバッグ情報が失われる
- ユーザーが `evaluate_phase2_6_complete.py` を実行しても、これらのメッセージを抽出できない

**なぜ起きたのか**:
- logger統合を行う際に、この2つのprint文を修正し忘れた
- 他のlogger呼び出し（94-98行、203-204行など）は正しく修正されているが、この2つだけ残された

**修正方法**:
```python
# 251行目を修正
if logger:
    logger.debug(f"[DEBUG retrieve_graph] Processing tag {i}/{len(tags)}")

# 271行目を修正
if logger:
    logger.info(f"[DEBUG retrieve_graph] Retrieved {len(one_hop_tags)} one-hop tags for: {search_term}")
```

**優先度**: ★★★ (HIGH) - これを修正しないと、今後のデバッグログ抽出が正確でない

---

### 問題 2: Token計算ロジックの不確実性（MEDIUM PRIORITY）

**所在**: `patchpilot/fl/repograph_utils.py` の 219行目

```python
tag_tokens = len(str(tag.get('text', []))) // 4 if tag.get('text') else 100
```

**問題点**:

1. **文字列長 → トークン数の変換が一貫していない**
   - ここでは `len(str(...)) // 4` で計算
   - `construct_code_graph_context()` の 393行目では `len(section) // 4` で計算
   - どちらが正確かが不明確

2. **デフォルト値100トークンが妥当かどうか不明**
   - テキストがない場合のデフォルト: 100トークン
   - しかし実際のタグは数十行ある可能性が高い
   - 過小評価の可能性

3. **テキストのエンコーディングが考慮されていない**
   - 日本語や特殊文字があるとバイト数が増える
   - `len()` は文字数を返すが、トークン数とは異なる

**確認すべき点**:
```python
# 実際のタグ内容を確認してから計算式を決める必要がある
# 例：
tag_text = tag.get('text', [])
if isinstance(tag_text, list):
    text_str = "\n".join(tag_text)
else:
    text_str = str(tag_text)

# 実際のトークン数をエンコーディングを考慮して計算
estimated_tokens = len(text_str.encode('utf-8')) // 4  # UTF-8バイト数 / 4
```

**影響**:
- Token予算の計算が不正確
- 実際には予算超過や不足が発生している可能性
- 評価スクリプトで抽出したトークン数と実装の計算が一致していない可能性

**優先度**: ★★ (MEDIUM) - 正確なToken管理には重要だが、大きく外れている訳ではない

---

### 問題 3: Token予算チェックの時点が遅い（MEDIUM PRIORITY）

**所在**: `patchpilot/fl/repograph_utils.py` の 332-336行目

```python
# Check if we still have budget
if remaining_budget < 1000:  # Minimum threshold: 1000 tokens
    items_skipped += sections_remaining
    if logger:
        logger.info(f"[INFO construct_code_graph_context] Token budget exhausted...")
    break
```

**問題点**:

1. **セクション処理の前にチェックしている**
   - `max_tokens_this_section` を計算した後にチェックしているため
   - すでに処理に入ってしまっている可能性がある

2. **1000トークンの閾値が恣意的**
   - なぜ1000か理由が不明確
   - 予算のパーセンテージベースの方が合理的

3. **チェック後も処理が続く**
   - `break` で抜けるが、`code_graph_context` にデータが残っている可能性
   - セクション追加前のリセットが396行目なので、このセクションが処理される可能性

**改善案**:
```python
# より早い段階でチェック
if section_idx > 0 and remaining_budget < total_token_budget * 0.05:  # 5%未満なら終了
    items_skipped += sections_remaining
    logger.info(f"Budget below 5% threshold, stopping early")
    break

# または、セクション処理後に予算超過のセクションは追加しない（現在の実装で OK）
```

**優先度**: ★★ (MEDIUM) - 現在の実装でも機能しているが、より効率的にできる

---

## 2. より良くできる部分

### 改善 1: Greedy Allocation の可視化（ENHANCEMENT）

**現在の実装**:
- Greedy 計算は行われているが、各セクションでの決定プロセスが不透明
- ログには出力されているが、分析が難しい

**改善案**:
```python
# construct_code_graph_context() の早い段階で
if logger:
    logger.info(f"[GREEDY ALLOCATION PLAN]")
    logger.info(f"  Total sections: {total_sections}")
    logger.info(f"  Total budget: {total_token_budget:,} tokens")
    logger.info(f"  Average per section: {total_token_budget / total_sections:.0f} tokens")
    logger.info(f"  Minimum threshold: 1000 tokens")
```

**効果**:
- デバッグが簡単になる
- `evaluate_phase2_6_complete.py` などで計画と実績を比較できる

---

### 改善 2: Tag 削除ロジックの最適化（ENHANCEMENT）

**現在の実装**:
```python
# Phase 2-6: Token-aware tag limiting
if max_tokens_for_section is not None:
    ref_tags_limited = []
    tokens_used = 0

    for tag in ref_tags_sorted:  # ← Composite score でソート済み
        tag_tokens = len(str(tag.get('text', []))) // 4
        if tokens_used + tag_tokens > max_tokens_for_section:
            break  # ← ここで削除開始

        ref_tags_limited.append(tag)
        tokens_used += tag_tokens

        if len(ref_tags_limited) >= max_tags:
            break
```

**問題点**:
- Composite score でソートしているが、削除される（後ろの）タグが重要な可能性
- トークン予算が小さいセクション（後ろのセクション）では、重要なタグが削除されやすい

**改善案 1: 二段階削除**
```python
# 第1段階: タグの「重要度」を計算
def calculate_tag_importance(tag, search_term, code_graph):
    """タグの重要度スコアを計算"""
    in_degree = code_graph.in_degree(tag['name']) if tag['name'] in code_graph else 0
    file_distance = 1.0 if tag.get('rel_fname') == target_file else 0.5
    # 重要度 = 頻度 × ファイル距離
    return in_degree * file_distance

# 第2段階: 重要度でフィルタリング（Composite score の後に）
if max_tokens_for_section is not None:
    # 重要度でスコアを付け直す
    ref_tags_scored = [(tag, calculate_tag_importance(tag, search_term, code_graph))
                       for tag in ref_tags_sorted]
    ref_tags_scored.sort(key=lambda x: x[1], reverse=True)

    # トークン予算に基づいてフィルタリング
    ref_tags_limited = []
    for tag, importance in ref_tags_scored:
        # 重要度の高いタグを優先的に保持
        ...
```

**改善案 2: 段階的削除（より実装しやすい）**
```python
# 最初は max_tags で制限
ref_tags_limited = ref_tags_sorted[:max_tags]

# その上で、トークン予算がある場合は削除
if max_tokens_for_section is not None:
    total_tokens = sum(len(str(tag.get('text', []))) // 4 for tag in ref_tags_limited)
    if total_tokens > max_tokens_for_section:
        # 逆順で削除（重要度低い順に）
        while total_tokens > max_tokens_for_section and len(ref_tags_limited) > 1:
            removed_tag = ref_tags_limited.pop()
            total_tokens -= len(str(removed_tag.get('text', []))) // 4
```

**優先度**: ★ (LOW to MEDIUM) - 現在の実装でも動作しているが、性能改善の余地あり

---

### 改善 3: Logger レベルの一貫性（ENHANCEMENT）

**現在の実装**:
- `logger.info()` と `logger.debug()` が混在している
- どの情報が「重要」でどの情報が「デバッグ用」かが不明確

**改善案**:
```python
# DEBUG: 詳細な計算過程
logger.debug(f"[DEBUG retrieve_graph] Section {section_idx}: max={max_tokens:.0f}")

# INFO: 重要な決定
logger.info(f"[INFO construct_code_graph_context] Section added: {len(tags)} tags")

# WARNING: 予期しない動作
logger.warning(f"[WARNING retrieve_graph] Token budget exceeded: {tokens}/{budget}")

# ERROR: 致命的エラー
logger.error(f"[ERROR] Failed to retrieve graph for: {search_term}")
```

**効果**:
- ログレベル別フィルタリングが可能
- ログファイルが見やすくなる

**優先度**: ★ (LOW) - 機能には影響しないが、保守性向上

---

### 改善 4: セクション処理の効率化（ENHANCEMENT）

**現在の実装**:
```python
for loc in tqdm(item):  # tqdm で進捗表示
    # 各 loc (function/class/qualified name) を処理
    ...

# セクション全体がメモリに保持される
section_tokens = len(section) // 4
```

**問題点**:
- 大きなセクション（複数の関数）を処理する場合、メモリ効率が悪い
- `tqdm` による進捗表示がコンソール出力（ログではない）

**改善案**:
```python
# tqdm を logger と統合
for loc_idx, loc in enumerate(item):
    if loc_idx % 10 == 0 and logger:
        logger.debug(f"Processing location {loc_idx}/{len(item)}: {loc}")

    # 処理...

# またはシンプルに tqdm を削除（ログで十分）
for loc in item:
    # 処理...
```

**優先度**: ★ (LOW) - 機能には影響しない

---

## 3. 実装の合理性

### OK な部分

✓ **Composite Score による Prioritization**
- ファイル関連性（1000/100/1）+ 直接隣人ボーナス（50）
- ラインレベルのコンテキスト選択には合理的

✓ **Def/Ref Tag の分離**
- 定義（def）と参照（ref）を別々に処理
- セマンティクスを考慮した設計

✓ **段階的な予算分配**
```python
max_tokens_this_section = remaining_budget / sections_remaining
```
- 数学的に合理的
- 後のセクションに予算を余すため効果的

✓ **Logger統合（大部分）**
- 64行にもわたるlogger統合が行われた
- ほぼすべての重要な決定がログに記録される

---

## 4. 優先度の再評価

### 提案した優先度の問題点

**現在の提案**:
1. 失敗した3インスタンスの完了
2. 完全な23インスタンス Baseline 実行
3. グラフ品質分析
4. ライン精度改善の再考

**問題点**:
- ❌ **Logger 統合不完全が修正されていない**
- ❌ **Token計算の不確実性が残っている**
- ⚠ 失敗した3インスタンスを修正する前に、実装のバグを修正すべき

---

## 5. 推奨される新しい優先度

### **優先度 1: Logger 統合の完成（CRITICAL）**

**理由**:
- 251行目・271行目のprint文を修正してloggerに統合
- これを修正しないと、すべてのデバッグ情報が失われる
- 所要時間: 5分以下

**実行コマンド**:
```bash
# repograph_utils.py の251行目と271行目を修正
# logger.debug() / logger.info() に変更
```

**検証方法**:
```bash
# 修正後、任意のインスタンスで再実行してログを確認
python patchpilot/fl/localize.py \
    --file instances/test_instances_debug_phase2_6.txt \
    --reproduce_folder results/reproduce \
    --code_graph_dir cache/code_graphs \
    --benchmark verified \
    --backend openai \
    --output_folder results/localization_test_logger_fix \
    --num_threads 1

# ログを確認
grep "Retrieved.*one-hop tags" results/localization_test_logger_fix/localization_logs/*.log
```

---

### **優先度 2: Token計算ロジックの検証と最適化（HIGH）**

**理由**:
- 現在の `len(str(...)) // 4` が正確かどうか不明
- Token予算の計算が不正確では、Greedy allocation が意味がない

**実行内容**:
1. 実際のタグサイズを調査
   ```bash
   # デバッグログから実際のタグサイズを確認
   grep "tag_tokens\|Token-aware limiting" results/localization_repo_23inst_phase2_6_20251109/localization_logs/*.log | head -20
   ```

2. トークン計算式を検証
   ```python
   # サンプルタグで確認
   tag_text = ["def foo(x, y):", "    return x + y", ...]
   text_str = "\n".join(tag_text)

   # 現在の計算
   current_tokens = len(str(text_str)) // 4

   # UTF-8ベースの計算
   utf8_tokens = len(text_str.encode('utf-8')) // 4

   # どちらが実際のトークン数に近いか確認
   ```

3. 計算式を統一
   ```python
   # repograph_utils.py の219行目と393行目を統一
   TOKENS_PER_CHAR_ESTIMATE = 4  # 定数として定義
   estimated_tokens = len(text) // TOKENS_PER_CHAR_ESTIMATE
   ```

**所要時間**: 30分程度

---

### **優先度 3: 失敗した3インスタンスの完了（HIGH）**

**理由**:
- 優先度1・2を修正した後なら、より正確な結果が得られる
- django__django-13401 は LINE-改善インスタンス（重要）

**実行内容**:
```bash
# 優先度1・2を修正してからこれを実行
python patchpilot/fl/localize.py \
    --file instances/test_instances_mixed_phase1_v2.txt \
    --reproduce_folder results/reproduce \
    --code_graph_dir cache/code_graphs \
    --benchmark verified \
    --backend openai \
    --output_folder results/localization_repo_23inst_phase2_6_final \
    --num_threads 2  # スレッド数を減らす
```

**所要時間**: 数時間（並列実行）

---

### **優先度 4: 完全な23インスタンス Baseline 実行（MEDIUM）**

**理由**:
- Repograph との比較に必要
- 優先度3の後に実行すれば OK

**実行内容**:
```bash
python patchpilot/fl/localize.py \
    --file instances/test_instances_mixed_phase1_v2.txt \
    --reproduce_folder results/reproduce \
    --output_folder results/localization_base_23inst_final_20251109 \
    --num_threads 4
```

**所要時間**: 数時間（並列実行）

---

### **優先度 5: グラフ品質分析（MEDIUM）**

**理由**:
- 優先度3・4の結果が揃ってから分析
- Line-level 改善のための最適化

**実行内容**:
```bash
# 削除されたタグの分析
python analyze_deleted_tags.py

# トークン使用率と性能の相関分析
python analyze_token_vs_performance.py
```

---

## 6. 修正コードの例

### 修正 1: Logger統合完成

```python
# patchpilot/fl/repograph_utils.py の retrieve_graph() 関数

# 251行目を修正
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 修正前:
    for i, tag in enumerate(tags):
        print(f"Retrieving graph for {i}/{len(tags)}")

# 修正後:
    for i, tag in enumerate(tags):
        if logger and i % max(1, len(tags) // 10) == 0:  # 10% ごとにログ
            logger.debug(f"[DEBUG retrieve_graph] Processing tag {i}/{len(tags)}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 271行目を修正
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 修正前:
    print(f"[DEBUG retrieve_graph] Retrieved {len(one_hop_tags)} one-hop tags for: {search_term}")
    return one_hop_tags

# 修正後:
    if logger:
        logger.info(f"[DEBUG retrieve_graph] Retrieved {len(one_hop_tags)} one-hop tags for: {search_term}")
    return one_hop_tags
```

---

### 修正 2: Token計算の統一

```python
# patchpilot/fl/repograph_utils.py の上部に定数を追加
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHARS_PER_TOKEN = 4  # 保守的な見積もり

def estimate_tokens(text):
    """テキストのトークン数を推定"""
    if isinstance(text, list):
        text = "\n".join(text)
    elif not isinstance(text, str):
        text = str(text)
    return len(text) // CHARS_PER_TOKEN

# 219行目を修正
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 修正前:
    tag_tokens = len(str(tag.get('text', []))) // 4 if tag.get('text') else 100

# 修正後:
    tag_tokens = estimate_tokens(tag.get('text')) if tag.get('text') else 200

# 393行目を修正
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 修正前:
    section_tokens = len(section) // 4

# 修正後:
    section_tokens = estimate_tokens(section)
```

---

## まとめ

| 問題 | 重大度 | 修正時間 | 影響 |
|------|--------|---------|------|
| Logger 統合不完全 | 🔴 HIGH | 5分 | すべてのデバッグ情報が失われる |
| Token計算の不確実性 | 🟠 MEDIUM | 30分 | Greedy allocation の正確性 |
| 予算チェックの時点 | 🟠 MEDIUM | 10分 | 効率性（機能には影響なし） |
| Tag削除ロジック | 🟡 LOW-MEDIUM | 1時間 | Line-level 性能 |
| Logger レベル統一 | 🟡 LOW | 15分 | 保守性 |

**推奨実行順序**:
1. ✅ Logger 統合完成（5分）
2. ✅ Token計算統一（30分）
3. ⏳ 失敗インスタンス完了（数時間）
4. ⏳ Baseline 実行（数時間）
5. 📊 グラフ品質分析（1時間）
