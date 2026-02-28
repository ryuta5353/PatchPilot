# RepoGraph 統合問題の調査チェックリスト

**目的**: 実装レベルでの根本原因を確認し、修正方針を決定する

---

## Phase A: ログ検証（3-4時間）

### A-1. Greedy Allocation がログに出ているか確認

```bash
# 検索コマンド
find results/localization_repo_23inst* -name "*.log" | head -1 | xargs grep -l "Token budget"

# 期待値: 何もヒットしない（print() だから）
# 実際: (検索して確認)
```

**確認項目:**
- [ ] "Token budget exhausted" が ログに出ているか
- [ ] "Global graph tokens" が ログに出ているか
- [ ] "DEBUG construct_code_graph_context" が ログに出ているか

**結果:**
- ✓ ヒットした → logger が実装されている（可能性）
- ✗ ヒットしない → print() のまま（確認）

### A-2. グラフコンテキストのサイズをログから抽出

```bash
# グラフコンテキストのサイズを含むログ行を探す
find results -name "*.log" -exec grep -l "graph" {} \;

# 各インスタンスの graph_context サイズを調査
# 期待値: ~30,740 tokens
# 実測値: 33K-70K tokens（超過の可能性）
```

**データ収集:**

インスタンス名 | Graph Size (chars) | Est. Tokens | Over Budget? | Line Recall Change
---|---|---|---|---
django-13401 | 12,000 | 3,000 | No | +8.7pp ✓
sphinx-8595 | 122,000 | 30,000+ | YES | -100pp ✗
astropy-12907 | 70,000 | 17,500+ | YES | Same
pylint-7080 | 44,000 | 11,000+ | YES | Degraded

### A-3. セクション数と関数数をログから確認

```bash
# 各インスタンスのセクション数、関数数をログから抽出
grep -E "sections?|locations?" results/localization_repo_23inst*/loc_outputs.log

# サマリー:
# - セクション数: 4-30
# - 関数位置数: 8-84
# - グラフサイズ: 12K-122K chars
```

**分析:**

セクション数 | インスタンス数 | 平均 Line Recall | 傾向
---|---|---|---
<10 | 2 | +2pp | 改善可能
10-20 | 8 | -3pp | 中立～悪化
20+ | 13 | -8.5pp | 悪化確定

---

## Phase B: トークン計算の検証（2-3時間）

### B-1. Token 推定精度の検証

```python
# repograph_utils.py の token 推定式を検証

実装:
  tag_tokens = len(str(tag.get('text', []))) // 4

検証方法:
  1. 実際のタグのテキストを取得
  2. len(text) // 4 で推定
  3. 実際の encode を使って比較
  4. 誤差率を計算
```

**期待される結果:**

```
実装の推定:     100 文字 → 25 tokens
実際の encode:  100 文字 → 30-40 tokens
誤差:          -20% ～ +50%（不正確！）

改善方法:
  tokens = len(encoding.encode(text))  # 正確な計算
```

### B-2. 予算配分の追跡

```python
# Greedy allocation の進行状況を追跡

初期予算: 30,740 tokens

セクション進行:
  Section 1 (storage.py):
    def_tags:  500 tokens (定義1個）
    ref_tags:  1,500 tokens (参照20個)
    残り: 30,740 - 2,000 = 28,740

  Section 2 (move.py):
    def_tags:  300 tokens
    ref_tags:  1,200 tokens
    残り: 28,740 - 1,500 = 27,240

  ...（17セクション）

最終: 実測 33,313 tokens (予算超過!)
```

### B-3. ファイル内容の削減量を確認

```python
# Phase 2-6 の矛盾を検証

Related Level:
  file_contents + problem_statement = 88,509 tokens

Fine-Grain Level (グラフあり):
  実測: 38,310 tokens ← なぜこんなに少ない？

削減量: 88,509 - 38,310 = 50,199 tokens！！

何が起きたのか:
  グラフを加える前に file_contents が削減されている
  → グラフの価値が失われている
```

---

## Phase C: グラフサイズの詳細分析（3-4時間）

### C-1. 関数定義の個数を集計

```bash
# 各インスタンスの def_tags 数を集計

for log in results/localization_repo_23inst*/loc_outputs.log; do
  echo "$(basename $(dirname $log)):"
  grep -o "def [a-zA-Z_]*(" $log | wc -l
done
```

