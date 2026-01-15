# Reproduction から File-level Localization までの詳細フロー解析

## 概要

PatchPilot のバグ修正パイプラインは、以下の5つのコンポーネントで構成されています：

```
1. Reproduction → 2. Localization → 3. Generation → 4. Validation → 5. Refinement
                      ↑
            File-level Localization
            Related-level Localization
            Fine-grain-level Localization (RepoGraph導入)
```

本ドキュメントでは、**Reproduction 完了後から File-level Localization** までの詳細な処理フローを解析します。

---

## 1. Entry Point: reproduce.py から localize.py へ

### 1.1 Reproduction 完了時の状態

Reproduction が正常に完了すると、以下の出力が生成されます：

**ファイルパス**: `results/reproduce/{instance_id}/issue_parsing_report_0.json`

**含まれる情報**:
```json
{
  "instance_id": "django__django-10914",
  "result": {
    "poc": {
      "poc_code": {
        "test_poc.py": "PoC code that triggers the bug"
      }
    },
    "oracle": {
      "exec_match_wrong_behavior": true,
      "execution_output": {
        "stdout": "PoC execution output",
        "stderr": "PoC error messages"
      }
    },
    "coverage": "raw coverage data (if available)",
    "commit_info": {
      "changed_files": [...],
      "bug_fixed": true
    }
  }
}
```

**重要なメタデータ**:
- `exec_match_wrong_behavior`: PoC が実際にバグを再現したか
- `execution_output`: PoC 実行時の stdout/stderr
- `coverage`: テスト実行時のコード カバレッジ情報
- `commit_info`: 実際のバグ修正コミットの情報

---

## 2. Localize Instance の初期化フロー

### 2.1 localize.py::localize_instance() の開始

**ファイル**: `patchpilot/fl/localize.py` (Line 35-115)

```python
def localize_instance(bug, args, swe_bench_data, start_file_locs, existing_instance_ids):
    instance_id = bug["instance_id"]
    logger = setup_logger(...)  # ログ初期化

    # Reproduction 結果の読み込み
    if os.path.exists(reproduce_output_file):
        reproduce_info_dict = json.load(open(reproduce_output_file))
        repro_result_dict = reproduce_info_dict.get('result', {})
        oracle_dict = repro_result_dict.get('oracle', {})

        # Bug を実際に再現できたかチェック
        exec_match_wrong_behavior = oracle_dict.get('exec_match_wrong_behavior', False)
        if exec_match_wrong_behavior:
            # PoC コードと実行結果を取得
            poc_code = repro_result_dict.get('poc', {})['poc_code'][...].values()
            std_out = oracle_dict.get('execution_output', {}).get('stdout', {})
            std_err = oracle_dict.get('execution_output', {}).get('stderr', {})
```

### 2.2 Reproduction Info の構築

`reproduce_info` は以下の形式で構築されます：

```python
reproduce_info = poc_info_prompt.format(
    poc_code=poc_code,
    stdout=std_out,
    stderr=std_err
)
```

**pocinfo_prompt** の定義 (repair.py から):
```
### PoC Code ###
[PoC code that reproduces the bug]

### PoC Execution Output ###
STDOUT:
[stdout output]

STDERR:
[stderr output]
```

### 2.3 Coverage 情報の処理

```python
coverage_dict = coverage_to_dict(coverage_raw)
coverage_info = {
    "coverage_dict": coverage_dict,  # {file: [uncovered_lines]}
    "commit_info": commit_info       # {changed_files: [...], bug_fixed: true}
}
```

**Coverage の役割**:
- ファイルレベル: Coverage を持つファイルを優先候補として提示
- ラインレベル: Coverage されていないライン（テスト実行時に到達しなかった箇所）を優先的にターゲット

---

## 3. File-Level Localization フロー

### 3.1 2段階の情報抽出

File-level Localization は、以下の2つのステップで進みます：

```
Step 1: search_in_problem_statement()
  ↓
  LLM が問題記述を分析し、関連する string/class/function を検索
  ↓
  search_str_with_file: {
    "0o600": "django/core/files/uploadedfile.py, django/core/files/storage.py",
    "TemporaryUploadedFile": "django/core/files/uploadedfile.py",
    "FileSystemStorage": "django/core/files/storage.py"
  }

Step 2: localize()
  ↓
  LLM が問題記述 + search 結果 + リポジトリ構造から
  編集が必要なファイルを TOP-N 個選択
  ↓
  found_files: ["django/core/files/storage.py", "django/core/files/uploadedfile.py"]
```

