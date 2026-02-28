# Debugging Summary: found_edit_locs Parsing Issue

## Problem Statement

The evaluation script reports that `found_edit_locs` appears to be empty, even though line numbers ARE present in the JSON data at `results/localization_repograph_corrected/loc_outputs.jsonl`.

## Root Cause Identified

**The data is NOT empty!** The bug is in the evaluation script's parsing logic at two locations:

### Bug #1: Line Recall Calculation (Lines 76-99 in evaluate_localization.py)

**Current Code:**
```python
for sample in predicted_edit_locs:
    if not sample:
        continue
    for file_result in sample:
        if not file_result:
            continue
        result_str = file_result[0] if isinstance(file_result, list) else file_result
        for line in result_str.split('\n'):
            line = line.strip()
            if line.startswith('line: '):
                try:
                    line_num = int(line.split(': ')[1].strip())
                    # BUG: Associates with first gold file (heuristic - they analyze gold file first)
                    for gold_file in gold_lines_dict.keys():
                        if gold_file not in predicted_lines_all:
                            predicted_lines_all[gold_file] = set()
                        predicted_lines_all[gold_file].add(line_num)
                        break  # <-- BUG: Only add to first gold file
                except (ValueError, IndexError):
                    continue
```

**Problem**:
- The `break` statement assigns ALL line numbers to the first gold file
- Files are NOT actually being matched; the code just dumps everything into the first key in `gold_lines_dict`

**Impact**:
- When `gold_lines_dict = {"django/views/debug.py": [8, 11, 486]}`
- ALL predicted lines get assigned to "django/views/debug.py"
- But the actual predictions are in files like "django/shortcuts.py", "django/middleware/common.py", "django/urls/resolvers.py"
- Result: **0% recall** because we're checking if lines from resolvers.py exist in the debug.py gold set

### Bug #2: Display Logic (Lines 164-183)

**Current Code:**
```python
for loc_group in predicted_edit_locs:
    if not loc_group:
        continue
    for loc_item in loc_group:
        if not loc_item:
            continue
        loc_str = loc_item if isinstance(loc_item, str) else str(loc_item)
        for line in loc_str.split('\n')[:20]:
            if line.strip().startswith('line: '):
                try:
                    line_num = int(line.strip().split(': ')[1])
                    if predicted_files:
                        f = predicted_files[0]  # <-- BUG: Always uses first file
                        if f not in predicted_lines_display:
                            predicted_lines_display[f] = []
                        predicted_lines_display[f].append(line_num)
                except:
                    pass
```

**Problem**:
- Uses `predicted_files[0]` for ALL lines
- Ignores the actual file structure in the data

## Data Structure (Verified Correct)

The JSON structure is:

```json
{
  "instance_id": "django__django-11620",
  "found_files": [
    "django/shortcuts.py",          // Index 0
    "django/middleware/common.py",  // Index 1
    "django/urls/resolvers.py"      // Index 2
  ],
  "found_edit_locs": [
    [  // Sample 0
      [""],                     // File 0: shortcuts.py - empty string
      [""],                     // File 1: common.py - empty string
      ["function: ...\nline: 262\nline: 571"]  // File 2: resolvers.py - has data
    ],
    [  // Sample 1
      [""],
      [""],
      ["function: ...\nline: 278\nline: 279\nline: 438..."]
    ],
    [  // Sample 2
      [""],
      [""],
      ["function: ...\nline: 278\nline: 279\nline: 438..."]
    ],
    [  // Sample 3
      ["function: get_object_or_404\nline: 57\nline: 78"],    // shortcuts.py has data!
      ["function: CommonMiddleware...\nline: 34\nline: 99"],  // common.py has data!
      ["function: URLResolver...\nline: 438\nline: 500\nline: 534"]
    ]
  ]
}
```

**Key Insight**: The file index in `found_edit_locs[sample_idx][file_idx]` maps directly to `found_files[file_idx]`.

## Actual Data Analysis

For instance `django__django-11620`:

**Sample 3 contains:**
- File 0 (django/shortcuts.py): 2 lines [57, 78]
- File 1 (django/middleware/common.py): 2 lines [34, 99]
- File 2 (django/urls/resolvers.py): Multiple lines including [438, 500, 534, 571, ...]

**Total across all samples:**
- django/shortcuts.py: [57, 78]
- django/middleware/common.py: [34, 99]
- django/urls/resolvers.py: [34, 57, 78, 99, 245, 262, 278, 279, 438, 497, 500, 504, 507, 511, 514, 518, 529, 532, 534, 571]

