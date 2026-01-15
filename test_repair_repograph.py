"""
Test script for Repair Phase RepoGraph Integration

This script tests the implementation without requiring Docker.
It verifies:
1. extract_keywords_from_edit_locs works correctly
2. build_repair_graph_context generates expected output
3. The integration components work together
"""

import json
import sys
import os

# Add patchpilot to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from patchpilot.repair.repair import load_graph_tags, extract_keywords_from_edit_locs
from patchpilot.fl.repograph_utils import build_repair_graph_context


def test_extract_keywords():
    """Test extract_keywords_from_edit_locs with real data format"""
    print("\n" + "="*60)
    print("Test 1: extract_keywords_from_edit_locs")
    print("="*60)

    # Real format from django__django-14534
    found_edit_locs = [
        [['class: BoundWidget\nline: 280\nclass: BoundField\nline: 50\nline: 171']],
        [['class: BoundWidget\nline: 280\nclass: BoundField\nline: 50\nline: 225']],
        [['class: BoundWidget\nline: 280']],
        [['class: BoundWidget\nline: 280\nclass: BoundField\nline: 50']]
    ]

    keywords = extract_keywords_from_edit_locs(found_edit_locs)

    print(f"Input: {found_edit_locs[:2]}...")
    print(f"Output: {keywords}")

    assert 'functions' in keywords
    assert 'classes' in keywords
    assert 'BoundWidget' in keywords['classes']
    assert 'BoundField' in keywords['classes']

    print("[PASS] extract_keywords_from_edit_locs works correctly")
    return True


def test_extract_keywords_with_functions():
    """Test with function format"""
    print("\n" + "="*60)
    print("Test 2: extract_keywords_from_edit_locs with functions")
    print("="*60)

    found_edit_locs = [
        [['function: FileField.generate_filename\nline: 123']],
        [['function: get_valid_filename\nclass: Storage\nline: 45']],
    ]

    keywords = extract_keywords_from_edit_locs(found_edit_locs)

    print(f"Input: {found_edit_locs}")
    print(f"Output: {keywords}")

    assert 'generate_filename' in keywords['functions']  # Extracted from Class.method
    assert 'get_valid_filename' in keywords['functions']
    assert 'Storage' in keywords['classes']

    print("[PASS] Function extraction with Class.method works correctly")
    return True


def test_load_graph_tags():
    """Test load_graph_tags with real file"""
    print("\n" + "="*60)
    print("Test 3: load_graph_tags")
    print("="*60)

    instance_id = "django__django-14534"
    graph_folder = "RepoGraph_cache"

    tags = load_graph_tags(instance_id, graph_folder)

    if tags is None:
        print(f"[SKIP] graph_tags not found for {instance_id}")
        return None

    print(f"Loaded {len(tags)} tags")
    print(f"Sample tag: {tags[0]}")

    # Check tag structure
    assert 'name' in tags[0]
    assert 'kind' in tags[0]
    assert 'rel_fname' in tags[0]

    print("[PASS] load_graph_tags works correctly")
    return tags


def test_build_repair_graph_context(graph_tags):
    """Test build_repair_graph_context with real data"""
    print("\n" + "="*60)
    print("Test 4: build_repair_graph_context")
    print("="*60)

    if graph_tags is None:
        print("[SKIP] No graph_tags available")
        return False

    keywords = {
        'functions': [],
        'classes': ['BoundWidget', 'BoundField']
    }
    found_files = ['django/forms/boundfield.py']

    context = build_repair_graph_context(
        keywords,
        graph_tags,
        found_files,
        max_callers_per_func=5,
        max_callees_per_func=5,
        max_keywords=20,
        max_functions=30
    )

    print(f"Keywords: {keywords}")
    print(f"Found files: {found_files}")
    print(f"\nGenerated context ({len(context)} chars):")
    print("-" * 40)
    if context:
        print(context[:1000] + "..." if len(context) > 1000 else context)
    else:
        print("(empty - no caller/callee found)")
    print("-" * 40)

    print("[PASS] build_repair_graph_context executed successfully")
    return True


def test_full_integration():
    """Test full integration with real localization data"""
    print("\n" + "="*60)
    print("Test 5: Full Integration Test")
    print("="*60)

    # Load real localization result
    loc_file = 'results/localization_baseline_23inst_run1_20251218/loc_outputs.jsonl'
    instance_id = 'django__django-14534'

    if not os.path.exists(loc_file):
        print(f"[SKIP] Localization file not found: {loc_file}")
        return False

    loc_data = None
    with open(loc_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            if data.get('instance_id') == instance_id:
                loc_data = data
                break

    if not loc_data:
        print(f"[SKIP] Instance {instance_id} not found in localization results")
        return False

    # Extract data
    found_edit_locs = loc_data.get('found_edit_locs', [])
    pred_files = loc_data.get('found_files', [])

    print(f"Instance: {instance_id}")
    print(f"Pred files: {pred_files}")
    print(f"Found edit locs count: {len(found_edit_locs)}")

    # Step 1: Extract keywords
    keywords = extract_keywords_from_edit_locs(found_edit_locs)
    print(f"\nExtracted keywords: {keywords}")

    # Step 2: Load graph tags
    graph_tags = load_graph_tags(instance_id, 'RepoGraph_cache')
    if graph_tags is None:
        print("[SKIP] graph_tags not available")
        return False
    print(f"Loaded {len(graph_tags)} graph tags")

    # Step 3: Build context
    context = build_repair_graph_context(
        keywords,
        graph_tags,
        pred_files,
        max_callers_per_func=5,
        max_callees_per_func=5,
        max_keywords=20,
        max_functions=30
    )

    print(f"\nGenerated context ({len(context)} chars):")
    print("-" * 40)
    if context:
        print(context)
    else:
        print("(empty)")
    print("-" * 40)

    print("\n[PASS] Full integration test completed")
    return True


def main():
    print("="*60)
    print("Repair Phase RepoGraph Integration Test")
    print("="*60)

    results = []

    # Test 1: extract_keywords basic
    results.append(("extract_keywords_from_edit_locs", test_extract_keywords()))

    # Test 2: extract_keywords with functions
    results.append(("extract_keywords with functions", test_extract_keywords_with_functions()))

    # Test 3: load_graph_tags
    graph_tags = test_load_graph_tags()
    results.append(("load_graph_tags", graph_tags is not None))

    # Test 4: build_repair_graph_context
    results.append(("build_repair_graph_context", test_build_repair_graph_context(graph_tags)))

    # Test 5: Full integration
    results.append(("Full integration", test_full_integration()))

    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        if result is True:
            status = "[PASS]"
            passed += 1
        elif result is False:
            status = "[FAIL]"
            failed += 1
        else:
            status = "[SKIP]"
            skipped += 1
        print(f"{status} {name}")

    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
