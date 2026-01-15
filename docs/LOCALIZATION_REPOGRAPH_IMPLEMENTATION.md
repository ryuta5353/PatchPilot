# Localization での RepoGraph 実装詳細

本ドキュメントでは、PatchPilot の Localization フェーズにおける RepoGraph 統合の実装詳細を説明する。

---

## 1. 実装タイミング

RepoGraph は Localization の **Related Level 直前** で統合される。

```
Localization フロー:
┌─────────────────────────────────────────────────────────────────────┐
│ Step 0: search_in_problem_statement()                               │
│         → 問題文からキーワード検索                                    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 1: File Level                                                  │
│         → ファイル候補を特定 (found_files)                           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ ★ RepoGraph 統合ポイント (Related Level 直前)                       │
│                                                                     │
│ 1. graph_tags 読み込み                                              │
│ 2. problem_statement からキーワード抽出                             │
│ 3. キーワードに一致する関数の Caller/Callee 取得                     │
│ 4. コンテキスト文字列を生成                                          │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 2: Related Level                                               │
│         → 関数・クラス候補を特定 (RepoGraph コンテキスト付き)         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 3: Line Level                                                  │
│         → 行番号を特定                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### コード位置

`patchpilot/fl/localize.py` L267-279

```python
# Related Level の直前で RepoGraph コンテキストを生成
keyword_graph_context = ""
if args.keyword_graph_context and graph_tags is not None:
    keywords = extract_keywords_from_problem(problem_statement, graph_tags, pred_files)
    keyword_graph_context = build_caller_callee_context(
        keywords, graph_tags, pred_files,
        max_callers_per_func=5, max_callees_per_func=5,
        max_keywords=20, max_functions=30
    )
```

---

## 2. 探索の入力元

### 2.1 入力データ

| 入力 | 内容 | 例 |
|------|------|-----|
| `problem_statement` | GitHub Issue の問題記述 | `"TypeError when calling serialize() with nested objects..."` |
| `graph_tags` | RepoGraph のタグデータ | `tags_{instance_id}.json` |
| `pred_files` | File Level で特定したファイル | `["django/db/models/query.py", ...]` |

### 2.2 キーワード抽出ロジック

**関数:** `extract_keywords_from_problem()` (`patchpilot/fl/repograph_utils.py` L607-676)

```python
# Step 1: 正規表現でキーワード候補を抽出
snake_case_pattern = r'\b([a-z_][a-z0-9_]{2,})\b'    # get_queryset, serialize など
camel_case_pattern = r'\b([A-Z][a-zA-Z0-9]+)\b'       # QuerySet, TypeSerializer など

# Step 2: pred_files 内のタグ名と照合
# graph_tags から、pred_files 内の def タグを収集
tag_names_in_files = {'functions': set(), 'classes': set()}
for tag in graph_tags:
    if tag['kind'] == 'def' and tag['rel_fname'] in found_files:
        if tag['category'] == 'function':
            tag_names_in_files['functions'].add(tag['name'])
        elif tag['category'] == 'class':
            tag_names_in_files['classes'].add(tag['name'])

# Step 3: フィルタリング（タグに存在するもののみ）
# 部分一致: キーワードがタグ名に含まれるか（3文字以上）
```

**出力例:**

```python
{
    'functions': ['serialize', 'get_queryset', 'handle_request'],
    'classes': ['TypeSerializer', 'QuerySet']
}
```

### 2.3 ストップワードによるフィルタリング

ノイズを削減するため、一般的な単語を除外する。

```python
KEYWORD_STOP_WORDS = {
    # 一般的な英単語（冠詞・前置詞・接続詞など）
    'and', 'or', 'not', 'for', 'with', 'from', 'the', 'all', 'any', 'but',
    'are', 'can', 'has', 'use', 'new', 'old', 'one', 'two', 'this', 'that',
    'into', 'also', 'been', 'have', 'will', 'would', 'could', 'should',

    # Python キーワード・組み込み
    'none', 'true', 'false', 'self', 'cls',

    # 非常に一般的な変数名
    'name', 'value', 'data', 'type', 'key', 'item', 'items', 'result',
    'args', 'kwargs', 'info',
}
```

---

## 3. Caller/Callee 取得ロジック

### 3.1 概要

**関数:** `build_caller_callee_context()` (`patchpilot/fl/repograph_utils.py` L1057-1155)

```python
# 各キーワードについて Caller と Callee を取得
for keyword in all_keywords:
    # Callers: この関数を呼び出している関数
    # found_files 内のみ対象（pred_files でフィルタ）
    callers_by_func = get_callers(keyword, graph_tags, found_files, max_callers_per_func)

    # Callees: この関数が呼び出している関数
    # found_files 内のみ対象
    callees_by_func = get_callees(keyword, graph_tags, found_files, max_callees_per_func)
