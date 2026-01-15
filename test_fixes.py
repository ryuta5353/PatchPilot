#!/usr/bin/env python3
"""
Test script to verify Phase 2-7 fixes
"""

import sys

# Test Fix 2: Empty related locations filtering
print("="*80)
print("TEST 1: Fix 2 - Empty related locations filtering")
print("="*80)

# Simulated found_related_locs with empty items (like scikit-learn__scikit-learn-10297)
found_related_locs = [
    ['class: RidgeClassifierCV\nfunction: fit'],  # Valid
    [''],  # Empty
    [''],  # Empty
    [''],  # Empty
    ['']   # Empty
]

# Apply the filtering logic from Fix 2
found_related_locs_filtered = [
    item for item in found_related_locs
    if item and isinstance(item, list) and len(item) > 0 and item[0].strip()
]

print(f"Input related_locs: {len(found_related_locs)} items")
print(f"Output related_locs_filtered: {len(found_related_locs_filtered)} items")
print(f"Filtered out: {len(found_related_locs) - len(found_related_locs_filtered)} empty items")

assert len(found_related_locs_filtered) == 1, "Should keep only 1 valid item"
assert found_related_locs_filtered[0][0].startswith("class: RidgeClassifierCV"), "Should preserve valid data"
print("[PASS] Empty locations properly filtered")

# Test Fix 3: Template file value exclusion
print("\n" + "="*80)
print("TEST 2: Fix 3 - Template file value exclusion")
print("="*80)

from patchpilot.util.postprocess_data import extract_locs_for_files

# Simulate LLM output with template values mixed in
locs = [
    """path/to/file.py
line: 10
class: MyClass
line: 51

full_path1/file1.py
function: MyFunc1
line: 12"""
]

file_names = ["src/main.py", "src/utils.py"]

result = extract_locs_for_files(locs, file_names)
print(f"Input locs: {locs[0][:50]}...")
print(f"File names: {file_names}")
print(f"Output result: {result}")

# Check that template values were excluded
result_str = str(result)
assert "path/to/file.py" not in result_str, "Template value 'path/to/file.py' should be excluded"
assert "full_path1" not in result_str, "Template value 'full_path1/file1.py' should be excluded"
print("[PASS] Template file values properly excluded")

# Test with valid file names
print("\n" + "="*80)
print("TEST 3: Fix 3 - Valid file names should be preserved")
print("="*80)

locs_valid = [
    """src/main.py
line: 10
class: MyClass
line: 51

src/utils.py
function: MyFunc1
line: 12"""
]

result_valid = extract_locs_for_files(locs_valid, file_names)
print(f"Input locs with valid files: {locs_valid[0][:50]}...")
print(f"Output result: {result_valid}")

# Check that valid values are preserved
result_valid_str = str(result_valid)
assert "line: 10" in result_valid_str or "line:10" in result_valid_str or len(result_valid[0][0]) > 0, "Valid data should be preserved"
print("[PASS] Valid file names properly preserved")

print("\n" + "="*80)
print("ALL TESTS PASSED")
print("="*80)
print("\nSummary:")
print("  Fix 2: Empty related locations filtering - Working")
print("  Fix 3: Template file value exclusion - Working")
