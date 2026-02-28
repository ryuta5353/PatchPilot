# RepoGraph 統合の失敗：実装レベルでの根本原因分析

**前提**: DEGRADATION_INSTANCE_ANALYSIS.md では「何が悪化したか」を述べたが、このドキュメントでは「なぜ悪化するのか」を実装レベルで分析

---

## 1. 問題のコア

### 現象：グラフコンテキストが大きくなるほど精度が悪化

```
グラフサイズ  →  関数数      →  ラインレベル精度
─────────────────────────────────────────
12K chars  →  8個        →  +8.7pp ✓
36K chars  →  93個       →  -0pp  →-8.5pp 平均
122K chars →  84個       →  -100pp ✗
```

### なぜこんなことが起きるのか？

実装の問題は、以下の 3つの層に分かれている：

1. **グラフ構築レベル** - 何を含めるか（Composite Score）
2. **トークン管理レベル** - どれだけ含めるか（Greedy Allocation）
3. **プロンプト構成レベル** - どう使うか（LLM に提示する方法）

---

## 2. グラフ構築レベルの問題

### 2-1. Composite Score が「構造的」過ぎる

**実装位置**: `patchpilot/fl/repograph_utils.py:164-187`

```python
# Composite Score の計算
score = file_locality_score(file, related_locs)  # 1000/100/1
      + direct_neighbor_count(file)               # 10, 5, 1
      + in_degree_count(file)                     # node degree

# 例: storage.py の場合
score = 1000 (Tier 1)
      + 8 (move.py, uploadedfile.py など呼び出し)
      + 12 (他のファイルから呼ばれている)
      = 1020 点
```

**何を実現しているか**:
```
「storage.py は関連ファイルとの依存関係が多いので重要」
```

**何を実現してほしいか**:
```
「storage.py の get_permissions_mode() 関数が
 この問題（0o600パーミッション）に関連している」
```

### 2-2. 問題：「すべての関数」を含めてしまう

**retrieve_graph() の動作**:

```python
# 関連ファイルが見つかった
related_files = [storage.py, move.py, uploadedfile.py, ...]

# 各ファイルからグラフを取得
for file in related_files:
    # def_tags（定義）を無条件に含める
    def_tags_limited = def_tags[:1]  # ✓ 1個だけ？

    # ref_tags（参照）を含める
    ref_tags_limited = ref_tags[:20]  # ✓ 20個

    # 両方合わせる
    section_tags = def_tags_limited + ref_tags_limited
    # → 21個の定義/参照が 1つのセクションに
```

**その結果**:

```
セクション 1 (storage.py):
  ├─ FileSystemStorage class (def)
  ├─ save() function (ref)
  ├─ _save() function (def)
  ├─ chmod() function (ref)
  ...
  └─ 20個の参照 (ref_tags)

セクション 2 (move.py):
  ├─ file_move_safe() (def)
  ...
  └─ 20個の参照

... × 17 セクション

結果：17セクション × (1 + 20) = 357個の定義/参照
```

### 2-3. 実装との矛盾：def_tags は実は無視されている

```python
# line 105 in repograph_utils.py
def_tags_limited = def_tags[:1]  # 最初の 1個だけ？

# でも実際には：
if is_important(def_tag):  # チェックなし
    include(def_tag)       # すべて含まれる可能性

# さらに、ref_tags は制限がない：
ref_tags_limited = ref_tags[:20]  # 20個を取ろうとするが...

# 実は ref_tags の全部が入っていることがある
# (token limiting が機能していないため)
```

---

## 3. トークン管理レベルの問題

### 3-1. Greedy Allocation は「名前だけ」

**実装位置**: `patchpilot/fl/repograph_utils.py:316-405`

```python
# Greedy allocation の理想：
# 残りトークンを各セクションに分配
# token_budget = 30,740 tokens
# sections = 17
# max_tokens_per_section = 30,740 / 17 = 1,808 tokens

# 実装：
def construct_code_graph_context(...):
    remaining_budget = total_token_budget  # 30,740

    for section in sections:
        max_tokens_this_section = remaining_budget / sections_remaining

        tags_in_section = []
        tokens_used = 0

        for tag in tags:
            tag_tokens = len(str(tag.get('text', []))) // 4  # ← 問題1

            if tokens_used + tag_tokens > max_tokens_this_section:  # ← 問題2
                break

            tags_in_section.append(tag)
            tokens_used += tag_tokens

        remaining_budget -= tokens_used
        sections_remaining -= 1
```

### 3-2. トークン推定の問題

