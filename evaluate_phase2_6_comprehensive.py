#!/usr/bin/env python3
"""
Phase 2-6 Comprehensive Evaluation: Baseline vs Repograph
File + Line Level Metrics + Graph Context Analysis
"""

import json
import sys

def load_jsonl(filepath):
    """Load JSONL file."""
    results = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                results[data['instance_id']] = data
        return results
    except FileNotFoundError:
        return {}

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

def line_recall(result_data, gold_lines_dict, predicted_files):
    """Calculate line-level recall."""
    if not gold_lines_dict:
        return None, 0, 0

    predicted_lines_by_file = {}

    if 'found_edit_locs' in result_data:
        found_edit_locs = result_data['found_edit_locs']

        for sample_idx, sample in enumerate(found_edit_locs):
            if not sample:
                continue

            for file_idx, file_result in enumerate(sample):
                if not file_result or file_idx >= len(predicted_files):
                    continue

                file_path = predicted_files[file_idx]

                result_str = file_result[0] if isinstance(file_result, list) else file_result
                if not result_str:
                    continue

                if file_path not in predicted_lines_by_file:
                    predicted_lines_by_file[file_path] = set()

                for line in result_str.split('\n'):
                    line = line.strip()
                    if line.startswith('line: '):
                        try:
                            line_num = int(line.split(': ')[1].strip())
                            predicted_lines_by_file[file_path].add(line_num)
                        except:
                            pass

    total_gold_lines = 0
    total_found_lines = 0

    for file_path, gold_lines in gold_lines_dict.items():
        total_gold_lines += len(gold_lines)

        if file_path in predicted_lines_by_file:
            predicted_lines = predicted_lines_by_file[file_path]
            found = len(predicted_lines & set(gold_lines))
            total_found_lines += found

    if total_gold_lines == 0:
        return None, 0, 0

    recall = total_found_lines / total_gold_lines
    return recall, total_gold_lines, total_found_lines

# Load all data
print("="*80)
print("Phase 2-6 COMPREHENSIVE EVALUATION")
print("="*80)

baseline_results = load_jsonl('results/localization_base_10inst_phase2_6_20251109/loc_outputs.jsonl')
repograph_results = load_jsonl('results/localization_repo_10inst_phase2_6_20251109/loc_outputs.jsonl')
gold_answers = load_gold('gold_answers/gold_answers_mixed_phase1_v2.json')

print(f"\nLoaded:")
print(f"  Baseline: {len(baseline_results)} instances")
print(f"  Repograph: {len(repograph_results)} instances")
print(f"  Gold answers: {len(gold_answers)} instances")

# Common instances
common_instances = set(baseline_results.keys()) & set(repograph_results.keys()) & set(gold_answers.keys())
print(f"  Common instances to evaluate: {len(common_instances)}")

# Evaluate
file_recalls_base = []
file_recalls_repo = []
line_recalls_base = []
line_recalls_repo = []

comparison_results = []

for instance_id in sorted(common_instances):
    gold_data = gold_answers[instance_id]
    gold_files = gold_data['gold_files']
    gold_lines = gold_data.get('gold_lines', {})

    # Baseline
    base_result = baseline_results[instance_id]
    base_files = base_result.get('found_files', [])
    base_file_recall = file_recall_at_k(base_files, gold_files, k=3)
    base_line_rec, base_gold_count, base_found_count = line_recall(base_result, gold_lines, base_files)

    # Repograph
    repo_result = repograph_results[instance_id]
    repo_files = repo_result.get('found_files', [])
    repo_file_recall = file_recall_at_k(repo_files, gold_files, k=3)
    repo_line_rec, repo_gold_count, repo_found_count = line_recall(repo_result, gold_lines, repo_files)

    if base_file_recall is not None:
        file_recalls_base.append(base_file_recall)
    if repo_file_recall is not None:
        file_recalls_repo.append(repo_file_recall)

    if base_line_rec is not None:
        line_recalls_base.append(base_line_rec)
    if repo_line_rec is not None:
        line_recalls_repo.append(repo_line_rec)

    # Status
    file_status = ""
    line_status = ""
    if base_file_recall is not None and repo_file_recall is not None:
        if repo_file_recall > base_file_recall:
            file_status = "IMPROVED (+)"
        elif repo_file_recall < base_file_recall:
            file_status = "DEGRADED (-)"
        else:
            file_status = "SAME (=)"

    if base_line_rec is not None and repo_line_rec is not None:
        if repo_line_rec > base_line_rec:
            line_status = "IMPROVED (+)"
        elif repo_line_rec < base_line_rec:
            line_status = "DEGRADED (-)"
        else:
            line_status = "SAME (=)"

    comparison_results.append({
        'instance_id': instance_id,
        'file_recall_base': base_file_recall,
        'file_recall_repo': repo_file_recall,
        'file_status': file_status,
        'line_recall_base': base_line_rec,
        'line_recall_repo': repo_line_rec,
        'line_status': line_status,
        'gold_files': gold_files,
    })

