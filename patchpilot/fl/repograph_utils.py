"""
Repograph utilities for code graph analysis.
Adapted from RepoGraph/agentless/fl/localize.py
"""

import pickle
import json
import re
from copy import deepcopy
from tqdm import tqdm


def find_target_file(search_term, graph_tags, preferred_files=None):
    """
    Find the file path where search_term is defined.
    Module-level function for use in both retrieve_graph() and construct_code_graph_context().

    MODIFICATION (段階Composite Score Phase 2-5): Accept preferred_files to disambiguate multiple definitions.
    When multiple definitions exist, prefer definitions from the predicted/selected files.

    Args:
        search_term: Function/class name to search for
        graph_tags: List of tag dictionaries
        preferred_files: (Optional) List of file paths where the search term should be preferred.
                        If multiple definitions exist, return the one from preferred_files first.

    Returns:
        str or None: rel_fname of the file where search_term is defined
    """
    # Collect all definitions
    all_defs = [tag for tag in graph_tags if tag['name'] == search_term and tag['kind'] == 'def']

    if not all_defs:
        return None

    # If only one definition exists, return it
    if len(all_defs) == 1:
        return all_defs[0]['rel_fname']

    # If multiple definitions exist and preferred_files is provided, prefer those
    if preferred_files:
        for def_tag in all_defs:
            if def_tag['rel_fname'] in preferred_files:
                print(f"[INFO find_target_file] {search_term} has {len(all_defs)} definitions, selected from preferred_files: {def_tag['rel_fname']}")
                return def_tag['rel_fname']
        # Log warning if no definition in preferred files
        print(f"[WARNING find_target_file] {search_term} has {len(all_defs)} definitions, none in preferred_files")
        print(f"  Definitions found in: {[tag['rel_fname'] for tag in all_defs]}")
        print(f"  Preferred files: {preferred_files}")

    # Default: return first definition (original behavior)
    if len(all_defs) > 1:
        print(f"[INFO find_target_file] {search_term} has {len(all_defs)} definitions, using first: {all_defs[0]['rel_fname']}")
    return all_defs[0]['rel_fname']


