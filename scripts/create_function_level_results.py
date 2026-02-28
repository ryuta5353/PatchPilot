#!/usr/bin/env python3
"""Create detailed function/class level evaluation results."""

import json
import re
import os
from collections import defaultdict

def load_tags(tags_file):
    """Load tags_json and organize by file."""
    with open(tags_file, 'r', encoding='utf-8') as f:
        tags = json.load(f)

    # Group definitions by file
    file_defs = defaultdict(list)
    for tag in tags:
        if tag.get('kind') == 'def':
            rel_fname = tag.get('rel_fname', '')
            file_defs[rel_fname].append({
                'name': tag.get('name'),
                'line': tag.get('line'),
                'category': tag.get('category'),
                'info': tag.get('info', '')
            })

    # Sort by line number and compute end lines
    for fname, defs in file_defs.items():
        defs.sort(key=lambda x: x['line'])
        for i, d in enumerate(defs):
            if i + 1 < len(defs):
                d['end_line'] = defs[i + 1]['line'] - 1
            else:
                # Estimate end line from info (count newlines)
                d['end_line'] = d['line'] + len(d['info'].split('\n')) + 50

    return file_defs

def find_function_for_line(file_defs, file_path, line_num):
    """Find which function/class contains the given line."""
    defs = file_defs.get(file_path, [])

    # Find all definitions that could contain this line
    candidates = []
    for d in defs:
        if d['line'] <= line_num <= d['end_line']:
            candidates.append(d)

    # Return the innermost (highest start line)
    if candidates:
        best = max(candidates, key=lambda x: x['line'])
        return best['name'], best['category'], best['line'], best['end_line']

    # If not found in range, find nearest definition before this line
    for d in reversed(defs):
        if d['line'] <= line_num:
            return d['name'], d['category'], d['line'], d['end_line']

    return None, None, None, None

def get_gold_locations(patch):
    """Extract gold files and lines from patch."""
    gold_locs = {}
    current_file = None
    current_line = 0

    for line in patch.split('\n'):
        if line.startswith('+++ b/'):
            current_file = line.replace('+++ b/', '')
            gold_locs[current_file] = []
        elif line.startswith('@@') and current_file:
            match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)', line)
            if match:
                current_line = int(match.group(1))
        elif current_file:
            if line.startswith('+') and not line.startswith('+++'):
                gold_locs[current_file].append(current_line)
                current_line += 1
            elif line.startswith('-') and not line.startswith('---'):
                pass
            else:
                current_line += 1

    return gold_locs

def get_predicted_functions(found_edit_locs):
    """Extract predicted function/class names from predictions."""
    predicted = set()

    for sample in found_edit_locs or []:
        if not sample:
            continue
        for file_result in sample:
            if not file_result:
                continue
            result_str = file_result[0] if isinstance(file_result, list) else file_result
            if not result_str:
                continue

            for line in result_str.split('\n'):
                line = line.strip()
                if line.startswith('function:'):
                    name = line.split(':', 1)[1].strip()
                    predicted.add(('function', name))
                elif line.startswith('class:'):
                    name = line.split(':', 1)[1].strip()
                    predicted.add(('class', name))

    return predicted

def get_predicted_lines_for_file(found_files, found_edit_locs, target_file):
    """Get predicted lines for a specific file."""
    if target_file not in found_files:
        return set(), []

    file_idx = found_files.index(target_file)
    all_lines = set()
    raw_outputs = []

    for sample in found_edit_locs or []:
        if not sample or file_idx >= len(sample):
            continue
        file_result = sample[file_idx]
        if not file_result:
            continue
        result_str = file_result[0] if isinstance(file_result, list) else file_result
        if not result_str:
            continue

        raw_outputs.append(result_str)
        for l in result_str.split('\n'):
            if l.strip().startswith('line:'):
                try:
                    all_lines.add(int(l.split(':')[1].strip()))
                except:
                    pass

    return all_lines, raw_outputs

