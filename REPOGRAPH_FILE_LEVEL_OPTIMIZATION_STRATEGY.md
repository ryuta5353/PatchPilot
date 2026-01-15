# File Level での RepoGraph 活用：無駄を排除する戦略

## 1. 現在の実装の問題点

### 1-1. 現在の流れ

```
Step 0 の検索結果:
  search_string("execute") → [file1, file2, file3, ... file50]
  search_func_def("save") → [file_a, file_b]
  search_string("permission") → [file_x, file_y, file_z, ... file100]

すべてのファイルを候補として使用:
  {
    "execute": ["django/core/base.py", "django/db/backend.py", "django/auth/models.py", ...],
    "save": ["django/db/models.py"],
    "permission": ["django/auth/permissions.py", "django/contrib/auth.py", ...]
  }

これをすべてプロンプトに含める
  ↓
LLM へのプロンプト:
  ### Search Results ###
  execute is in: ['django/core/base.py', 'django/db/backend.py', ...] (50+ files)
  save is in: ['django/db/models.py']
  permission is in: ['django/auth/permissions.py', ...] (100+ files)

  修正ファイルを選択してください
```

### 1-2. この実装の問題

```
問題1: キーワードの曖昧性
  - "execute" は 50+ ファイルに存在（ノイズが大量）
  - "permission" は 100+ ファイル（どれが関連か不明）

問題2: 無差別な候補提示
  - 定義ファイル（重要）と参照ファイル（関連性低）が混在
  - LLM が重要度を判断する材料がない

問題3: 精度低下
  - LLM が 150+ ファイルから正解を推定する必要
  - エラーが出た時点で「execute が呼ばれている箇所」と単純判定
  - 実は無関係なファイルを選ぶ可能性が高い

結果: File Recall@3 が低い (55.6%)
```

---

## 2. RepoGraph を使った改善戦略

### 戦略1: キーワード関数の「定義ファイルのみ」を使う（簡単）

```
Step 0: search_string("execute") → 50+ ファイル

↓ RepoGraph で定義を抽出

search_func_def("execute") ← 定義ファイルのみ取得
  → ["django/core/management/base.py", "django/db/backends/base.py"]

LLM へのプロンプト:
  ### Keyword Definition Files ###
  execute is defined in: ['django/core/management/base.py', 'django/db/backends/base.py']

結果: 50+ ファイルを 2 ファイルに削減

メリット:
  ✓ 最も関連性が高い（定義ファイル）
  ✓ 実装が簡単（既存の search_func_def() を使用）

デメリット:
  ✗ 呼び出し元の情報が失われる
  ✗ 「バグは定義ファイルにある」という仮定（不常に正確ではない）
```

---

### 戦略2: キーワード関数からの「1-hop 呼び出し側」でフィルタ（中等度）

```
Step 0: search_string("execute") → 50+ ファイル

↓ RepoGraph で「execute を呼び出している関数」を調査

retrieve_graph("execute") (predecessors mode):
  execute を呼ぶ関数:
    - Command.run (in django/core/management/base.py)
    - BaseDatabase.query_execute (in django/db/backends/base.py)
    - test_runner (in django/test/utils.py)
    - ... (20 関数)

↓ これらの関数が定義されているファイル = 「execute に直接依存するファイル」

フィルタ後の候補:
  ["django/core/management/base.py",
   "django/db/backends/base.py",
   "django/test/utils.py",
   ...]  ← 50+ から 20 程度に削減

LLM へのプロンプト:
  ### execute - Related Files (from RepoGraph) ###
  execute is called by functions in:
    - django/core/management/base.py
    - django/db/backends/base.py
    - django/test/utils.py

  These files depend on the execute function.

メリット:
  ✓ 定義ファイル + 直接呼び出し側の両方をカバー
  ✓ グラフによる正当な依存関係
  ✓ ノイズ大幅削減 (50+ → 20)

デメリット:
  ✗ 実装が複雑（predecessors 抽出）
  ✗ テスト/デバッグが必要
```

---

### 戦略3: 複数キーワードの「共通関連ファイル」を見つける（推奨）

