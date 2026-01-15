# PatchPilot Repair Phase: RepoGraph Integration Plan

## 概要

PatchPilotのRepairフェーズにRepoGraph（コード依存関係情報）を統合する実装計画。
Localizationの`keyword_graph_context`と同じアプローチを採用し、`graph_tags`（JSONファイル）のみを使用する。

---

## 1. 現状分析

### Localizationでの実装（参考）

`keyword_graph_context`オプションで使用されている関数：

| 関数 | 用途 | 必要データ |
|------|------|-----------|
| `extract_keywords_from_problem()` | 問題文からキーワード抽出 | graph_tags |
| `build_caller_callee_context()` | caller/callee関係を構築 | graph_tags |
| `get_callers()` | 呼び出し元を取得 | graph_tags |
| `get_callees()` | 呼び出し先を取得 | graph_tags |

**重要**: これらはすべて`graph_tags`のみで動作し、`code_graph`（pklファイル）は不要。

### Repairでの方針

Repair専用の`build_repair_graph_context()`を新規作成する。
（Localizationの`build_caller_callee_context()`とは異なるフィルタ設定）

入力ソース：
- Localization: `problem_statement`からキーワード抽出
- Repair: `found_edit_locs`から関数/クラス名を抽出

フィルタの違い：
- Callers: Repairでは`found_files`フィルタなし（影響範囲を正確に把握）
- Callees: 両者とも`found_files`フィルタあり

---

## 2. 実装方針

### 2.1 データフロー

```
found_edit_locs (Localization結果)
        │
        ▼
┌───────────────────────────────────────┐
│  extract_keywords_from_edit_locs()    │
│  "function: FileField.generate_filename"
│  → {'functions': ['generate_filename'], 'classes': [...]}
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  build_repair_graph_context()         │  ← Repair専用（Callerフィルタなし）
│  (graph_tags のみ使用)                 │
└───────────────────────────────────────┘
        │
        ▼
Graph Context 出力:
    ## generate_filename
    Callers:
      - django/db/models/fields/files.py::save
    Callees:
      - django/utils/text.py::get_valid_filename
```

### 2.2 出力形式

```
## {関数名}
Callers:
  - {ファイルパス}::{呼び出し元関数名}
  - ...
Callees:
  - {ファイルパス}::{呼び出し先関数名}
  - ...
```

---

## 3. 必要な変更

### 3.1 repograph_utils.py への変更

#### (1) `get_callers` の修正

`found_files=None` の場合にフィルタをスキップするように修正：

```python
def get_callers(keyword: str, graph_tags: list, found_files: list, max_count_per_func: int = 5) -> dict:
    """
    キーワードにマッチした関数ごとに、その関数を呼び出している関数（caller）を取得

    修正: found_files=None の場合、ファイルフィルタを適用しない
    """
    callers_by_func = {}
    seen_by_func = {}
    keyword_lower = keyword.lower()

    for tag in graph_tags:
        # フィルタ1: refタグのみ対象
        if tag.get('kind') != 'ref':
            continue

        # フィルタ2: found_files内のファイルのみ（Noneの場合はスキップ）
        if found_files is not None and tag.get('rel_fname') not in found_files:
            continue

        # フィルタ3: 部分一致でキーワードを含むか確認
        tag_name = tag.get('name', '')
        if keyword_lower not in tag_name.lower():
            continue

        # このrefタグを含む関数を取得
        caller = get_containing_function(tag, graph_tags)
        if caller:
            # フィルタ4: 自己参照を除外
            if caller['name'].lower() == tag_name.lower():
                continue

            if tag_name not in callers_by_func:
                callers_by_func[tag_name] = []
                seen_by_func[tag_name] = set()

            key = (caller['name'], caller['file'])
            if key not in seen_by_func[tag_name]:
                # フィルタ5: 関数ごとの最大caller数
                if len(callers_by_func[tag_name]) < max_count_per_func:
                    seen_by_func[tag_name].add(key)
                    callers_by_func[tag_name].append(caller)

    return callers_by_func
```

#### (2) `build_repair_graph_context` の新規追加

Repair専用のGraph Context構築関数：

