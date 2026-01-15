# File Level RepoGraph 統合 実装計画書

## 1. 概要

File Level Localization に RepoGraph を統合し、キーワード検索では発見できないファイルを候補に追加する。

**既存機能への影響**: なし（`--repo_graph` フラグが無効の場合、従来通りの動作）

---

## 1.5 RepoGraph データ構造（調査結果）

### 1.5.1 graph_tags（JSON）構造

**ファイル**: `{code_graph_dir}/tags_{instance_id}.json`

```python
{
  "fname": "playground/.../django/__init__.py",  # 絶対パス（使わない）
  "rel_fname": "django/__init__.py",             # 相対パス ← これを使う
  "line": 7,
  "name": "setup",                               # 関数/クラス名
  "kind": "def" or "ref",                        # def=定義, ref=参照（呼び出し）
  "category": "function" or "class",
  "info": "def setup(...): ..."                  # コード内容
}
```

**Caller取得のロジック**:
- `kind == "ref"` のタグは「その関数を呼び出している場所」
- `rel_fname` でどのファイルから呼ばれているか分かる
- 例: `{name: "setup", kind: "ref", rel_fname: "django/core/management/__init__.py"}`
  → `setup` 関数は `django/core/management/__init__.py` から呼ばれている

### 1.5.2 Caller ファイルの取得方法

**graph_tags の ref タグを直接使用**:
```python
# function_name を呼び出しているファイルを取得
ref_tags = [t for t in graph_tags if t['name'] == function_name and t['kind'] == 'ref']
caller_files = set(t['rel_fname'] for t in ref_tags)
```

**例**:
```python
target = 'ValidationError'

ref_tags = [t for t in graph_tags if t['name'] == target and t['kind'] == 'ref']
# → 131件の ref タグ

caller_files = set(t['rel_fname'] for t in ref_tags)
# → {'django/contrib/admin/forms.py', 'django/forms/fields.py', ...}
```

### 1.5.3 設計方針

**File Level では code_graph（pkl）を使用しない**。graph_tags（JSON）のみで実装する。

理由:
- graph_tags の ref タグから直接 Caller ファイルを取得できる
- シンプルな実装になる
- code_graph によるスコアリングは現時点では不要

| データ | 用途 |
|--------|------|
| `graph_tags` | Caller ファイルの取得、関数の定義場所の取得 |

### 1.5.4 既存コマンド引数との関係

| 引数 | 現在の用途 | File Level での使用 |
|------|-----------|-------------------|
| `--repo_graph` | Fine-grain Level で有効化 | **同じフラグで File Level も有効化** |
| `--code_graph_dir` | PKL/JSON のディレクトリ指定 | **既存のまま使用** |
| `--use-coverage` | Coverage 使用フラグ | Coverage Bonus 計算に使用 |

**重要**: 新規コマンド引数の追加は不要。既存の `--repo_graph` と `--code_graph_dir` をそのまま活用。

---

## 2. 処理フロー

```
[既存] Step 0: LLM が検索キーワード提案
[既存] Step 1: 検索実行 → search_str_with_file 取得
                ↓
[NEW]  Step 1.5: RepoGraph による候補拡張
                - seed_files からキーワードマッチ関数を特定
                - Caller ファイルを取得
                - スコアリング（Hub Bonus + Coverage Bonus）
                - Top-5 を推薦ファイルとして追加
                ↓
[既存] Step 2: LLM がファイル選択（拡張された情報から）
```

---

## 3. 実装詳細

### 3.1 新規関数（repograph_utils.py に追加）

#### 3.1.1 `get_seed_files_from_search_results()`

```python
def get_seed_files_from_search_results(search_str_with_file: dict) -> list[str]:
    """
    検索結果から seed_files を抽出する

    Args:
        search_str_with_file: {"keyword": "file1.py file2.py", ...}

    Returns:
        ["file1.py", "file2.py", ...] (重複なし)
    """
```

#### 3.1.2 `get_matching_functions_in_file()`

