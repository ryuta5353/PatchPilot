#!/usr/bin/env python3
"""
Localization Evaluation Script

Metrics:
    - Precision: 予測した中で正解だった割合
    - Recall: 正解の中で予測できた割合
    - Exact Match: 完全一致したインスタンスの割合
    - Recall=1.0 Rate: 全ての正解を見つけたインスタンスの割合

Usage:
    python scripts/evaluate_localization.py \
        --task_list instances/django_common_20.txt \
        --loc_file results/localization_xxx/merged/loc_all_merged_outputs.jsonl \
        --benchmark verified \
        --output results/localization_xxx/evaluation_report.json
"""

import argparse
import json
import re
from pathlib import Path
from collections import defaultdict
from datasets import load_dataset


def load_task_list(task_list_file: str) -> list:
    """Load instance IDs from task list file."""
    with open(task_list_file, 'r') as f:
        return [line.strip() for line in f if line.strip()]


def load_localization_results(loc_file: str) -> dict:
    """Load localization results from JSONL file."""
    results = {}
    with open(loc_file, 'r') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                instance_id = data.get('instance_id')
                if instance_id:
                    results[instance_id] = data
    return results


def parse_patch_for_files(patch: str) -> list:
    """Extract modified files from a git diff patch."""
    files = []
    for match in re.finditer(r'diff --git a/(.+?) b/', patch):
        files.append(match.group(1))

    if not files:
        for match in re.finditer(r'--- a/(.+?)\n', patch):
            files.append(match.group(1))

    return list(set(files))


def parse_patch_for_functions_and_lines(patch: str) -> dict:
    """
    Extract modified functions/classes and line numbers from a git diff patch.
    Returns dict: {file_path: {'functions': set(), 'classes': set(), 'lines': set()}}
    """
    result = defaultdict(lambda: {'functions': set(), 'classes': set(), 'lines': set()})

    current_file = None
    current_line_old = 0
    current_line_new = 0

    lines = patch.split('\n')

    for i, line in enumerate(lines):
        file_match = re.match(r'diff --git a/(.+?) b/', line)
        if file_match:
            current_file = file_match.group(1)
            continue

        hunk_match = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)', line)
        if hunk_match:
            current_line_old = int(hunk_match.group(1))
            current_line_new = int(hunk_match.group(2))

            # Extract function/class name from hunk context
            context = hunk_match.group(3).strip()
            if context and current_file:
                # Try to extract function or class name
                func_match = re.search(r'def\s+(\w+)', context)
                class_match = re.search(r'class\s+(\w+)', context)
                if func_match:
                    result[current_file]['functions'].add(func_match.group(1))
                if class_match:
                    result[current_file]['classes'].add(class_match.group(1))
            continue

        # Also check for def/class in the actual changed lines
        if current_file:
            if line.startswith('+') and not line.startswith('+++'):
                # Check for function/class definitions in added lines
                func_match = re.search(r'def\s+(\w+)', line)
                class_match = re.search(r'class\s+(\w+)', line)
                if func_match:
                    result[current_file]['functions'].add(func_match.group(1))
                if class_match:
                    result[current_file]['classes'].add(class_match.group(1))

                result[current_file]['lines'].add(current_line_new)
                current_line_new += 1
            elif line.startswith('-') and not line.startswith('---'):
                # Check for function/class definitions in removed lines
                func_match = re.search(r'def\s+(\w+)', line)
                class_match = re.search(r'class\s+(\w+)', line)
                if func_match:
                    result[current_file]['functions'].add(func_match.group(1))
                if class_match:
                    result[current_file]['classes'].add(class_match.group(1))

                result[current_file]['lines'].add(current_line_old)
                current_line_old += 1
            elif not line.startswith('\\'):
                current_line_old += 1
                current_line_new += 1

    return dict(result)


def normalize_file_path(path: str) -> str:
    """Normalize file path for comparison."""
    return path.strip().lstrip('./')