**期待される結果:**

インスタンス | Def Tags 数 | Line Recall
---|---|---
sphinx-8595 | 84+ | -100pp
astropy-12907 | 50+ | -
pytest-7490 | 93 | -8.5pp (平均)
django-13401 | 8 | +8.7pp ✓

**パターン:** def_tags が 50個以上で必ず悪化

### C-2. セクション構造の可視化

```python
# 各インスタンスのグラフ構造を分析

graph_structure = {
    "django-13401": {
        "sections": 4,
        "tags_per_section": 2-3,  # 小さい
        "total_chars": 12000,
        "line_recall_change": +8.7
    },
    "sphinx-8595": {
        "sections": 17,
        "tags_per_section": 10-15,  # 大きい
        "total_chars": 122000,
        "line_recall_change": -100
    }
}

結論: セクション数 ✗ タグ数 = 性能を大きく悪化させる
```

### C-3. Composite Score の検証

```python
# Composite Score が「すべての関数」を選出しているか確認

関連ファイル: storage.py, move.py, uploadedfile.py

Composite Score の結果:
  storage.py:
    file_locality: 1000 (Tier 1)
    neighbors: 8
    in_degree: 12
    合計: 1020 点 ← 最高スコア

  move.py:
    file_locality: 100 (Tier 2)
    neighbors: 5
    in_degree: 3
    合計: 108 点

  uploadedfile.py:
    file_locality: 1 (Tier 3)
    neighbors: 2
    in_degree: 1
    合計: 4 点

結果: すべてのファイルが選出される（フィルタリングなし）
     → グラフサイズが大きくなる
     → LLM が混乱
```

---

## Phase D: 失敗パターンの詳細調査（4-5時間）

### D-1. サイレント失敗の 4インスタンスを確認

```bash
# 4つの失敗インスタンスの詳細ログを確認

インスタンス:
  - django-13933
  - django-14534
  - sklearn-13496
  - sphinx-11445

確認項目:
  1. File Level までは完走しているか
  2. Related Level の出力があるか
  3. エラーメッセージがあるか
```

**ログの確認:**

```bash
# ベースライン（成功）
tail -100 results/localization_baseline_10inst/log/django-13933.log
# → Related level completed
# → Fine-grain level completed

# RepoGraph（失敗）
tail -100 results/localization_repo_23inst/log/django-13933.log
# → File level completed
# →（ここで終わり）
# → Related level が出力されない
```

### D-2. 例外発生箇所の特定

```python
# localize.py:225 付近で何が起きているか

locate_function_from_compressed_files(
    found_related_locs,  # ← ここで例外？
    structure,
    ...
)

潜在的な例外:
  1. found_related_locs が異常（NaN, 型エラー）
  2. compress_file() が失敗
  3. graph generation で OutOfMemory
  4. LLM API エラー（キャッチされない）
```

### D-3. 処理ログの比較

```
ベースライン（successful）:
  [INFO] Search completed: 5,234 bytes
  [INFO] File level completed: 123 KB log
  [INFO] Related level completed: 145 KB log
  [INFO] Fine-grain level completed: 150 KB log
  完료

RepoGraph（failed）:
  [INFO] Search completed: 5,234 bytes  ← 同じ
  [INFO] File level completed: 18 KB log ← 縮小
  （ここで終わり）
  失敗
```

**分析:**
  - File Level のログが 90% 削減
  - Related Level の出力がない
  - エラーログもない（サイレント）

### D-4. トレースバック情報の復旧

```bash
# タイムスタンプでベースラインと RepoGraph を比較

ベースライン実行時刻:
  2025-11-09 14:35:22 - Search start
  2025-11-09 14:35:45 - Search end (23秒)
  2025-11-09 14:36:12 - File level end
  2025-11-09 14:37:00 - Related level end
  2025-11-09 14:37:50 - Fine-grain level end

RepoGraph実行時刻:
  2025-11-09 15:10:12 - Search start
  2025-11-09 15:10:35 - Search end
  2025-11-09 15:11:02 - File level end
  （ここで停止 → Related level が始まらない）

推定原因:
  localize_function_from_compressed_files() の呼び出し
  で例外発生 → 処理中断
```