def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=50, target_file=None, max_tokens_for_section=None):
    """
    Retrieve one-hop neighbors from the code graph for a given search term.

    MODIFICATION (段階Composite Score): Use composite score for prioritization
    Reason: in_degree (call frequency) doesn't correlate with bug-fix relevance.
    New strategy: Prioritize by file locality (same file/dir) + direct call relationships + in_degree (auxiliary).

    MODIFICATION (段階V2): Separate callers and callees, limit each to top-N by in_degree
    Reason: Different ref tags have different semantics:
    - Caller tags: functions that call this function (might need updates if this function changes)
    - Callee tags: functions that this function calls (might need modifications for coordination)
    We retrieve the most important of each type separately to reduce noise and improve focus.

    MODIFICATION (Phase 2-6: Dynamic Token Limiting): Accept max_tokens_for_section parameter
    When specified, limit tag retrieval based on token budget per section.
    This enables fine-grained token control within each section of the graph context.

    Args:
        code_graph: NetworkX graph object
        graph_tags: List of tag dictionaries
        search_term: Function or class name to search for
        structure: Repository structure dictionary
        max_tags: Maximum number of tags per category (default changed from 100 to 50)
        target_file: (Optional) Target file path for composite score. If None, auto-determined.
        max_tokens_for_section: (Optional) Maximum tokens allowed for this section's tags.
                               If specified, stop tag retrieval when this limit would be exceeded.

    Returns:
        List of (function/method dict, filename) tuples
    """
    one_hop_tags = []
    tags = []

    # DEBUG: Tag statistics
    ref_tags_total = sum(1 for tag in graph_tags if tag['name'] == search_term and tag['kind'] == 'ref')
    def_tags_total = sum(1 for tag in graph_tags if tag['name'] == search_term and tag['kind'] == 'def')
    print(f"[DEBUG retrieve_graph] Searching for: {search_term}")
    print(f"[DEBUG retrieve_graph] Total 'ref' tags in graph: {ref_tags_total}")
    print(f"[DEBUG retrieve_graph] Total 'def' tags in graph: {def_tags_total}")
    print(f"[DEBUG retrieve_graph] max_tags limit per category: {max_tags}")

    # MODIFICATION (段階2): Collect both def and ref tags, with def having priority
    def_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'def']
    ref_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'ref']

    # MODIFICATION (段階6): Limit def tags to 1
    def_tags_limited = def_tags[:1]

    # MODIFICATION (段階V2): Separate callers and callees, limit each independently
    # Helper function to get in_degree
    def get_in_degree(tag):
        """Get the in_degree of the function that this tag refers to."""
        try:
            return code_graph.in_degree(tag['name'])
        except:
            return 0

    # Helper function to get out_degree (importance as a callee)
    def get_out_degree(tag):
        """Get the out_degree of the function that this tag refers to."""
        try:
            return code_graph.out_degree(tag['name'])
        except:
            return 0

    # MODIFICATION (段階Composite Score): New helper functions for composite scoring
    def get_file_locality_score(tag, target_file):
        """
        Calculate file locality score for a tag.
        Prioritizes tags in the same file and directory as target function.

        Args:
            tag: Tag dictionary with 'rel_fname' field
            target_file: Target file path (rel_fname)

        Returns:
            int: Score (1000=same file, 100=same dir, 1=different)
        """
        if tag['rel_fname'] == target_file:
            return 1000  # Same file: highest priority
        elif tag['rel_fname'].split('/')[0] == target_file.split('/')[0]:
            return 100   # Same directory: medium priority
        else:
            return 1     # Different file/dir: low priority

    def is_direct_neighbor(tag, search_term, code_graph):
        """
        Check if tag is directly connected to search_term in the code graph.

        Args:
            tag: Tag dictionary with 'name' field
            search_term: Function/class name to search for
            code_graph: NetworkX graph object

        Returns:
            bool: True if tag and search_term have direct edge in either direction
        """
        try:
            tag_name = tag['name']
            # Check both directions: tag → search_term and search_term → tag
            return (code_graph.has_edge(tag_name, search_term) or
                    code_graph.has_edge(search_term, tag_name))
        except:
            return False

    def calculate_composite_score(tag, search_term, code_graph, target_file):
        """
        Calculate composite score for prioritizing ref_tags.

        Score composition:
        - File locality (1000/100/1): Prioritize same-file and same-directory functions
        - Direct neighbor bonus (50): Functions directly calling/called by search_term
        - In-degree auxiliary (0-10): Call frequency as supplementary factor

        Args:
            tag: Tag dictionary
            search_term: Target function/class name
            code_graph: NetworkX graph object
            target_file: Target file path (rel_fname)

        Returns:
            float: Composite score for sorting (higher = more important)
        """
        locality_score = get_file_locality_score(tag, target_file)
        neighbor_bonus = 50 if is_direct_neighbor(tag, search_term, code_graph) else 0
        in_degree = code_graph.in_degree(tag['name']) if tag['name'] in code_graph else 0
        in_degree_score = min(in_degree / 10, 10)  # Normalize to max 10 points

        return locality_score + neighbor_bonus + in_degree_score

    # MODIFICATION (段階Composite Score): Replace in_degree sort with composite score
    # Find target file for composite score calculation
    if target_file is None:
        target_file = find_target_file(search_term, graph_tags)
    print(f"[DEBUG retrieve_graph] Target file for {search_term}: {target_file}")

    if target_file:
        # Sort by composite score (file locality + direct neighbor + in_degree auxiliary)
        def composite_score_key(tag):
            return calculate_composite_score(tag, search_term, code_graph, target_file)

        ref_tags_sorted = sorted(ref_tags, key=composite_score_key, reverse=True)
        print(f"[INFO retrieve_graph] Sorted by composite score (file locality + direct neighbor + in_degree auxiliary)")
    else:
        # Fallback to in_degree if target file not found
        ref_tags_sorted = sorted(ref_tags, key=get_in_degree, reverse=True)
        print(f"[WARNING retrieve_graph] Target file not found, falling back to in_degree sort")

    # MODIFICATION (Phase 2-6): Implement token-aware tag limiting
    # If max_tokens_for_section is specified, limit tags based on estimated token budget
    if max_tokens_for_section is not None:
        ref_tags_limited = []
        tokens_used = 0

        for tag in ref_tags_sorted:
            # Estimate token cost of this tag (conservative: ~100-150 tokens per tag)
            tag_tokens = len(str(tag.get('text', []))) // 4 if tag.get('text') else 100

            # Check if adding this tag would exceed budget
            if tokens_used + tag_tokens > max_tokens_for_section:
                print(f"[INFO retrieve_graph] Token limit reached for {search_term}: {tokens_used}/{max_tokens_for_section} tokens used")
                break

            ref_tags_limited.append(tag)
            tokens_used += tag_tokens

            # Also respect max_tags limit
            if len(ref_tags_limited) >= max_tags:
                break

        print(f"[DEBUG retrieve_graph] Token-aware limiting: {len(ref_tags)} → {len(ref_tags_limited)} tags ({tokens_used}/{max_tokens_for_section} tokens)")
    else:
        # Original behavior: just use max_tags limit
        ref_tags_limited = ref_tags_sorted[:max_tags]

    # Combine: def tag + top ref tags
    tags = def_tags_limited + ref_tags_limited

    print(f"[DEBUG retrieve_graph] Found {len(def_tags)} 'def' + {len(ref_tags)} 'ref' total tags")
    print(f"[DEBUG retrieve_graph] Using {len(def_tags_limited)} def + {len(ref_tags_limited)} ref = {len(tags)} tags (max_tags per category: {max_tags})")
    if len(ref_tags) > max_tags:
        print(f"[INFO retrieve_graph] Filtered ref tags: {len(ref_tags)} → {len(ref_tags_limited)} (kept top {max_tags} by composite score)")

    # For each tag, find the containing function/class
    for i, tag in enumerate(tags):
        print(f"Retrieving graph for {i}/{len(tags)}")

        # Navigate through structure to find the file
        path = tag['rel_fname'].split('/')
        s = deepcopy(structure)
        for p in path:
            s = s[p]

        # Check if tag is in a function
        for txt in s['functions']:
            if tag['line'] >= txt['start_line'] and tag['line'] <= txt['end_line']:
                one_hop_tags.append((txt, tag['rel_fname']))

        # Check if tag is in a class method
        for txt in s['classes']:
            for func in txt['methods']:
                if tag['line'] >= func['start_line'] and tag['line'] <= func['end_line']:
                    func['text'].insert(0, txt['text'][0])
                    one_hop_tags.append((func, tag['rel_fname']))

    print(f"[DEBUG retrieve_graph] Retrieved {len(one_hop_tags)} one-hop tags for: {search_term}")
    return one_hop_tags