def extract_functions_from_locs(found_related_locs: list) -> tuple:
    """
    Extract function/class names from found_related_locs.

    Handles formats like:
    - "function: BoundField.subwidgets" -> extracts "subwidgets"
    - "function: my_func" -> extracts "my_func"
    - "class: MyClass" -> extracts "MyClass"
    """
    functions = set()
    classes = set()

    if not found_related_locs:
        return functions, classes

    def parse_loc_string(loc_str: str):
        """Parse a location string and extract function/class names."""
        if not isinstance(loc_str, str):
            return

        for line in loc_str.split('\n'):
            line = line.strip()

            # Match "function: ClassName.method_name" or "function: func_name"
            func_match = re.match(r'function:\s*(?:(\w+)\.)?(\w+)', line)
            if func_match:
                # Add both the method name and class name if present
                if func_match.group(2):
                    functions.add(func_match.group(2))  # method name
                if func_match.group(1):
                    classes.add(func_match.group(1))  # class name from prefix

            # Match "class: ClassName"
            class_match = re.match(r'class:\s*(\w+)', line)
            if class_match:
                classes.add(class_match.group(1))

    for loc_list in found_related_locs:
        if isinstance(loc_list, list):
            for loc in loc_list:
                parse_loc_string(loc)
        elif isinstance(loc_list, str):
            parse_loc_string(loc_list)

    return functions, classes


def extract_lines_from_edit_locs(found_edit_locs: list) -> set:
    """Extract line numbers from found_edit_locs."""
    lines = set()

    if not found_edit_locs:
        return lines

    for loc in found_edit_locs:
        if isinstance(loc, str):
            for match in re.finditer(r'line:\s*(\d+)', loc):
                lines.add(int(match.group(1)))
        elif isinstance(loc, list):
            for item in loc:
                if isinstance(item, str):
                    for match in re.finditer(r'line:\s*(\d+)', item):
                        lines.add(int(match.group(1)))

    return lines


def extract_functions_from_edit_locs(found_edit_locs: list) -> tuple:
    """Extract function/class names from found_edit_locs (for cross-validation)."""
    functions = set()
    classes = set()

    if not found_edit_locs:
        return functions, classes

    def parse_loc_string(loc_str: str):
        if not isinstance(loc_str, str):
            return

        for line in loc_str.split('\n'):
            line = line.strip()

            func_match = re.match(r'function:\s*(?:(\w+)\.)?(\w+)', line)
            if func_match:
                if func_match.group(2):
                    functions.add(func_match.group(2))
                if func_match.group(1):
                    classes.add(func_match.group(1))

            class_match = re.match(r'class:\s*(\w+)', line)
            if class_match:
                classes.add(class_match.group(1))

    for loc in found_edit_locs:
        if isinstance(loc, str):
            parse_loc_string(loc)
        elif isinstance(loc, list):
            for item in loc:
                parse_loc_string(item)

    return functions, classes


def calc_precision_recall_f1(matched: int, pred_count: int, gold_count: int) -> dict:
    """Calculate precision, recall, and F1 score."""
    precision = matched / pred_count if pred_count > 0 else 0.0
    recall = matched / gold_count if gold_count > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1
    }


def match_files(pred_files: list, gold_files: list) -> set:
    """Match predicted files with gold files."""
    pred_normalized = set(normalize_file_path(f) for f in pred_files)
    gold_normalized = set(normalize_file_path(f) for f in gold_files)

    matched = set()
    for gf in gold_normalized:
        for pf in pred_normalized:
            if gf == pf or gf.endswith('/' + pf) or pf.endswith('/' + gf):
                matched.add(gf)
                break
    return matched


def match_lines_with_tolerance(pred_lines: set, gold_lines: set, tolerance: int = 0) -> set:
    """Match predicted lines with gold lines, with optional tolerance."""
    matched = set()
    for gl in gold_lines:
        for pl in pred_lines:
            if abs(gl - pl) <= tolerance:
                matched.add(gl)
                break
    return matched


