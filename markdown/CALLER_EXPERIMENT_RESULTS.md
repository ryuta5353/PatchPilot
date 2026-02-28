# Localization Experiment Results (43 Django Instances)

Date: 2025-12-08

## Summary

| Metric | Baseline | RepoGraph | Diff |
|--------|----------|-----------|------|
| File-Level | 36/43 (83.7%) | 32/43 (74.4%) | -4 |
| Line-Level | 28/43 (65.1%) | 28/43 (65.1%) | +0 |

## Detailed Results

| Instance | File(Base) | File(Repo) | Line(Base) | Line(Repo) | Seeds | Callers |
|----------|------------|------------|------------|------------|-------|--------|
| django__django-10914 | O | O | O | O | 0 | 0 |
| django__django-11099 | O | O | O | O | 2 | 5 |
| django__django-11133 | O | O | X | O | 1 | 10 |
| django__django-11179 | O | O | O | X | 0 | 0 |
| django__django-11815 | O | X | O | X | 0 | 0 |
| django__django-11848 | O | O | O | O | 1 | 1 |
| django__django-11964 | X | X | X | X | 0 | 0 |
| django__django-11999 | X | X | X | X | 0 | 0 |
| django__django-12125 | O | O | X | X | 0 | 0 |
| django__django-12308 | O | O | O | O | 5 | 2 |
| django__django-12708 | O | O | O | O | 0 | 0 |
| django__django-13028 | O | O | X | X | 0 | 0 |
| django__django-13033 | O | X | X | X | 0 | 0 |
| django__django-13158 | X | X | X | X | 0 | 0 |
| django__django-13315 | O | O | O | O | 0 | 0 |
| django__django-13401 | O | O | O | O | 0 | 0 |
| django__django-13551 | O | O | O | O | 1 | 0 |
| django__django-13590 | O | O | O | O | 0 | 0 |
| django__django-13658 | O | O | O | O | 2 | 2 |
| django__django-13925 | X | X | X | X | 1 | 0 |
| django__django-13933 | O | O | O | O | 1 | 0 |
| django__django-13964 | O | O | X | O | 0 | 0 |
| django__django-14017 | O | O | O | O | 196 | 10 |
| django__django-14155 | O | O | O | O | 1 | 0 |
| django__django-14238 | O | O | O | O | 1 | 0 |
| django__django-14534 | O | O | O | O | 2 | 1 |
| django__django-14580 | O | X | X | X | 25 | 0 |
| django__django-14608 | O | O | O | O | 1 | 0 |
| django__django-14672 | O | O | O | O | 2 | 7 |
| django__django-14752 | O | O | O | O | 1 | 0 |
| django__django-14787 | O | O | O | O | 0 | 0 |
| django__django-14855 | O | O | O | O | 0 | 0 |
| django__django-14915 | O | O | X | O | 0 | 0 |
| django__django-14999 | O | O | O | O | 1 | 1 |
| django__django-15252 | O | O | O | O | 1 | 3 |
| django__django-15695 | X | X | X | X | 0 | 0 |
| django__django-15814 | O | O | X | X | 0 | 0 |
| django__django-15851 | X | X | X | X | 0 | 0 |
| django__django-16139 | O | O | O | O | 1 | 0 |
| django__django-16255 | O | O | O | O | 0 | 0 |
| django__django-16527 | O | O | O | O | 0 | 0 |
| django__django-16595 | O | X | O | X | 1 | 4 |
| django__django-17087 | X | X | X | X | 1 | 0 |

## Analysis

### File-Level Changes

- Improved (Base X -> Repo O): 0
- Degraded (Base O -> Repo X): 4
  - django__django-11815 (callers=0)
  - django__django-13033 (callers=0)
  - django__django-14580 (callers=0)
  - django__django-16595 (callers=4)

### Line-Level Changes

- Improved (Base X -> Repo O): 3
  - django__django-11133 (callers=10)
  - django__django-13964 (callers=0)
  - django__django-14915 (callers=0)
- Degraded (Base O -> Repo X): 3
  - django__django-11179 (callers=0)
  - django__django-11815 (callers=0)
  - django__django-16595 (callers=4)

### Caller Feature Usage

- Instances with callers > 0: 11/43

---
Legend: O = Correct, X = Incorrect
