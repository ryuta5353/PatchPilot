import json
import re

# Load all data
with open('analysis/gold_answers_23inst_with_lines.json', 'r') as f:
    gold_answers = json.load(f)

with open('analysis/caller_callee_23inst_data.json', 'r') as f:
    cc_results = json.load(f)

baseline_results = {'run1': {}, 'run2': {}}
with open('results/localization_baseline_23inst_run1_20251218/loc_outputs.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        inst = data.get('instance_id', '')
        baseline_results['run1'][inst] = {
            'found_files': data.get('found_files', []),
            'found_edit_locs': data.get('found_edit_locs', [])
        }

with open('results/localization_baseline_23inst_run2_20251218/loc_outputs.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        inst = data.get('instance_id', '')
        baseline_results['run2'][inst] = {
            'found_files': data.get('found_files', []),
            'found_edit_locs': data.get('found_edit_locs', [])
        }

expected = [
    'django__django-13933', 'django__django-13964', 'django__django-14017', 'django__django-14155',
    'django__django-14238', 'django__django-14534', 'django__django-14580', 'django__django-14608',
    'django__django-14672', 'django__django-14752', 'django__django-14787', 'django__django-14855',
    'django__django-14915', 'django__django-14999', 'django__django-15252', 'django__django-15695',
    'django__django-15814', 'django__django-15851', 'django__django-16139', 'django__django-16255',
    'django__django-16527', 'django__django-16595', 'django__django-17087'
]

# Find common instances
common = []
for inst in expected:
    if (inst in baseline_results['run1'] and inst in baseline_results['run2'] and
        inst in cc_results['run1'] and inst in cc_results['run2']):
        common.append(inst)

print(f'Common instances (completed in all 4 runs): {len(common)}')
print(f'{common}')
print()

def evaluate_file_level(found_files, gold_files):
    for gold in gold_files:
        for found in found_files:
            if gold in found or found in gold:
                return True
    return False

def evaluate_function_level(found_edit_locs, gold_funcs, gold_classes):
    if not found_edit_locs:
        return False
    all_locs = []
    for sample in found_edit_locs:
        for file_loc in sample:
            if isinstance(file_loc, list):
                all_locs.extend(file_loc)
            else:
                all_locs.append(file_loc)
    loc_text = ' '.join(str(loc) for loc in all_locs).lower()
    for func in gold_funcs:
        if func.lower() in loc_text:
            return True
    for cls in gold_classes:
        if cls.lower() in loc_text:
            return True
    return False

def evaluate_line_level_strict(found_edit_locs, gold_file_details):
    if not found_edit_locs:
        return False
    all_locs_text = []
    for sample in found_edit_locs:
        for file_loc in sample:
            if isinstance(file_loc, list):
                all_locs_text.extend(file_loc)
            else:
                all_locs_text.append(file_loc)
    loc_text = ' '.join(str(loc) for loc in all_locs_text)
    found_lines = set(re.findall(r'line:\s*(\d+)', loc_text))
    found_lines = {int(l) for l in found_lines}
    for file_path, info in gold_file_details.items():
        gold_lines = set(info['modified_lines'])
        if gold_lines & found_lines:
            return True
    return False

# Evaluate all 4 runs for common instances
results = {
    'baseline_run1': {'file': 0, 'func': 0, 'line': 0},
    'baseline_run2': {'file': 0, 'func': 0, 'line': 0},
    'cc_run1': {'file': 0, 'func': 0, 'line': 0},
    'cc_run2': {'file': 0, 'func': 0, 'line': 0}
}

for inst in common:
    gold = gold_answers[inst]

    # Baseline Run 1
    found_files = baseline_results['run1'][inst]['found_files']
    found_edit_locs = baseline_results['run1'][inst]['found_edit_locs']
    if evaluate_file_level(found_files, gold['files']): results['baseline_run1']['file'] += 1
    if evaluate_function_level(found_edit_locs, gold['functions'], gold['classes']): results['baseline_run1']['func'] += 1
    if evaluate_line_level_strict(found_edit_locs, gold['file_details']): results['baseline_run1']['line'] += 1

    # Baseline Run 2
    found_files = baseline_results['run2'][inst]['found_files']
    found_edit_locs = baseline_results['run2'][inst]['found_edit_locs']
    if evaluate_file_level(found_files, gold['files']): results['baseline_run2']['file'] += 1
    if evaluate_function_level(found_edit_locs, gold['functions'], gold['classes']): results['baseline_run2']['func'] += 1
    if evaluate_line_level_strict(found_edit_locs, gold['file_details']): results['baseline_run2']['line'] += 1

    # Caller/Callee Run 1
    found_files = cc_results['run1'][inst]['found_files']
    found_edit_locs = cc_results['run1'][inst]['found_edit_locs']
    if evaluate_file_level(found_files, gold['files']): results['cc_run1']['file'] += 1
    if evaluate_function_level(found_edit_locs, gold['functions'], gold['classes']): results['cc_run1']['func'] += 1
    if evaluate_line_level_strict(found_edit_locs, gold['file_details']): results['cc_run1']['line'] += 1

    # Caller/Callee Run 2
    found_files = cc_results['run2'][inst]['found_files']
    found_edit_locs = cc_results['run2'][inst]['found_edit_locs']
    if evaluate_file_level(found_files, gold['files']): results['cc_run2']['file'] += 1
    if evaluate_function_level(found_edit_locs, gold['functions'], gold['classes']): results['cc_run2']['func'] += 1
    if evaluate_line_level_strict(found_edit_locs, gold['file_details']): results['cc_run2']['line'] += 1

n = len(common)
print('=== Summary (Common Instances Only) ===')
print()
print('| Method | Run | File Level | Function Level | Line Level |')
print('|--------|-----|------------|----------------|------------|')
print(f"| Baseline | Run1 | {results['baseline_run1']['file']}/{n} ({100*results['baseline_run1']['file']/n:.1f}%) | {results['baseline_run1']['func']}/{n} ({100*results['baseline_run1']['func']/n:.1f}%) | {results['baseline_run1']['line']}/{n} ({100*results['baseline_run1']['line']/n:.1f}%) |")
print(f"| Baseline | Run2 | {results['baseline_run2']['file']}/{n} ({100*results['baseline_run2']['file']/n:.1f}%) | {results['baseline_run2']['func']}/{n} ({100*results['baseline_run2']['func']/n:.1f}%) | {results['baseline_run2']['line']}/{n} ({100*results['baseline_run2']['line']/n:.1f}%) |")
print(f"| Caller/Callee | Run1 | {results['cc_run1']['file']}/{n} ({100*results['cc_run1']['file']/n:.1f}%) | {results['cc_run1']['func']}/{n} ({100*results['cc_run1']['func']/n:.1f}%) | {results['cc_run1']['line']}/{n} ({100*results['cc_run1']['line']/n:.1f}%) |")
print(f"| Caller/Callee | Run2 | {results['cc_run2']['file']}/{n} ({100*results['cc_run2']['file']/n:.1f}%) | {results['cc_run2']['func']}/{n} ({100*results['cc_run2']['func']/n:.1f}%) | {results['cc_run2']['line']}/{n} ({100*results['cc_run2']['line']/n:.1f}%) |")

# Average
print()
print('=== Average Performance ===')
b_file = (results['baseline_run1']['file'] + results['baseline_run2']['file']) / 2
b_func = (results['baseline_run1']['func'] + results['baseline_run2']['func']) / 2
b_line = (results['baseline_run1']['line'] + results['baseline_run2']['line']) / 2
cc_file = (results['cc_run1']['file'] + results['cc_run2']['file']) / 2
cc_func = (results['cc_run1']['func'] + results['cc_run2']['func']) / 2
cc_line = (results['cc_run1']['line'] + results['cc_run2']['line']) / 2

print(f"| Baseline Avg | {b_file:.1f}/{n} ({100*b_file/n:.1f}%) | {b_func:.1f}/{n} ({100*b_func/n:.1f}%) | {b_line:.1f}/{n} ({100*b_line/n:.1f}%) |")
print(f"| Caller/Callee Avg | {cc_file:.1f}/{n} ({100*cc_file/n:.1f}%) | {cc_func:.1f}/{n} ({100*cc_func/n:.1f}%) | {cc_line:.1f}/{n} ({100*cc_line/n:.1f}%) |")
print()
print('Delta (Caller/Callee - Baseline):')
print(f'  File: {100*(cc_file-b_file)/n:+.1f}pp')
print(f'  Function: {100*(cc_func-b_func)/n:+.1f}pp')
print(f'  Line: {100*(cc_line-b_line)/n:+.1f}pp')