```python
def build_repair_graph_context(keywords: dict,
                                graph_tags: list,
                                found_files: list,
                                max_callers_per_func: int = 5,
                                max_callees_per_func: int = 5,
                                max_keywords: int = 20,
                                max_functions: int = 30) -> str:
    """
    Repair用のGraph Context構築

    Localization用の build_caller_callee_context との違い:
    - Callers: found_filesフィルタなし（全ファイルから取得）
    - Callees: found_filesフィルタあり（従来通り）

    Args:
        keywords: {'functions': [...], 'classes': [...]}
        graph_tags: tags_*.json のデータ
        found_files: Localizationで特定されたファイル（calleesのみに使用）
        max_callers_per_func: 関数あたりの最大caller数
        max_callees_per_func: 関数あたりの最大callee数
        max_keywords: 処理する最大キーワード数
        max_functions: 出力する最大関数数

    Returns:
        フォーマットされたコンテキスト文字列
    """
    # ストップワードでフィルタリング
    filtered = filter_keywords_with_stopwords(keywords)
    all_keywords = filtered.get('functions', []) + filtered.get('classes', [])

    if not all_keywords:
        return ""

    func_info = {}
    processed_keywords = 0

    for keyword in all_keywords:
        if processed_keywords >= max_keywords:
            break

        # Callers: found_files=None でフィルタなし（全ファイルから取得）
        callers_by_func = get_callers(keyword, graph_tags, None, max_callers_per_func)
        for func_name, callers in callers_by_func.items():
            if func_name not in func_info:
                func_info[func_name] = {'callers': [], 'callees': []}
            existing_callers = {(c['name'], c['file']) for c in func_info[func_name]['callers']}
            for c in callers:
                if (c['name'], c['file']) not in existing_callers:
                    func_info[func_name]['callers'].append(c)

        # Callees: found_files でフィルタあり（従来通り）
        callees_by_func = get_callees(keyword, graph_tags, found_files, max_callees_per_func)
        for func_name, callees in callees_by_func.items():
            if func_name not in func_info:
                func_info[func_name] = {'callers': [], 'callees': []}
            existing_callees = {(c['name'], c['file']) for c in func_info[func_name]['callees']}
            for c in callees:
                if (c['name'], c['file']) not in existing_callees:
                    func_info[func_name]['callees'].append(c)

        processed_keywords += 1

    if not func_info:
        return ""

    # 出力を構築
    lines = []
    output_count = 0

    for func_name, info in func_info.items():
        if output_count >= max_functions:
            break

        callers = info['callers']
        callees = info['callees']

        if not callers and not callees:
            continue

        lines.append(f"## {func_name}")

        if callers:
            lines.append("Callers:")
            for c in callers[:max_callers_per_func]:
                lines.append(f"  - {c['file']}::{c['name']}")

        if callees:
            lines.append("Callees:")
            for c in callees[:max_callees_per_func]:
                lines.append(f"  - {c['file']}::{c['name']}")

        lines.append("")
        output_count += 1

    if output_count == 0:
        return ""

    return "\n".join(lines)
```

#### (3) フィルタの違い

| 関数 | 使用フェーズ | Caller: found_filesフィルタ | Callee: found_filesフィルタ |
|------|-------------|:-------------------------:|:-------------------------:|
| `build_caller_callee_context` | Localization | あり | あり |
| `build_repair_graph_context` | Repair | **なし** | あり |

---

### 3.2 repair.py への変更

#### (1) インポート追加

```python
# repair.py 冒頭に追加
from patchpilot.fl.repograph_utils import build_repair_graph_context
```

#### (2) コマンドライン引数追加

```python
# main() 内の argparse に追加
parser.add_argument("--use_repograph", action="store_true",
                    help="Add RepoGraph dependencies to planning prompt")
parser.add_argument("--graph_folder", type=str, default="RepoGraph_cache",
                    help="Folder containing tags_*.json files")
```

#### (3) グラフタグ読み込み関数追加

```python
def load_graph_tags(instance_id, graph_folder, logger=None):
    """
    Load graph_tags for a given instance.

    Note: Only loads tags JSON file (pkl file is NOT required)

    Args:
        instance_id: SWE-bench instance ID (e.g., "django__django-12345")
        graph_folder: Path to folder containing tags files
        logger: Optional logger instance

    Returns:
        List of tag dictionaries, or None if not found
    """
    tags_path = os.path.join(graph_folder, f"tags_{instance_id}.json")

    if not os.path.exists(tags_path):
        if logger:
            logger.info(f"graph_tags not found: {tags_path}")
        return None

    try:
        with open(tags_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to load graph_tags for {instance_id}: {e}")
        return None
```

#### (4) キーワード抽出関数追加