```python
def get_matching_functions_in_file(
    file_path: str,
    keywords: list[str],
    graph_tags: list[dict]
) -> list[str]:
    """
    ファイル内でキーワードを含む関数/クラス名を返す

    マッチング戦略（優先順位順）:
    1. キーワードと graph_tags の name が完全一致 & rel_fname が file_path
    2. 部分一致（キーワードが name に含まれる）& rel_fname が file_path
    3. file_path 内の全 def タグ（フォールバック）

    Args:
        file_path: 対象ファイルパス（正規化済み）
        keywords: 検索キーワードのリスト（関数名、クラス名、文字列）
        graph_tags: RepoGraph のタグ情報

    Returns:
        マッチした関数/クラス名のリスト（重複なし）

    実装例:
        # 1. file_path 内の全 def タグを取得
        defs_in_file = [t for t in graph_tags
                        if t['rel_fname'] == file_path and t['kind'] == 'def']

        matched = set()
        for keyword in keywords:
            # 2. 完全一致
            exact = [t['name'] for t in defs_in_file if t['name'] == keyword]
            if exact:
                matched.update(exact)
                continue

            # 3. 部分一致（キーワードが名前に含まれる）
            partial = [t['name'] for t in defs_in_file
                       if keyword.lower() in t['name'].lower()]
            if partial:
                matched.update(partial)
                continue

        # 4. マッチがない場合、全 def を返す（フォールバック）
        if not matched:
            matched = set(t['name'] for t in defs_in_file)

        return list(matched)
    """
```

#### 3.1.3 `get_caller_files()`

```python
def get_caller_files(
    function_name: str,
    graph_tags: list[dict],
    exclude_files: list[str] = None
) -> list[str]:
    """
    指定関数の Caller ファイルを取得する（graph_tags のみ使用）

    ロジック:
    1. graph_tags から function_name の ref タグを取得
    2. 各 ref タグの rel_fname が Caller ファイル
    3. exclude_files（seed files）は除外

    Args:
        function_name: 関数/クラス名
        graph_tags: RepoGraph のタグ情報
        exclude_files: 除外するファイル（seed files）

    Returns:
        Caller ファイルのリスト（重複なし）

    実装例:
        ref_tags = [t for t in graph_tags
                    if t['name'] == function_name and t['kind'] == 'ref']

        caller_files = set()
        for t in ref_tags:
            if exclude_files and t['rel_fname'] in exclude_files:
                continue
            caller_files.add(t['rel_fname'])

        return list(caller_files)
    """
```

#### 3.1.4 `score_and_rank_files()`

```python
def score_and_rank_files(
    caller_files: list[dict],
    seed_files: list[str],
    coverage_dict: dict,
    top_n: int = 5
) -> list[dict]:
    """
    Caller ファイルにスコアを付与してランキング（graph_tags のみ使用）

    スコアリングルール:
    - 基本点: +1（seed を呼んでいる）
    - Hub Bonus: +30（2つ以上の seed 関数を呼んでいる）
    - Coverage Bonus: +50（PoC Coverage に含まれる）

    Args:
        caller_files: Caller 情報のリスト [{"file": "...", "called_function": "..."}, ...]
        seed_files: seed ファイルのリスト
        coverage_dict: Coverage 情報 {"file.py": [line1, line2, ...], ...}
        top_n: 上位何件を返すか

    Returns:
        [{"file": "...", "score": 81, "reason": "Hub + Coverage", "calls": [{"function": "..."}]}, ...]

    実装例:
        # ファイルごとに呼び出し関係を集約
        file_to_calls = {}
        for caller in caller_files:
            f = caller['file']
            if f not in file_to_calls:
                file_to_calls[f] = []
            file_to_calls[f].append(caller['called_function'])

        results = []
        for file, called_funcs in file_to_calls.items():
            score = len(set(called_funcs))  # 基本点: 呼んでいる関数の数
            reasons = []

            # Hub Bonus
            if len(set(called_funcs)) >= 2:
                score += 30
                reasons.append("Hub file - calls multiple seed functions")

            # Coverage Bonus
            if coverage_dict and file in coverage_dict:
                score += 50
                reasons.append("Found in PoC coverage")

            # 理由がない場合
            if not reasons:
                reasons.append("Caller of seed file")

            results.append({
                "file": file,
                "score": score,
                "reason": "; ".join(reasons),
                "calls": [{"function": f} for f in set(called_funcs)]
            })

        return sorted(results, key=lambda x: x['score'], reverse=True)[:top_n]
    """
```

#### 3.1.5 `construct_file_level_graph_context()`

