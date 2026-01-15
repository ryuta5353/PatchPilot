# Phase 2-6 Investigation Report: Greedy Dynamic Token Allocation

**Date**: 2025-11-09
**Focus**: Why line-level performance degraded despite file-level improvement

## Executive Summary

Phase 2-6 (Greedy Dynamic Token Allocation) was implemented to optimize graph context within a 30,740 token budget. However:

- **File-level improved** by +5.3pp (68.4% → 73.7%) ✓
- **Line-level degraded** by -8.5pp (24.1% → 15.6%) ✗

The investigation reveals the Greedy allocation has **critical implementation issues** preventing proper token control, and more importantly, **graph context provides poor quality guidance for line-level precision**.

## Key Findings

### 1. CRITICAL: Logging Issue - Debug Output Not Visible

**Problem**: Phase 2-6 implementation uses `print()` statements instead of `logger.info()`, so debug output is NOT captured in log files.

**Impact**:
- Cannot verify that Greedy allocation is actually working
- Cannot see token limiting decisions (why tags were skipped)
- Cannot validate that budget is being respected

**Evidence**:
```
Searched for: "Token limit reached", "Global graph tokens", "DEBUG construct_code_graph_context"
Result: NO MATCHES in any log file (0/23 instances)
```

**Root Cause**:
- Lines 326, 391, 396 in `repograph_utils.py`: Use `print()` instead of proper logger
- Line 244 in `repograph_utils.py`: Uses `tqdm()` print which may not be logged

**Recommendation**: Replace `print()` with proper logging to see actual Greedy allocation behavior.

---

### 2. Token Budget Exceeded - Average 33.3K vs 30.7K Budget

**Finding**: Average token usage across all instances is **33,313 tokens**, exceeding the 30,740 budget by **2,573 tokens (8.4% over)**.

**Instance Breakdown**:
| Instance | Sections | Tokens | Status |
|----------|----------|--------|--------|
| astropy__astropy-12907 | 30 | 69,938 | SAME (2.3x budget!) |
| pytest-dev__pytest-7490 | 25 | 36,481 | IMPROVED ✓ |
| pylint-dev__pylint-7080 | 24 | 44,949 | SAME (1.5x budget) |
| sphinx-doc__sphinx-8595 | 17 | 51,170 | DEGRADED ✗ |

**Conclusion**: Greedy allocation is NOT properly constraining tokens to the 30,740 budget.

---

### 3. FALLBACK MECHANISM: 1 Instance (pydata__xarray-4094)

**Problem**: File-level improved 0% → 100%, but this was NOT due to graph context.

**Details**:
- Graph context with graph: **146,536 tokens** (exceeds 128K hard limit by 18,536)
- **FALLBACK TRIGGERED** → switched to non-graph template
- Final tokens without graph: 119,277

**Impact**: File-level improvement was due to LLM randomness with non-graph template, NOT due to graph context working correctly.

**Implication**: True file-level improvement is only 1 instance (pytest-dev__pytest-7490), not 2.

---

### 4. Graph Context Size vs Performance: The Quality Trade-off

**Finding**: Larger graphs correlate with worse line-level performance.

#### Best Case (LINE-LEVEL IMPROVED):
- **Instance**: django__django-13401
- **Graph**: 4 sections, 8 locations, **12K chars**, 29,994 tokens
- **Performance**: 9% → 17% (improvement +8.7pp)
- **Profile**: Small, focused graph

#### Worst Case (LINE-LEVEL DEGRADED):
- **Instance**: sphinx-doc__sphinx-8595
- **Graph**: 17 sections, 84 locations, **122K chars**, 51,170 tokens
- **Performance**: 100% → 0% (degradation -100pp)
- **Profile**: MASSIVE, unfocused graph

#### Pattern:
```
django__django-13401:     12K chars → LINE IMPROVED ✓
astropy__astropy-14182:    10K chars → LINE DEGRADED (slightly)
pytest-dev__pytest-7432:   34K chars → LINE DEGRADED
sphinx-doc__sphinx-11445: 122K chars → LINE DEGRADED
sphinx-doc__sphinx-8595:  122K chars → LINE DEGRADED ✗✗
```