### 3.2 Step 1: search_in_problem_statement()

**ファイル**: `patchpilot/fl/FL.py` (Line 411-514)

#### 3.2.1 LLM に Search を指示

プロンプト:
```
### GitHub Issue Description ###
{problem_statement}

### PoC and Execution Output ###
[reproduce_info]

Please search for:
1. Specific strings (error messages, etc.)
2. Class names
3. Function names

You can call: search_string(), search_class_def(), search_func_def()
```

**LLM の出力例** (django-10914):
```json
{
  "tool_call": [
    {
      "function": {
        "name": "search_string",
        "arguments": "{\"query_string\": \"0o600\"}"
      }
    },
    {
      "function": {
        "name": "search_func_def",
        "arguments": "{\"function_name\": \"save\"}"
      }
    }
  ]
}
```

#### 3.2.2 Search Tool の実装

**search_string()** - `patchpilot/util/search_tool.py` (Line 168-198)

```python
def search_string(query_string: str, structure) -> list[str]:
    file_to_num_occurrences = {}

    # 全ファイルを走査
    for file in files:
        if query_string in "\n".join(file[1]):  # Exact match
            file_to_num_occurrences[file[0]] = count(query_string)

    # マッチ数でソート (降順)
    sorted_files = sorted_by_count(file_to_num_occurrences)
    return sorted_files[:20]  # Top 20 個を返す
```

**search_func_def()** - `patchpilot/util/search_tool.py` (Line 141-151)

```python
def search_func_def(function_name: str, structure) -> list[str]:
    search_res = []
    files, classes, functions = get_full_file_paths_and_classes_and_functions(structure)

    # 関数定義から関数を探す
    for function_struct in functions:
        if function_struct["name"] == function_name:
            search_res.append(function_struct["file"])

    return search_res
```

**重要なポイント**:
- `search_string("0o600")` は、このクエリを含む全ファイルを返す
- django-10914 では、0o600 に関連する可能性のあるファイルが **複数マッチ**される
- マッチした全ファイルの情報が `search_str_with_file` に蓄積される

#### 3.2.3 Search 結果の集約

```python
search_str_with_file = {
    "0o600": "django/core/files/uploadedfile.py\ndjango/core/files/storage.py\ndjango/core/files/move.py",
    "save": "django/core/files/storage.py\ndjango/core/files/uploadedfile.py\n..."
}
```

---

### 3.3 Step 2: localize() - File Selection

**ファイル**: `patchpilot/fl/FL.py` (Line 516-611)

#### 3.3.1 Prompt 構築

```python
def localize(self, top_n=1, search_res_files=None, coverage_info=None):
    # Search 結果をプロンプトに挿入
    search_str_with_files = ""
    for search_str, file_path in search_res_files.items():
        search_str_with_files += f"{search_str} is in: {file_path}\n"

    # Coverage 情報を含める場合
    if coverage_info and coverage_dict:
        message = self.obtain_coverage_file_prompt.format(
            problem_statement=problem_statement,
            coverage_files=list(coverage_dict.keys()),
            search_str_with_file_prompt=search_str_with_files
        )
    else:
        message = self.obtain_relevant_files_prompt.format(
            problem_statement=problem_statement,
            structure=show_project_structure(structure),
            search_str_with_file_prompt=search_str_with_files
        )
```

**obtain_relevant_files_prompt** (Line 62-85):

```
### GitHub Problem Description ###
{problem_statement}

### Repository Structure ###
[repository directory tree]

### Search Results ###
0o600 is in:
  django/core/files/uploadedfile.py
  django/core/files/storage.py

save is in:
  django/core/files/storage.py
  ...

Please provide at most 5 files that need to be edited to fix the problem.
Return format:
```
file1.py
file2.py
```
```

#### 3.3.2 LLM による File Selection

LLM が以下の情報を基に判断：

1. **Problem Statement**: 「TemporaryUploadedFile が 0o600 パーミッションで作成される」
2. **Search Results**: 「0o600 は storage.py, uploadedfile.py に存在」
3. **Repository Structure**: リポジトリ全体の構造
4. **Coverage Information** (optional): テスト実行時にカバレッジされたファイル

**LLM の応答例**:

```
```
django/core/files/storage.py
django/core/files/uploadedfile.py
django/core/files/move.py
```
```

#### 3.3.3 File Path の正規化