```python
def extract_keywords_from_edit_locs(found_edit_locs):
    """
    Extract function and class names from found_edit_locs.

    Converts localization output format to keywords dict format
    compatible with build_caller_callee_context().

    Args:
        found_edit_locs: Localization result containing function/class info
            Format: [[[""], ["function: Name\\nline: 123"], ...], ...]

    Returns:
        dict: {'functions': ['func1', ...], 'classes': ['Class1', ...]}
    """
    functions = set()
    classes = set()

    for item in found_edit_locs:
        # Handle nested list structure
        if isinstance(item, list):
            for sub_item in item:
                if isinstance(sub_item, list):
                    sub_item = sub_item[0] if sub_item else ""
                if not sub_item:
                    continue

                for line in sub_item.splitlines():
                    line = line.strip()

                    if line.startswith("function: "):
                        name = line[len("function: "):].strip()
                        # Handle "Class.method" format - extract method name
                        if "." in name:
                            name = name.split(".")[-1]
                        if name:
                            functions.add(name)

                    elif line.startswith("class: "):
                        name = line[len("class: "):].strip()
                        if name:
                            classes.add(name)

    return {
        'functions': list(functions),
        'classes': list(classes)
    }
```

#### (5) process_loc() 内でのRepoGraph統合

**重要**: `structure`変数は既に`process_loc()`内の706-712行目でロード済み。

```python
def process_loc(loc, args, swe_bench_data, prev_generations=None):
    # ... 既存コード ...
    # pred_files は File Level の結果として既に取得済み

    # RepoGraph情報の構築 (structure ロード後に配置)
    graph_context = ""
    if args.use_repograph:
        graph_tags = load_graph_tags(instance_id, args.graph_folder, logger)

        if graph_tags is None:
            logger.warning(f"[RepoGraph] graph_tags not found for {instance_id}, skipping dependencies")
        else:
            found_edit_locs = loc.get("found_edit_locs", [])

            if not found_edit_locs:
                logger.warning(f"[RepoGraph] found_edit_locs is empty for {instance_id}, skipping dependencies")
            else:
                # found_edit_locs からキーワードを抽出
                keywords = extract_keywords_from_edit_locs(found_edit_locs)

                if not keywords['functions'] and not keywords['classes']:
                    logger.warning(f"[RepoGraph] No keywords extracted from found_edit_locs for {instance_id}")
                    logger.debug(f"[RepoGraph] found_edit_locs content: {str(found_edit_locs)[:500]}...")
                else:
                    logger.info(f"[RepoGraph] Extracted keywords: functions={keywords['functions']}, classes={keywords['classes']}")

                    # Repair専用の関数を使用（Callerはfound_filesフィルタなし）
                    graph_context = build_repair_graph_context(
                        keywords,
                        graph_tags,
                        pred_files,  # Calleesのみに使用
                        max_callers_per_func=5,
                        max_callees_per_func=5,
                        max_keywords=20,
                        max_functions=30
                    )

                    if not graph_context:
                        logger.warning(f"[RepoGraph] No caller/callee relationships found for keywords")
                    else:
                        logger.info(f"[RepoGraph] Graph context generated: {len(graph_context)} chars")

    # Planning Prompt 構築時に依存関係を追加
    # 実際のコードでは sample_mod と refine_mod で異なるプロンプトを使用
    if args.sample_mod or base_patch_diff == "":
        if graph_context:
            message_get_plan = planning_prompt_random_file_with_deps.format(
                problem_statement=problem_statement,
                content=topn_content.rstrip(),
                example=example,
                files=' '.join(file_loc_intervals.keys()),
                dependencies=graph_context,
            ).strip()
        else:
            message_get_plan = planning_prompt_random_file.format(
                problem_statement=problem_statement,
                content=topn_content.rstrip(),
                example=example,
                files=' '.join(file_loc_intervals.keys()),
            ).strip()
    elif args.refine_mod:
        if graph_context:
            message_get_plan = planning_prompt_poc_feedback_with_deps.format(
                problem_statement=problem_statement,
                content=topn_content.rstrip(),
                example=example,
                feedback=feedback_prompt,
                dependencies=graph_context,
            ).strip()
        else:
            message_get_plan = planning_prompt_poc_feedback.format(
                problem_statement=problem_statement,
                content=topn_content.rstrip(),
                example=example,
                feedback=feedback_prompt,
            ).strip()
    else:
        raise ValueError("invalid mode, must be sample_mod or refine_mod")
```

