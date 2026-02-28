# Best Strategy: RepoGraph at File-Level Localization

## Current Problem

Current File-Level Localization Flow:
1. LLM proposes search keywords (Step 0)
2. Execute search_string, search_class_def, search_func_def
3. Coverage or Repository Structure + Search Results -> LLM selects files

Issues:
- If search keywords are not appropriate, related files are missed
- Without Coverage, repository structure alone is insufficient
- Dependencies are not considered

---

## Proposal: 2-Phase Approach

### Phase A: Initial File Candidate Retrieval (Existing)
- Step 0: LLM proposes search keywords -> Execute search
- Step 1: LLM selects file candidates (max top_n)

### Phase B: Expand Candidates with RepoGraph Dependencies (NEW)
- Step 2: Get dependencies of initial candidate files
- Step 3: Add dependency files to candidate list

---

## Concrete Implementation

### Step 2-3 Details

```python
def get_file_dependencies(target_file: str, tags: list[dict]) -> tuple[dict, dict]:
    """
    Get file-level dependencies from RepoGraph tags.

    Returns:
        incoming: dict[file_path -> set of function names] - files that USE target_file's functions
        outgoing: dict[file_path -> set of function names] - files whose functions ARE USED BY target_file
    """
    from collections import defaultdict

    # Step 1: Find all defs in target file
    defs_in_file = [t for t in tags if t['rel_fname'] == target_file and t['kind'] == 'def']
    def_names = set(t['name'] for t in defs_in_file)

    # Step 2: Incoming - files that USE target_file's functions
    incoming_files = defaultdict(set)
    for t in tags:
        if t['kind'] == 'ref' and t['name'] in def_names and t['rel_fname'] != target_file:
            incoming_files[t['rel_fname']].add(t['name'])

    # Step 3: Outgoing - files whose functions are USED BY target_file
    refs_in_file = [t for t in tags if t['rel_fname'] == target_file and t['kind'] == 'ref']
    ref_names = set(t['name'] for t in refs_in_file)

    outgoing_files = defaultdict(set)
    for t in tags:
        if t['kind'] == 'def' and t['name'] in ref_names and t['rel_fname'] != target_file:
            outgoing_files[t['rel_fname']].add(t['name'])

    return dict(incoming_files), dict(outgoing_files)


def expand_files_with_dependencies(
    initial_files: list[str],
    graph_tags: list[dict],
    max_expansions: int = 3,
    min_connections: int = 2,
    exclude_patterns: list[str] = ['test', 'tests', 'conftest']
) -> list[str]:
    """
    Expand initial file candidates using RepoGraph dependencies.

    Args:
        initial_files: Initial file candidate list
        graph_tags: RepoGraph tags (JSON)
        max_expansions: Maximum number of files to add
        min_connections: Minimum function connection count (noise filter)
        exclude_patterns: File patterns to exclude

    Returns:
        Expanded file list
    """
    expansion_candidates = {}

    for initial_file in initial_files:
        incoming, outgoing = get_file_dependencies(initial_file, graph_tags)

        # OUTGOING priority (more likely to need modification)
        for file_path, funcs in outgoing.items():
            if len(funcs) >= min_connections:
                if not any(pat in file_path.lower() for pat in exclude_patterns):
                    if file_path not in initial_files:
                        score = len(funcs) * 2  # OUTGOING weight
                        if file_path in expansion_candidates:
                            expansion_candidates[file_path] += score
                        else:
                            expansion_candidates[file_path] = score

        # INCOMING (reference information)
        for file_path, funcs in incoming.items():
            if len(funcs) >= min_connections:
                if not any(pat in file_path.lower() for pat in exclude_patterns):
                    if file_path not in initial_files:
                        score = len(funcs)  # INCOMING weight
                        if file_path in expansion_candidates:
                            expansion_candidates[file_path] += score
                        else:
                            expansion_candidates[file_path] = score

    # Sort by score and add top candidates
    sorted_candidates = sorted(
        expansion_candidates.items(),
        key=lambda x: x[1],
        reverse=True
    )

    expanded_files = initial_files.copy()
    for file_path, score in sorted_candidates[:max_expansions]:
        expanded_files.append(file_path)

    return expanded_files
```

---

## Why This Approach is Best

### 1. Minimal Changes, Maximum Effect
- Existing Step 0-1 unchanged
- Just add Step 2-3
- Fine-grain level keeps existing RepoGraph integration

### 2. Design Based on Investigation Results
- Failed instance analysis showed 3/4 discoverable via INCOMING/OUTGOING
- OUTGOING prioritized (files "used by" predicted file = more likely to need modification)
- Filter by function count (noise reduction)

### 3. Low Computational Cost
- Direct calculation from tags JSON (no pkl needed)
- 1-hop search only (O(n))
- No increase in LLM calls

### 4. Flexible Tuning
- max_expansions: Control number of added files
- min_connections: Noise reduction threshold
- OUTGOING/INCOMING weighting

---

## Evidence from Investigation

| Instance | Gold File | Predicted File | 1-hop Discovery |
|----------|-----------|----------------|-----------------|
| django-11999 | fields/__init__.py | base.py | OUTGOING (10 funcs), INCOMING (1 func) |
| sympy-13031 | matrices.py | dense.py | INCOMING (17 funcs) |
| pytest-7490 | nodes.py | python.py | INCOMING (7 funcs) |
| pylint-7080 | argument.py | config_initialization.py | 1-hop: NO, 2-hop: YES |

**Result: 3/4 failed cases discoverable via 1-hop dependencies!**

---

## Expected Effect

### Before (Current)
- File Recall@3: Baseline
- Depends on search keywords
- Accuracy drops without Coverage

### After (Proposed)
- File Recall@3: +5-10% improvement expected
- Dependencies complement missed files
- Especially effective for "tightly coupled modules"

---

## Implementation Location

```
patchpilot/fl/
├── FL.py                 # Existing (no changes)
├── localize.py           # Add Step 2-3
├── repograph_utils.py    # Add expand_files_with_dependencies()
```

### Code Integration Point in localize.py

```python
# After file level localization (around line 168)
if args.file_level:
    # ... existing code ...
    found_files, additional_artifact_loc_file, file_traj = fl.localize(...)

# NEW: Expand with RepoGraph dependencies
if args.repo_graph and graph_tags is not None:
    from patchpilot.fl.repograph_utils import expand_files_with_dependencies
    found_files = expand_files_with_dependencies(
        initial_files=found_files,
        graph_tags=graph_tags,
        max_expansions=3,
        min_connections=2
    )
    logger.info(f"Expanded files with dependencies: {found_files}")
```

---

## Caveats and Limitations

1. **Instances without RepoGraph**: Maintain existing flow without expansion
2. **Large repositories**: May need score normalization if too many dependencies
3. **Circular dependencies**: Avoided by limiting to 1-hop
4. **Test files**: Explicitly excluded via exclude_patterns

---

## Summary

The most simple and effective method:
1. Keep existing file-level candidate retrieval
2. Calculate dependencies (OUTGOING > INCOMING) of retrieved candidate files
3. Rank by function count, add top candidates to list
4. Pass expanded file list to Fine-grain level

Benefits:
- Minimal code changes
- LLM call count unchanged
- Dependencies complement missed files
- Consistent with investigation results (3/4 discoverable via 1-hop)
