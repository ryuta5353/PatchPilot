#!/usr/bin/env python3
"""Compare baseline vs repograph evaluation results."""

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
    """Calculate file-level Recall@k."""
    if not gold_files:
        return None
    top_k = predicted_files[:k]
    for gold_file in gold_files:
        if gold_file in top_k:
            return 1.0
    return 0.0

def line_recall(predicted_edit_locs, gold_lines_dict, predicted_files):
    """Calculate line-level recall."""
    if not gold_lines_dict:
        return None, None, None

    predicted_lines_all = {}

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
                        for gold_file in gold_lines_dict.keys():
                            if gold_file not in predicted_lines_all:
                                predicted_lines_all[gold_file] = set()
                            predicted_lines_all[gold_file].add(line_num)
                            break
                    except (ValueError, IndexError):
                        continue

    total_gold_lines = sum(len(lines) for lines in gold_lines_dict.values())
    total_predicted_lines = sum(len(lines) for lines in predicted_lines_all.values())
    total_hits = sum(
        len(predicted_lines_all.get(file, set()) & set(gold_lines_dict.get(file, [])))
        for file in gold_lines_dict.keys()
    )

    recall = total_hits / total_gold_lines if total_gold_lines > 0 else None

    return recall, total_hits, total_gold_lines

def evaluate_file(results_file, gold_file):
    """Evaluate a single file."""
    results = load_jsonl(results_file)
    gold = load_gold(gold_file)

    line_recalls = []
    file_recalls = []
    func_recalls = []

    for result in results:
        iid = result['instance_id']
        if iid not in gold:
            continue

        gold_files = gold[iid].get('files', [])
        pred_files = result.get('found_files', [])

        # File recall@3
        file_r = file_recall_at_k(pred_files, gold_files, k=3)
        if file_r is not None:
            file_recalls.append(file_r)

        # Line recall
        gold_lines_dict = gold[iid].get('lines', {})
        pred_edit_locs = result.get('found_edit_locs', [])
        line_r, _, _ = line_recall(pred_edit_locs, gold_lines_dict, pred_files)
        if line_r is not None:
            line_recalls.append(line_r)

    return {
        'line_recall': sum(line_recalls) / len(line_recalls) if line_recalls else None,
        'file_recall': sum(file_recalls) / len(file_recalls) if file_recalls else None,
        'instances': len(file_recalls)
    }

def main():
    baseline_file = "results/localization_baseline_new2/loc_outputs.jsonl"
    repograph_file = "results/localization_repograph_corrected/loc_outputs.jsonl"
    gold_file = "gold_answers_10new.json"

    print("=" * 80)
    print("LOCALIZATION EVALUATION COMPARISON")
    print("=" * 80)

    print("\n📊 Evaluating Baseline...")
    baseline_results = evaluate_file(baseline_file, gold_file)

    print("📊 Evaluating Repograph...")
    repograph_results = evaluate_file(repograph_file, gold_file)

    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    print(f"\n{'Metric':<20} {'Baseline':<20} {'Repograph':<20} {'Difference':<20}")
    print("-" * 80)

    for metric in ['line_recall', 'file_recall']:
        baseline_val = baseline_results.get(metric)
        repograph_val = repograph_results.get(metric)

        if baseline_val is None or repograph_val is None:
            continue

        baseline_str = f"{baseline_val*100:.1f}%" if baseline_val is not None else "N/A"
        repograph_str = f"{repograph_val*100:.1f}%" if repograph_val is not None else "N/A"
        diff_val = (repograph_val - baseline_val) * 100
        diff_str = f"{diff_val:+.1f}%"

        print(f"{metric:<20} {baseline_str:<20} {repograph_str:<20} {diff_str:<20}")

    # Instances
    print(f"\n{'Instances':<20} {baseline_results['instances']:<20} {repograph_results['instances']:<20}")

if __name__ == "__main__":
    main()