```
Step 0 で複数キーワード:
  - execute: 50+ ファイル
  - save: 2 ファイル
  - permission: 100+ ファイル

↓ 各キーワードのグラフを取得

retrieve_graph("execute"):
  関連ファイル: {file1, file2, file3, file4, file5, ...}

retrieve_graph("save"):
  関連ファイル: {file1, file2, file6, file7}

retrieve_graph("permission"):
  関連ファイル: {file2, file3, file8, file9, file10, ...}

↓ ファイルを「関連キーワード数」でスコアリング

ファイル別スコア:
  - file1: execute, save に関連 (2つ)
  - file2: execute, save, permission に関連 (3つ) ← 最高スコア
  - file3: execute, permission に関連 (2つ)
  - file4: execute のみ (1つ)
  - ...

↓ スコアでソート（3つ関連 > 2つ関連 > 1つ関連）

優先度付き候補:
  1. file2 (スコア 3)
  2. file1 (スコア 2)
  3. file3 (スコア 2)
  4. file4 (スコア 1) ← ここまで

  → 50+ + 2 + 100+ = 152+ 候補を 4 ファイルに削減!

LLM へのプロンプト:
  ### File Candidates (Ranked by RepoGraph) ###

  Tier 1 - Connected to 3 keywords:
    - django/db/models.py (execute, save, permission に関連)
      → Bug fix の中心になる可能性が高い

  Tier 2 - Connected to 2 keywords:
    - django/core/management/base.py (execute, save に関連)
    - django/core/backend.py (execute, permission に関連)

  Tier 3 - Connected to 1 keyword:
    - django/test/utils.py (execute のみ)

  修正ファイルを選択してください

メリット:
  ✓ 複数の bug symptom に同時に関連するファイルを特定
  ✓ グラフの「交差点」= 修正すべき箇所の可能性が高い
  ✓ 候補を 152+ から 4 ファイルに大幅削減
  ✓ LLM の判断が容易

デメリット:
  ✗ 複数キーワードに対応する必要
  ✗ グラフの質に依存
```

---

## 3. 推奨実装：戦略3

### 3-1. 実装の流れ

```python
def optimize_file_candidates_with_repograph(
    search_res_files,        # Step 0 の検索結果
    code_graph,              # RepoGraph
    graph_tags,              # グラフタグ
    structure
):
    """
    RepoGraph を使用して Search Results をフィルタ＆スコアリング

    入力: search_res_files = {
        "execute": ["file1", "file2", ...],
        "save": ["file_a", "file_b"],
        ...
    }

    出力: optimized_results = {
        "django/db/models.py": {
            "tier": 1,
            "score": 300,
            "related_keywords": ["execute", "save", "permission"],
            "reason": "Central to 3 keywords"
        },
        ...
    }
    """

    # Step 1: グラフキーワードの判定
    graph_keywords = {}
    for keyword in search_res_files.keys():
        # 関数/クラス定義がグラフに存在するか確認
        if is_function_or_class_in_graph(keyword, graph_tags):
            graph_keywords[keyword] = True
        else:
            graph_keywords[keyword] = False  # 文字列など

    # Step 2: グラフキーワード各々に対してグラフ取得
    keyword_related_files = {}

    for keyword, has_graph in graph_keywords.items():
        if has_graph:
            # グラフから「このキーワードに関連するファイル」を抽出
            related_funcs = retrieve_graph(
                keyword,
                code_graph,
                graph_tags,
                structure
            )
            related_files = set()
            for func, file in related_funcs:
                related_files.add(file)

            keyword_related_files[keyword] = related_files
        else:
            # グラフなし: Step 0 の結果をそのまま使用
            keyword_related_files[keyword] = set(search_res_files[keyword])

    # Step 3: ファイルの「関連キーワード数」をカウント
    file_to_keywords = {}

    for keyword, files in keyword_related_files.items():
        for file in files:
            if file not in file_to_keywords:
                file_to_keywords[file] = []
            file_to_keywords[file].append(keyword)

    # Step 4: スコアリング
    # スコア = 関連キーワード数 × 100
    # （複数キーワードに関連するファイルを優先）

    scored_files = []
    for file, keywords in file_to_keywords.items():
        score = len(keywords) * 100
        scored_files.append((file, score, keywords))

    # Step 5: スコアでソート
    scored_files.sort(key=lambda x: x[1], reverse=True)

    # Step 6: Tier 分け＆返却（上位 10 個に制限）
    optimized_results = {}

    for i, (file, score, keywords) in enumerate(scored_files[:10]):
        # Tier 判定
        if len(keywords) >= 3:
            tier = 1
        elif len(keywords) >= 2:
            tier = 2
        else:
            tier = 3

        optimized_results[file] = {
            'tier': tier,
            'score': score,
            'related_keywords': keywords,
            'reason': f"Related to {len(keywords)} keyword(s): {', '.join(keywords)}"
        }

    return optimized_results
```

### 3-2. プロンプト生成