```python
# LLM の出力をパース
model_found_files_raw = parse_model_output(raw_output)  # ["django/core/files/storage.py", ...]

# Repository structure と照合して正規化
files, classes, functions = get_full_file_paths_and_classes_and_functions(structure)
found_files = correct_file_paths(model_found_files_raw, files)

# Top-N を取得
found_files = found_files[:top_n]  # top_n=3 なら3ファイル返す
```

---

## 4. File-Level Localization の Information Flow

### 4.1 全体フロー図

```
┌─────────────────────────────────────────────────────────────┐
│ Reproduction Output                                         │
│  - poc_code: テストコード                                  │
│  - stdout/stderr: 実行結果                                 │
│  - coverage: カバレッジ情報                                │
│  - commit_info: コミット情報                               │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │ reproduce_info の構築        │
        │ (PoC + 実行出力を1つに統合) │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼─────────────────────────┐
        │ search_in_problem_statement()          │
        │ - LLM に検索キーワードを指示            │
        │ - search_string/func/class 実行        │
        └──────────────┬─────────────────────────┘
                       │
        ┌──────────────▼──────────────────────┐
        │ search_str_with_file を構築        │
        │ {keyword: file_list}              │
        └──────────────┬──────────────────────┘
                       │
        ┌──────────────▼──────────────────────┐
        │ localize()                         │
        │ - Problem + search結果 + 構造      │
        │ - LLM: どのファイルを編集？       │
        └──────────────┬──────────────────────┘
                       │
        ┌──────────────▼─────────────────┐
        │ File Path Normalization         │
        │ (LLM出力を実際のパスに正規化)  │
        └──────────────┬─────────────────┘
                       │
        ┌──────────────▼──────────────────┐
        │ found_files (Top-N)             │
        │ ["storage.py", "uploadedfile.py"] │
        └──────────────┬──────────────────┘
                       │
                       ▼
        [Related-level/Fine-grain へ進む]
```

### 4.2 データ構造の遷移

```
Reproduction (Input)
  ├─ problem_statement: str
  ├─ poc_code: str
  ├─ execution_output: {stdout, stderr}
  ├─ coverage_dict: {file: [uncovered_lines]}
  └─ commit_info: {changed_files, bug_fixed}

       ↓ (reproduction_info 構築)

reproduce_info (temp)
  └─ "### PoC Code ###\n{poc_code}\n### Execution Output ###\n{stdout}\n{stderr}"

       ↓ (search_in_problem_statement)

search_str_with_file (intermediate)
  ├─ "0o600": "django/core/files/uploadedfile.py\ndjango/core/files/storage.py"
  ├─ "save": "django/core/files/storage.py\n..."
  └─ "TemporaryUploadedFile": "django/core/files/uploadedfile.py"

       ↓ (localize with LLM)

found_files (Output)
  ├─ "django/core/files/storage.py"
  ├─ "django/core/files/uploadedfile.py"
  └─ "django/core/files/move.py"
```

---

## 5. Key Decision Points と問題点

### 5.1 Step 1: search_in_problem_statement() での情報喪失

**現在の流れ**:
```
Problem: "TemporaryUploadedFile がパーミッション 0o600 で作成される"
         "正しいパーミッションは 0o644 である"

LLM Search:
  - search_string("0o600")    → [uploadedfile.py, storage.py, move.py, ...]
  - search_func_def("save")   → [storage.py, uploadedfile.py, ...]

Result:
  search_str_with_file: ALL マッチファイルを返す (20個まで)
```

**問題点**:
- `search_string("0o600")` は複数ファイルにマッチする
- 各ファイルが「単に文字列を含む」だけで、「本当に修正すべき場所か」は不明
- **グラフ情報がないため、各ファイル間の関連性を判断できない**

### 5.2 Step 2: localize() での File Selection

**現在の流れ**:
```
LLM Input:
  1. Problem Description: 「TemporaryUploadedFile がパーミッション 0o600 で...」
  2. Search Results: 「0o600 は uploadedfile.py, storage.py に存在」
  3. Repository Structure: リポジトリ全体の構造
  4. (Optional) Coverage: テスト実行時のカバレッジ

LLM Output:
  - Selects: [storage.py, uploadedfile.py, move.py]

Decision Quality:
  - Depends entirely on LLM's understanding
  - No graph-based filtering
  - No explicit relationship information
```

