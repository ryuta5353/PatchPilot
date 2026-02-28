# PatchPilot RepoGraph 統合の実装方法：完全ガイド

**作成日**: 2025-11-10
**対象**: RepoGraph が PatchPilot にどのように統合されているかの完全説明

---

## 概要

PatchPilot は 3 段階の階層的 Localization パイプラインを使用して、バグ修復に必要なコード場所を特定します。RepoGraph はこのうちの **Fine-Grain Level** でのみ統合されています。

```
┌─────────────────────────────────────────────────────────────┐
│ PatchPilot Localization Pipeline                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  LEVEL 1: File Level Localization                          │
│  └─ 問題説明から修正対象ファイルを特定                          │
│     (LLMFL.localize)                                       │
│     INPUT: 問題説明                                         │
│     OUTPUT: 修正対象ファイル (top_n 個)                      │
│     ✗ RepoGraph 未使用                                      │
│                                                              │
│  ↓                                                           │
│                                                              │
│  LEVEL 2: Related Level Localization                       │
│  └─ ファイル内の関連する関数・クラスを特定                      │
│     (LLMFL.localize_function_from_compressed_files)        │
│     INPUT: File Level の結果 + ファイルコンテンツ(圧縮)       │
│     OUTPUT: 関連ロケーション（各ファイルごと）                │
│     ✗ RepoGraph 未使用                                      │
│                                                              │
│  ↓                                                              │
│                                                              │
│  LEVEL 3: Fine-Grain Level Localization                   │
│  └─ Related Level の関数・クラス内の具体的な行を特定            │
│     (LLMFL.localize_line_from_coarse_function_locs)        │
│     INPUT: Related Level の結果 + グラフコンテキスト ★        │
│     OUTPUT: 修正対象の具体的な行番号                          │
│     ✓ RepoGraph 使用（グラフコンテキスト統合）                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 処理フロー：詳細

### Phase 1: グラフ生成と読み込み

**ファイル**: `patchpilot/fl/localize.py` 行 67-73

```python
# RepoGraph が --repo_graph フラグで有効な場合
if args.repo_graph:
    code_graph = pickle.load(
        open(os.path.join(args.code_graph_dir, f"{instance_id}.pkl"), "rb")
    )
    graph_tags = json.load(
        open(os.path.join(args.code_graph_dir, f"tags_{instance_id}.json"), "r")
    )
```

**重要な特性**:
- グラフは **事前生成** されている（localize.py 実行前）
- グラフファイルの場所: `args.code_graph_dir`（デフォルト: `cache/code_graphs/`）
- 2つのファイルが必要:
  1. `{instance_id}.pkl` - NetworkX グラフ
  2. `tags_{instance_id}.json` - ノードとエッジ情報

**グラフの内容** (`tags_*.json`):
```json
[
  {
    "name": "function_or_class_name",
    "kind": "def" or "ref",
    "rel_fname": "relative/path/to/file.py",
    "fname": "/absolute/path/to/file.py",
    "line": [start_line, end_line],
    "category": "function" or "class",
    "info": "metadata or function_code"
  },
  ...
]
```

### Phase 2: File Level Localization

**ファイル**: `patchpilot/fl/localize.py` 行 150-168
**メソッド**: `LLMFL.localize()`

```python
fl = LLMFL(...)
found_files, additional_artifact_loc_file, file_traj = fl.localize(
    mock=args.mock,
    match_partial_paths=args.match_partial_paths,
    search_res_files=search_str_with_file,
    num_samples=args.num_samples,
    top_n=args.top_n,
    coverage_info=coverage_info
)
```

**処理**:
- LLM を使用して問題説明から修正対象ファイルを特定
- 通常は top_n=5 として、最も可能性の高い 5 つのファイルを選択

**出力**:
```
found_files = ["path/to/file1.py", "path/to/file2.py", ...]
```

**グラフ使用**: ✗ なし

### Phase 3: Related Level Localization

**ファイル**: `patchpilot/fl/localize.py` 行 207-230
**メソッド**: `LLMFL.localize_function_from_compressed_files()`

```python
fl = LLMFL(...)
if args.compress:
    found_related_locs, additional_artifact_loc_related, related_loc_traj = \
        fl.localize_function_from_compressed_files(
            pred_files,
            mock=args.mock,
            num_samples=args.num_samples,
            coverage_info=coverage_info
        )
