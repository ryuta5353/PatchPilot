# File-Level Localization 拡張 - 詳細実装プラン v4

## 1. 概要

キーワード検索結果に対して、呼び出し関係（Caller）ファイルを追加し、LLMの候補選択を支援する。

## 2. 実現可能性評価

| 評価項目 | スコア |
|---------|-------|
| 目標機能の実現可能性 | **99%** |
| 既存機能を壊さない確率 | **100%** |

**理由:** 既存コード（FL.py, repair.py）を一切変更せず、新規関数追加とlocalize.pyへの統合のみで実現。

## 3. フラグ設計

### 3.1 新規フラグ: `--file_level_caller`

既存の `--repo_graph` とは**独立**した新しいフラグを追加。

```
--file_level_caller : File Level で呼び出し関係ファイルを候補に追加
--repo_graph        : Fine-grain Level (Function/Line) でグラフコンテキストを使用
```

### 3.2 フラグの組み合わせ

| コマンド | File Level | Fine-grain Level |
|---------|------------|------------------|
| (なし) | 通常 | 通常 |
| `--file_level_caller` | Caller追加 | 通常 |
| `--repo_graph` | 通常 | Graph Context |
| 両方 | Caller追加 | Graph Context |

### 3.3 処理フロー

```
┌─────────────────────────────────────────────────────────────┐
│  File Level Localization                                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Step 0: キーワード検索                                │  │
│  │ Step 0.5: ★呼び出し関係ファイル追加 (--file_level_caller)│ │
│  │ Step 1: LLMがfound_filesを選択                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                          ↓                                  │
│                    found_files 確定                         │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Function/Line Level Localization                           │
│  ※ --file_level_caller の影響なし（既存PatchPilotのまま）   │
│  ※ --repo_graph 使用時のみ Graph Context 適用              │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 実装方針: タグベース推論

検索タイプ（string/class/function）を記録する代わりに、タグデータから推論する。

```python
# 検索結果
search_str_with_file = {
    "MigrationExecutor": "django/db/migrations/executor.py",
}

# タグから推論:
# 1. "MigrationExecutor" がタグのnameと一致 → クラス/関数検索
# 2. 一致しなければ、infoフィールドから検索 → 文字列検索
# 3. どちらでも見つからなければ → スキップ
```

---

## 5. 改修箇所一覧

### 5.1 ファイル別改修内容

| ファイル | 改修内容 | 影響 |
|---------|---------|------|
| `patchpilot/fl/FL.py` | **変更なし** | なし |
| `patchpilot/repair/repair.py` | **変更なし** | なし |
| `patchpilot/fl/repograph_utils.py` | 3つの新規関数追加 | なし |
| `patchpilot/fl/localize.py` | フラグ追加 + Step 0.5追加 | 低 |

---

## 6. 詳細実装

### 6.1 repograph_utils.py への新規関数追加

**場所:** `patchpilot/fl/repograph_utils.py`（既存ファイルに追加）

#### 6.1.1 identify_seed_names()

```python
def identify_seed_names(search_str_with_file: dict, graph_tags: list) -> list:
    """
    検索結果から起点となる関数/クラス名を特定する

    タグベース推論:
    1. キーワードがタグのnameと一致 → そのまま使用（クラス/関数検索）
    2. 一致しなければ、infoから検索 → 関数名を特定（文字列検索）
    3. どちらでも見つからなければスキップ

    Args:
        search_str_with_file: {"keyword": "file1.py file2.py", ...}
        graph_tags: tags_json データ

    Returns:
        list of dict: [{"name": "func_name", "file": "path/to/file.py"}, ...]
    """
    seed_names = []

    for keyword, files_str in search_str_with_file.items():
        result_files = files_str.split()
        found_as_name = False

        # Step 1: キーワードがタグのnameと一致するか（クラス/関数検索）
        for tag in graph_tags:
            if tag["kind"] == "def" and tag["name"] == keyword:
                if tag["rel_fname"] in result_files:
                    seed_names.append({"name": keyword, "file": tag["rel_fname"]})
                    found_as_name = True

        # Step 2: 見つからなければ、infoから探す（文字列検索）
        if not found_as_name:
            for tag in graph_tags:
                if tag["kind"] != "def":
                    continue
                if tag["rel_fname"] not in result_files:
                    continue
                # infoに検索キーワードが含まれるか
                if keyword in tag.get("info", ""):
                    seed_names.append({
                        "name": tag["name"],
                        "file": tag["rel_fname"]
                    })

        # Step 3: それでも見つからなければスキップ（何もしない）

    # 重複除去
    seen = set()
    unique_seeds = []
    for seed in seed_names:
        key = (seed["name"], seed["file"])
        if key not in seen:
            seen.add(key)
            unique_seeds.append(seed)

    return unique_seeds