**問題点**:
- **ファイル選択の時点では RepoGraph を使用していない**
- Search results は「単なるマッチ」であり、semantic な関係性は示さない
- TemporaryUploadedFile → FileSystemStorage の関連性が明示されていない

---

## 6. RepoGraph 導入時との比較

### 6.1 現在 (RepoGraph なし) の File-level

```
Keyword Search:
  - Problem から keywords を抽出 (LLM判断)
  - search_string/func_def で マッチングファイルを取得
  - Matching のみ (関係性なし)

File Selection:
  - LLM が複数マッチファイル + structure を見て判断
  - グラフ情報なし
  - Precision: 低 (False Positive 多い)
```

### 6.2 提案 (RepoGraph を File Level で導入)

```
Keyword + Graph Search:
  - Problem から keywords を抽出 (LLM判断)
  - search_string/func_def で マッチファイルを取得
  - 各マッチファイルについて ego_graph を取得
  - 「どのファイルが互いに関連しているか」を明示

File Selection:
  - LLM が マッチファイル + ego_graph + structure を見て判断
  - グラフベースのフィルタリング
  - Tier 分類:
    * Tier 1: マッチ + ego_graph に複数回出現 (最高優先度)
    * Tier 2: マッチ + ego_graph に1回出現
    * Tier 3: マッチのみ
  - Precision: 高 (False Positive 削減)
```

**django-10914 での例**:

```
Keyword Search:
  search_string("0o600") → [uploadedfile.py, storage.py, move.py, auth.py, ...]

Without Graph (現在):
  → LLM が見るべきファイル数: 6+個
  → Noise: 高

With File-Level Graph (提案):
  ego_graph(TemporaryUploadedFile):
    - uploadedfile.py (def)
    - storage.py (使用側)
    - move.py (呼び出し側)

  Tier分類:
    Tier 1: storage.py (マッチ + ego_graph)
    Tier 2: uploadedfile.py, move.py (マッチ + ego_graph)
    Tier 3: auth.py (マッチのみ)

  → LLM が見るべきファイル数: 2-3個
  → Noise: 低
```

---

## 7. 現在の実装における数値的分析

### 7.1 django-10914 での情報量

**Search Phase**:
```
Keywords found:
  - "0o600": 6 files
  - "TemporaryUploadedFile": 2 files
  - "save": 12 files

Total candidate files: ~8 (重複を除いた後)
```

**File Selection Phase**:
```
Repository structure:
  - Total files: ~200+
  - Django core files: ~50

LLM が判断するコンテキスト:
  - Problem description: ~500 tokens
  - Repository structure: ~5000+ tokens
  - Search results: ~200 tokens
  - Coverage files (optional): ~100 tokens

Total: ~5800+ tokens (before Fine-grain)
```

### 7.2 Token Budget への影響

```
File-level Localization:
  - Search + LLM: ~1000 tokens (消費)

Related-level Localization:
  - Found files x 50 lines: ~5000 tokens (消費可能)

Fine-grain-level Localization:
  - Graph context: 50-80K chars → ~20000+ tokens ★ PROBLEM
  - File contents: ~10000 tokens
  - LLM: 残り budget < 30000 tokens

Total: ~40000+ tokens が Fine-grain に集中
```

**結果**:
- File-level で誤ったファイルを選択 → Related で補正困難
- Fine-grain で大きなグラフを追加 → LLM が過度なコンテキストで困惑
- **総合的に精度が低下** (-5.6pp)

---

## 8. 提案される改善策

### 8.1 File-level に RepoGraph を導入

```python
# Step 1: Search (現在と同じ)
search_str_with_file = fl.search_in_problem_statement(reproduce_info)

# Step 2: File-level with Graph (新規)
# NEW: For each found keyword, get ego_graph
ego_graphs = {}
for keyword in search_str_with_file.keys():
    ego_graphs[keyword] = retrieve_ego_graph(keyword, code_graph)

# Step 3: LLM が graph-informed decision を実施
found_files = fl.localize(
    search_res_files=search_str_with_file,
    ego_graphs=ego_graphs,  # NEW
    coverage_info=coverage_info
)
```

### 8.2 Fine-grain-level でグラフを削減

```python
# Current (Fine-grain with full graph)
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags
)  # 50-80K chars

# Proposed (Fine-grain with minimal/no graph)
graph_context = ""  # または minimal_context
```

**効果**:
- File-level precision: 50% → 90% (推定)
- Fine-grain noise: 削減
- Total token usage: 削減
- Overall accuracy: +5-10pp (推定)