def evaluate_instance(pred: dict, gold_files: list, gold_details: dict, line_tolerance: int = 0) -> dict:
    """Evaluate a single instance with Precision, Recall, Exact Match."""

    # === File-level ===
    pred_files = pred.get('found_files', [])
    matched_files = match_files(pred_files, gold_files)

    file_metrics = calc_precision_recall_f1(
        len(matched_files),
        len(pred_files),
        len(gold_files)
    )
    file_exact_match = set(normalize_file_path(f) for f in pred_files) == set(normalize_file_path(f) for f in gold_files)

    # === Function/Class-level ===
    gold_functions = set()
    gold_classes = set()
    for file_path, details in gold_details.items():
        gold_functions.update(details.get('functions', set()))
        gold_classes.update(details.get('classes', set()))

    # Extract from both found_related_locs and found_edit_locs
    pred_functions_rel, pred_classes_rel = extract_functions_from_locs(pred.get('found_related_locs', []))
    pred_functions_edit, pred_classes_edit = extract_functions_from_edit_locs(pred.get('found_edit_locs', []))

    pred_functions = pred_functions_rel | pred_functions_edit
    pred_classes = pred_classes_rel | pred_classes_edit

    matched_functions = gold_functions & pred_functions
    matched_classes = gold_classes & pred_classes

    # Combine functions and classes for overall function-level metrics
    gold_func_class = gold_functions | gold_classes
    pred_func_class = pred_functions | pred_classes
    matched_func_class = matched_functions | matched_classes

    func_metrics = calc_precision_recall_f1(
        len(matched_func_class),
        len(pred_func_class),
        len(gold_func_class)
    )
    func_exact_match = pred_func_class == gold_func_class

    # === Line-level ===
    gold_lines = set()
    for file_path, details in gold_details.items():
        gold_lines.update(details.get('lines', set()))

    pred_lines = extract_lines_from_edit_locs(pred.get('found_edit_locs', []))

    matched_lines = match_lines_with_tolerance(pred_lines, gold_lines, line_tolerance)

    line_metrics = calc_precision_recall_f1(
        len(matched_lines),
        len(pred_lines),
        len(gold_lines)
    )
    line_exact_match = pred_lines == gold_lines

    return {
        'instance_id': pred.get('instance_id'),
        'file_level': {
            'gold': gold_files,
            'pred': pred_files,
            'matched': list(matched_files),
            'gold_count': len(gold_files),
            'pred_count': len(pred_files),
            'matched_count': len(matched_files),
            **file_metrics,
            'exact_match': file_exact_match,
            'recall_1': file_metrics['recall'] == 1.0
        },
        'function_level': {
            'gold_functions': list(gold_functions),
            'gold_classes': list(gold_classes),
            'pred_functions': list(pred_functions),
            'pred_classes': list(pred_classes),
            'matched_functions': list(matched_functions),
            'matched_classes': list(matched_classes),
            'gold_count': len(gold_func_class),
            'pred_count': len(pred_func_class),
            'matched_count': len(matched_func_class),
            **func_metrics,
            'exact_match': func_exact_match,
            'recall_1': func_metrics['recall'] == 1.0
        },
        'line_level': {
            'gold': sorted(list(gold_lines)),
            'pred': sorted(list(pred_lines)),
            'matched': sorted(list(matched_lines)),
            'gold_count': len(gold_lines),
            'pred_count': len(pred_lines),
            'matched_count': len(matched_lines),
            **line_metrics,
            'exact_match': line_exact_match,
            'recall_1': line_metrics['recall'] == 1.0,
            'tolerance': line_tolerance
        }
    }


