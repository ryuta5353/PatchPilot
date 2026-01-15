#!/usr/bin/env python3
"""Evaluate localization results against gold answers."""

import json
import sys

def load_jsonl(filepath):
    """Load JSONL file."""
    results = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            results.append(json.loads(line))
    return results

def load_gold(filepath):
    """Load gold answers."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def file_recall_at_k(predicted_files, gold_files, k=3):
    """
    Calculate file-level Recall@k.

    Returns 1.0 if any gold file is in top-k predictions, else 0.0
    """
    if not gold_files:
        return None  # No gold answer

    top_k = predicted_files[:k]
    for gold_file in gold_files:
        if gold_file in top_k:
            return 1.0
    return 0.0

def function_recall(predicted_locs, gold_functions):
    """
    Calculate function-level recall.

    Returns proportion of gold functions found in predictions.
    """
    if not gold_functions:
        return None  # No gold answer

    # Extract functions from predicted locations
    predicted_funcs = set()
    for loc_list in predicted_locs:
        if not loc_list:
            continue
        loc_str = loc_list[0] if isinstance(loc_list, list) else loc_list
        for line in loc_str.split('\n'):
            if line.startswith('function: ') or line.startswith('class: '):
                func_name = line.split(': ', 1)[1].strip()
                predicted_funcs.add(func_name)

    # Check how many gold functions are found
    hits = sum(1 for gold_func in gold_functions if gold_func in predicted_funcs)
    return hits / len(gold_functions)

def evaluate_results(results_file, gold_file, k=3):
    """Evaluate localization results."""
    results = load_jsonl(results_file)
    gold = load_gold(gold_file)

    # Index by instance_id
    results_dict = {r['instance_id']: r for r in results}

    file_recalls = []
    func_recalls = []

    print("=" * 80)
    print(f"Evaluating: {results_file}")
    print("=" * 80)

    for instance_id, gold_data in sorted(gold.items()):
        if instance_id not in results_dict:
            print(f"\nWARNING: {instance_id} not in results")
            continue

        result = results_dict[instance_id]

        print(f"\n[{instance_id}]")
        print("-" * 80)

        # File-level evaluation
        gold_files = gold_data.get('gold_files', [])
        predicted_files = result.get('found_files', [])

        file_recall = file_recall_at_k(predicted_files, gold_files, k=k)

        print(f"\nFile-level (Top-{k}):")
        print(f"  Gold:      {gold_files}")
        print(f"  Predicted: {predicted_files[:k]}")
        print(f"  Recall@{k}:  {file_recall:.0%}" if file_recall is not None else "  N/A")

        if file_recall is not None:
            file_recalls.append(file_recall)

        # Function-level evaluation
        gold_functions = gold_data.get('gold_functions', [])
        predicted_locs = result.get('found_related_locs', [])

        func_recall = function_recall(predicted_locs, gold_functions)

        print(f"\nFunction-level:")
        print(f"  Gold:      {gold_functions}")

        # Show predicted functions
        predicted_funcs = set()
        for loc_list in predicted_locs:
            if not loc_list:
                continue
            loc_str = loc_list[0] if isinstance(loc_list, list) else loc_list
            for line in loc_str.split('\n')[:10]:  # First 10 lines
                if line.startswith('function: ') or line.startswith('class: '):
                    func_name = line.split(': ', 1)[1].strip()
                    predicted_funcs.add(func_name)

        print(f"  Predicted: {list(predicted_funcs)[:5]}")  # Show first 5
        print(f"  Recall:    {func_recall:.0%}" if func_recall is not None else "  N/A")

        if func_recall is not None:
            func_recalls.append(func_recall)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if file_recalls:
        avg_file_recall = sum(file_recalls) / len(file_recalls)
        print(f"\nFile Recall@{k}:     {avg_file_recall:.1%} ({sum(file_recalls)}/{len(file_recalls)} instances)")
    else:
        print(f"\nFile Recall@{k}:     N/A")

    if func_recalls:
        avg_func_recall = sum(func_recalls) / len(func_recalls)
        print(f"Function Recall:   {avg_func_recall:.1%} ({sum(func_recalls):.1f}/{len(func_recalls)} instances)")
    else:
        print(f"Function Recall:   N/A")

    return {
        'file_recall': sum(file_recalls) / len(file_recalls) if file_recalls else None,
        'func_recall': sum(func_recalls) / len(func_recalls) if func_recalls else None,
        'instances': len(file_recalls)
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evaluate_localization.py <results_file>")
        sys.exit(1)

    results_file = sys.argv[1]
    gold_file = "gold_answers.json"

    evaluate_results(results_file, gold_file, k=3)
