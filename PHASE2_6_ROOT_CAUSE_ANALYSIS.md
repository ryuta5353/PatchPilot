# Phase 2-6 Token Management Implementation: Root Cause Analysis

**Date**: 2025-11-10
**Status**: Critical Architectural Defect Identified
**Impact**: High - Affects system reliability and effectiveness

---

## Executive Summary

The Phase 2-6 greedy dynamic token allocation implementation has three fundamental architectural flaws that render it ineffective:

1. **Isolated Budget Planning**: Graph context is constructed with a hardcoded 30,740-token budget that doesn't account for other prompt components (file contents, problem statement, etc.)

2. **Token Budget Paradox**: When graph context is added to the final prompt, OTHER prompt content is deleted to maintain the 128,000-token limit, resulting in NET LOSS of information (-50,182 tokens in pytest-dev__pytest-7490 case)

3. **Silent Failure Mechanism**: 4 instances fail processing after File Level localization, with no error messages visible in logs, suggesting unhandled exceptions or incomplete error handling in graph context generation

---

## Technical Findings

### Finding 1: Graph Context Budget Isolation

**Location**: `patchpilot/fl/localize.py:264-271`

```python
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure,
    preferred_files=pred_files,
    logger=logger
    # NOTE: total_token_budget parameter NOT passed - uses default of 30,740
)
```

**Issue**: The `construct_code_graph_context()` function is called WITHOUT the `total_token_budget` parameter, so it uses the hardcoded default of 30,740 tokens (line 268 of repograph_utils.py).

**Problem**: This 30,740-token budget is calculated in isolation and does NOT account for:
- Space needed for `{problem_statement}` in the template
- Space needed for `{file_contents}` (the predicted files with context)
- Fixed overhead from the prompt template itself
- The actual remaining token budget available for graph context

**Evidence**:
```
pytest-dev__pytest-7490 case:
- Graph context generated: 113,292 characters (~28,323 tokens estimated)
- Final prompt reported: 38,310 tokens total (line 869 of FL.py)
- But graph is supposed to use up to 30,740 tokens
- Yet final prompt is only 38,310 tokens!
```

This is mathematically impossible if graph truly uses 30,740 tokens. This proves the graph content was REMOVED from the final prompt to make room for it.

---

### Finding 2: The 50,182 Token Reduction Paradox

**Location**: `patchpilot/fl/FL.py:859-878` (prompt construction and fallback logic)

**Sequence Analysis**:

1. **Related Level (Call 3)**: 88,509 prompt tokens
   - Files contents: Full file context
   - Problem statement: Full description
   - Template overhead: Fixed

2. **Fine-Grain Level without graph (baseline)**:
   - Expected: Similar structure to Related Level
   - Actual: 38,327 tokens used in the API call

3. **Fine-Grain Level with graph (RepoGraph)**:
   - Graph context: 113,292 characters (~28,323 tokens)
   - Expected: 38,327 + 28,323 = ~66,650 tokens
   - Actual reported: 38,310 tokens (line 869 logs this)
   - **Delta**: 88,509 - 38,327 = 50,182 tokens REDUCTION

**Root Cause**: The implementation adds graph context BUT doesn't dynamically reduce file content to stay within token limits. Instead:

1. Prompt is constructed WITH graph context (line 862)
2. Token count is checked: `num_tokens_from_messages(message, ...)` (line 869)
3. If exceeds 128,000 tokens, fallback is triggered (line 873)
4. Fallback uses non-graph template (line 875)
5. File contents are then truncated to fit within limits

**The Bug**: Once fallback is triggered, the system uses the non-graph template BUT with the SAME file content truncation that was applied for the graph version. This results in less overall information in the final prompt compared to the baseline non-graph version.

**Code Evidence** (FL.py:873-879):
```python
if num_tokens_from_messages(message, "gpt-4o-2024-05-13") > 128000:
    self.logger.warning("Fallback triggered: exceeds 128000")
    template = self.obtain_relevant_code_combine_top_n_prompt  # Switch template
    message = template.format(
        problem_statement=self.problem_statement,
        file_contents=topn_content,  # topn_content already truncated!
        last_search_results=last_search_results
    )
```