def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure, preferred_files=None, total_token_budget=30740, logger=None):
    """
    Construct code graph context from found related locations with Greedy dynamic token allocation.

    MODIFICATION (段階Composite Score Phase 2-5): Accept preferred_files to disambiguate multiple definitions.
    Pass preferred_files to find_target_file() to ensure definitions from selected files are prioritized.

    MODIFICATION (Phase 2-6: Greedy Dynamic Token Allocation): Accept total_token_budget parameter
    Dynamically allocate token budget to each section based on:
    - Current budget consumed
    - Number of remaining sections
    - Formula: max_tokens_this_section = remaining_budget / sections_remaining
    This ensures optimal utilization of the global token budget across all sections.

    Args:
        found_related_locs: List of related code locations
        code_graph: NetworkX graph object
        graph_tags: List of tag dictionaries
        structure: Repository structure dictionary
        preferred_files: (Optional) List of file paths to prefer when multiple definitions exist
        total_token_budget: (Optional) Total token budget for all graph context (default: 30740)
        logger: (Optional) Logger instance for debug output (default: None)

    Returns:
        String containing formatted graph context
    """
    graph_context = ""

    # MODIFICATION (Phase 2-6): Greedy allocation tracking
    tokens_used_global = 0
    total_sections = len(found_related_locs)
    items_added = 0
    items_skipped = 0

    graph_item_format = """
### Dependencies for {func}
{dependencies}
"""
    tag_format = """
location: {fname} lines {start_line} - {end_line}
name: {name}
contents:
{contents}

"""

    # Retrieve the code graph for dependent functions and classes
    for section_idx, item in enumerate(found_related_locs):
        # MODIFICATION (Phase 2-6): Greedy dynamic token allocation
        sections_remaining = total_sections - section_idx
        remaining_budget = total_token_budget - tokens_used_global

        # Guard against division by zero
        if sections_remaining <= 0:
            sections_remaining = 1

        # Check if we still have budget
        if remaining_budget < 1000:  # Minimum threshold: 1000 tokens
            items_skipped += sections_remaining
            print(f"[INFO construct_code_graph_context] Token budget exhausted: {tokens_used_global:,}/{total_token_budget:,} tokens used")
            break

        # Greedy allocation: distribute remaining budget across remaining sections
        max_tokens_this_section = remaining_budget / sections_remaining

        code_graph_context = ""
        item = item[0].splitlines()

        # MODIFICATION (Fix 2): Skip empty related locations before graph generation
        # Reason: Prevent empty sections from consuming tokens and polluting context
        if not item or not any(line.strip() for line in item):
            items_skipped += 1
            continue

        for loc in tqdm(item):
            # Handle class references
            if loc.startswith("class: ") and "." not in loc:
                loc = loc[len("class: "):].strip()
                # MODIFICATION (段階Composite Score Phase 2-5): Pass target_file explicitly with preferred_files
                target_file = find_target_file(loc, graph_tags, preferred_files=preferred_files)
                # MODIFICATION (Phase 2-6): Pass max_tokens_for_section for fine-grained token control
                tags = retrieve_graph(code_graph, graph_tags, loc, structure, target_file=target_file, max_tokens_for_section=max_tokens_this_section)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )

            # Handle function references
            elif loc.startswith("function: ") and "." not in loc:
                loc = loc[len("function: "):].strip()
                # MODIFICATION (段階Composite Score Phase 2-5): Pass target_file explicitly with preferred_files
                target_file = find_target_file(loc, graph_tags, preferred_files=preferred_files)
                # MODIFICATION (Phase 2-6): Pass max_tokens_for_section for fine-grained token control
                tags = retrieve_graph(code_graph, graph_tags, loc, structure, target_file=target_file, max_tokens_for_section=max_tokens_this_section)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )

            # Handle qualified names (e.g., Class.method)
            elif "." in loc:
                loc = loc.split(".")[-1].strip()
                # MODIFICATION (段階Composite Score Phase 2-5): Pass target_file explicitly with preferred_files
                target_file = find_target_file(loc, graph_tags, preferred_files=preferred_files)
                # MODIFICATION (Phase 2-6): Pass max_tokens_for_section for fine-grained token control
                tags = retrieve_graph(code_graph, graph_tags, loc, structure, target_file=target_file, max_tokens_for_section=max_tokens_this_section)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )

            # MODIFICATION (段階4): Only add section if code_graph_context is not empty
            # Reason: Skip empty sections to save tokens and improve graph context quality
            if code_graph_context.strip():
                section = graph_item_format.format(func=loc, dependencies=code_graph_context)
                section_tokens = len(section) // 4  # Conservative estimate: 4 chars per token

                # Add section if within budget
                if tokens_used_global + section_tokens <= total_token_budget:
                    graph_context += section
                    tokens_used_global += section_tokens
                    items_added += 1
                else:
                    items_skipped += 1
                    print(f"[INFO construct_code_graph_context] Section '{loc}' skipped: {section_tokens:,} tokens would exceed budget")

                code_graph_context = ""  # Reset for next section

    # MODIFICATION (Phase 2-6): Log final statistics
    print(f"[DEBUG construct_code_graph_context] Global graph tokens: {tokens_used_global:,}/{total_token_budget:,} (sections_added={items_added}, sections_skipped={items_skipped})")

    return graph_context