```

#### 6.1.2 get_caller_files()

```python
def get_caller_files(seed_names: list, graph_tags: list,
                     coverage_dict: dict = None,
                     max_files: int = 10) -> dict:
    """
    起点から呼び出し元ファイルを取得（DEF=1のみ）

    Args:
        seed_names: [{"name": "xxx", "file": "yyy"}, ...]
        graph_tags: tags_json データ
        coverage_dict: カバレッジ情報（オプション）
        max_files: 最大ファイル数

    Returns:
        dict: {
            "caller_files": ["file1.py", "file2.py", ...],
            "details": [{"file": "...", "calls": [...], "score": N}, ...]
        }
    """
    caller_info = {}  # file -> {"calls": set(), "score": 0}

    for seed in seed_names:
        name = seed["name"]
        seed_file = seed["file"]

        # DEF数チェック（一意でなければスキップ）
        def_count = sum(1 for t in graph_tags
                        if t["kind"] == "def" and t["name"] == name)
        if def_count != 1:
            continue

        # REFタグから呼び出し元を取得
        for tag in graph_tags:
            if tag["kind"] == "ref" and tag["name"] == name:
                caller_file = tag["rel_fname"]

                # 自己ループのみ除外（同じファイル内での呼び出し）
                if caller_file == seed_file:
                    continue

                # テストファイルは除外
                if "test" in caller_file.lower():
                    continue

                if caller_file not in caller_info:
                    caller_info[caller_file] = {"calls": set(), "score": 0}

                caller_info[caller_file]["calls"].add(name)

    # スコアリング
    for file, info in caller_info.items():
        score = 0

        # 基本点: 呼び出している関数の数
        score += len(info["calls"])

        # Hub Bonus: 2つ以上の異なるSeedを呼んでいる
        if len(info["calls"]) >= 2:
            score += 30

        # Coverage Bonus: カバレッジに含まれている
        if coverage_dict and file in coverage_dict:
            score += 50

        # Locality Bonus: Seedと同じディレクトリ
        for seed in seed_names:
            seed_dir = "/".join(seed["file"].split("/")[:-1])
            file_dir = "/".join(file.split("/")[:-1])
            if file_dir == seed_dir:
                score += 5
                break

        info["score"] = score

    # スコア順でソート
    sorted_files = sorted(caller_info.items(),
                          key=lambda x: x[1]["score"],
                          reverse=True)

    # 上位N件を返す
    result_files = [f for f, _ in sorted_files[:max_files]]
    result_details = [
        {"file": f, "calls": list(info["calls"]), "score": info["score"]}
        for f, info in sorted_files[:max_files]
    ]

    return {
        "caller_files": result_files,
        "details": result_details
    }
```

#### 6.1.3 format_caller_prompt()

```python
def format_caller_prompt(caller_result: dict, coverage_dict: dict = None) -> str:
    """
    呼び出し関係ファイルのプロンプトを生成

    Args:
        caller_result: get_caller_files() の結果
        coverage_dict: カバレッジ情報

    Returns:
        str: プロンプトに追加するテキスト
    """
    if not caller_result.get("details"):
        return ""

    lines = [
        "",
        "### Structural Analysis (Call Relationship Suggestions) ###",
        "The following files call the functions/classes found in your keyword search.",
        "Please consider checking them as potential bug locations.",
        ""
    ]

    for i, detail in enumerate(caller_result["details"], 1):
        file = detail["file"]
        calls = detail["calls"]

        # Coverageステータス
        status = ""
        if coverage_dict and file in coverage_dict:
            status = " [Executed in PoC]"

        lines.append(f"{i}. {file}{status}")
        lines.append(f"   - Calls: {', '.join(calls)}")

        if len(calls) >= 2:
            lines.append(f"   - Note: Hub file (calls multiple search results)")

        lines.append("")

    return "\n".join(lines)