```

**処理**:
- File Level で特定されたファイル内から、関連する関数・クラスを特定
- ファイルコンテンツは圧縮されて提供（トークン削減のため）

**出力形式**:
```
found_related_locs = [
    ["class: MyClass\nfunction: my_method\nfunction: helper_function\n..."],
    [...],
    ...  # len(found_files) 個の要素
]
```

**グラフ使用**: ✗ なし

### Phase 4: Fine-Grain Level Localization ★ グラフ統合ポイント

**ファイル**: `patchpilot/fl/localize.py` 行 237-304
**メソッド**: `LLMFL.localize_line_from_coarse_function_locs()`

#### ステップ 4a: グラフコンテキスト生成

```python
if args.repo_graph and code_graph is not None and graph_tags is not None:
    logger.info("==== GRAPH CONTEXT GENERATION DEBUG (Fine-Grain Level) ====")

    # グラフコンテキスト生成
    graph_context = construct_code_graph_context(
        found_related_locs,  # Related Level の結果
        code_graph,          # NetworkX グラフ
        graph_tags,          # ノード情報
        structure,           # リポジトリ構造
        preferred_files=pred_files,  # ファイル選択の優先度
        logger=logger
    )
```

**`construct_code_graph_context` の処理フロー**:

```
INPUT: found_related_locs
       └─ 関連関数・クラスのリスト

FOR EACH 関連関数・クラス:
  ├─ Greedy Token Allocation で予算計算
  │  └─ max_tokens_this_section = remaining_budget / sections_remaining
  │
  ├─ retrieve_graph() で 1-hop 依存関係を取得
  │  ├─ 論文: ref タグのみ、max_tags=100
  │  └─ PatchPilot: def+ref、Composite Score、max_tags=50
  │
  └─ タグをフォーマットして graph_context に追加
     └─ "### Dependencies for FUNCTION_NAME" セクション

OUTPUT: graph_context（文字列）
```

**グラフコンテキストの例**:
```
### Dependencies for FileSystemStorage

location: django/contrib/staticfiles/finders.py lines 52 - 68
name: __init__
contents:
class FileSystemFinder(BaseFinder):
    def __init__(self, app_names=None, *args, **kwargs):
        # ...

### Dependencies for some_other_function

location: ...
```

#### ステップ 4b: プロンプト構築とグラフ統合

```python
if code_graph:
    # グラフありテンプレートを使用
    template = self.obtain_relevant_code_graph_prompt
    message = template.format(
        problem_statement=self.problem_statement,
        file_contents=topn_content,        # Related Level から取得
        code_graph=graph_context,          # グラフコンテキスト ★
        last_search_results=last_search_results
    )
```

**プロンプトテンプレート構造** (`obtain_relevant_code_graph_prompt`):

```
Please review the following GitHub problem description and relevant files...

### GitHub Problem Description ###
{problem_statement}

### Related Files ###
Below are the files that contain the code mentioned in the problem description.
{file_contents}

### Code Relationship Graph ###

Format:
- Each "### Dependencies for X" section lists functions directly connected to X
- Entries are ordered by relevance to the bug
- Graph includes only immediate relationships (1-hop neighbors)

For bug fixing:
1. Identify the function with the core bug from the problem description
2. Check callers (functions that call the target): may need coordinated updates
3. Check callees (functions called by target): updates may need propagation to callers
4. Primary source is the problem description; use this graph to identify related locations

{code_graph}  ← グラフコンテキストはここに挿入される

###

{last_search_results}

Please provide the class name, function or method name, or the exact line numbers that need to be edited.
...
```

**注意**:
- グラフコンテキストは "### Code Relationship Graph ###" セクションに配置
- ファイルコンテンツ（{file_contents}）との順序が重要
- グラフが大きすぎるとトークン超過

#### ステップ 4c: トークンチェックと Fallback

```python
if num_tokens_from_messages(message, "gpt-4o-2024-05-13") > 128000:
    logger.warning("⚠️ FALLBACK TRIGGERED: Token count exceeds 128000")

    # グラフなしテンプレートに切り替え
    template = self.obtain_relevant_code_combine_top_n_prompt
    message = template.format(
        problem_statement=self.problem_statement,
        file_contents=topn_content,
        last_search_results=last_search_results
    )
