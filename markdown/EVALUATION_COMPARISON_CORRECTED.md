# Evaluation Comparison: Baseline vs RepoGraph (Corrected)

## Executive Summary

This report compares the fault localization performance between the baseline approach and the RepoGraph-enhanced approach on 10 Django instances using the corrected evaluation methodology.

## Results Overview

| Metric | Baseline | RepoGraph | Difference | Winner |
|--------|----------|-----------|------------|--------|
| **Line Recall (MOST IMPORTANT)** | 17.2% | 11.3% | -5.9% | **Baseline** |
| **File Recall@3** | 55.6% | 66.7% | +11.1% | **RepoGraph** |
| **Function Recall** | N/A | N/A | N/A | N/A |

## Detailed Analysis

### Line Recall (Primary Metric)
- **Baseline**: 17.2% (1.6/9 instances)
- **RepoGraph**: 11.3% (1.0/9 instances)
- **Difference**: -5.9 percentage points
- **Winner**: Baseline

The baseline approach shows better line-level recall, which is the most important metric for fault localization. RepoGraph's line recall is actually worse than baseline by approximately 6 percentage points.

### File Recall@3 (Secondary Metric)
- **Baseline**: 55.6% (5.0/9 instances)
- **RepoGraph**: 66.7% (6.0/9 instances)
- **Difference**: +11.1 percentage points
- **Winner**: RepoGraph

RepoGraph shows improvement in file-level localization, successfully identifying the correct file in the top-3 predictions for one additional instance compared to baseline.

### Function Recall
- Both approaches returned N/A for function recall, indicating that function-level information is not available in the gold answers for these instances.

## Instance-by-Instance Breakdown

### Instances Where Baseline Performed Better

1. **django__django-11630**
   - Baseline Line Recall: 50.0% (8/16 lines)
   - RepoGraph Line Recall: 0.0% (0/16 lines)
   - Baseline found the file correctly and located 8 out of 16 gold lines

2. **django__django-11848**
   - Baseline Line Recall: 57.1% (4/7 lines)
   - RepoGraph Line Recall: 28.6% (2/7 lines)
   - Baseline found nearly twice as many correct lines

### Instances Where RepoGraph Performed Better

1. **django__django-11815**
   - Baseline Line Recall: 0.0% (0/4 lines)
   - RepoGraph Line Recall: 25.0% (1/4 lines)
   - RepoGraph also found the correct file (baseline missed it)

2. **File-level only improvements**:
   - django__django-11797: RepoGraph missed the file, baseline also missed

### Instances With Equal Performance

1. **django__django-11583**
   - Both: 25.0% (1/4 lines)
   - Both found the correct file

2. **django__django-11422, 11564, 11620, 11905**
   - Both had 0.0% line recall

## Missing Instances

- **Baseline**: Missing django__django-11797
- **RepoGraph**: Missing django__django-11742

## Key Findings

1. **Line-level accuracy favors Baseline**: The baseline approach achieves better overall line recall (17.2% vs 11.3%), which is critical for effective fault localization.

2. **File-level accuracy favors RepoGraph**: RepoGraph shows improvement in identifying the correct files (66.7% vs 55.6%), suggesting better initial file filtering.

3. **Trade-off between breadth and precision**: RepoGraph appears to cast a wider net at the file level but sacrifices precision at the line level, while baseline is more focused but achieves better line-level accuracy.

4. **Low absolute performance**: Both approaches show relatively low line recall (under 20%), indicating significant room for improvement in the fault localization process.

5. **Instance coverage**: Both approaches failed to process all 10 instances, each missing one different instance.

## Conclusions

Based on the corrected evaluation:

- **For line-level localization (most important)**: **Baseline is superior** with a 5.9 percentage point advantage
- **For file-level localization**: **RepoGraph is superior** with an 11.1 percentage point advantage
- **Overall recommendation**: **Baseline is preferred** since line-level accuracy is the primary metric for effective fault localization

The RepoGraph integration improves file-level recall but degrades the more critical line-level recall. Further investigation is needed to understand why RepoGraph's additional context leads to worse line-level predictions despite better file identification.

## Recommendations

1. Investigate why RepoGraph's improved file recall doesn't translate to better line recall
2. Consider a hybrid approach that uses RepoGraph for file-level filtering but applies baseline techniques for line-level localization
3. Analyze the specific instances where RepoGraph failed (11630, 11848) to understand what contextual information led to worse predictions
4. Improve overall line recall for both approaches, as neither achieves satisfactory performance (both under 20%)