```

### 3.2 制限パラメータ

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `max_callers_per_func` | 5 | 関数あたりの最大 Caller 数 |
| `max_callees_per_func` | 5 | 関数あたりの最大 Callee 数 |
| `max_keywords` | 20 | 処理する最大キーワード数 |
| `max_functions` | 30 | 出力する最大関数数 |

### 3.3 Caller 抽出ロジック

**関数:** `get_callers()` (`patchpilot/fl/repograph_utils.py` L919-972)

```python
def get_callers(keyword, graph_tags, found_files, max_count_per_func):
    """キーワードにマッチした関数を呼び出している関数（caller）を取得"""
    for tag in graph_tags:
        if tag['kind'] != 'ref':
            continue
        if found_files is not None and tag['rel_fname'] not in found_files:
            continue
        if keyword not in tag['name'].lower():
            continue

        # refタグを含む関数を特定（同一ファイル内で直前のdef関数）
        caller = get_containing_function(tag, graph_tags)
```

**`get_containing_function()` の動作:**

```python
def get_containing_function(ref_tag, graph_tags):
    """ref タグを含む関数を特定する"""
    ref_file = ref_tag['rel_fname']
    ref_line = ref_tag['line']

    # 同じファイル内のdef関数タグを取得し、行番号でソート
    def_tags_in_file = [t for t in graph_tags
                        if t['rel_fname'] == ref_file
                        and t['kind'] == 'def'
                        and t['category'] == 'function']
    def_tags_in_file.sort(key=lambda t: t['line'])

    # ref_line より前で最も近いdef関数を見つける
    containing_func = None
    for tag in def_tags_in_file:
        if tag['line'] <= ref_line:
            containing_func = tag
        else:
            break

    return {'name': containing_func['name'], 'file': containing_func['rel_fname']}
```

### 3.4 Callee 抽出ロジック

**関数:** `get_callees()` (`patchpilot/fl/repograph_utils.py` L975-1054)

```python
def get_callees(keyword, graph_tags, found_files, max_count_per_func):
    """キーワードにマッチした関数が呼び出している関数（callee）を取得"""

    # キーワードにマッチするdef関数を見つける
    for def_tag in matching_defs:
        def_file = def_tag['rel_fname']
        def_line = def_tag['line']

        # 次の関数定義の行を見つけて、関数の終了位置を推定
        next_def_line = find_next_function_definition(def_file, def_line, graph_tags)
        func_end = next_def_line - 1 if next_def_line else def_line + 500

        # 関数の範囲（def_line ~ func_end）内のrefタグを収集
        for tag in graph_tags:
            if tag['kind'] == 'ref' and def_line <= tag['line'] <= func_end:
                callees.append(tag['name'])
```

---

## 4. 生成されるコンテキスト形式

### 4.1 出力フォーマット

```
## {関数名}
Callers:
  - {ファイルパス}::{呼び出し元関数名}
  - ...
Callees:
  - {ファイルパス}::{呼び出し先関数名}
  - ...