```

**Fallback メカニズム**:
- プロンプト + グラフコンテキストがトークン超過 (>128,000) の場合
- グラフなしテンプレートに自動切り替え
- この場合、ファイルコンテンツのみで修復を行う

---

## グラフ検索戦略：詳細

### retrieve_graph() 関数

**ファイル**: `patchpilot/fl/repograph_utils.py` 行 56-265
**役割**: 1-hop 依存関係を取得

**現在の実装** (Phase 2-6):
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure,
                   max_tags=50, target_file=None, max_tokens_for_section=None):
    # 1. def タグを 1 つ取得
    def_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'def']
    def_tags_limited = def_tags[:1]

    # 2. ref タグを取得
    ref_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'ref']

    # 3. Composite Score でソート
    ref_tags_sorted = sorted(ref_tags, key=composite_score_key, reverse=True)

    # 4. max_tags で制限
    ref_tags_limited = ref_tags_sorted[:max_tags]

    # 5. タグごとの詳細情報を検索
    for tag in def_tags_limited + ref_tags_limited:
        # ... タグの詳細情報を取得
```

### Composite Score スキーム

**定義** (行 164-187):
```python
def calculate_composite_score(tag, search_term, code_graph, target_file):
    locality_score = get_file_locality_score(tag, target_file)
    # 同じファイル: 1000, 同じディレクトリ: 100, 異なる: 1

    neighbor_bonus = 50 if is_direct_neighbor(tag, search_term, code_graph) else 0
    # グラフで直接接続: +50

    in_degree = code_graph.in_degree(tag['name'])
    in_degree_score = min(in_degree / 10, 10)  # 最大10
    # 呼び出し回数（正規化）

    return locality_score + neighbor_bonus + in_degree_score
```

**スコア計算の例**:
- 同ファイル + 直接接続 + in_degree=5: 1000 + 50 + 5 = 1055 ← 高優先度
- 同ディレクトリ + 接続なし + in_degree=0: 100 + 0 + 0 = 100
- 異なるファイル + 直接接続 + in_degree=20: 1 + 50 + 10 = 61

---

## パラメータと設定オプション

### コマンドラインオプション

```bash
python patchpilot/fl/localize.py \
    --file_level                      # File Level を実行
    --related_level                   # Related Level を実行
    --fine_grain_line_level           # Fine-Grain Level を実行
    --repo_graph                      # ★ グラフを有効にする
    --code_graph_dir cache/code_graphs/  # グラフファイルのディレクトリ
    --top_n 5                         # File Level で選択するファイル数
    --context_window 20               # Fine-Grain Level のコンテキスト（行数）
    --compress                        # Related Level でファイルを圧縮
    --num_samples 4                   # LLM 呼び出しのサンプル数
    --model gpt-4o-2024-05-13         # 使用する LLM
    --output_folder results/localization/  # 出力先
```

### グラフ関連パラメータ

| パラメータ | デフォルト | 説明 |
|-----------|---------|------|
| `--repo_graph` | False | グラフコンテキストを有効にするフラグ |
| `--code_graph_dir` | `cache/code_graphs/` | グラフファイルの場所 |
| `max_tags`（retrieve_graph） | 50 | 1-hop で取得するタグの最大数 |
| `total_token_budget` | 30,740 | グラフコンテキスト全体のトークン予算 |

---

## グラフの前提条件と依存関係

### 必須ファイル

グラフを使用するには、以下のファイルが必要：
```
cache/code_graphs/
├── {instance_id_1}.pkl
├── tags_{instance_id_1}.json
├── {instance_id_2}.pkl
├── tags_{instance_id_2}.json
└── ...
```

**生成方法**:
```bash
python generate_graphs.py <instance_list> cache/code_graphs/
```

参照: `RepoGraph/repograph/construct_graph.py`

### グラフ生成の内容

**construct_graph.py** (RepoGraph の実装):
- tree-sitter を使用して Python/JavaScript コードをパース
- 関数定義（def）と関数呼び出し（ref）を抽出
- フィルタリング:
  - 標準ライブラリ関数を除外
  - Built-in 関数を除外
  - 第三者ライブラリを除外

---

## 処理の流れ：全体図