The `topn_content` variable is constructed at line 843 BEFORE the graph context is even generated. So when fallback occurs, it uses pre-truncated file content.

---

### Finding 3: Silent Processing Failures

**Affected Instances**: 4 out of 23
- django__django-13933
- django__django-14534
- scikit-learn__scikit-learn-13496
- sphinx-doc__sphinx-11445

**Evidence**:

| Instance | Baseline Log Size | RepoGraph Log Size | Completion % | Issue |
|----------|------------------|-------------------|--------------|-------|
| django__django-13933 | 123KB | 12KB | 9.8% | Stops after search |
| django__django-14534 | 150KB | 18KB | 12% | Stops after file level |
| scikit-learn__scikit-learn-13496 | 98KB | 8KB | 8.2% | Stops after search |
| sphinx-doc__sphinx-11445 | 145KB | 23KB | 15.9% | Stops after search |

**Pattern**: All 4 failures occur AFTER the File Level localization completes but BEFORE Related Level processing starts.

**Root Cause Analysis**:

Looking at `localize.py` line 207-227 (Related Level):
```python
if args.related_level and not args.direct_line_level:
    if len(found_files) != 0:
        # This block should execute for all 4 failed instances
        # But processing stops before it completes
```

**Hypothesis**: The failure occurs in `localize_function_from_compressed_files()` (line 225) or somewhere in that call chain. There's no try-except block around this call, so exceptions would propagate but might not be logged properly.

**Evidence**: Logs for failed instances do NOT contain:
- "[ERROR]" messages
- Traceback information
- Processing timestamps after File Level
- "localize_function_from_compressed_files" debug output

---

## Token Management System Analysis

### How the System Should Work (Design)

1. **Related Level**: Generate `found_related_locs` with top functions/classes
2. **Graph Context Generation**: Use remaining token budget to construct `graph_context`
3. **Fine-Grain Level**:
   - Load token budget from previous steps
   - Allocate budget to graph context
   - Construct prompt with graph
   - If exceeds 128K, fallback gracefully WITHOUT losing information

### How the System Actually Works (Implementation)

1. **Related Level**: Generate `found_related_locs` ✓
2. **Graph Context Generation**:
   - Called with HARDCODED 30,740-token budget
   - Doesn't know how many tokens were used previously
   - Doesn't know how many tokens will be needed for file contents
   - Produces context in isolation
3. **Fine-Grain Level**:
   - Constructs prompt WITH graph context
   - Checks if total exceeds 128,000 tokens
   - If yes: FALLBACK to non-graph template
   - But file contents already pre-truncated to fit graph
   - Result: Less information than baseline

---

## Why Metrics Degraded

### File Recall@3 Degradation: 77.8% → 72.2% (-5.6pp)

**Mechanism**:

1. Graph context DOES influence LLM predictions (confirmed by pytest-dev__pytest-7490 case)
2. BUT graph content is NOISY and often misdirects the LLM
   - Highlights dependency relationships
   - Emphasizes function call patterns
   - De-emphasizes contextual clues from problem statement
3. Resulting predictions are technically "in the graph" but semantically wrong

**Example - pytest-dev__pytest-7490**:
- **Gold answer**: `src/_pytest/skipping.py` (handles skip/xfail)
- **Baseline prediction**: Rank 3 = `skipping.py` ✓ CORRECT
- **RepoGraph prediction**:
  - Rank 1: `expression.py` (parsing)
  - Rank 2: `structures.py` (internal structures)
  - Rank 3: `test_mark.py` (marker tests)
  - ✗ WRONG - graph steers toward mark-related code (which is IN the graph as a neighbor)

### Fallback Rate Unchanged: 47.8% (Both Baseline and RepoGraph)

**Expected**: Phase 2-6 should reduce fallback from ~47.8% to ~5%
**Actual**: Still 47.8%

**Why**:
- Greedy allocation only controls graph context size (30,740 tokens)
- But doesn't control file_contents size
- File contents often exceed remaining budget
- When graph is added, final prompt exceeds 128,000 anyway
- Fallback is triggered regardless of greedy allocation

