#!/usr/bin/env python3
"""Generate detailed localization results markdown file."""

import json
import re

# Load tasks map
with open('setup_result/verified_tasks_map.json', 'r') as f:
    tasks_map = json.load(f)

# Read baseline results
baseline_20 = []
baseline_23 = []

with open('results/localization_base_20inst_20251207/loc_outputs.jsonl', 'r') as f:
    for line in f:
        baseline_20.append(json.loads(line))

with open('results/localization_base_23inst_20251208/loc_outputs.jsonl', 'r') as f:
    for line in f:
        baseline_23.append(json.loads(line))

all_baseline = baseline_20 + baseline_23

def get_gold_locations(patch):
    files = {}
    current_file = None
    current_line = 0

    for line in patch.split('\n'):
        if line.startswith('+++ b/'):
            match = re.search(r'\+\+\+ b/(.+)', line)
            if match:
                current_file = match.group(1)
                files[current_file] = []
        elif line.startswith('@@'):
            match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)', line)
            if match:
                current_line = int(match.group(1))
        elif current_file:
            if line.startswith('+') and not line.startswith('+++'):
                files[current_file].append(current_line)
                current_line += 1
            elif line.startswith('-') and not line.startswith('---'):
                pass
            else:
                current_line += 1

    return files

def get_predicted_lines(found_files, found_edit_locs):
    predicted = {}
    for sample in found_edit_locs:
        if not sample:
            continue
        for file_idx, file_result in enumerate(sample):
            if not file_result or file_idx >= len(found_files):
                continue
            result_str = file_result[0] if isinstance(file_result, list) else file_result
            if not result_str:
                continue
            file_path = found_files[file_idx]
            if file_path not in predicted:
                predicted[file_path] = set()
            for line in result_str.split('\n'):
                line = line.strip()
                if line.startswith('line: '):
                    try:
                        line_num = int(line.split(': ')[1].strip())
                        predicted[file_path].add(line_num)
                    except:
                        pass
    return predicted

def check_line_level(found_files, found_edit_locs, gold_locs):
    if not gold_locs or not found_edit_locs:
        return False
    predicted = get_predicted_lines(found_files, found_edit_locs)
    for gold_file, gold_lines in gold_locs.items():
        if gold_file in predicted:
            for gl in gold_lines:
                if gl in predicted[gold_file]:
                    return True
    return False

# Generate markdown content
md_lines = []
md_lines.append('# PatchPilot Baseline Localization Results (43 Django Instances)')
md_lines.append('')
md_lines.append('Generated: 2025-12-09')
md_lines.append('')
md_lines.append('## Summary')
md_lines.append('')

file_correct = 0
line_correct = 0
results = []

for item in all_baseline:
    instance_id = item.get('instance_id', 'unknown')
    found_files = item.get('found_files', [])
    found_edit_locs = item.get('found_edit_locs', [])

    task = tasks_map.get(instance_id, {})
    test_patch = task.get('patch', '')
    gold_locs = get_gold_locations(test_patch)
    gold_files = list(gold_locs.keys())

    file_ok = any(gf in found_files for gf in gold_files)
    line_ok = check_line_level(found_files, found_edit_locs, gold_locs)

    if file_ok:
        file_correct += 1
    if line_ok:
        line_correct += 1

    predicted_lines = get_predicted_lines(found_files, found_edit_locs)

    results.append({
        'instance_id': instance_id,
        'file_ok': file_ok,
        'line_ok': line_ok,
        'found_files': found_files,
        'gold_files': gold_files,
        'gold_locs': gold_locs,
        'predicted_lines': predicted_lines
    })

total = len(all_baseline)
md_lines.append('| Metric | Correct | Total | Accuracy |')
md_lines.append('|--------|---------|-------|----------|')
md_lines.append(f'| **File-Level** | {file_correct} | {total} | {100*file_correct/total:.1f}% |')
md_lines.append(f'| **Line-Level** | {line_correct} | {total} | {100*line_correct/total:.1f}% |')
md_lines.append('')
md_lines.append('---')
md_lines.append('')
md_lines.append('## Quick Reference Table')
md_lines.append('')
md_lines.append('| # | Instance | File | Line | Gold File |')
md_lines.append('|---|----------|------|------|-----------|')

for i, r in enumerate(results, 1):
    instance_id = r['instance_id']
    file_status = 'O' if r['file_ok'] else 'X'
    line_status = 'O' if r['line_ok'] else 'X'
    gold_file = r['gold_files'][0] if r['gold_files'] else 'N/A'
    # Shorten gold file path
    if len(gold_file) > 40:
        gold_file = '...' + gold_file[-37:]
    md_lines.append(f'| {i} | {instance_id} | {file_status} | {line_status} | `{gold_file}` |')

md_lines.append('')
md_lines.append('---')
md_lines.append('')
md_lines.append('## Detailed Results')
md_lines.append('')

for r in results:
    instance_id = r['instance_id']
    file_status = 'O' if r['file_ok'] else 'X'
    line_status = 'O' if r['line_ok'] else 'X'

    md_lines.append(f"### {instance_id}")
    md_lines.append('')
    md_lines.append('| File-Level | Line-Level |')
    md_lines.append('|------------|------------|')
    md_lines.append(f'| {file_status} | {line_status} |')
    md_lines.append('')

    # Gold files and lines
    md_lines.append('**Gold (Expected):**')
    md_lines.append('')
    for gf, gl in r['gold_locs'].items():
        lines_str = ', '.join(map(str, sorted(gl)[:10]))
        if len(gl) > 10:
            lines_str += f' ... ({len(gl)} total)'
        md_lines.append(f'- `{gf}`: lines {lines_str}')
    md_lines.append('')

    # Predicted files
    md_lines.append('**Predicted Files:**')
    md_lines.append('')
    for i, pf in enumerate(r['found_files'][:5], 1):
        is_gold = ' **(GOLD)**' if pf in r['gold_files'] else ''
        md_lines.append(f'{i}. `{pf}`{is_gold}')
    md_lines.append('')

    # Predicted lines for gold files
    gold_in_predicted = {pf: plines for pf, plines in r['predicted_lines'].items() if pf in r['gold_files']}
    if gold_in_predicted:
        md_lines.append('**Predicted Lines (for gold files):**')
        md_lines.append('')
        for pf, plines in gold_in_predicted.items():
            lines_str = ', '.join(map(str, sorted(plines)[:15]))
            if len(plines) > 15:
                lines_str += f' ... ({len(plines)} total)'
            gold_lines = set(r['gold_locs'].get(pf, []))
            hit_lines = plines & gold_lines
            hit_str = f' (HIT: {sorted(hit_lines)})' if hit_lines else ''
            md_lines.append(f'- `{pf}`: lines {lines_str}{hit_str}')
        md_lines.append('')

    md_lines.append('---')
    md_lines.append('')

# Write to file
with open('BASELINE_43_RESULTS.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(md_lines))

print(f'Generated BASELINE_43_RESULTS.md')
print(f'File-Level: {file_correct}/{total} ({100*file_correct/total:.1f}%)')
print(f'Line-Level: {line_correct}/{total} ({100*line_correct/total:.1f}%)')