---

## Phase E: 実装コードの検証（2-3時間）

### E-1. logger vs print の確認

```python
# repograph_utils.py を確認

現在の実装を確認:
  line 326: print(f"[INFO]...") ← ログに出ない
  line 391: print(f"...") ← ログに出ない
  line 396: print(f"...") ← ログに出ない

変更すべき箇所:
  print() → logger.info()
  tqdm print → logging に変更
```

### E-2. Token 推定の確認

```python
# repograph_utils.py の token 推定式

現在:
  tag_tokens = len(str(tag.get('text', []))) // 4

問題:
  - // 4 は粗い推定
  - フォーマット、改行を無視
  - 実際と大きく異なる可能性

改善案:
  from tiktoken import encoding_for_model
  enc = encoding_for_model("gpt-4o")
  tag_tokens = len(enc.encode(text))
```

### E-3. def_tags の無条件含有を確認

```python
# repograph_utils.py line 105

現在:
  def_tags_limited = def_tags[:1]  # 最初の 1個？

  # でも実際には：
  if not in_related_files:
    include(def_tag)  # 無条件？

確認すべき:
  - def_tags は本当に 1個だけか？
  - 多くのタグが含まれているのか？
  - トークン管理に含まれているか？
```

### E-4. エラーハンドリング の確認

```python
# localize.py line 225

現在:
  result = localize_function_from_compressed_files(...)
  # → try-except がない

改善案:
  try:
      result = localize_function_from_compressed_files(...)
  except Exception as e:
      logger.error(f"Graph context generation failed: {e}")
      # Non-graph path にフォールバック
```

---

## 調査の流れ

### Day 1: Phase A + B （ログと計算の検証）

```
午前:
  A-1. Greedy allocation ログを検索
  A-2. グラフサイズ を集計

午後:
  B-1. Token 推定精度を検証
  B-2. 予算配分を追跡
  B-3. ファイル削減量を確認
```

**出力**: 「Greedy allocation は機能していないこと」を証明

### Day 2: Phase C + D （グラフと失敗の分析）

```
午前:
  C-1. 関数定義の個数を集計
  C-2. セクション構造を可視化

午後:
  D-1. 4インスタンスの失敗を確認
  D-2. 例外発生箇所を特定
```

**出力**: 「グラフサイズとセクション数が精度を悪化させること」を証明

### Day 3: Phase E + 修正提案

```
午前:
  E-1. logger vs print を確認
  E-2. token 推定を改善

午後:
  E-3. def_tags 処理を改善
  E-4. エラーハンドリング 追加

修正提案書を作成
```

**出力**: 具体的な修正方針

---

## 期待される発見

### 発見 1: Greedy Allocation は機能していない

```
証拠:
  - logger 出力なし（print() のまま）
  - トークン超過（30.7K → 33K-70K）
  - グラフサイズが予算と無関係
```

### 発見 2: グラフサイズと精度に逆相関

```
証拠:
  - 小グラフ (12K) → +8.7pp
  - 大グラフ (122K) → -100pp
  - セクション 20+ → 必ず悪化
```

### 発見 3: サイレント失敗が処理完了率を低下

```
証拠:
  - 4インスタンスで Related level 出力なし
  - エラーログなし（例外がキャッチされていない）
  - 処理完了率 95.7% → 78.3%
```

---

## 修正の優先順位（確認後に決定）

### 優先度 1（今日中に修正可能）
- [ ] print() → logger.info() に変更（1時間）
- [ ] try-except の追加（1時間）

### 優先度 2（1-2日で修正可能）
- [ ] グラフサイズ制限（15個以下）（4時間）
- [ ] Token 推定の改善（2時間）

### 優先度 3（1週間で改善）
- [ ] Composite Score を意味的に改善（2日）
- [ ] 適応的グラフサイズ（2日）

---

## 成功の定義

あなたの調査が成功したら：

1. ✓ Greedy Allocation が機能していないことを証明
2. ✓ グラフサイズと精度の逆相関を数値で示す
3. ✓ 4インスタンス失敗の原因を特定
4. ✓ 修正方針を 3-5項目に絞る
5. ✓ 各修正の見積もり時間を提示

これが完成したら、すぐに修正フェーズに移行できます。