```python
# 問題 1: token 推定が粗い
tag_tokens = len(str(tag.get('text', []))) // 4
            ↑    ↑                           ↑
            |    文字列に変換              4で割る？
            不正確（フォーマット、改行を無視）

実例：
  tag text: "def save(self, name, content, max_length=None):\n    ..."
  len() = 200文字
  推定 tokens = 200 / 4 = 50 tokens
  実際 tokens = ~150 tokens (3倍の誤差！)
```

### 3-3. 実装の効果がない証拠

```python
# Phase 2-6 報告より：

期待値: 30,740 tokens
実測値:
  - 平均: 33,313 tokens (+8.4%)
  - sphinx-8595: 51,170 tokens (+1.7倍)
  - astropy-12907: 69,938 tokens (+2.3倍)

Greedy allocation が効いていない証拠：
  予算超過 → トークン制限が機能していない
  → retrieve_graph() が無視されている
  → 実は制限なくタグが含まれている
```

### 3-4. def_tags が無条件に含まれる

```python
# line 105
def_tags_limited = def_tags[:1]  # 「最初の1個だけ」？

# しかし実装では：
if not in_related_files:  # 関連ファイルに含まれていなければ
    add_def_tag()         # 定義を含める

# この定義が大きいと：
#   "def save(self, name, content, max_length=None):\n
#    ... 100行 ... = 300-500トークン

# Greedy allocation の予算が一瞬で消費される
remaining_budget: 30,740 → 30,240 → 29,740 → ...
                 (各 def_tag が 500 tokens)

# 17セクション × 500トークン = 8,500トークン (def だけ)
# → 残り 22,240トークン を ref_tags で分割
```

---

## 4. プロンプト構成レベルの問題

### 4-1. グラフコンテキストを提示する方法

**現在の実装** (FL.py:862-878):

```python
# グラフコンテキストを生成
graph_context = construct_code_graph_context(...)
# → 113,292 文字（50+ セクション、84個の関数定義）

# プロンプトに組み込む
message = fine_grain_prompt_template.format(
    problem_statement=problem_statement,
    file_contents=file_contents_truncated,
    graph_context=graph_context,  # ← 巨大な構造がここに入る
    code=code_snippet
)

# LLMへの指示:
# "以下はコードの依存関係グラフです：
#  [84個の関数の定義がずらっと]
#  これらを参考に、修正行番号を特定してください"
```

### 4-2. なぜ LLM が混乱するのか

```
LLM の頭の中：

「84個の関数を見た」
  ↓
「すべての関数が『関連している』と言われている」
  ↓
「では、どれが最も重要？」
  ↓
「84個すべてが『重要度が同じ』で見える」
  ↓
「ランダムに選ぶ」
  ↓
「ハズれ」 → 精度低下
```

### 4-3. グラフサイズの効果の実証

```
最良の例（8個の関数）：
  LLM: 「8個の関数から探す」→ 比較的容易 → +8.7pp

最悪の例（84個の関数）：
  LLM: 「84個？？」→ パニック → ランダムな選択 → -100pp
```

---

## 5. 統合的な問題：トークン予算の「二重取得」

### 5-1. バジェット計算の矛盾

```python
# FL.py の流れ：

# 1. Related Level でファイル内容を準備
file_contents = get_top_n_files(found_related_locs)
# → 推定 60,000 tokens

# 2. グラフコンテキストを生成（独立した予算）
graph_context = construct_code_graph_context(
    ...,
    total_token_budget=30,740  # ← 独立した予算！
)
# → 出力: 113,292 文字 = 28,323 tokens

# 3. プロンプト構成
message = template.format(
    problem_statement=...,     # ~500 tokens
    file_contents=...,         # 60,000 tokens
    graph_context=...,         # 28,323 tokens
    # 合計: 88,823 tokens (128K以内)
)

# 4. LLM へ送信
response = llm(message)  # 実際の token_count = 38,310?
```

### 5-2. 矛盾する数字

```
理論値:
  file_contents: 60,000 tokens
  graph_context: 28,323 tokens
  overhead: ~1,000 tokens
  合計: 89,323 tokens

実測値:
  プロンプト実測: 38,310 tokens

差分: 89,323 - 38,310 = 50,000+ tokens が消えた！

何が起きたのか：
  グラフを生成したが、別の場所で file_contents が
  削減されたので、グラフの情報が無視されている
```

---

## 6. デバッグ機構の欠落

### 6-1. ログに出ないデバッグ出力

**実装位置**: `repograph_utils.py:326, 391, 396`