```

### 4.2 出力例

  ### Dependencies for get_queryset
  location: django/db/models/query.py lines 142 - 180
  name: _fetch_all
  contents:
  def _fetch_all(self):
      if self._result_cache is None:
          self._result_cache = list(self._iterable_class(self))
      ...

  location: django/db/models/query.py lines 200 - 250
  name: __iter__
  contents:
  def __iter__(self):
      self._fetch_all()
      return iter(self._result_cache)

## 5. プロンプト

### 5.1 テンプレート

`obtain_relevant_functions_and_vars_from_compressed_files_with_dependencies_prompt` (`patchpilot/fl/FL.py` L480-530)

```
Please look through the following GitHub Problem Description and the Skeleton of Relevant Files.
Identify all locations that need inspection or editing to fix the problem, including directly related areas as well as any potentially related global variables, functions, and classes.
For each location you provide, either give the name of the class, the name of a method in a class, the name of a function, or the name of a global variable.
You should explicitly analyse whether a new function needs to be added, output whether a new function should be added and why. If a new function needs to be added, you should provide the class where the new function should be introduced as one of the locations, listing only the class name in this case. All other locations should be returned as usual, so do not return only this one class.

### GitHub Problem Description ###
{problem_statement}

### Skeleton of Relevant Files ###
Each file section is introduced by
### File: path/to/file.py ###
{file_contents}

### Function Dependencies ###

The file skeletons above show the structure but not how functions interact.
Below are caller/callee relationships as supplementary context:
- Callers: Functions that call this function
- Callees: Functions that this function calls

Use this to understand function interactions not visible in the skeleton.

{dependencies}

###

Please provide the complete set of locations as either a class name, a function name, or a variable name.
Note that if you include a class, you do not need to list its specific methods.
You can include either the entire class or don't include the class name and instead include specific methods in the class.
Here is the format you need to follow, don't forget the "```":
### Examples:
```
full_path1/file1.py
function: my_function_1
class: MyClass1
function: MyClass2.my_method

full_path2/file2.py
variable: my_var
function: MyClass3.my_method

full_path3/file3.py
function: my_function_2
function: my_function_3
function: MyClass4.my_method_1
class: MyClass5
```

Return just the locations. Do not include any comments or explanations. Do not forget the "```".
```

### 5.2 プロンプト構成

| セクション | 内容 |
|-----------|------|
| `{problem_statement}` | GitHub Issue の問題記述 |
| `{file_contents}` | File Level で特定したファイルの Skeleton（関数・クラス定義のみ） |
| `{dependencies}` | **RepoGraph から生成した Caller/Callee コンテキスト** |

---

## 6. 設計意図

### 6.1 なぜ Related Level で統合したか

| レベル | 内容 | RepoGraph の必要性 |
|--------|------|-------------------|
| File Level | ファイル名のみで判断 | 不要（構造情報は不要） |
| **Related Level** | 関数・クラスを特定 | **必要（呼び出し関係が有用）** |
| Line Level | 具体的な行番号 | 不要（すでに関数が特定されている） |

Related Level では Skeleton（関数・クラスの構造）のみが提供されるが、**関数間の呼び出し関係は見えない**。RepoGraph の Caller/Callee 情報を追加することで、LLM が依存関係を把握できる。

### 6.2 フィルタリングの理由

```python
# Localization では pred_files 内のみを対象
callers = get_callers(keyword, graph_tags, found_files, ...)  # ★ found_files でフィルタ
callees = get_callees(keyword, graph_tags, found_files, ...)  # ★ found_files でフィルタ
```

| 設計判断 | 理由 |
|---------|------|
| Callers を pred_files 内に限定 | 外部ファイルからの呼び出しはノイズになる |
| Callees を pred_files 内に限定 | バグ箇所の絞り込みフェーズでは関連性の高い情報のみが有用 |

**目的:** Localization はバグ箇所の絞り込みフェーズであり、すでに File Level で特定したファイル内での依存関係のみが有用。

---

## 7. 使用方法

### 7.1 コマンドラインフラグ

```bash
python patchpilot/fl/localize.py \
    --keyword_graph_context \
    --code_graph_dir path/to/RepoGraph_cache \
    ...
```

| フラグ | 説明 |
|--------|------|
| `--keyword_graph_context` | Related Level で Caller/Callee コンテキストを追加 |
| `--code_graph_dir` | RepoGraph のキャッシュディレクトリ（`tags_*.json` を含む） |

### 7.2 必要なファイル

```
RepoGraph_cache/
├── tags_{instance_id}.json    # タグデータ（必須）
└── graph_{instance_id}.pkl    # グラフデータ（keyword_graph_context では不要）
```