```
localize_instance()
│
├─ [グラフ前処理]
│  └─ code_graph = pickle.load(f"{instance_id}.pkl")
│     graph_tags = json.load(f"tags_{instance_id}.json")
│
├─ [LEVEL 1: File Level]
│  └─ LLMFL.localize()
│     ├─ INPUT: problem_statement
│     └─ OUTPUT: found_files (e.g., ["file1.py", "file2.py", ...])
│
├─ [LEVEL 2: Related Level]
│  └─ LLMFL.localize_function_from_compressed_files()
│     ├─ INPUT: found_files + file_contents (compressed)
│     └─ OUTPUT: found_related_locs
│                 (e.g., ["class: MyClass\nfunction: method1\n..."])
│
└─ [LEVEL 3: Fine-Grain Level] ★ グラフ統合点
   │
   ├─ IF (args.repo_graph AND code_graph AND graph_tags):
   │  │
   │  ├─ construct_code_graph_context(found_related_locs, ...)
   │  │  └─ FOR EACH related location:
   │  │     ├─ retrieve_graph(search_term, ...)
   │  │     │  └─ 1-hop 依存関係を取得
   │  │     └─ タグをフォーマット
   │  │
   │  └─ RESULT: graph_context (string)
   │
   ├─ template.format(..., code_graph=graph_context, ...)
   │  └─ プロンプト構築
   │
   ├─ num_tokens() > 128000?
   │  ├─ YES: Fallback → グラフなしテンプレート
   │  └─ NO: グラフありテンプレット使用
   │
   └─ LLMFL.localize_line_from_coarse_function_locs()
      └─ LLM に送信して修正行を特定
         OUTPUT: found_edit_locs (e.g., [line_100, line_105, ...])
```

---

## 主要ファイル一覧

| ファイル | 役割 |
|---------|------|
| `patchpilot/fl/localize.py` | メイン localization パイプライン |
| `patchpilot/fl/FL.py` | LLMFL クラス（各 level の実装） |
| `patchpilot/fl/repograph_utils.py` | グラフ関連ユーティリティ |
| `RepoGraph/repograph/construct_graph.py` | グラフ生成（事前実行） |
| `RepoGraph/agentless/fl/localize.py` | 論文の実装（参考） |

---

## デバッグ情報

### ログ出力例

```
[INFO] ==== GRAPH CONTEXT GENERATION DEBUG (Fine-Grain Level) ====
[INFO] Repo graph enabled: True
[INFO] Number of related locations: 7
[INFO]   Related location 0: 250 chars, items: 3
[INFO]   Related location 1: 180 chars, items: 2
[INFO] Generated graph context: 113272 characters
[INFO] Graph context sections (### Dependencies for): 7
[INFO] Graph context locations: 28
[INFO] Graph context preview (first 500 chars):
### Dependencies for FileSystemStorage
location: django/contrib/staticfiles/finders.py lines 52 - 68
...
[INFO] ==== GRAPH CONTEXT GENERATION DEBUG (Fine-Grain Level) ====

[INFO] ==== GRAPH CONTEXT DEBUG ====
[INFO] Graph context enabled: True
[INFO] Graph context size: 113272 characters
[INFO] Graph context items (Dependencies for): 7
[INFO] Prompt total tokens (with graph): 25502
[INFO] Graph context preview (first 500 chars): ...
[INFO] ==== END GRAPH CONTEXT DEBUG ====
```

### Fallback 検出

```
[WARNING] ⚠️ FALLBACK TRIGGERED: Token count exceeds 128000,
          switching to non-graph template
[INFO] Prompt total tokens (without graph, fallback): 21345
```

---

## 重要な発見と注意点

### ポイント1: グラフは Fine-Grain Level のみ

Related Level ではグラフが使用されていません。つまり：
- グラフはあくまで「補助情報」
- 主要な情報は Related Level で決定される
- グラフが大きすぎると、必要なファイルコンテンツが削減される

### ポイント2: Token 管理の仕組み

```
プロンプト計算:
  = problem_statement (固定)
  + file_contents（Related Level から） ← 削減される可能性
  + code_graph（グラフコンテキスト）
  + template 説明文
  + last_search_results

合計 > 128,000 → ファイルコンテンツが削除される
```

### ポイント3: グラフコンテキスト生成の時間計算量

```
O(n * m)

n = found_related_locs の関数・クラス数（通常 5-20）
m = 各関数の 1-hop 依存関係数（通常 30-100）

期待値: n=10, m=50 → 500 タグの処理
実際のグラフ内容: 23,040 タグ全体から、それぞれを検索
```

---

## まとめ

PatchPilot の RepoGraph 統合は **Fine-Grain Level でのみ** 行われます。グラフコンテキストは、各関数・クラスの 1-hop 依存関係を表示することで、修復に必要な行を特定するのを支援することを目的としています。

しかし、現在の実装では：
1. グラフサイズが大きい（28,323 トークン）
2. ファイルコンテンツが圧迫される（-50,199 トークン）
3. 修復に必要な情報が失われる（-5.6pp のパフォーマンス低下）

という問題が生じています。