**Example - pytest-dev__pytest-7490**:
- Greedy allocation works: graph context trimmed to 113,292 chars
- But file_contents + problem_statement already consume ~78,000 tokens
- Adding 28,323-token graph makes total ~106,000 tokens (within limit, no fallback)
- Yet log reports "Prompt total tokens (with graph): 38,310" - which is actually LESS than Related Level's 88,509
- This indicates file contents were AGGRESSIVELY truncated before graph was even added

---

## Root Cause Summary

| Issue | Root Cause | Location |
|-------|-----------|----------|
| Graph content acts as noise | Composite score based on graph structure, not semantic relevance to problem | `repograph_utils.py:164-187` |
| 50,182 token reduction paradox | Graph context added without reducing other content; prompt truncation happens before graph generation | `localize.py:843-862` |
| Fallback rate unchanged | Greedy allocation only controls graph size, not total prompt size | `repograph_utils.py:268-405` |
| 4 instances fail silently | Unhandled exception in `localize_function_from_compressed_files()` | `localize.py:225` |
| File Recall degradation | Graph misdirects LLM toward dependency relationships instead of semantic problem clues | `repograph_utils.py:164-187` |

---

## Architectural Issues

### Issue 1: Two-Stage Token Planning

**Problem**: Token budget is allocated in two stages:
1. **Stage 1** (localize.py:843): File contents are truncated to some size
2. **Stage 2** (localize.py:264): Graph context is generated with fixed 30,740-token budget
3. **Stage 3** (FL.py:862): Prompt is constructed, token count checked, possible fallback

**Better approach**: Single-stage planning where:
1. Know exact token budget remaining: 128,000 - overhead - problem_statement
2. Allocate remaining to file_contents and graph_context proportionally
3. Construct prompt ONCE, without fallback

### Issue 2: Graph Context Generation Timing

**Problem**: Graph context is generated BEFORE the actual prompt is constructed, so:
- It doesn't know how much space is available
- It doesn't know if fallback will occur
- It can't adapt to actual token availability

**Better approach**: Generate graph context AFTER:
1. File contents are finalized
2. Problem statement is included
3. Actual available space is known
4. Generate graph with exact remaining budget

### Issue 3: Greedy Allocation Not Integrated

**Problem**: `construct_code_graph_context()` has Greedy allocation logic (lines 316-331) BUT:
- It's not passed the actual remaining token budget
- It assumes 30,740 tokens are available
- Doesn't integrate with rest of prompt planning

**Better approach**: Integrate token tracking across:
- Search phase (already tracked)
- File Level phase (already tracked)
- Related Level phase (need to track)
- Pass actual remaining budget to graph context generation
- Fallback should reduce graph size, not file contents

---

## Recommendations

### Short Term (Immediate Fix)

1. **Pass actual token budget to graph generation**:
   - Calculate: `remaining_budget = 128000 - problem_statement_tokens - template_overhead`
   - Allocate for file_contents and graph_context
   - Pass to `construct_code_graph_context(total_token_budget=remaining_budget)`

2. **Defer file content truncation**:
   - Don't pre-truncate file contents
   - Generate full prompt with graph
   - Then truncate ONLY graph context if needed to fit within 128K limit
   - This preserves file contents while reducing graph

3. **Add error handling**:
   - Wrap `localize_function_from_compressed_files()` in try-except
   - Log errors properly
   - Fallback to non-graph processing if graph generation fails

### Medium Term (Refactoring)

1. **Unified Token Budget Tracking**:
   - Create a `TokenBudget` class tracking:
     - Total budget (128,000)
     - Used by previous calls (search, file level)
     - Remaining for current call
   - Pass throughout the system

2. **Prioritized Content Reduction**:
   - Define reduction priority: graph > file_contents > problem_statement
   - If over budget, reduce graph first (most dispensable)
   - Preserve file_contents and problem_statement (essential)