```python
def construct_file_level_graph_context(
    search_str_with_file: dict,
    graph_tags: list[dict],
    coverage_dict: dict = None,
    top_n: int = 5
) -> str:
    """
    File Level 用の RepoGraph コンテキストを生成する（graph_tags のみ使用）

    処理フロー:
    1. get_seed_files_from_search_results() で seed files 取得
    2. 各 seed file から get_matching_functions_in_file() でキーワードマッチ関数を特定
    3. 各関数に対して get_caller_files() で Caller 取得
       - graph_tags の ref タグで呼び出し元ファイルを直接取得
    4. score_and_rank_files() でスコアリング
    5. 上位 top_n ファイルをコンテキスト文字列に整形（reason 情報付き）

    Args:
        search_str_with_file: 検索結果 {"keyword": "file1.py file2.py", ...}
        graph_tags: タグ情報 - Caller ファイルの取得
        coverage_dict: Coverage 情報（オプション）- Coverage Bonus 計算
        top_n: 推薦ファイル数

    Returns:
        LLM に渡すための文字列形式のコンテキスト（reason 情報付き）

    実装例:
        # 1. seed files を取得
        seed_files = get_seed_files_from_search_results(search_str_with_file)
        if not seed_files:
            return ""

        # 2. キーワードリストを作成
        keywords = list(search_str_with_file.keys())

        # 3. 各 seed file からマッチング関数を特定し、Caller を取得
        all_caller_info = []
        for seed_file in seed_files:
            matching_funcs = get_matching_functions_in_file(seed_file, keywords, graph_tags)
            for func in matching_funcs:
                caller_files = get_caller_files(func, graph_tags, exclude_files=seed_files)
                for caller_file in caller_files:
                    all_caller_info.append({
                        "file": caller_file,
                        "called_function": func
                    })

        if not all_caller_info:
            return ""

        # 4. スコアリング
        ranked_files = score_and_rank_files(
            caller_files=all_caller_info,
            seed_files=seed_files,
            coverage_dict=coverage_dict,
            top_n=top_n
        )

        # 5. コンテキスト文字列を生成
        return format_graph_context(ranked_files)
    """
```

### 3.2 修正箇所

#### 3.2.1 localize.py の構造確認

**現在のlocalize.py構造（行63-168付近）**:
```python
# 行63-73: code_graph と graph_tags の読み込み（既存）
code_graph = None
graph_tags = None
if args.repo_graph:
    code_graph = pickle.load(open(os.path.join(args.code_graph_dir, f"{instance_id}.pkl"), "rb"))
    graph_tags = json.load(open(os.path.join(args.code_graph_dir, f"tags_{instance_id}.json"), "r"))

# 行136-147: Step 0 キーワード検索
search_str_with_file = fl.search_in_problem_statement(reproduce_info)

# 行149-168: file level localization
if args.file_level:
    ...
    found_files, additional_artifact_loc_file, file_traj = fl.localize(...)
```

**注意点**:
- `code_graph` と `graph_tags` は **File Level の前**に既に読み込まれている（行63-73）
- 現在は Fine-grain Level（行253-304）でのみ使用
- File Level で使用するには、Step 0 と Step 2 の間に処理を追加

#### 3.2.2 localize.py 修正案（行147-168付近）

```python
# [既存] Step 0: キーワード検索
search_str_with_file = fl.search_in_problem_statement(reproduce_info)

# [NEW] Step 1.5: RepoGraph による File Level 候補拡張
file_level_graph_context = ""
if args.repo_graph and graph_tags is not None:
    from patchpilot.fl.repograph_utils import construct_file_level_graph_context

    coverage_dict = coverage_info.get("coverage_dict", {}) if coverage_info else {}
    file_level_graph_context = construct_file_level_graph_context(
        search_str_with_file=search_str_with_file,
        graph_tags=graph_tags,
        coverage_dict=coverage_dict,
        top_n=5
    )
    logger.info(f"Generated RepoGraph context for File Level: {len(file_level_graph_context)} chars")

# [既存] file level localization
if args.file_level:
    fl = LLMFL(...)
    found_files, additional_artifact_loc_file, file_traj = fl.localize(
        mock=args.mock,
        match_partial_paths=args.match_partial_paths,
        search_res_files=search_str_with_file,
        num_samples=args.num_samples,
        top_n=args.top_n,
        coverage_info=coverage_info,
        additional_info=file_level_graph_context  # [NEW] RepoGraph 情報を追加
    )
```

**データの役割**:
- `graph_tags`: ref タグで Caller ファイルを特定（**唯一の依存**）
- `coverage_dict`: Coverage Bonus 計算（オプション）

**注意**: `code_graph`（pkl）は File Level では使用しない。Fine-grain Level でのみ使用される。

#### 3.2.2 FL.py（localize メソッド - 変更不要）

既存の `additional_info` パラメータを使用するため、メソッド自体の変更は不要。

```python
def localize(
    self, top_n=1, mock=False, match_partial_paths=False,
    search_res_files=None, num_samples=1, coverage_info=None,
    additional_info=None  # ← これを使う
):
    ...
    if additional_info:
        message = message + additional_info  # ← ここで追加される
```

---

## 4. RepoGraph コンテキストのフォーマット

