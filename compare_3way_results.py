import json
import re

# Load gold answers
with open("gold_answers/gold_answers_mixed_phase1_v2.json") as f:
    gold_answers = json.load(f)

# Load all three result sets
baseline_data = {}
repograph_1sample_data = {}
repograph_4sample_data = {}

# Baseline
with open("results/localization_base_23inst_final_20251109/loc_outputs.jsonl") as f:
    for line in f:
        data = json.loads(line)
        baseline_data[data['instance_id']] = data

with open("results/localization_base_10inst_phase2_6_20251109/loc_outputs.jsonl") as f:
    for line in f:
        data = json.loads(line)
        if data['instance_id'] == 'django__django-15695':
            baseline_data[data['instance_id']] = data

# Repograph (1 sample)
with open("results/localization_repo_23inst_phase2_6_20251109/loc_outputs.jsonl") as f:
    for line in f:
        data = json.loads(line)
        repograph_1sample_data[data['instance_id']] = data

with open("results/localization_repo_failed_complete_20251109/loc_outputs.jsonl") as f:
    for line in f:
        data = json.loads(line)
        repograph_1sample_data[data['instance_id']] = data

# Repograph (4 samples) - Fair comparison
with open("results/localization_repo_23inst_fair_num_samples4_20251109/loc_outputs.jsonl") as f:
    for line in f:
        data = json.loads(line)
        repograph_4sample_data[data['instance_id']] = data

def extract_lines_from_edit_locs(found_files, found_edit_locs):
    """Extract all found line numbers mapped to files."""
    file_line_map = {}

    for sample in found_edit_locs:
        for file_idx, entry_list in enumerate(sample):
            if file_idx >= len(found_files):
                continue

            file_path = found_files[file_idx]
            if file_path not in file_line_map:
                file_line_map[file_path] = set()

            if isinstance(entry_list, list):
                entries = entry_list
            else:
                entries = [entry_list]

            for entry in entries:
                if not entry or not isinstance(entry, str):
                    continue

                lines = re.findall(r'line:\s*(\d+)', entry)
                for line_num in lines:
                    file_line_map[file_path].add(int(line_num))

    return file_line_map

# Calculate accuracy for all three versions
results = []
for instance_id in sorted(gold_answers.keys()):
    if instance_id not in baseline_data or instance_id not in repograph_1sample_data or instance_id not in repograph_4sample_data:
        continue

    gold_entry = gold_answers[instance_id]
    gold_lines = gold_entry.get('gold_lines', {})

    # Baseline
    baseline = baseline_data[instance_id]
    baseline_lines = extract_lines_from_edit_locs(baseline['found_files'], baseline['found_edit_locs'])

    # Repograph (1 sample)
    repograph_1 = repograph_1sample_data[instance_id]
    repograph_1_lines = extract_lines_from_edit_locs(repograph_1['found_files'], repograph_1['found_edit_locs'])

    # Repograph (4 samples)
    repograph_4 = repograph_4sample_data[instance_id]
    repograph_4_lines = extract_lines_from_edit_locs(repograph_4['found_files'], repograph_4['found_edit_locs'])

    # Count matches
    baseline_correct = 0
    baseline_total = 0
    repograph_1_correct = 0
    repograph_1_total = 0
    repograph_4_correct = 0
    repograph_4_total = 0

    for file_path, gold_line_list in gold_lines.items():
        baseline_total += len(gold_line_list)
        repograph_1_total += len(gold_line_list)
        repograph_4_total += len(gold_line_list)

        baseline_found = baseline_lines.get(file_path, set())
        repograph_1_found = repograph_1_lines.get(file_path, set())
        repograph_4_found = repograph_4_lines.get(file_path, set())

        for line_num in gold_line_list:
            if line_num in baseline_found:
                baseline_correct += 1
            if line_num in repograph_1_found:
                repograph_1_correct += 1
            if line_num in repograph_4_found:
                repograph_4_correct += 1

    baseline_acc = baseline_correct / baseline_total if baseline_total > 0 else 0
    repograph_1_acc = repograph_1_correct / repograph_1_total if repograph_1_total > 0 else 0
    repograph_4_acc = repograph_4_correct / repograph_4_total if repograph_4_total > 0 else 0

    results.append({
        'instance': instance_id,
        'baseline_correct': baseline_correct,
        'baseline_total': baseline_total,
        'baseline_acc': baseline_acc,
        'repograph_1_correct': repograph_1_correct,
        'repograph_1_total': repograph_1_total,
        'repograph_1_acc': repograph_1_acc,
        'repograph_4_correct': repograph_4_correct,
        'repograph_4_total': repograph_4_total,
        'repograph_4_acc': repograph_4_acc,
    })