### 3.2 新しいプロンプトテンプレート

#### (1) sample_mod用: `planning_prompt_random_file_with_deps`

`planning_prompt_random_file` に依存関係セクションを追加：

```python
planning_prompt_random_file_with_deps = """
We are currently solving the following issue within our repository.
You are a maintainer of the project. Please analyze the bug as a maintainer, since the issue description might only describe the surface-level problem. Please analyze the bug thoroughly and infer the underlying real problem that needs to be addressed, using your inherit knowledge of the project. For example, if the goal is to fix an error or warning, focus on resolving the logic that causes the error or warning rather than simply suppressing or bypassing it.
Then, provide an analysis of the reason for the bug, and then provide a step-by-step plan for repairing it.
Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken.
The actions should be wrapped in <Actions to be Taken> and </Actions to be Taken>.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided. You do not have the freedom to open the codebase and look for the bug. You should only rely on the information provided in the issue description and the code snippet.
You should only modify the file that you have chosen to modify.

Please develop a comprehensive plan that addresses the underlying issue described. The plan should be broad enough to apply to similar cases, not just the specific example provided in the issue description.
Note that if a file name or argument is provided in the issue description as an example for reproduction, other arguments may also trigger the issue. Therefore, make the fix as general as possible.
You should ensure that the proposed plan fixes the code to do the expected behavior.
Choose the most general way to fix the issue, don't make any assumption of the input.
You are required to propose a plan to fix the issue with minimal modifications. Follow these guidelines:
Number of Steps: The number of steps to fix the issue should be at most 3.
Modification: Each step should perform exactly one modification at exactly one location in the code.
Necessity: Do not modify the code unless it is necessary to fix the issue.
Your plan should outline only the steps that involve code modifications. If a step does not require a code change, do not include it in the plan.
You should only modify the file that you have chosen to modify.
In each step, specify the file that need to be modified.
If the issue text includes a recommended fix, do not apply it directly. You should explicitly reason whether it can fix the issue.
You always need to adapt the code to the existing codebase's style and standards by considering the context of the code.
Remember that you should not write any code in the plan.

{example}

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---

### Function Dependencies ###

The code above shows the implementation but not how functions interact with the rest of the codebase.
Below are caller/callee relationships for functions you may need to modify:

- **Callers**: Functions that call this function.
  If you change the function's signature, parameters, or return value, these callers may also need updates.

- **Callees**: Functions that this function calls.
  Understanding what this function depends on helps you avoid breaking existing behavior.

Even though only function names are shown, use these relationships to:
1. Consider side effects of your changes
2. Ensure compatibility with calling code
3. Verify that dependencies remain satisfied

{dependencies}

###

You should only choose to modify files from the following list: {files}
"""
```

#### (2) refine_mod用: `planning_prompt_poc_feedback_with_deps`

`planning_prompt_poc_feedback` に依存関係セクションを追加：

```python
planning_prompt_poc_feedback_with_deps = """
We are currently solving the following issue within our repository.
You are a maintainer of the project. Please analyze the bug as a maintainer, since the issue description might only describe the surface-level problem. Please analyze the bug thoroughly and infer the underlying real problem that needs to be addressed, using your inherit knowledge of the project.
Then, provide an analysis of the reason for the bug, and then provide a step-by-step plan for repairing it.
Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken.
The actions should be wrapped in <Actions to be Taken> and </Actions to be Taken>.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided.

Generate a detailed plan to address the issue, avoiding overly general solutions. Analyze the scope of the critical variable by reasoning about the specific values that should and should not be affected.
Identify the situations the patch should handle and explicitly outline the scenarios it should avoid. Ensure the patch directly targets the issue without impacting unrelated code or values.

Please develop a comprehensive plan that addresses the underlying issue described. The plan should be broad enough to apply to similar cases, not just the specific example provided in the issue description.
You should ensure that the proposed plan fixes the code to do the expected behavior.
You are required to propose a plan to fix the issue with minimal modifications. Follow these guidelines:
Number of Steps: The number of steps to fix the issue should be at most 2.
Modification: Each step should perform exactly one modification at exactly one location in the code.
Necessity: Do not modify the code unless it is necessary to fix the issue.
Your plan should outline only the steps that involve code modifications. If a step does not require a code change, do not include it in the plan.
Don't write any code in the plan.

{example}

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---

### Function Dependencies ###

The code above shows the implementation but not how functions interact with the rest of the codebase.
Below are caller/callee relationships for functions you may need to modify:

- **Callers**: Functions that call this function.
  If you change the function's signature, parameters, or return value, these callers may also need updates.

- **Callees**: Functions that this function calls.
  Understanding what this function depends on helps you avoid breaking existing behavior.

Even though only function names are shown, use these relationships to:
1. Consider side effects of your changes
2. Ensure compatibility with calling code
3. Verify that dependencies remain satisfied

{dependencies}

###

{feedback}
"""
```