```
### RepoGraph Recommendations ###
The following files are identified by analyzing code dependencies.
These files call functions/classes found in the search results.

1. django/core/files/storage.py
   - Score: 81 (Hub Bonus + Coverage Bonus)
   - Reason: Hub file - calls multiple seed functions; Found in PoC coverage
   - Calls: TemporaryUploadedFile (from uploadedfile.py), move_file (from move.py)

2. django/http/request.py
   - Score: 31 (Hub Bonus)
   - Reason: Hub file - calls multiple seed functions
   - Calls: TemporaryUploadedFile (from uploadedfile.py), InMemoryUploadedFile (from uploadedfile.py)

3. django/core/files/base.py
   - Score: 1
   - Reason: Caller of seed file
   - Calls: TemporaryUploadedFile (from uploadedfile.py)

Please consider these files when selecting the most relevant files to fix the issue.
```

---

## 5. パス正規化

RepoGraph と PatchPilot でパス形式が異なる可能性があるため、正規化関数を追加：

```python
def normalize_path(path: str) -> str:
    """
    パスを正規化する（先頭の ./ や src/ を除去、バックスラッシュを統一）
    """
    path = path.replace('\\', '/')
    if path.startswith('./'):
        path = path[2:]
    if path.startswith('src/'):
        path = path[4:]
    return path
```

---

## 6. 実装順序

### Phase 1: 基盤関数の実装
1. `normalize_path()` - パス正規化
2. `get_seed_files_from_search_results()` - seed 抽出
3. `get_matching_functions_in_file()` - キーワードマッチ

### Phase 2: RepoGraph 連携
4. `get_caller_files()` - Caller 取得
5. `score_and_rank_files()` - スコアリング

### Phase 3: 統合
6. `construct_file_level_graph_context()` - コンテキスト生成
7. localize.py の修正

### Phase 4: テスト
8. 単体テスト（各関数）
9. 統合テスト（既存機能が壊れていないことを確認）

---

## 7. 既存機能への影響確認

### 7.1 影響を受けるファイル

| ファイル | 変更内容 | 影響度 |
|---------|---------|--------|
| `repograph_utils.py` | 新規関数追加 | 低（既存関数に変更なし）|
| `localize.py` | Step 1.5 追加 | 低（フラグ制御で既存動作を維持）|
| `FL.py` | 変更なし | なし |

### 7.2 既存動作の維持

- `--repo_graph` フラグが無効の場合: `repograph_context = ""` となり、従来通りの動作
- `additional_info` が空文字の場合: プロンプトへの追加なし（既存実装の動作）

### 7.3 テスト項目

1. `--repo_graph` なしで実行 → 従来と同じ結果
2. `--repo_graph` ありで実行 → RepoGraph 情報が追加される
3. Coverage あり/なし両方でテスト
4. 検索結果が空の場合のエラーハンドリング

---

## 8. 実装上の注意点

### 8.1 Fine-grain Level との引数重複

**現状**: `--repo_graph` フラグは Fine-grain Level（行253-304）でも使用されている。

**対応**:
- 同じフラグで File Level も有効化
- File Level では `file_level_graph_context` として別の変数に格納
- Fine-grain Level では既存の `graph_context` を引き続き使用
- 両者は独立して動作するため、衝突なし

### 8.2 パス正規化の必要性

**問題**:
- `graph_tags` の `rel_fname`: `"django/core/files/storage.py"`
- `search_str_with_file` の値: `"django/core/files/storage.py"` または `"storage.py"`

**対応**:
- `normalize_path()` で先頭の `./` や `src/` を除去
- 部分一致でも検索できるように `endswith()` も併用

### 8.3 空の検索結果への対応

```python
def construct_file_level_graph_context(...):
    seed_files = get_seed_files_from_search_results(search_str_with_file)
    if not seed_files:
        return ""  # 検索結果がない場合は空文字を返す
    ...
```

### 8.4 テストファイルの除外

**問題**: Caller にテストファイルが含まれる可能性

**対応**:
```python
def get_caller_files(...):
    ...
    # テストファイルを除外
    ref_tags = [t for t in ref_tags if not is_test_file(t["rel_fname"])]
    ...

def is_test_file(path: str) -> bool:
    return "/tests/" in path or "/test_" in path or path.startswith("tests/")
```

---

## 9. 変更履歴

| 日付 | 内容 |
|------|------|
| 2025-11-28 | 初版作成 |
| 2025-11-28 | RepoGraph データ構造の詳細追記 |
| 2025-11-28 | キーワードマッチング戦略を詳細化（完全一致→部分一致→フォールバック）|
| 2025-11-28 | code_graph と graph_tags の連携を正しく修正: code_graph.predecessors() で呼び出し元関数名を取得 → graph_tags で定義ファイルを取得 |
| 2025-11-28 | **設計簡素化**: code_graph（pkl）を使用しない設計に変更。graph_tags（JSON）のみで Caller ファイルを取得する。in_degree スコアリングは現時点では不要 |
