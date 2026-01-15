#!/usr/bin/env python3
"""Evaluate related level (function/class) localization using found_related_locs."""

import json
import re
import os
from collections import defaultdict

def load_tags(tags_file):
    """Load tags_json and organize by file."""
    with open(tags_file, 'r', encoding='utf-8') as f:
        tags = json.load(f)

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

    for fname, defs in file_defs.items():
        defs.sort(key=lambda x: x['line'])
        for i, d in enumerate(defs):
            if i + 1 < len(defs):
                d['end_line'] = defs[i + 1]['line'] - 1
            else:
                d['end_line'] = d['line'] + len(d['info'].split('\n')) + 50

    return file_defs

def find_function_for_line(file_defs, file_path, line_num):
    """Find which function/class contains the given line."""
    defs = file_defs.get(file_path, [])
    candidates = []
    for d in defs:
        if d['line'] <= line_num <= d['end_line']:
            candidates.append(d)
    if candidates:
        best = max(candidates, key=lambda x: x['line'])
        return best['name'], best['category'], best['line'], best['end_line']
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

def extract_related_funcs(found_related_locs, found_files, target_file):
    """Extract function/class names from found_related_locs for a specific file."""
    if target_file not in found_files:
        return set(), ''

    file_idx = found_files.index(target_file)
    funcs = set()
    raw = ''

    if found_related_locs and file_idx < len(found_related_locs):
        rel = found_related_locs[file_idx]
        if rel and isinstance(rel, list):
            raw = rel[0] if rel else ''
            for line in raw.split('\n'):
                line = line.strip()
                if line.startswith('function:'):
                    name = line.split(':', 1)[1].strip()
                    # Handle Class.method format
                    if '.' in name:
                        funcs.add(name.split('.')[-1])  # method name
                        funcs.add(name)  # full name
                    else:
                        funcs.add(name)
                elif line.startswith('class:'):
                    name = line.split(':', 1)[1].strip()
                    funcs.add(name)

    return funcs, raw

def get_predicted_lines(found_files, found_edit_locs, target_file):
    """Get predicted lines for a specific file."""
    if target_file not in found_files:
        return set()
    file_idx = found_files.index(target_file)
    all_lines = set()
    for sample in found_edit_locs or []:
        if not sample or file_idx >= len(sample):
            continue
        file_result = sample[file_idx]
        if not file_result:
            continue
        result_str = file_result[0] if isinstance(file_result, list) else file_result
        for l in result_str.split('\n'):
            if l.strip().startswith('line:'):
                try:
                    all_lines.add(int(l.split(':')[1].strip()))
                except:
                    pass
    return all_lines