def main():
    # Load tasks map
    with open('setup_result/verified_tasks_map.json', 'r', encoding='utf-8') as f:
        tasks_map = json.load(f)

    # Load baseline results
    results = []
    with open('results/localization_base_20inst_20251207/loc_outputs.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            results.append(json.loads(line))
    with open('results/localization_base_23inst_20251208/loc_outputs.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            results.append(json.loads(line))

    tags_dir = 'RepoGraph_cache'

    # Build markdown
    md = []
    md.append('# Function/Class Level Localization Evaluation (43 Django Instances)')
    md.append('')
    md.append('This evaluation adds Function/Class level accuracy between File and Line levels.')
    md.append('')

    # Stats
    stats = {'total': 0, 'has_tags': 0, 'file_ok': 0, 'func_ok': 0, 'line_ok': 0}
    all_details = []

    for item in results:
        instance_id = item['instance_id']
        task = tasks_map.get(instance_id, {})
        patch = task.get('patch', '')

        gold_locs = get_gold_locations(patch)
        if not gold_locs:
            continue

        stats['total'] += 1

        # Check tags file
        tags_file = os.path.join(tags_dir, f'tags_{instance_id}.json')
        has_tags = os.path.exists(tags_file)

        if has_tags:
            stats['has_tags'] += 1
            file_defs = load_tags(tags_file)
        else:
            file_defs = {}

        # Get gold functions
        gold_funcs = []
        for gold_file, gold_lines in gold_locs.items():
            for gold_line in gold_lines:
                if has_tags:
                    func_name, category, start, end = find_function_for_line(file_defs, gold_file, gold_line)
                    if func_name:
                        gold_funcs.append({
                            'name': func_name,
                            'category': category,
                            'file': gold_file,
                            'gold_line': gold_line,
                            'func_start': start,
                            'func_end': end
                        })

        # Get predictions
        found_files = item.get('found_files', [])
        found_edit_locs = item.get('found_edit_locs', [])
        pred_funcs = get_predicted_functions(found_edit_locs)

        # File level check
        gold_files = list(gold_locs.keys())
        file_ok = any(gf in found_files for gf in gold_files)

        # Function level check (name match)
        gold_func_names = set(gf['name'] for gf in gold_funcs)
        pred_func_names = set(name for cat, name in pred_funcs)
        func_ok = bool(gold_func_names & pred_func_names)

        # Line level check
        line_ok = False
        for gold_file, gold_lines in gold_locs.items():
            pred_lines, _ = get_predicted_lines_for_file(found_files, found_edit_locs, gold_file)
            for gl in gold_lines:
                if gl in pred_lines:
                    line_ok = True
                    break

        if file_ok:
            stats['file_ok'] += 1
        if func_ok:
            stats['func_ok'] += 1
        if line_ok:
            stats['line_ok'] += 1

        # Get predicted lines and raw output for gold file
        pred_lines_for_gold = set()
        raw_output = []
        for gold_file in gold_files:
            pl, ro = get_predicted_lines_for_file(found_files, found_edit_locs, gold_file)
            pred_lines_for_gold.update(pl)
            raw_output.extend(ro)

        all_details.append({
            'instance_id': instance_id,
            'has_tags': has_tags,
            'file_ok': file_ok,
            'func_ok': func_ok,
            'line_ok': line_ok,
            'gold_files': gold_files,
            'gold_locs': gold_locs,
            'gold_funcs': gold_funcs,
            'pred_funcs': list(pred_funcs),
            'found_files': found_files,
            'pred_lines': sorted(pred_lines_for_gold),
            'raw_output': raw_output[:2]
        })

    # Summary
    md.append('## Summary')
    md.append('')
    md.append('| Level | Correct | Total | Accuracy |')
    md.append('|-------|---------|-------|----------|')
    md.append(f'| **File** | {stats["file_ok"]} | {stats["has_tags"]} | {100*stats["file_ok"]/stats["has_tags"]:.1f}% |')
    md.append(f'| **Function/Class** | {stats["func_ok"]} | {stats["has_tags"]} | {100*stats["func_ok"]/stats["has_tags"]:.1f}% |')
    md.append(f'| **Line** | {stats["line_ok"]} | {stats["has_tags"]} | {100*stats["line_ok"]/stats["has_tags"]:.1f}% |')
    md.append('')

    # Quick reference table
    md.append('## Quick Reference Table')
    md.append('')
    md.append('| # | Instance | File | Func | Line | Gold Func | Pred Func |')
    md.append('|---|----------|------|------|------|-----------|-----------|')

    for i, d in enumerate(all_details, 1):
        f = 'O' if d['file_ok'] else 'X'
        fn = 'O' if d['func_ok'] else 'X'
        l = 'O' if d['line_ok'] else 'X'
        gf = ', '.join(set(g['name'] for g in d['gold_funcs'][:2])) or '-'
        pf = ', '.join(n for c, n in d['pred_funcs'][:2]) or '-'
        if len(gf) > 25:
            gf = gf[:22] + '...'
        if len(pf) > 25:
            pf = pf[:22] + '...'
        md.append(f'| {i} | {d["instance_id"]} | {f} | {fn} | {l} | {gf} | {pf} |')

    md.append('')
    md.append('---')
    md.append('')

    # Detailed results
    md.append('## Detailed Results')
    md.append('')

    for d in all_details:
        md.append(f'### {d["instance_id"]}')
        md.append('')
        md.append('| Level | Result |')
        md.append('|-------|--------|')
        md.append(f'| File | {"O" if d["file_ok"] else "X"} |')
        md.append(f'| Function/Class | {"O" if d["func_ok"] else "X"} |')
        md.append(f'| Line | {"O" if d["line_ok"] else "X"} |')
        md.append('')

        # Gold info
        md.append('**Gold (Expected):**')
        md.append('')
        for gold_file, gold_lines in d['gold_locs'].items():
            md.append(f'- File: `{gold_file}`')
            md.append(f'- Lines: {gold_lines}')
        md.append('')

        if d['gold_funcs']:
            md.append('**Gold Functions (from tags_json):**')
            md.append('')
            seen = set()
            for gf in d['gold_funcs']:
                key = (gf['name'], gf['category'])
                if key not in seen:
                    seen.add(key)
                    md.append(f'- `{gf["name"]}` ({gf["category"]}) @ lines {gf["func_start"]}-{gf["func_end"]}')
                    md.append(f'  - Gold line {gf["gold_line"]} is within this range')
            md.append('')

        # Predicted info
        md.append('**Predicted Files:**')
        md.append('')
        for i, pf in enumerate(d['found_files'][:5], 1):
            is_gold = ' **(GOLD)**' if pf in d['gold_files'] else ''
            md.append(f'{i}. `{pf}`{is_gold}')
        md.append('')

        if d['pred_funcs']:
            md.append('**Predicted Functions/Classes:**')
            md.append('')
            for cat, name in d['pred_funcs'][:10]:
                match = '**MATCH**' if name in set(g['name'] for g in d['gold_funcs']) else ''
                md.append(f'- `{name}` ({cat}) {match}')
            md.append('')

        md.append(f'**Predicted Lines:** {d["pred_lines"][:15]}')
        md.append('')

        if d['raw_output']:
            md.append('**Raw LLM Output (Sample 0):**')
            md.append('')
            md.append('```')
            md.append(d['raw_output'][0][:500])
            md.append('```')
            md.append('')

        md.append('---')
        md.append('')

    # Write file
    with open('analysis/FUNCTION_LEVEL_EVALUATION.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    print('Created: analysis/FUNCTION_LEVEL_EVALUATION.md')
    print()
    print('Summary:')
    print(f'  File Level:     {stats["file_ok"]}/{stats["has_tags"]} ({100*stats["file_ok"]/stats["has_tags"]:.1f}%)')
    print(f'  Function Level: {stats["func_ok"]}/{stats["has_tags"]} ({100*stats["func_ok"]/stats["has_tags"]:.1f}%)')
    print(f'  Line Level:     {stats["line_ok"]}/{stats["has_tags"]} ({100*stats["line_ok"]/stats["has_tags"]:.1f}%)')

if __name__ == '__main__':
    main()