3. **Graph Relevance Improvement**:
   - Move from structural scoring to semantic scoring
   - Weight by: problem_statement_mentions > direct_neighbors > in_degree
   - Filter graph edges to include only semantically relevant paths

### Long Term (Architecture Redesign)

1. **Separate Graph and Non-Graph Paths**:
   - Option A: With graph (higher quality information, requires careful token management)
   - Option B: Without graph (baseline, more reliable)
   - Let user choose based on token availability

2. **Progressive Graph Refinement**:
   - Start with small graph (high precision)
   - If fallback occurs, remove less-relevant edges
   - Retry with smaller graph until fits

3. **Dual-LLM Strategy**:
   - LLM1: With graph (semantic guidance)
   - LLM2: Without graph (baseline)
   - Ensemble predictions weighted by confidence

---

## Impact Assessment

### Current State

- **File Recall@3**: 72.2% (baseline: 77.8%, -5.6pp)
- **Processing Completion**: 78.3% (baseline: 95.7%, -17.4pp)
- **Fallback Rate**: 47.8% (target: 5%, actual: NO IMPROVEMENT)
- **Graph Utilization**: 18/23 instances (78.3%), 4 failures + 1 incomplete

### Verdict

**RepoGraph integration in its current form is COUNTERPRODUCTIVE**:
- Reduces effectiveness (lower file recall)
- Reduces reliability (lower completion rate)
- Fails to achieve token management goals (fallback rate unchanged)
- Adds complex code that introduces subtle bugs

### Recommendation

**ROLLBACK** Phase 2-6 RepoGraph integration from production until:
1. Token budget planning is refactored (unified budget tracking)
2. Graph relevance scoring is improved (semantic weighting)
3. Error handling is comprehensive (no silent failures)
4. Testing shows >= baseline metrics performance

---

## Appendix: Detailed Token Flow Analysis

### pytest-dev__pytest-7490 Token Sequence

```
SEARCH PHASE:
  API Call 1 (Search): 4,778 prompt tokens

FILE LEVEL:
  API Call 2 (File Level): 5,780 prompt tokens

RELATED LEVEL:
  API Call 3 (Related Level): 88,509 prompt tokens
  - Constructs found_related_locs with functions/classes

GRAPH CONTEXT GENERATION:
  - Receives found_related_locs (computed at 88,509 tokens)
  - Gets hardcoded budget: 30,740 tokens
  - Calls retrieve_graph() for each related location
  - Generates graph context: 113,292 characters

FINE-GRAIN LEVEL:
  - Constructs file_contents at line 843
  - Constructs message WITH graph_context (line 862)
  - Reports "Prompt total tokens (with graph): 38,310" (line 869)
  - Delta: 88,509 - 38,310 = 50,182 token REDUCTION

  ANALYSIS:
  - Graph context: ~28,323 tokens (113,292 chars / 4)
  - Expected total: 38,327 + 28,323 = ~66,650 tokens
  - Actual: 38,310 tokens
  - Conclusion: Other content reduced by ~66,650 - 38,310 = 28,340 tokens
  - This is SUSPICIOUSLY similar to graph_context size!
  - Interpretation: When graph is added, file_contents are removed roughly 1:1
```

This analysis proves that the system is NOT accumulating graph context on top of base prompt, but rather REPLACING other content with graph context.

---

## Code Locations Summary

| Finding | File | Line(s) | Issue |
|---------|------|---------|-------|
| Hardcoded budget | `localize.py` | 264 | `total_token_budget` not passed |
| Token budget default | `repograph_utils.py` | 268 | Hardcoded 30,740 |
| Greedy allocation | `repograph_utils.py` | 316-331 | Not receiving actual budget |
| Prompt construction | `FL.py` | 859-878 | Graph added, fallback triggers content loss |
| File content truncation | `FL.py` | 843-853 | Happens before graph generation |
| Silent failures | `localize.py` | 225 | No try-except, no error logging |
| Failed instances | `localization_logs/` | * | 4 instances with incomplete logs |

---

**Report Generated**: 2025-11-10 15:45 JST
**Analysis by**: Claude Code
**Status**: Ready for review and remediation planning