# Print summary
print("="*130)
print("LINE-LEVEL ACCURACY COMPARISON - 3-WAY (23 INSTANCES)")
print("="*130)
print(f"\n{'Instance':<40} {'Baseline':<20} {'Repograph(1)':<20} {'Repograph(4)':<20} {'Delta(4-Base)':<15}")
print(f"{'':40} {'(Correct/Total)':<20} {'(Correct/Total)':<20} {'(Correct/Total)':<20} {'pp':<15}")
print("-"*130)

total_baseline_correct = 0
total_baseline_total = 0
total_repograph_1_correct = 0
total_repograph_1_total = 0
total_repograph_4_correct = 0
total_repograph_4_total = 0

for result in sorted(results, key=lambda x: x['instance']):
    baseline_pct = result['baseline_acc'] * 100
    repograph_1_pct = result['repograph_1_acc'] * 100
    repograph_4_pct = result['repograph_4_acc'] * 100
    delta = repograph_4_pct - baseline_pct

    baseline_str = f"{result['baseline_correct']}/{result['baseline_total']} ({baseline_pct:5.1f}%)"
    repograph_1_str = f"{result['repograph_1_correct']}/{result['repograph_1_total']} ({repograph_1_pct:5.1f}%)"
    repograph_4_str = f"{result['repograph_4_correct']}/{result['repograph_4_total']} ({repograph_4_pct:5.1f}%)"

    total_baseline_correct += result['baseline_correct']
    total_baseline_total += result['baseline_total']
    total_repograph_1_correct += result['repograph_1_correct']
    total_repograph_1_total += result['repograph_1_total']
    total_repograph_4_correct += result['repograph_4_correct']
    total_repograph_4_total += result['repograph_4_total']

    print(f"{result['instance']:<40} {baseline_str:<20} {repograph_1_str:<20} {repograph_4_str:<20} {delta:+6.1f}pp")

# Calculate overall statistics
baseline_overall = total_baseline_correct / total_baseline_total if total_baseline_total > 0 else 0
repograph_1_overall = total_repograph_1_correct / total_repograph_1_total if total_repograph_1_total > 0 else 0
repograph_4_overall = total_repograph_4_correct / total_repograph_4_total if total_repograph_4_total > 0 else 0

print("-"*130)
baseline_str = f"{total_baseline_correct}/{total_baseline_total} ({baseline_overall*100:5.1f}%)"
repograph_1_str = f"{total_repograph_1_correct}/{total_repograph_1_total} ({repograph_1_overall*100:5.1f}%)"
repograph_4_str = f"{total_repograph_4_correct}/{total_repograph_4_total} ({repograph_4_overall*100:5.1f}%)"
delta_overall = (repograph_4_overall - baseline_overall) * 100

print(f"{'OVERALL':<40} {baseline_str:<20} {repograph_1_str:<20} {repograph_4_str:<20} {delta_overall:+6.1f}pp")
print("="*130)

print(f"\nSUMMARY:")
print(f"  Baseline:             {total_baseline_correct}/{total_baseline_total} = {baseline_overall*100:.1f}%")
print(f"  Repograph (1 sample): {total_repograph_1_correct}/{total_repograph_1_total} = {repograph_1_overall*100:.1f}%")
print(f"  Repograph (4 samples): {total_repograph_4_correct}/{total_repograph_4_total} = {repograph_4_overall*100:.1f}%")
print(f"\n  Change (Repograph 4 vs Baseline): {delta_overall:+.1f}pp")
print(f"  Change (Repograph 1 vs Baseline): {(repograph_1_overall - baseline_overall)*100:+.1f}pp")
print(f"  Improvement (4 samples vs 1 sample): {(repograph_4_overall - repograph_1_overall)*100:+.1f}pp")