```python
def build_optimized_prompt(optimized_results, problem_statement, structure):
    """
    RepoGraph による最適化結果をプロンプトに組み込む
    """

    # Tier ごとにグループ化
    tier_files = {1: [], 2: [], 3: []}
    for file, info in optimized_results.items():
        tier_files[info['tier']].append((file, info))

    # プロンプト構築
    prompt_parts = []

    prompt_parts.append("### GitHub Problem Description ###")
    prompt_parts.append(problem_statement)
    prompt_parts.append("")

    prompt_parts.append("### File Candidates (Ranked by RepoGraph Analysis) ###")
    prompt_parts.append("")

    for tier in [1, 2, 3]:
        if tier_files[tier]:
            prompt_parts.append(f"Tier {tier} - Connected to {tier} keyword(s):")
            for file, info in tier_files[tier]:
                keywords_str = ", ".join(info['related_keywords'])
                prompt_parts.append(f"  - {file}")
                prompt_parts.append(f"    Related keywords: {keywords_str}")
                prompt_parts.append(f"    {info['reason']}")
            prompt_parts.append("")

    prompt_parts.append("### Recommendation ###")
    prompt_parts.append(
        "Files in Tier 1 are connected to multiple keywords and are most likely "
        "to be the focus of the bug fix. Consider these first."
    )
    prompt_parts.append("")

    prompt_parts.append("Please select the file(s) that need to be modified.")

    return "\n".join(prompt_parts)
```

---

## 4. 期待効果

### 4-1. パフォーマンス改善

```
現状:
  File Recall@3: 55.6% (50-100+ 候補から選定)

改善後（推定):
  File Recall@3: 70-75% (4-10 候補から選定)

理由:
  ✓ ノイズ削減: 150+ → 5-10 候補
  ✓ グラフベースの依存関係活用
  ✓ 複数キーワード間の相互参照を検出
  ✓ LLM の判断が容易に
```

### 4-2. トークン削減

```
現状:
  search_str_with_file_prompt:
    - execute: "is in: [file1, file2, ... file50]" (500+ tokens)
    - permission: "is in: [file1, ... file100]" (1000+ tokens)
    合計: 1500+ tokens

改善後:
  optimized_prompt:
    - Tier 1: 3-5 ファイル (100-200 tokens)
    - Tier 2: 3-5 ファイル (100-200 tokens)
    - Tier 3: 1-3 ファイル (50-100 tokens)
    合計: 250-500 tokens

削減量: 1500 tokens → 500 tokens (約 66% 削減)
```

### 4-3. 計算複雑度

```
retrieve_graph() 呼び出し数:
  - 現状: キーワード数 (3-5 回)
  - 改善後: グラフキーワード数 (2-4 回、通常)

計算量: O(n * m)
  n = キーワード数 (少)
  m = グラフノード数 (一定)
  → 実用的範囲内
```

---

## 5. 実装上の注意点

### 5-1. グラフキーワードの判定

```python
def is_function_or_class_in_graph(keyword, graph_tags):
    """
    キーワードが関数/クラス定義として存在するか確認
    """
    # search_func_def() を実行してチェック
    for tag in graph_tags:
        if tag['name'] == keyword and tag['kind'] == 'def':
            return True
    return False
```

### 5-2. グラフのスコープ制限

```python
# 1-hop のみ（k-hop は避ける）
def retrieve_graph(keyword, code_graph, graph_tags, structure):
    """
    1-hop neighbors のみを取得
    - predecessors(keyword): keyword を呼ぶ関数
    - successors(keyword): keyword が呼ぶ関数

    k >= 2 は避ける（トークン爆発）
    """
    # 実装: 現在の retrieve_graph() と同じ
    pass
```

### 5-3. フォールバック

```python
# グラフが利用不可な場合
if not code_graph or not graph_tags:
    # Step 0 の結果をそのまま返す
    return search_res_files

# グラフキーワードが見つからない場合
if not any(graph_keywords.values()):
    # Step 0 の結果をフォールバック
    return search_res_files
```

---

## 6. 比較表

| 特性 | 現在 | 戦略1 | 戦略2 | 戦略3(推奨) |
|------|------|------|------|-----------|
| **候補数** | 150+ | 2-5 | 20 | 4-10 |
| **精度** | 低 | 中 | 中~高 | 高 |
| **トークン** | 1500+ | 300 | 600 | 250-500 |
| **実装難度** | 簡 | 簡 | 中 | 中 |
| **グラフ利用** | なし | def のみ | pred/succ | pred/succ |
| **複数キーワード** | ✗ | ✗ | △ | ✓ |

---

## 7. 結論

**Q: RepoGraph を使って Search Results の無駄を排除できるか？**

**A: はい。複数キーワードの共通関連ファイル（戦略3）を使うことで、150+ 候補を 4-10 に削減可能。**

```
推奨実装:
  1. 各キーワードが関数/クラス定義を持つか確認
  2. グラフキーワードに対して retrieve_graph() 実行
  3. 各ファイルの「関連キーワード数」をカウント
  4. スコアリング＆Tier 分け
  5. Tier 1-3 をプロンプトに含める

期待効果:
  - File Recall@3: 55.6% → 70-75% (+15pp)
  - トークン: 1500+ → 250-500 (66% 削減)
  - LLM の判断精度向上（候補削減）
```