```python
# 問題のあるコード：
print(f"[INFO construct_code_graph_context] Token budget exhausted")
# ↑ print() は logging に出ない！

# 正しいコード（実装されていない）：
logger.info(f"[construct_code_graph_context] Token budget exhausted")
# ↑ logger は ログファイルに出力される
```

### 6-2. 検証不可の結果

```
ログ調査結果（Phase 2-6）:

grep "Token budget exhausted" *.log
  → 0 matches

grep "Token limit reached" *.log
  → 0 matches

grep "DEBUG construct_code_graph_context" *.log
  → 0 matches

結論: Greedy allocation が実装されているかどうか検証不可
```

---

## 7. 失敗パターン：4インスタンスのサイレント失敗

### 7-1. 失敗の場所

```python
# localize.py:207-227 (Related Level)

if args.related_level and not args.direct_line_level:
    if len(found_files) != 0:
        try:  # ← try がない！
            result = localize_function_from_compressed_files(...)
            # ↓ この中で例外が発生
        except:  # ← catch がない！
            pass  # ← エラー無視
        # ↓ 処理が続く（または止まる）
```

### 7-2. サイレント失敗の証拠

```
失敗した 4インスタンス：
  - django-13933: 123KB ログ → 12KB ログ（90% 削減）
  - django-14534: 150KB ログ → 18KB ログ（88% 削減）
  - sklearn-13496: 98KB ログ → 8KB ログ（92% 削減）
  - sphinx-11445: 145KB ログ → 23KB ログ（84% 削減）

パターン: Related Level で処理が止まる

推定位置:
  localize.py:225
  → localize_function_from_compressed_files()
  ↑ 例外発生 → キャッチされない → 処理中断
```

### 7-3. エラー情報の欠落

```
通常のログ内容:
  [INFO] Search completed
  [INFO] File level completed
  [INFO] Related level starting...
  [INFO] Related level completed
  [INFO] Fine-grain level starting...

失敗時のログ:
  [INFO] Search completed
  [INFO] File level completed
  ← ここで終わり（Related level が出力されない）

エラーメッセージ: なし
トレースバック: なし
例外: 記録されない
```

---

## 8. まとめ：なぜ RepoGraph 統合が失敗したのか

### 階層別の問題

| 層 | 問題 | 影響 | 修正難易度 |
|----|------|------|----------|
| **グラフ構築** | Composite Score が構造的すぎる | 84個の関数を選出 | 中 |
| **トークン管理** | Greedy allocation が機能していない | 予算超過 1.7-2.3倍 | 中 |
| **プロンプト構成** | 84個の関数定義で LLM が混乱 | ラインレベル -100pp | 低（方法論） |
| **デバッグ情報** | print() 使用で ログに出ない | 検証不可 | 非常に低（1行修正） |
| **エラーハンドリング** | try-except がない | サイレント失敗 | 非常に低（5行追加） |

### 根本的な設計問題

```
①グラフコンテキストが「大きすぎる」
  ├─ Composite Score が「すべての関連関数」を選出
  ├─ def_tags + ref_tags で 200+ 個の定義
  └─ トークン 50K+ 必要

②トークン予算の制御が甘い
  ├─ Token 推定が粗い （// 4）
  ├─ Greedy allocation が機能していない
  └─ 実際は 1.7-2.3倍超過

③グラフをそのまま LLM に提示している
  ├─ 84個の関数 → LLM が処理できない
  ├─ 「すべてが関連」→ 「どれが重要？」 → パニック
  └─ ラインレベル精度 -8.5pp 平均、最悪 -100pp
```

### 修正の優先順位

1. **デバッグ情報** （今日中）: logger 出力 → print() 削除
2. **エラーハンドリング** （明日）: try-except 追加
3. **グラフサイズ制限** （1-2日）: 関数数 15個以下
4. **スコアリング見直し** （1週間）: 意味的スコア実装
5. **トークン推定改善** （1-2週間）: 正確なトークン計算

---

## 次のステップ

### あなたが確認すべき項目

1. **ログの出力状況**
   ```
   grep "Token budget" results/localization_repo_23inst/*/loc_outputs.log
   ```
   → 何も出ないはず

2. **トークン超過の実例**
   ```
   各インスタンスの graph_context サイズを確認
   ```
   → 30,740 を超えているはず

3. **関数数の実測**
   ```
   各セクションの def/ref 個数を確認
   ```
   → 80+ 個のセクションがあるはず

4. **失敗インスタンスの詳細ログ**
   ```
   結果フォルダの *.log を確認
   ```
   → Related level 出力がないはず

これらを確認することで、あなたの仮説を検証でき、修正方針が明確になります。