# ============================================================================
# File-Level Caller Expansion Functions (Step 0.5)
# ============================================================================

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


# ============================================================================
# Keyword-based Graph Context Functions (Related Level Enhancement)
# ============================================================================

def extract_keywords_from_problem(problem_statement: str,
                                   graph_tags: list,
                                   found_files: list) -> dict:
    """
    問題記述からキーワードを抽出し、タグに存在するもののみ返す

    Args:
        problem_statement: GitHub Issue の問題記述
        graph_tags: tags_*.json のデータ
        found_files: File Level で特定したファイルリスト

    Returns:
        {
            'functions': ['serialize', 'handle', ...],  # 関数+メソッド
            'classes': ['TypeSerializer', ...]          # クラス
        }
    """
    # Step 1: 正規表現でキーワード候補を抽出
    # snake_case パターン (3文字以上)
    snake_case_pattern = r'\b([a-z_][a-z0-9_]{2,})\b'
    snake_candidates = set(re.findall(snake_case_pattern, problem_statement))

    # CamelCase パターン (2文字以上)
    camel_case_pattern = r'\b([A-Z][a-zA-Z0-9]+)\b'
    camel_candidates = set(re.findall(camel_case_pattern, problem_statement))

    # Step 2: found_files 内のタグ名を収集
    tag_names_in_files = {'functions': set(), 'classes': set()}

    for tag in graph_tags:
        if tag.get('kind') != 'def':
            continue
        if tag.get('rel_fname') not in found_files:
            continue

        name = tag.get('name', '')
        category = tag.get('category', '')

        if category == 'function':
            tag_names_in_files['functions'].add(name)
        elif category == 'class':
            tag_names_in_files['classes'].add(name)

    # Step 3: フィルタリング（タグに存在するもののみ）
    # 部分一致: キーワードがタグ名に含まれるか（3文字以上のキーワードのみ）
    def keyword_matches_any_tag(keyword, tag_names):
        """キーワードがいずれかのタグ名に部分一致するか"""
        keyword_lower = keyword.lower()

        # 短いキーワード（3文字未満）は完全一致のみ
        if len(keyword) < 3:
            return keyword_lower in {t.lower() for t in tag_names}

        # 3文字以上は部分一致
        for tag_name in tag_names:
            if keyword_lower in tag_name.lower():
                return True
        return False

    all_tags = tag_names_in_files['functions'] | tag_names_in_files['classes']

    filtered_functions = [kw for kw in snake_candidates
                          if keyword_matches_any_tag(kw, all_tags)]
    filtered_classes = [kw for kw in camel_candidates
                        if keyword_matches_any_tag(kw, all_tags)]

    return {
        'functions': sorted(set(filtered_functions)),
        'classes': sorted(set(filtered_classes))
    }