---

## 4. ファイル構成

```
patchpilot/
├── fl/
│   ├── repograph_utils.py   # ★変更 (get_callers修正 + build_repair_graph_context追加)
│   └── ...
├── repair/
│   ├── repair.py            # ★変更
│   ├── bfs.py
│   └── utils.py
└── ...

RepoGraph_cache/              # グラフファイル格納場所
├── tags_django__django-12345.json   # ★これのみ必要 (pklは不要)
├── tags_django__django-12346.json
├── ...
```

---

## 5. 実行コマンド例

### Baseline（RepoGraphなし）

```bash
python patchpilot/repair/repair.py \
    --loc_file results/localization/merged/loc_all_merged_outputs.jsonl \
    --output_folder results/repair_baseline \
    --loc_interval \
    --top_n 5 \
    --context_window 20 \
    --max_samples 12 \
    --batch_size 4 \
    --refine_mod \
    --model gpt-4o-mini \
    --backend openai
```

### RepoGraphあり

```bash
python patchpilot/repair/repair.py \
    --loc_file results/localization/merged/loc_all_merged_outputs.jsonl \
    --output_folder results/repair_repograph \
    --use_repograph \                    # ★新規オプション
    --graph_folder RepoGraph_cache \     # ★新規オプション
    --loc_interval \
    --top_n 5 \
    --context_window 20 \
    --max_samples 12 \
    --batch_size 4 \
    --refine_mod \
    --model gpt-4o-mini \
    --backend openai
```

**重要**: `--use_repograph`オプションを指定しない場合は従来通りのBaselineとして動作する。

---

## 6. 実装ステップ

### Phase 1: 基本実装 (必須)

| Step | 作業内容 | ファイル |
|------|----------|----------|
| 1-1 | `get_callers()` の修正（found_files=None対応） | repograph_utils.py |
| 1-2 | `build_repair_graph_context()` 関数追加 | repograph_utils.py |
| 1-3 | インポート追加 | repair.py |
| 1-4 | コマンドライン引数追加 (`--use_repograph`, `--graph_folder`) | repair.py |
| 1-5 | `load_graph_tags()` 関数追加 | repair.py |
| 1-6 | `extract_keywords_from_edit_locs()` 関数追加 | repair.py |
| 1-7 | `planning_prompt_random_file_with_deps` テンプレート追加 (sample_mod用) | repair.py |
| 1-8 | `planning_prompt_poc_feedback_with_deps` テンプレート追加 (refine_mod用) | repair.py |
| 1-9 | `process_loc()` 内でのRepoGraph統合（sample_mod/refine_mod両対応） | repair.py |

### Phase 2: テスト・評価

| Step | 作業内容 |
|------|----------|
| 2-1 | 小規模テスト (5インスタンス) |
| 2-2 | RepoGraph有無での比較評価 |
| 2-3 | トークン使用量の確認 |

---

## 7. 考慮事項

### 7.1 トークン制限

- `build_repair_graph_context()`は関数名のみを出力するため、トークン消費は小さい
- `max_functions=30`で出力関数数を制限
- 必要に応じて調整可能

### 7.2 グラフファイルの事前生成

RepairフェーズでRepoGraphを使用するには、事前にタグファイルが必要：

```bash
# Localization時に生成される
python patchpilot/fl/localize.py \
    --file_level --related_level --fine_grain_line_level \
    --keyword_graph_context \
    --code_graph_dir RepoGraph_cache \
    --output_folder results/localization \
    ...
```

### 7.3 エラーハンドリング

- タグファイルが存在しない場合: 警告を出力し、依存関係なしで続行
- キーワードが抽出できない場合: 依存関係なしで続行
- `build_caller_callee_context`が空文字を返す場合: 通常のプロンプトを使用

### 7.4 データ形式

| ファイル | 形式 | 必要性 |
|----------|------|--------|
| `tags_{instance_id}.json` | JSON配列 | **必須** |
| `{instance_id}.pkl` | pickle | **不要** |