def main():
    parser = argparse.ArgumentParser(description='Evaluate localization accuracy with Precision/Recall/Exact Match')
    parser.add_argument('--task_list', type=str, required=True,
                        help='Path to task list file')
    parser.add_argument('--loc_file', type=str, required=True,
                        help='Path to localization results JSONL file')
    parser.add_argument('--benchmark', type=str, default='verified',
                        choices=['lite', 'verified'],
                        help='SWE-bench benchmark to use')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file for detailed report (JSON)')
    parser.add_argument('--verbose', action='store_true',
                        help='Print detailed results for each instance')
    parser.add_argument('--line_tolerance', type=int, default=0,
                        help='Tolerance for line matching (default: 0 = exact)')

    args = parser.parse_args()

    # Load task list
    print(f"Loading task list from {args.task_list}...")
    task_ids = load_task_list(args.task_list)
    print(f"  Found {len(task_ids)} instances")

    # Load localization results
    print(f"Loading localization results from {args.loc_file}...")
    loc_results = load_localization_results(args.loc_file)
    print(f"  Found {len(loc_results)} results")

    # Load SWE-bench dataset
    print(f"Loading SWE-bench {args.benchmark} dataset...")
    if args.benchmark == 'lite':
        dataset = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    else:
        dataset = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")

    gold_data = {item['instance_id']: item for item in dataset}
    print(f"  Loaded {len(gold_data)} instances from dataset")

    # Evaluate each instance
    results = []
    total = 0

    # Accumulators for micro-average
    file_matched_total, file_pred_total, file_gold_total = 0, 0, 0
    func_matched_total, func_pred_total, func_gold_total = 0, 0, 0
    line_matched_total, line_pred_total, line_gold_total = 0, 0, 0

    # Accumulators for macro-average, exact match, and recall=1.0
    file_precision_sum, file_recall_sum, file_exact_match_count, file_recall_1_count = 0, 0, 0, 0
    func_precision_sum, func_recall_sum, func_exact_match_count, func_recall_1_count = 0, 0, 0, 0
    line_precision_sum, line_recall_sum, line_exact_match_count, line_recall_1_count = 0, 0, 0, 0

    print("\n" + "=" * 80)
    print("Evaluating localization accuracy...")
    print("=" * 80)

    for instance_id in task_ids:
        if instance_id not in loc_results:
            print(f"  [SKIP] {instance_id}: No localization result")
            continue

        if instance_id not in gold_data:
            print(f"  [SKIP] {instance_id}: Not in benchmark dataset")
            continue

        total += 1
        pred = loc_results[instance_id]
        gold_patch = gold_data[instance_id]['patch']

        gold_files = parse_patch_for_files(gold_patch)
        gold_details = parse_patch_for_functions_and_lines(gold_patch)

        eval_result = evaluate_instance(pred, gold_files, gold_details, args.line_tolerance)
        results.append(eval_result)

        # Accumulate for micro-average
        file_matched_total += eval_result['file_level']['matched_count']
        file_pred_total += eval_result['file_level']['pred_count']
        file_gold_total += eval_result['file_level']['gold_count']

        func_matched_total += eval_result['function_level']['matched_count']
        func_pred_total += eval_result['function_level']['pred_count']
        func_gold_total += eval_result['function_level']['gold_count']

        line_matched_total += eval_result['line_level']['matched_count']
        line_pred_total += eval_result['line_level']['pred_count']
        line_gold_total += eval_result['line_level']['gold_count']

        # Accumulate for macro-average, exact match, recall=1.0
        file_precision_sum += eval_result['file_level']['precision']
        file_recall_sum += eval_result['file_level']['recall']
        if eval_result['file_level']['exact_match']:
            file_exact_match_count += 1
        if eval_result['file_level']['recall_1']:
            file_recall_1_count += 1

        func_precision_sum += eval_result['function_level']['precision']
        func_recall_sum += eval_result['function_level']['recall']
        if eval_result['function_level']['exact_match']:
            func_exact_match_count += 1
        if eval_result['function_level']['recall_1']:
            func_recall_1_count += 1

        line_precision_sum += eval_result['line_level']['precision']
        line_recall_sum += eval_result['line_level']['recall']
        if eval_result['line_level']['exact_match']:
            line_exact_match_count += 1
        if eval_result['line_level']['recall_1']:
            line_recall_1_count += 1

        if args.verbose:
            print(f"  {instance_id}:")
            print(f"    File:  P={eval_result['file_level']['precision']:.2f} R={eval_result['file_level']['recall']:.2f} EM={eval_result['file_level']['exact_match']} R=1:{eval_result['file_level']['recall_1']}")
            print(f"    Func:  P={eval_result['function_level']['precision']:.2f} R={eval_result['function_level']['recall']:.2f} EM={eval_result['function_level']['exact_match']} R=1:{eval_result['function_level']['recall_1']}")
            print(f"    Line:  P={eval_result['line_level']['precision']:.2f} R={eval_result['line_level']['recall']:.2f} EM={eval_result['line_level']['exact_match']} R=1:{eval_result['line_level']['recall_1']}")

    # Calculate final metrics
    def calc_micro_macro(matched, pred, gold, prec_sum, rec_sum, em_count, r1_count, total):
        micro_p = matched / pred if pred > 0 else 0
        micro_r = matched / gold if gold > 0 else 0
        micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) > 0 else 0

        macro_p = prec_sum / total if total > 0 else 0
        macro_r = rec_sum / total if total > 0 else 0
        macro_f1 = 2 * macro_p * macro_r / (macro_p + macro_r) if (macro_p + macro_r) > 0 else 0

        em_rate = em_count / total if total > 0 else 0
        r1_rate = r1_count / total if total > 0 else 0

        return {
            'micro': {'precision': micro_p, 'recall': micro_r, 'f1': micro_f1},
            'macro': {'precision': macro_p, 'recall': macro_r, 'f1': macro_f1},
            'exact_match': {'count': em_count, 'rate': em_rate},
            'recall_1': {'count': r1_count, 'rate': r1_rate}
        }

    file_summary = calc_micro_macro(
        file_matched_total, file_pred_total, file_gold_total,
        file_precision_sum, file_recall_sum, file_exact_match_count, file_recall_1_count, total
    )
    func_summary = calc_micro_macro(
        func_matched_total, func_pred_total, func_gold_total,
        func_precision_sum, func_recall_sum, func_exact_match_count, func_recall_1_count, total
    )
    line_summary = calc_micro_macro(
        line_matched_total, line_pred_total, line_gold_total,
        line_precision_sum, line_recall_sum, line_exact_match_count, line_recall_1_count, total
    )

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total instances evaluated: {total}")
    print(f"Line tolerance: {args.line_tolerance}")
    print()

    print("FILE-LEVEL:")
    print(f"  Micro:  Precision={file_summary['micro']['precision']:.3f}  Recall={file_summary['micro']['recall']:.3f}  F1={file_summary['micro']['f1']:.3f}")
    print(f"  Macro:  Precision={file_summary['macro']['precision']:.3f}  Recall={file_summary['macro']['recall']:.3f}  F1={file_summary['macro']['f1']:.3f}")
    print(f"  Exact Match:  {file_summary['exact_match']['count']}/{total} ({file_summary['exact_match']['rate']*100:.1f}%)")
    print(f"  Recall=1.0:   {file_summary['recall_1']['count']}/{total} ({file_summary['recall_1']['rate']*100:.1f}%)")
    print()

    print("FUNCTION-LEVEL:")
    print(f"  Micro:  Precision={func_summary['micro']['precision']:.3f}  Recall={func_summary['micro']['recall']:.3f}  F1={func_summary['micro']['f1']:.3f}")
    print(f"  Macro:  Precision={func_summary['macro']['precision']:.3f}  Recall={func_summary['macro']['recall']:.3f}  F1={func_summary['macro']['f1']:.3f}")
    print(f"  Exact Match:  {func_summary['exact_match']['count']}/{total} ({func_summary['exact_match']['rate']*100:.1f}%)")
    print(f"  Recall=1.0:   {func_summary['recall_1']['count']}/{total} ({func_summary['recall_1']['rate']*100:.1f}%)")
    print()

    print("LINE-LEVEL:")
    print(f"  Micro:  Precision={line_summary['micro']['precision']:.3f}  Recall={line_summary['micro']['recall']:.3f}  F1={line_summary['micro']['f1']:.3f}")
    print(f"  Macro:  Precision={line_summary['macro']['precision']:.3f}  Recall={line_summary['macro']['recall']:.3f}  F1={line_summary['macro']['f1']:.3f}")
    print(f"  Exact Match:  {line_summary['exact_match']['count']}/{total} ({line_summary['exact_match']['rate']*100:.1f}%)")
    print(f"  Recall=1.0:   {line_summary['recall_1']['count']}/{total} ({line_summary['recall_1']['rate']*100:.1f}%)")

    # Save detailed report
    if args.output:
        report = {
            'task_list': args.task_list,
            'loc_file': args.loc_file,
            'benchmark': args.benchmark,
            'line_tolerance': args.line_tolerance,
            'summary': {
                'total': total,
                'file_level': file_summary,
                'function_level': func_summary,
                'line_level': line_summary
            },
            'details': results
        }

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nDetailed report saved to: {args.output}")


if __name__ == '__main__':
    main()