def keyword_matches_tag(keyword: str, tag_name: str) -> bool:
    """
    キーワードとタグ名のマッチングを判定

    マッチングルール:
    - 3文字未満: 完全一致のみ（id が valid にマッチしないように）
    - 3文字以上: 部分一致（キーワードがタグ名に含まれる）

    Args:
        keyword: 検索キーワード
        tag_name: タグの名前

    Returns:
        bool: マッチするかどうか
    """
    keyword_lower = keyword.lower()
    tag_name_lower = tag_name.lower()

    # 短いキーワード（3文字未満）は完全一致のみ
    if len(keyword) < 3:
        return keyword_lower == tag_name_lower

    # 3文字以上は部分一致（キーワードがタグ名に含まれる）
    return keyword_lower in tag_name_lower


def search_tags_by_keywords(graph_tags: list,
                            keywords: dict,
                            found_files: list) -> dict:
    """
    キーワードにマッチするタグを検索（部分一致対応）

    Args:
        graph_tags: tags_*.json のデータ
        keywords: extract_keywords_from_problem の結果
        found_files: File Level で特定したファイルリスト

    Returns:
        {
            'def': [tag1, tag2, ...],  # 定義タグ
            'ref': [tag3, tag4, ...]   # 参照タグ
        }
    """
    matched_tags = {'def': [], 'ref': []}

    # 全キーワードを収集
    all_keywords = keywords.get('functions', []) + keywords.get('classes', [])

    if not all_keywords:
        return matched_tags

    # タグをループしてマッチング
    seen_defs = set()  # 重複防止
    seen_refs = set()

    for tag in graph_tags:
        # found_files 内のタグのみ対象
        if tag.get('rel_fname') not in found_files:
            continue

        tag_name = tag.get('name', '')
        kind = tag.get('kind', '')
        line = tag.get('line', 0)

        # いずれかのキーワードにマッチするか
        for keyword in all_keywords:
            if keyword_matches_tag(keyword, tag_name):
                if kind == 'def':
                    key = (tag_name, tag.get('rel_fname'), line)
                    if key not in seen_defs:
                        seen_defs.add(key)
                        matched_tags['def'].append(tag)
                elif kind == 'ref':
                    key = (tag_name, tag.get('rel_fname'), line)
                    if key not in seen_refs:
                        seen_refs.add(key)
                        matched_tags['ref'].append(tag)
                break  # 一つのキーワードでマッチしたら次のタグへ

    return matched_tags