# Print file-level results
print("\n" + "="*80)
print("FILE LEVEL RESULTS (Recall@3)")
print("="*80)

if file_recalls_base:
    baseline_avg = sum(file_recalls_base) / len(file_recalls_base) * 100
    print(f"Baseline Average:  {baseline_avg:.1f}%")
else:
    baseline_avg = 0
    print("Baseline: No results")

if file_recalls_repo:
    repograph_avg = sum(file_recalls_repo) / len(file_recalls_repo) * 100
    print(f"Repograph Average: {repograph_avg:.1f}%")
else:
    repograph_avg = 0
    print("Repograph: No results")

if file_recalls_base and file_recalls_repo:
    file_delta = repograph_avg - baseline_avg
    print(f"Delta: {file_delta:+.1f}pp")

# Print line-level results
print("\n" + "="*80)
print("LINE LEVEL RESULTS")
print("="*80)

if line_recalls_base:
    baseline_line_avg = sum(line_recalls_base) / len(line_recalls_base) * 100
    print(f"Baseline Average:  {baseline_line_avg:.1f}%")
else:
    baseline_line_avg = 0
    print("Baseline: No results")

if line_recalls_repo:
    repograph_line_avg = sum(line_recalls_repo) / len(line_recalls_repo) * 100
    print(f"Repograph Average: {repograph_line_avg:.1f}%")
else:
    repograph_line_avg = 0
    print("Repograph: No results")

if line_recalls_base and line_recalls_repo:
    line_delta = repograph_line_avg - baseline_line_avg
    print(f"Delta: {line_delta:+.1f}pp")

# Instance-by-instance
print("\n" + "="*80)
print("INSTANCE-BY-INSTANCE COMPARISON")
print("="*80)
print(f"{'Instance':<35} {'File':<20} {'Line':<20}")
print(f"{'':35} {'Base / Repo':<20} {'Base / Repo':<20}")
print("-" * 75)

for result in comparison_results:
    file_base = f"{result['file_recall_base']:.0%}" if result['file_recall_base'] is not None else "N/A"
    file_repo = f"{result['file_recall_repo']:.0%}" if result['file_recall_repo'] is not None else "N/A"
    line_base = f"{result['line_recall_base']:.0%}" if result['line_recall_base'] is not None else "N/A"
    line_repo = f"{result['line_recall_repo']:.0%}" if result['line_recall_repo'] is not None else "N/A"

    print(f"{result['instance_id']:<35} {file_base:>6} / {file_repo:<6} {line_base:>6} / {line_repo:<6}")

# Statistics
improved_file = sum(1 for r in comparison_results if r['file_status'] == 'IMPROVED (+)')
degraded_file = sum(1 for r in comparison_results if r['file_status'] == 'DEGRADED (-)')
same_file = sum(1 for r in comparison_results if r['file_status'] == 'SAME (=)')

improved_line = sum(1 for r in comparison_results if r['line_status'] == 'IMPROVED (+)')
degraded_line = sum(1 for r in comparison_results if r['line_status'] == 'DEGRADED (-)')
same_line = sum(1 for r in comparison_results if r['line_status'] == 'SAME (=)')

print("\n" + "="*80)
print("STATISTICS")
print("="*80)

print(f"\nFile Level (Recall@3):")
print(f"  Improved: {improved_file}/{len(comparison_results)} ({improved_file/len(comparison_results)*100:.1f}%)")
print(f"  Degraded: {degraded_file}/{len(comparison_results)} ({degraded_file/len(comparison_results)*100:.1f}%)")
print(f"  Same:     {same_file}/{len(comparison_results)} ({same_file/len(comparison_results)*100:.1f}%)")

print(f"\nLine Level:")
print(f"  Improved: {improved_line}/{len(comparison_results)} ({improved_line/len(comparison_results)*100:.1f}%)")
print(f"  Degraded: {degraded_line}/{len(comparison_results)} ({degraded_line/len(comparison_results)*100:.1f}%)")
print(f"  Same:     {same_line}/{len(comparison_results)} ({same_line/len(comparison_results)*100:.1f}%)")

# Save comprehensive results
with open('evaluation/phase2_6_comprehensive_results_20251109.json', 'w') as f:
    json.dump({
        'file_level': {
            'baseline_avg': baseline_avg,
            'repograph_avg': repograph_avg,
            'delta_pp': file_delta if file_recalls_base and file_recalls_repo else None,
            'improved': improved_file,
            'degraded': degraded_file,
            'same': same_file,
        },
        'line_level': {
            'baseline_avg': baseline_line_avg,
            'repograph_avg': repograph_line_avg,
            'delta_pp': line_delta if line_recalls_base and line_recalls_repo else None,
            'improved': improved_line,
            'degraded': degraded_line,
            'same': same_line,
        },
        'total_instances': len(comparison_results),
        'details': comparison_results
    }, f, indent=2)

print(f"\nComprehensive results saved to: evaluation/phase2_6_comprehensive_results_20251109.json")