Note: Some lines appear in multiple files because different samples generated them for different files.

## Gold Answer

```json
{
  "instance_id": "django__django-11620",
  "gold_files": ["django/views/debug.py"],
  "gold_lines": {
    "django/views/debug.py": [8, 11, 486]
  }
}
```

**Observation**:
- Gold file is "django/views/debug.py"
- Predicted files are "django/shortcuts.py", "django/middleware/common.py", "django/urls/resolvers.py"
- No match at file level → This is a localization accuracy issue (separate from the parsing bug)

## Solution

### Fix #1: Correct line_recall() function

```python
def line_recall(predicted_edit_locs, gold_lines_dict, predicted_files):
    """
    Calculate line-level recall.

    Args:
        predicted_edit_locs: found_edit_locs from localization
        gold_lines_dict: dict mapping file -> list of gold line numbers
        predicted_files: found_files from localization (file path for each index)

    Returns: proportion of gold lines found in predictions
    """
    if not gold_lines_dict:
        return None, None, None  # No gold answer

    # Extract predicted lines from all samples: {file: set(line_numbers)}
    predicted_lines_all = {}

    for sample in predicted_edit_locs:  # Each sample from num_samples
        if not sample:
            continue
        for file_idx, file_result in enumerate(sample):  # Each file's result
            if not file_result:
                continue

            # file_result is a list with single string element
            result_str = file_result[0] if isinstance(file_result, list) else file_result

            if len(result_str) == 0:  # Skip empty strings
                continue

            # Map file index to actual file path from predicted_files
            if file_idx >= len(predicted_files):
                continue  # Safety check

            file_path = predicted_files[file_idx]

            # Extract line numbers from result string
            for line in result_str.split('\n'):
                line = line.strip()
                if line.startswith('line: '):
                    try:
                        line_num = int(line.split(': ')[1].strip())
                        if file_path not in predicted_lines_all:
                            predicted_lines_all[file_path] = set()
                        predicted_lines_all[file_path].add(line_num)
                    except (ValueError, IndexError):
                        continue

    # Calculate recall for each file
    total_gold_lines = sum(len(lines) for lines in gold_lines_dict.values())
    total_hits = 0

    for gold_file, gold_line_nums in gold_lines_dict.items():
        if gold_file in predicted_lines_all:
            pred_lines = predicted_lines_all[gold_file]
            hits = sum(1 for gold_line in gold_line_nums if gold_line in pred_lines)
            total_hits += hits

    recall = total_hits / total_gold_lines if total_gold_lines > 0 else 0
    return recall, total_hits, total_gold_lines
```

### Fix #2: Correct display logic

```python
# Show predicted lines
predicted_lines_display = {}
for sample_idx, loc_group in enumerate(predicted_edit_locs):
    if not loc_group:
        continue
    for file_idx, loc_item in enumerate(loc_group):
        if not loc_item:
            continue
        loc_str = loc_item[0] if isinstance(loc_item, list) else loc_item

        if len(loc_str) == 0:
            continue

        # Map to actual file
        if file_idx >= len(predicted_files):
            continue
        file_path = predicted_files[file_idx]

        for line in loc_str.split('\n'):
            if line.strip().startswith('line: '):
                try:
                    line_num = int(line.strip().split(': ')[1])
                    if file_path not in predicted_lines_display:
                        predicted_lines_display[file_path] = []
                    predicted_lines_display[file_path].append(line_num)
                except:
                    pass
```

## Expected Outcome After Fix

For `django__django-11620`:

**Current (WRONG):**
```
Predicted: {'django/views/debug.py': [all lines dumped here]}
Recall: 0.0% (0/3 lines)
```

**After Fix (CORRECT):**
```
Predicted: {
  'django/shortcuts.py': [57, 78],
  'django/middleware/common.py': [34, 99],
  'django/urls/resolvers.py': [245, 262, 278, 279, 438, ...]
}
Recall: 0.0% (0/3 lines)  # Still 0% because gold is debug.py, predicted are other files
```

The recall is still 0%, but now we can SEE what was actually predicted, which is crucial for debugging localization accuracy.

## Impact

This bug affects ALL evaluation metrics:
- **Line recall**: Completely broken, always 0% or wrong
- **File matching**: Not visible what files were actually predicted
- **Debugging**: Cannot diagnose localization quality issues

## Next Steps

1. Apply the fixes to `evaluate_localization.py`
2. Re-run evaluation on all result files
3. Analyze actual localization performance with corrected metrics
4. Investigate why some instances predict wrong files (e.g., debug.py vs resolvers.py)