---

## 8. Localizationとの比較

| 項目 | Localization (keyword_graph_context) | Repair (提案) |
|------|--------------------------------------|---------------|
| 入力ソース | problem_statement | found_edit_locs |
| キーワード抽出 | `extract_keywords_from_problem()` | `extract_keywords_from_edit_locs()` |
| コンテキスト構築 | `build_caller_callee_context()` | `build_repair_graph_context()` ★Repair専用 |
| Caller取得 | found_filesフィルタあり | **found_filesフィルタなし** |
| Callee取得 | found_filesフィルタあり | found_filesフィルタあり ★同じ |
| 必要ファイル | tags_*.json | tags_*.json ★同じ |
| 出力形式 | Callers/Callees リスト | Callers/Callees リスト ★同じ |

---

## 9. Agentlessとの比較

| 項目 | Agentless | PatchPilot (提案) |
|------|-----------|-------------------|
| 注入箇所 | Repair Prompt | Planning Prompt |
| 必要ファイル | pkl + json | **jsonのみ** |
| 出力形式 | コード含む | **関数名のみ** |
| トークン消費 | 大 | **小** |
| Localizationとの一貫性 | - | **統一** |

---

## 10. 期待される効果

1. **修正精度の向上**: 依存関係を理解した上でのPlan作成
2. **副作用の軽減**: callerへの影響を考慮した修正
3. **Localizationとの一貫性**: 同じアプローチで効果比較が容易
4. **運用の簡素化**: pklファイル不要

---

## 11. リスクと対策

| リスク | 対策 |
|--------|------|
| キーワードが抽出できない | 依存関係なしで続行（フォールバック） |
| caller/calleeが見つからない | 空の場合は通常プロンプトを使用 |
| トークン超過 | `max_functions`パラメータで制限 |

---

## 12. 修正履歴

### 2025-01-02 初版作成

- `construct_code_graph_context`を使用する計画

### 2025-01-02 修正 (v2)

1. **アプローチ変更**: `construct_code_graph_context` → `build_caller_callee_context`
   - Localizationの`keyword_graph_context`と同じ関数を再利用
   - pklファイル不要、graph_tags（JSON）のみで動作

2. **関数変更**:
   - `load_repograph()` → `load_graph_tags()` (JSONのみ読み込み)
   - 新規: `extract_keywords_from_edit_locs()` (found_edit_locsからキーワード抽出)

3. **出力形式変更**:
   - コード全体を含む形式 → 関数名のみのリスト形式
   - トークン消費を大幅に削減

### 2025-01-02 修正 (v3)

1. **Repair専用関数の作成**:
   - `build_repair_graph_context()` を新規追加（repograph_utils.py）
   - Localization用の `build_caller_callee_context()` とは別に管理

2. **Callerのfound_filesフィルタ削除**:
   - `get_callers()` を修正し、`found_files=None` でフィルタをスキップ可能に
   - Repair時は全ファイルからCallerを取得（変更の影響範囲を正確に把握）
   - Calleeは従来通りfound_files内のみ

3. **プロンプト説明文の強化**:
   - 関数名のみでもLLMが意図を理解できるよう詳細な説明を追加

4. **ログ出力の強化**:
   - found_edit_locsが空の場合など、各ステップで詳細なログを出力

### 2025-01-03 修正 (v4)

1. **プロンプト名の修正**:
   - 計画書のプロンプト名を実際のrepair.pyに合わせて修正
   - `planning_prompt_general` → `planning_prompt_random_file` (sample_mod用)
   - `planning_prompt_poc_feedback` を明示 (refine_mod用)

2. **依存関係付きプロンプトの追加**:
   - `planning_prompt_random_file_with_deps` (sample_mod + RepoGraph)
   - `planning_prompt_poc_feedback_with_deps` (refine_mod + RepoGraph)

3. **process_loc内の分岐修正**:
   - sample_modとrefine_modで異なるプロンプトを使用する分岐を反映
   - `{files}` パラメータ（sample_mod用）を追加

4. **Localizationとの比較表更新**:
   - Repair専用関数 `build_repair_graph_context()` を明記
   - Caller/Calleeのフィルタ差異を明記

5. **Baseline実験対応の確認**:
   - `--use_repograph` フラグでRepoGraph機能のON/OFFが可能
   - RepoGraphなし時は既存プロンプトを使用（フォールバック）