**Hypothesis**: **Graph context overwhelms the LLM with too many function/class definitions, creating noise that obscures line-level precision.**

---

### 5. Composite Score Weakness

**Issue**: Composite score (file locality + direct neighbor + in_degree) prioritizes "relevant" files but includes TOO MANY definitions.

**Evidence**:
- pytest-dev__pytest-7490: 25 sections, 93 locations → File improved but line stayed 0%
- sphinx-doc__sphinx-8595: 17 sections, 84 locations → File same, line degraded 100%

**Problem with Current Scoring**:
1. File locality (1000/100/1): Good for finding relevant files
2. BUT: Includes ALL functions from those files
3. When showing 84 locations → LLM must scan through 84+ functions
4. Line-level recall requires precision → too much noise → worse recall

**Recommendation**: Limit number of tags per location or implement more aggressive token limiting.

---

### 6. Token-Aware Tag Limiting Implementation (retrieve_graph)

**Status**: Implemented but incomplete/ineffective

**Current Implementation** (lines 209-229, repograph_utils.py):
```python
if max_tokens_for_section is not None:
    for tag in ref_tags_sorted:
        tag_tokens = len(str(tag.get('text', []))) // 4  # Token estimation
        if tokens_used + tag_tokens > max_tokens_for_section:
            break  # Stop adding tags
        ref_tags_limited.append(tag)
```

**Issues**:
1. Token estimation `// 4` is crude approximation
2. Only applies to `ref_tags`, NOT `def_tags` (line 105 takes first def unconditionally)
3. Doesn't account for section header, formatting tokens
4. `max_tokens_for_section` value may be too large (budget spread across many sections)

**Execution Path**:
- Greedy allocation: `max_tokens_this_section = remaining_budget / sections_remaining`
- Example: 30,740 / 17 sections = 1,808 tokens per section
- But actual context size is 51K+ tokens (17 sections × 3K+ avg = exceeds)

---

## Root Cause Analysis

### Why File-level Improved But Line-level Degraded?

**File-level Improvement Mechanism**:
- Graph context provides additional dependency context
- LLM can better identify which FILES are relevant
- Composite score helps find the right files
- Result: File recall improved (+5.3pp)

**Line-level Degradation Mechanism**:
- Graph context includes TOO MANY function definitions
- Each definition adds 100-300 tokens (parameter descriptions, function bodies)
- 84 locations × 200 tokens = 16,800+ tokens of function code
- When presented with 84+ function definitions, LLM loses focus
- Cannot precisely identify which LINES within files are relevant
- Result: Line recall degraded (-8.5pp)

**Analogy**:
- File-level: "Here are files A, B, C that are related" → Works well ✓
- Line-level: "Here are 84 function definitions and their internals" → Too much noise ✗

---

## Technical Issues Found

### Issue #1: Debug Output Not Logged
- **Location**: `repograph_utils.py` lines 326, 391, 396
- **Problem**: Uses `print()` instead of `logger.info()`
- **Impact**: Cannot verify Greedy allocation is working
- **Fix**: Replace `print()` calls with `logging.info()` or pass logger object