def build_keyword_graph_context(matched_tags: dict,
                                 keywords: dict) -> str:
    """
    マッチしたタグから Graph Context 文字列を構築

    Args:
        matched_tags: search_tags_by_keywords の結果
        keywords: extract_keywords_from_problem の結果

    Returns:
        フォーマット済みの Graph Context 文字列
    """
    if not matched_tags['def'] and not matched_tags['ref']:
        return ""

    lines = [
        "",
        "### Supplementary Reference ###",
        "Note: Use this only if the skeleton above is insufficient.",
        ""
    ]

    # Keywords セクション
    func_kws = keywords.get('functions', [])
    class_kws = keywords.get('classes', [])

    if func_kws or class_kws:
        lines.append("Keywords found in codebase:")
        if func_kws:
            lines.append(f"- functions: {', '.join(func_kws[:10])}")
        if class_kws:
            lines.append(f"- classes: {', '.join(class_kws[:10])}")
        lines.append("")

    # Definitions セクション
    if matched_tags['def']:
        lines.append("Definitions:")
        seen = set()
        for tag in matched_tags['def'][:20]:  # 最大20件
            name = tag.get('name', '')
            category = tag.get('category', 'unknown')
            rel_fname = tag.get('rel_fname', '')
            line = tag.get('line', 0)

            key = (name, rel_fname)
            if key not in seen:
                seen.add(key)
                lines.append(f"- {name} ({category}) @ {rel_fname}:{line}")
        lines.append("")

    # References セクション
    if matched_tags['ref']:
        lines.append("References (call sites):")
        seen = set()
        for tag in matched_tags['ref'][:15]:  # 最大15件
            name = tag.get('name', '')
            rel_fname = tag.get('rel_fname', '')
            line = tag.get('line', 0)

            key = (name, rel_fname, line)
            if key not in seen:
                seen.add(key)
                lines.append(f"- {name} @ {rel_fname}:{line}")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Caller/Callee Context (Improved keyword graph context)
# ============================================================================

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


def filter_keywords_with_stopwords(keywords: dict, min_length: int = 4) -> dict:
    """
    ストップワードと長さでキーワードをフィルタリング

    Args:
        keywords: {'functions': [...], 'classes': [...]}
        min_length: 最小文字数

    Returns:
        フィルタリングされたキーワード辞書
    """
    def is_valid_keyword(kw):
        kw_lower = kw.lower()
        # ストップワードチェック
        if kw_lower in KEYWORD_STOP_WORDS:
            return False
        # 長さチェック
        if len(kw) < min_length:
            return False
        # 数字のみは除外
        if kw.isdigit():
            return False
        return True

    return {
        'functions': [kw for kw in keywords.get('functions', []) if is_valid_keyword(kw)],
        'classes': [kw for kw in keywords.get('classes', []) if is_valid_keyword(kw)]
    }