```

---

### 6.2 localize.py の改修

**場所:** `patchpilot/fl/localize.py`

#### 6.2.1 引数パーサーにフラグ追加

```python
# 既存の --repo_graph の近くに追加
parser.add_argument("--repo_graph", action="store_true")
parser.add_argument("--file_level_caller", action="store_true",
                    help="Add caller files as candidates in file-level localization")
```

#### 6.2.2 グラフデータ読み込み条件の更新

```python
# Before (Line 67付近)
if args.repo_graph:
    # グラフデータ読み込み

# After
if args.repo_graph or args.file_level_caller:
    # グラフデータ読み込み
```

#### 6.2.3 Step 0.5 追加（search_in_problem_statementの後、file level localizationの前）

```python
    search_str_with_file = fl.search_in_problem_statement(reproduce_info)

    # ★ Step 0.5: 構造的拡張（呼び出し関係ファイルの追加）
    caller_prompt = ""
    if args.file_level_caller and graph_tags is not None and search_str_with_file:
        from patchpilot.fl.repograph_utils import (
            identify_seed_names,
            get_caller_files,
            format_caller_prompt
        )

        # 起点を特定（タグベース推論）
        seed_names = identify_seed_names(
            search_str_with_file,
            graph_tags
        )
        logger.info(f"[Step 0.5] Identified {len(seed_names)} seed names")

        if seed_names:
            # 呼び出し元ファイルを取得
            coverage_dict = coverage_info.get("coverage_dict") if coverage_info else None
            caller_result = get_caller_files(
                seed_names,
                graph_tags,
                coverage_dict=coverage_dict,
                max_files=10
            )
            logger.info(f"[Step 0.5] Found {len(caller_result['caller_files'])} caller files")

            # プロンプト生成
            if caller_result["caller_files"]:
                caller_prompt = format_caller_prompt(
                    caller_result,
                    coverage_dict=coverage_dict
                )

    # file level localization
```

#### 6.2.4 additional_info パラメータ追加

```python
# Before
found_files, additional_artifact_loc_file, file_traj = fl.localize(
    mock=args.mock,
    match_partial_paths=args.match_partial_paths,
    search_res_files=search_str_with_file,
    num_samples=args.num_samples,
    top_n=args.top_n,
    coverage_info=coverage_info
)

# After
found_files, additional_artifact_loc_file, file_traj = fl.localize(
    mock=args.mock,
    match_partial_paths=args.match_partial_paths,
    search_res_files=search_str_with_file,
    num_samples=args.num_samples,
    top_n=args.top_n,
    coverage_info=coverage_info,
    additional_info=caller_prompt  # 追加
)
```

---

## 7. 実装順序チェックリスト

1. [ ] **repograph_utils.py**: 新規関数追加
   - [ ] identify_seed_names()
   - [ ] get_caller_files()
   - [ ] format_caller_prompt()

2. [ ] **localize.py**: フラグ追加 + Step 0.5 統合
   - [ ] `--file_level_caller` 引数追加
   - [ ] グラフ読み込み条件更新
   - [ ] Step 0.5 ロジック追加
   - [ ] additional_info パラメータ追加

3. [ ] **検証実験**: instances/django_common_20.txt で実行

---

## 8. テストコマンド

```bash
# File Level Caller のみ（Fine-grain Level は通常）
python patchpilot/fl/localize.py \
    --file_level \
    --file_level_caller \
    --code_graph_dir RepoGraph_cache \
    --output_folder results/localization_caller_test \
    --task_list_file instances/django_common_20.txt \
    --top_n 5 \
    --num_samples 1
```

**注:** `--file_level_caller` 使用時は `--code_graph_dir` が必須（タグデータの読み込みに必要）

---

## 9. ロールバック計画

万が一問題が発生した場合:
1. localize.py の Step 0.5 コードをコメントアウト
2. `--file_level_caller` 引数を削除

**注:** FL.py, repair.py は変更していないため、ロールバックは非常に簡単。