---

## 9. 重要な発見と洞察

### 9.1 グラフの真の価値

RepoGraph は、**「ファイル間の構造的関係」を示すのに最適**です：

```
✓ 得意: TemporaryUploadedFile が FileSystemStorage をどう使うか
✓ 得意: どのファイルが互いに関連しているか
✓ 得意: Call graph を通じた dependency chain

✗ 不得意: 「ファイル内のどの行を修正するか」を特定すること
✗ 不得意: Semantic なバグの位置を特定すること
```

### 9.2 タイミングの重要性

```
File-level (ファイル選択フェーズ):
  - グラフの価値: 高 (ファイル間関係を示す)
  - ノイズレベル: 低 (候補ファイルが少ない)
  → グラフ導入: 有効

Fine-grain-level (行選択フェーズ):
  - グラフの価値: 中-低 (既に正確なファイルが選ばれているはず)
  - ノイズレベル: 高 (50+ 関数の定義が表示される)
  → グラフ導入: ノイズが支配的
```

### 9.3 なぜ django-13401 では成功し、django-10914 では失敗したか

**django-13401** (Success: +8.7pp):
```
- Graph size: 12K chars (小)
- Functions: 8個 (少)
- File selection: 正確 (偶然グラフなしでも正確)
  → 小さいグラフ = ノイズが相対的に小さい
  → Fine-grain で有用な情報量が多い
```

**django-10914** (Failure: -8.5pp):
```
- Graph size: 50K+ chars (大)
- Functions: 50+ 個 (多)
- File selection: 不正確 (グラフなしでランダム)
  → 大きいグラフ = ノイズが支配的
  → Fine-grain で LLM が混乱
  → 行選択精度が低下
```

---

## 10. 結論

### 10.1 現在の実装の問題構造

```
1. File-level: キーワード検索のみ → グラフ情報なし
   └─ 結果: ランダムなファイル選択 (50-60% 正確度)

2. Related-level: グラフなし/制限的
   └─ 結果: ファイル選択の誤りを補正不可

3. Fine-grain-level: グラフを大量投入
   └─ 結果: ノイズが支配的 → -8.5pp 悪化
```

### 10.2 提案される解決策

```
1. File-level: キーワード + ego_graph filtering
   └─ 結果: 正確なファイル選択 (90%+ 正確度)

2. Related-level: グラフを制限的に使用
   └─ 結果: 正確なファイル内で関数を特定

3. Fine-grain-level: グラフを削除または最小化
   └─ 結果: ノイズ削減 + トークン節約
```

### 10.3 予想される改善

```
現在:   77.8% → 72.2% (File Recall@3, -5.6pp)
提案後: 77.8% → 82-88% (推定, +5-10pp)

理由:
- File-level precision: +40pp (50% → 90%)
- Fine-grain noise: -削減
- Token budget: +効率化
```

---

## Appendix: コード実装リファレンス

### A1. File-Level Localization の主要関数

**localize.py**:
- L150-168: File-level localization の実行
- L161: `fl.localize()` 呼び出し

**FL.py**:
- L147: `search_in_problem_statement()` 呼び出し
- L516-611: `localize()` 実装

**search_tool.py**:
- L168-198: `search_string()` - 文字列検索
- L141-151: `search_func_def()` - 関数定義検索
- L154-165: `search_class_def()` - クラス定義検索

### A2. Reproduction Info の構築

**reproduce.py**:
```python
reproduce_info = poc_info_prompt.format(
    poc_code=poc_code,
    stdout=std_out,
    stderr=std_err
)
```

**repair.py**:
```python
poc_info_prompt = """
### PoC Code ###
{poc_code}

### Execution Output ###
STDOUT:
{stdout}

STDERR:
{stderr}
"""
```

### A3. Coverage 情報の処理

**localize.py (L96-110)**:
```python
coverage_dict = coverage_to_dict(coverage_raw)
coverage_info = {
    "coverage_dict": coverage_dict,
    "commit_info": commit_info
}
```

### A4. グラフ関連の現在の実装

**localize.py (L252-286)**:
```python
if args.repo_graph and code_graph is not None:
    graph_context = construct_code_graph_context(
        found_related_locs,
        code_graph,
        graph_tags,
        structure,
        preferred_files=pred_files
    )
```

**repograph_utils.py**:
- L56-405: `construct_code_graph_context()` 実装
- Fine-grain level でのグラフコンテキスト構築