def get_containing_function(ref_tag: dict, graph_tags: list) -> dict:
    """
    ref タグを含む関数を特定する

    Args:
        ref_tag: 参照タグ (kind='ref')
        graph_tags: 全タグリスト

    Returns:
        {'name': 関数名, 'file': ファイルパス} or None
    """
    ref_file = ref_tag.get('rel_fname', '')
    ref_line = ref_tag.get('line', 0)

    # 同じファイル内のdef関数タグを取得
    def_tags_in_file = [
        t for t in graph_tags
        if t.get('rel_fname') == ref_file
        and t.get('kind') == 'def'
        and t.get('category') == 'function'
    ]

    # 行番号でソート
    def_tags_in_file.sort(key=lambda t: t.get('line', 0))

    # ref_line より前で最も近いdef関数を見つける
    containing_func = None
    for tag in def_tags_in_file:
        if tag.get('line', 0) <= ref_line:
            containing_func = tag
        else:
            break

    if containing_func:
        return {
            'name': containing_func.get('name', ''),
            'file': containing_func.get('rel_fname', '')
        }
    return None


def get_callers(keyword: str, graph_tags: list, found_files: list = None, max_count_per_func: int = 5) -> dict:
    """
    キーワードにマッチした関数ごとに、その関数を呼び出している関数（caller）を取得

    Args:
        keyword: 検索キーワード
        graph_tags: 全タグリスト
        found_files: 検索対象ファイルリスト (Noneの場合はフィルタなし)
        max_count_per_func: 関数あたりの最大caller数

    Returns:
        {
            'matched_func_name': [{'name': caller関数名, 'file': ファイルパス}, ...],
            ...
        }
    """
    # マッチした関数名ごとにcallerをグループ化
    callers_by_func = {}
    seen_by_func = {}
    keyword_lower = keyword.lower()

    for tag in graph_tags:
        # refタグのみ対象
        if tag.get('kind') != 'ref':
            continue

        # found_files内のみ対象 (Noneの場合はスキップ)
        if found_files is not None and tag.get('rel_fname') not in found_files:
            continue

        # 部分一致でキーワードを含むか確認
        tag_name = tag.get('name', '')
        if keyword_lower not in tag_name.lower():
            continue

        # このrefタグを含む関数を取得
        caller = get_containing_function(tag, graph_tags)
        if caller:
            # 自己参照を除外（自分自身を呼び出しているケースは除外）
            if caller['name'].lower() == tag_name.lower():
                continue

            # マッチした関数名でグループ化
            if tag_name not in callers_by_func:
                callers_by_func[tag_name] = []
                seen_by_func[tag_name] = set()

            key = (caller['name'], caller['file'])
            if key not in seen_by_func[tag_name]:
                if len(callers_by_func[tag_name]) < max_count_per_func:
                    seen_by_func[tag_name].add(key)
                    callers_by_func[tag_name].append(caller)

    return callers_by_func