### Issue #2: Token Budget Exceeded
- **Location**: `construct_code_graph_context()` line 330
- **Problem**: Average token usage 33.3K > budget 30.7K
- **Root Cause**:
  - Token estimation (section_tokens = len(section) // 4) is inaccurate
  - Actual tokens in prompt include formatting, context, system messages
  - Greedy allocation per-section formula doesn't account for global overhead
- **Fix**: Use actual tokenizer to count tokens instead of character-based estimation

### Issue #3: def_tags Not Token-Limited
- **Location**: `retrieve_graph()` line 105
- **Problem**: `def_tags_limited = def_tags[:1]` takes definition unconditionally
- **Impact**: Cannot skip definitions if token budget is tight
- **Fix**: Apply token-aware limiting to def_tags as well

### Issue #4: Tag Ordering for Line-level Precision
- **Location**: `retrieve_graph()` lines 196-200
- **Problem**: Composite score optimizes for file locality, not line-level relevance
- **Impact**: May prioritize large functions over small but critical functions
- **Recommendation**:
  - For file-level: Use composite score (works well)
  - For line-level: Use different scoring (in-degree only, or def-ref weight)

---

## Performance Data

### File-level (Recall@3)
- Baseline: 68.4%
- Repograph: 73.7%
- Delta: **+5.3pp** ✓ (Improved)

**Improved**: 2 instances (1 via fallback)
**Degraded**: 1 instance
**Same**: 16 instances

### Line-level
- Baseline: 24.1%
- Repograph: 15.6%
- Delta: **-8.5pp** ✗ (Degraded)

**Improved**: 1 instance (django__django-13401, +8.7pp)
**Degraded**: 4 instances (up to -100pp)
**Same**: 14 instances

---

## Recommendations

### Short-term (Debug Phase 2-6)
1. **Fix logging**: Replace `print()` with `logger.info()` to see actual behavior
2. **Verify token counting**: Add actual tokenizer instead of char/4 estimation
3. **Test Greedy allocation**: Run on single instance and verify:
   - Are tags actually being skipped when budget is tight?
   - What is actual token usage per section?
   - Is token limiting working as designed?

### Medium-term (Improve Line-level Performance)
1. **Reduce graph context size**:
   - Limit number of locations from 50-100+ to 10-20
   - OR: Limit tag count per location (max 3-5 tags per location)
   - OR: Remove function bodies, keep only signatures

2. **Two-tier context approach**:
   - File-level phase: Use full graph context (optimized for file selection)
   - Line-level phase: Use minimal graph context (only call relationships, no bodies)

3. **Adjust composite score for line-level**:
   - When generating context for line-level, de-prioritize functions from unrelated files
   - Focus on dependencies within the same file first

### Long-term (Redesign Graph Context Strategy)
1. **Separate file and line contexts**:
   - File context: Show dependency graph structure (minimal code)
   - Line context: Show only essential function signatures + inline comments

2. **Context prioritization by relevance**:
   - Use bug description to weight which functions are most critical
   - Use execution trace (if available) to prioritize hot functions

3. **Adaptive token allocation**:
   - For simple bugs (few dependencies): Use full context
   - For complex bugs (many dependencies): Use filtered context

---

## Test Instance Profiles

### WHERE GRAPH HELPED (File-level improved)
**pytest-dev__pytest-7490**
- File-level: 0% → 100% ✓
- Line-level: 0% → 0% (no change)
- Graph: 25 sections, 93 locations, 88K chars, 36K tokens
- Note: Graph context helped find the file but not the lines

### WHERE GRAPH HURT (Line-level degraded)
**sphinx-doc__sphinx-8595**
- File-level: 100% → 100% (no change, already found)
- Line-level: 100% → 0% ✗✗
- Graph: 17 sections, 84 locations, 122K chars, 51K tokens
- Note: Massive graph context with 84 locations confused the LLM

**sphinx-doc__sphinx-11445**
- File-level: 100% → 0% ✗ (DEGRADED)
- Line-level: 17% → 0% ✗
- Graph: 17 sections, 82 locations, 122K chars, 35K tokens
- Note: Large graph actually harmed both metrics

### BEST CASE (Line-level improved)
**django__django-13401**
- File-level: 100% → 100% (same)
- Line-level: 9% → 17% ✓
- Graph: 4 sections, 8 locations, 12K chars, 30K tokens
- Note: SMALLEST graph with focused content = LINE IMPROVEMENT

---

## Conclusion

Phase 2-6 implementation has **structural issues** preventing proper evaluation:
1. **Debug output not visible** → Can't verify implementation correctness
2. **Token budget exceeded** → Greedy allocation not working as designed
3. **Fallback masking results** → File improvement attributed to graph but due to fallback

More importantly, the **graph context quality vs size trade-off** reveals:
- **Graph helps file-level selection** (better file ranking)
- **Graph hurts line-level precision** (too much noise, 12K chars good, 122K chars bad)

**The root issue is not the Greedy allocation algorithm, but the fundamental mismatch between providing broad context (good for files) and precise guidance (needed for lines).**

Recommend redesigning to use **separate, purpose-built contexts for file vs line localization** rather than a single large graph context.
