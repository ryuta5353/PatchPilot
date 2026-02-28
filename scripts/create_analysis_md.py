#!/usr/bin/env python3
"""Create detailed line-level failure analysis markdown file."""

import json
import re

with open('setup_result/verified_tasks_map.json', 'r', encoding='utf-8') as f:
    tasks_map = json.load(f)

# Load results
results_20 = {}
results_23 = {}
with open('results/localization_base_20inst_20251207/loc_outputs.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        results_20[data['instance_id']] = data
with open('results/localization_base_23inst_20251208/loc_outputs.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        results_23[data['instance_id']] = data

instances = [
    'django__django-11133',
    'django__django-12125',
    'django__django-13028',
    'django__django-13033',
    'django__django-13964',
    'django__django-14915',
    'django__django-14580',
    'django__django-15814'
]

def get_gold_info(patch):
    files = {}
    current_file = None
    current_line = 0
    for line in patch.split('\n'):
        if line.startswith('+++ b/'):
            current_file = line.replace('+++ b/', '')
            files[current_file] = {'lines': [], 'changes': []}
        elif line.startswith('@@') and current_file:
            match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)', line)
            if match:
                current_line = int(match.group(1))
        elif current_file:
            if line.startswith('+') and not line.startswith('+++'):
                files[current_file]['lines'].append(current_line)
                files[current_file]['changes'].append((current_line, '+', line[1:]))
                current_line += 1
            elif line.startswith('-') and not line.startswith('---'):
                files[current_file]['changes'].append((current_line, '-', line[1:]))
            else:
                current_line += 1
    return files

def get_predicted_info(data, gold_file):
    found_files = data.get('found_files', [])
    if gold_file not in found_files:
        return None, []
    gold_idx = found_files.index(gold_file)

    all_lines = set()
    details = []
    for sample_idx, sample in enumerate(data.get('found_edit_locs', [])):
        if sample and gold_idx < len(sample) and sample[gold_idx]:
            result = sample[gold_idx][0] if isinstance(sample[gold_idx], list) else sample[gold_idx]
            details.append(result)
            for l in result.split('\n'):
                if l.strip().startswith('line:'):
                    try:
                        all_lines.add(int(l.split(':')[1].strip()))
                    except:
                        pass
    return sorted(all_lines), details

md = []
md.append('# Line-Level Localization Failure Analysis')
md.append('')
md.append('8 instances where File-Level=O but Line-Level=X')
md.append('')
md.append('Generated for detailed manual analysis')
md.append('')
md.append('---')
md.append('')

for inst in instances:
    task = tasks_map.get(inst, {})
    data = results_20.get(inst) or results_23.get(inst)

    problem = task.get('problem_statement', '')
    patch = task.get('patch', '')
    gold_info = get_gold_info(patch)
    gold_file = list(gold_info.keys())[0] if gold_info else ''
    gold_lines = gold_info.get(gold_file, {}).get('lines', [])
    gold_changes = gold_info.get(gold_file, {}).get('changes', [])

    predicted_lines, predicted_details = get_predicted_info(data, gold_file)

    md.append(f'## {inst}')
    md.append('')

    # Summary table
    md.append('### Summary')
    md.append('')
    md.append('| Item | Value |')
    md.append('|------|-------|')
    md.append(f'| Gold File | `{gold_file}` |')
    md.append(f'| Gold Lines | {gold_lines} |')
    md.append(f'| Predicted Lines | {predicted_lines if predicted_lines else "(empty)"} |')

    if predicted_lines and gold_lines:
        min_dist = min(abs(p - g) for p in predicted_lines for g in gold_lines)
        md.append(f'| Min Distance | {min_dist} lines |')
    elif not predicted_lines:
        md.append(f'| Min Distance | N/A (no prediction) |')
    md.append('')

    # Problem statement
    md.append('### Problem Statement')
    md.append('')
    md.append('```')
    # Truncate if too long
    prob_text = problem[:2500]
    if len(problem) > 2500:
        prob_text += '\n... (truncated)'
    md.append(prob_text)
    md.append('```')
    md.append('')

    # Gold patch
    md.append('### Gold Patch (Correct Answer)')
    md.append('')
    md.append('```diff')
    md.append(patch)
    md.append('```')
    md.append('')

    # Predicted details
    md.append('### Predicted Location Details')
    md.append('')
    if predicted_details:
        for i, detail in enumerate(predicted_details[:2]):
            md.append(f'**Sample {i}:**')
            md.append('```')
            md.append(detail)
            md.append('```')
            md.append('')
    else:
        md.append('*No line predictions made*')
        md.append('')

    # Analysis placeholder
    md.append('### Analysis')
    md.append('')
    md.append('**Failure Pattern:**')
    md.append('')

    # Add automatic pattern detection
    if not predicted_lines:
        md.append('- [ ] Pattern: No line prediction output')
    elif predicted_lines and gold_lines:
        min_dist = min(abs(p - g) for p in predicted_lines for g in gold_lines)
        if min_dist <= 5:
            md.append('- [ ] Pattern: Near miss (within 5 lines)')
        elif min_dist <= 50:
            md.append('- [ ] Pattern: Wrong method in same area')
        else:
            md.append('- [ ] Pattern: Completely wrong location')

    md.append('')
    md.append('**Why did LLM fail?**')
    md.append('')
    md.append('(To be filled in during analysis)')
    md.append('')
    md.append('**Keywords in problem that led to wrong location:**')
    md.append('')
    md.append('(To be filled in during analysis)')
    md.append('')

    md.append('---')
    md.append('')

# Write file
with open('analysis/LINE_LEVEL_FAILURE_ANALYSIS.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(md))

print('Created: analysis/LINE_LEVEL_FAILURE_ANALYSIS.md')
print(f'Total instances: {len(instances)}')