def get_callees(keyword: str, graph_tags: list, found_files: list, max_count_per_func: int = 5) -> dict:
    """
    キーワードにマッチした関数ごとに、その関数が呼び出している関数（callee）を取得

    Args:
        keyword: 検索キーワード
        graph_tags: 全タグリスト
        found_files: 検索対象ファイルリスト
        max_count_per_func: 関数あたりの最大callee数

    Returns:
        {
            'matched_func_name': [{'name': callee関数名, 'file': ファイルパス}, ...],
            ...
        }
    """
    callees_by_func = {}
    keyword_lower = keyword.lower()

    # キーワードにマッチする全てのdef関数を見つける
    matching_defs = []
    for tag in graph_tags:
        if tag.get('kind') != 'def':
            continue
        if tag.get('rel_fname') not in found_files:
            continue
        if keyword_lower not in tag.get('name', '').lower():
            continue
        matching_defs.append(tag)

    # 各マッチした関数についてcalleeを取得
    for def_tag in matching_defs:
        def_file = def_tag.get('rel_fname', '')
        def_line = def_tag.get('line', 0)
        def_name = def_tag.get('name', '')

        # 次の関数定義の行を見つけて、関数の終了位置を推定
        next_def_line = None
        for tag in graph_tags:
            if (tag.get('rel_fname') == def_file
                and tag.get('kind') == 'def'
                and tag.get('category') == 'function'
                and tag.get('line', 0) > def_line):
                if next_def_line is None or tag.get('line', 0) < next_def_line:
                    next_def_line = tag.get('line', 0)

        # 関数の範囲を設定（次の関数まで、または500行後）
        func_end = next_def_line - 1 if next_def_line else def_line + 500

        # 関数内のrefタグを収集
        callees = []
        seen = set()
        for tag in graph_tags:
            if tag.get('kind') != 'ref':
                continue
            if tag.get('rel_fname') != def_file:
                continue

            tag_line = tag.get('line', 0)
            if def_line <= tag_line <= func_end:
                callee_name = tag.get('name', '')

                # 自己参照を除外
                if callee_name.lower() == def_name.lower():
                    continue

                if callee_name not in seen:
                    seen.add(callee_name)
                    callees.append({
                        'name': callee_name,
                        'file': def_file
                    })

                    if len(callees) >= max_count_per_func:
                        break

        if callees:
            callees_by_func[def_name] = callees

    return callees_by_func


def build_caller_callee_context(keywords: dict,
                                 graph_tags: list,
                                 found_files: list,
                                 max_callers_per_func: int = 5,
                                 max_callees_per_func: int = 5,
                                 max_keywords: int = 20,
                                 max_functions: int = 30) -> str:
    """
    キーワードにマッチした関数ごとにcaller/callee関係を構築してコンテキストを生成

    Args:
        keywords: 抽出されたキーワード {'functions': [...], 'classes': [...]}
        graph_tags: RepoGraphのタグリスト
        found_files: 検索対象ファイルリスト
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

    # 全キーワードからマッチした関数を収集
    # {関数名: {'callers': [...], 'callees': [...]}}
    func_info = {}

    processed_keywords = 0
    for keyword in all_keywords:
        if processed_keywords >= max_keywords:
            break

        # callerを取得（関数名でグループ化された結果）
        callers_by_func = get_callers(keyword, graph_tags, found_files, max_callers_per_func)
        for func_name, callers in callers_by_func.items():
            if func_name not in func_info:
                func_info[func_name] = {'callers': [], 'callees': []}
            # 重複を避けて追加
            existing_callers = {(c['name'], c['file']) for c in func_info[func_name]['callers']}
            for c in callers:
                if (c['name'], c['file']) not in existing_callers:
                    func_info[func_name]['callers'].append(c)

        # calleeを取得（関数名でグループ化された結果）
        callees_by_func = get_callees(keyword, graph_tags, found_files, max_callees_per_func)
        for func_name, callees in callees_by_func.items():
            if func_name not in func_info:
                func_info[func_name] = {'callers': [], 'callees': []}
            # 重複を避けて追加
            existing_callees = {(c['name'], c['file']) for c in func_info[func_name]['callees']}
            for c in callees:
                if (c['name'], c['file']) not in existing_callees:
                    func_info[func_name]['callees'].append(c)

        processed_keywords += 1

    if not func_info:
        return ""

    # 出力を構築 (ヘッダーはテンプレート側で定義)
    lines = []

    output_count = 0
    for func_name, info in func_info.items():
        if output_count >= max_functions:
            break

        callers = info['callers']
        callees = info['callees']

        # caller も callee も見つからなければスキップ
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


# ============================================================================
# Repair Phase Graph Context (Caller filter disabled)
# ============================================================================

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

    # 全キーワードからマッチした関数を収集
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

        # caller も callee も見つからなければスキップ
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