def main():
    with open('setup_result/verified_tasks_map.json', 'r', encoding='utf-8') as f:
        tasks_map = json.load(f)

    results = []
    with open('results/localization_base_20inst_20251207/loc_outputs.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            results.append(json.loads(line))
    with open('results/localization_base_23inst_20251208/loc_outputs.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            results.append(json.loads(line))

    tags_dir = 'RepoGraph_cache'

    md = []
    md.append('# Three-Level Localization Evaluation (43 Django Instances)')
    md.append('')
    md.append('Evaluating File Level, Related Level (function/class), and Line Level.')
    md.append('')
    md.append('**Related Level uses `found_related_locs` from the localization output.**')
    md.append('')

    stats = {'total': 0, 'file_ok': 0, 'related_ok': 0, 'line_ok': 0}
    all_details = []

    for item in results:
        instance_id = item['instance_id']
        task = tasks_map.get(instance_id, {})
        patch = task.get('patch', '')
        gold_locs = get_gold_locations(patch)
        if not gold_locs:
            continue

        stats['total'] += 1

        found_files = item.get('found_files', [])
        found_related_locs = item.get('found_related_locs', [])
        found_edit_locs = item.get('found_edit_locs', [])
        gold_files = list(gold_locs.keys())

        # File level
        file_ok = any(gf in found_files for gf in gold_files)

        # Get gold functions from tags
        tags_file = os.path.join(tags_dir, f'tags_{instance_id}.json')
        gold_funcs = []
        if os.path.exists(tags_file):
            file_defs = load_tags(tags_file)
            for gold_file, gold_lines in gold_locs.items():
                for gold_line in gold_lines:
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

        # Related level - extract from found_related_locs
        pred_funcs_related = set()
        related_raw = {}
        for gold_file in gold_files:
            funcs, raw = extract_related_funcs(found_related_locs, found_files, gold_file)
            pred_funcs_related.update(funcs)
            if raw:
                related_raw[gold_file] = raw

        gold_func_names = set(gf['name'] for gf in gold_funcs)
        related_ok = bool(gold_func_names & pred_funcs_related)

        # Line level
        line_ok = False
        pred_lines = set()
        for gold_file, gold_lines in gold_locs.items():
            pl = get_predicted_lines(found_files, found_edit_locs, gold_file)
            pred_lines.update(pl)
            for gl in gold_lines:
                if gl in pl:
                    line_ok = True

        if file_ok:
            stats['file_ok'] += 1
        if related_ok:
            stats['related_ok'] += 1
        if line_ok:
            stats['line_ok'] += 1

        all_details.append({
            'instance_id': instance_id,
            'file_ok': file_ok,
            'related_ok': related_ok,
            'line_ok': line_ok,
            'gold_files': gold_files,
            'gold_locs': gold_locs,
            'gold_funcs': gold_funcs,
            'pred_funcs_related': list(pred_funcs_related),
            'found_files': found_files,
            'pred_lines': sorted(pred_lines),
            'related_raw': related_raw
        })

    # Summary
    md.append('## Summary')
    md.append('')
    md.append('| Level | Correct | Total | Accuracy |')
    md.append('|-------|---------|-------|----------|')
    md.append(f'| **File** | {stats["file_ok"]} | {stats["total"]} | {100*stats["file_ok"]/stats["total"]:.1f}% |')
    md.append(f'| **Related (Func/Class)** | {stats["related_ok"]} | {stats["total"]} | {100*stats["related_ok"]/stats["total"]:.1f}% |')
    md.append(f'| **Line** | {stats["line_ok"]} | {stats["total"]} | {100*stats["line_ok"]/stats["total"]:.1f}% |')
    md.append('')

    # Quick reference
    md.append('## Quick Reference Table')
    md.append('')
    md.append('| # | Instance | File | Related | Line | Gold Func | Pred Func (Related) |')
    md.append('|---|----------|------|---------|------|-----------|---------------------|')

    for i, d in enumerate(all_details, 1):
        f = 'O' if d['file_ok'] else 'X'
        r = 'O' if d['related_ok'] else 'X'
        l = 'O' if d['line_ok'] else 'X'
        gf = ', '.join(set(g['name'] for g in d['gold_funcs'][:2])) or '-'
        pf = ', '.join(d['pred_funcs_related'][:3]) or '-'
        if len(gf) > 20:
            gf = gf[:17] + '...'
        if len(pf) > 25:
            pf = pf[:22] + '...'
        md.append(f'| {i} | {d["instance_id"]} | {f} | {r} | {l} | {gf} | {pf} |')

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
        md.append(f'| Related | {"O" if d["related_ok"] else "X"} |')
        md.append(f'| Line | {"O" if d["line_ok"] else "X"} |')
        md.append('')

        md.append('**Gold (Expected):**')
        md.append('')
        for gold_file, gold_lines in d['gold_locs'].items():
            md.append(f'- File: `{gold_file}`')
            md.append(f'- Lines: {gold_lines}')
        md.append('')

        if d['gold_funcs']:
            md.append('**Gold Functions:**')
            md.append('')
            seen = set()
            for gf in d['gold_funcs']:
                if gf['name'] not in seen:
                    seen.add(gf['name'])
                    md.append(f'- `{gf["name"]}` ({gf["category"]}) @ {gf["func_start"]}-{gf["func_end"]}')
            md.append('')

        md.append('**Predicted (Related Level):**')
        md.append('')
        if d['pred_funcs_related']:
            for pf in d['pred_funcs_related'][:10]:
                match = ' **MATCH**' if pf in set(g['name'] for g in d['gold_funcs']) else ''
                md.append(f'- `{pf}`{match}')
        else:
            md.append('- (none)')
        md.append('')

        if d['related_raw']:
            md.append('**Raw Related Output:**')
            md.append('')
            for file, raw in d['related_raw'].items():
                md.append(f'File: `{file}`')
                md.append('```')
                md.append(raw[:400])
                md.append('```')
            md.append('')

        md.append(f'**Predicted Lines:** {d["pred_lines"][:15]}')
        md.append('')
        md.append('---')
        md.append('')

    with open('analysis/RELATED_LEVEL_EVALUATION.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    print('Created: analysis/RELATED_LEVEL_EVALUATION.md')
    print()
    print('Summary:')
    print(f'  File Level:    {stats["file_ok"]}/{stats["total"]} ({100*stats["file_ok"]/stats["total"]:.1f}%)')
    print(f'  Related Level: {stats["related_ok"]}/{stats["total"]} ({100*stats["related_ok"]/stats["total"]:.1f}%)')
    print(f'  Line Level:    {stats["line_ok"]}/{stats["total"]} ({100*stats["line_ok"]/stats["total"]:.1f}%)')

if __name__ == '__main__':
    main()
