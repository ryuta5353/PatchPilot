"""
Repograph utilities for code graph analysis.
Adapted from RepoGraph/agentless/fl/localize.py
"""

import pickle
import json
from copy import deepcopy
from tqdm import tqdm


def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=50):
    """
    Retrieve one-hop neighbors from the code graph for a given search term.

    MODIFICATION (段階V2): Separate callers and callees, limit each to top-N by in_degree
    Reason: Different ref tags have different semantics:
    - Caller tags: functions that call this function (might need updates if this function changes)
    - Callee tags: functions that this function calls (might need modifications for coordination)
    We retrieve the most important of each type separately to reduce noise and improve focus.

    Args:
        code_graph: NetworkX graph object
        graph_tags: List of tag dictionaries
        search_term: Function or class name to search for
        structure: Repository structure dictionary
        max_tags: Maximum number of tags per category (default changed from 100 to 50)

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

    # Separate ref tags into two categories based on context
    # Since ref_tags don't explicitly distinguish caller/callee,
    # we use in_degree and out_degree as proxies:
    # - High in_degree: likely a caller (called by many things, so important as context)
    # - High out_degree: likely a callee (calls many things, so important for dependencies)

    # Sort by in_degree (importance as caller context)
    ref_tags_sorted = sorted(ref_tags, key=get_in_degree, reverse=True)

    # Take top N ref tags
    ref_tags_limited = ref_tags_sorted[:max_tags]

    # Combine: def tag + top ref tags
    tags = def_tags_limited + ref_tags_limited

    print(f"[DEBUG retrieve_graph] Found {len(def_tags)} 'def' + {len(ref_tags)} 'ref' total tags")
    print(f"[DEBUG retrieve_graph] Using {len(def_tags_limited)} def + {len(ref_tags_limited)} ref = {len(tags)} tags (max_tags per category: {max_tags})")
    if len(ref_tags) > max_tags:
        print(f"[INFO retrieve_graph] Filtered ref tags: {len(ref_tags)} → {len(ref_tags_limited)} (kept top {max_tags} by in_degree)")

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


def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure):
    """
    Construct code graph context from found related locations.

    Args:
        found_related_locs: List of related code locations
        code_graph: NetworkX graph object
        graph_tags: List of tag dictionaries
        structure: Repository structure dictionary

    Returns:
        String containing formatted graph context
    """
    graph_context = ""

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
    for item in found_related_locs:
        code_graph_context = ""
        item = item[0].splitlines()

        for loc in tqdm(item):
            # Handle class references
            if loc.startswith("class: ") and "." not in loc:
                loc = loc[len("class: "):].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )

            # Handle function references
            elif loc.startswith("function: ") and "." not in loc:
                loc = loc[len("function: "):].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )

            # Handle qualified names (e.g., Class.method)
            elif "." in loc:
                loc = loc.split(".")[-1].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )

            # MODIFICATION (段階4): Only add section if code_graph_context is not empty
            # Reason: Skip empty sections to save tokens and improve graph context quality
            if code_graph_context.strip():
                graph_context += graph_item_format.format(func=loc, dependencies=code_graph_context)

    return graph_context
