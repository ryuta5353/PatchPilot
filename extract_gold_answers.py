#!/usr/bin/env python3
"""Extract gold answers from SWE-bench tasks_map."""

import json
import re
import sys

def extract_changed_lines_from_patch(patch):
    """
    Extract changed line numbers from unified diff patch.

    Returns: dict mapping file_path to list of changed line numbers
    """
    file_lines = {}
    current_file = None
    current_line_num = None

    for line in patch.split('\n'):
        # New file
        if line.startswith('diff --git'):
            match = re.search(r'diff --git a/(.*?) b/', line)
            if match:
                current_file = match.group(1)
                if not current_file.startswith('tests/'):
                    file_lines[current_file] = []

        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        elif line.startswith('@@') and current_file:
            match = re.search(r'@@ -(\d+),?\d* \+(\d+),?\d* @@', line)
            if match:
                # Use new file line number (after the change)
                current_line_num = int(match.group(2))

        # Changed lines
        elif current_file and current_line_num is not None:
            if line.startswith('+') and not line.startswith('+++'):
                # Added line
                if current_file in file_lines:
                    file_lines[current_file].append(current_line_num)
                current_line_num += 1
            elif line.startswith('-') and not line.startswith('---'):
                # Deleted line (use same line number, don't increment)
                if current_file in file_lines:
                    file_lines[current_file].append(current_line_num)
            elif not line.startswith('\\'):
                # Context line (no change)
                current_line_num += 1

    # Remove test files and empty entries
    file_lines = {k: sorted(set(v)) for k, v in file_lines.items()
                  if v and not k.startswith('tests/')}

    return file_lines

# Load tasks map
with open('setup_result/verified_tasks_map.json', 'r', encoding='utf-8') as f:
    tasks_map = json.load(f)

# Target instances - read from command line or use default
if len(sys.argv) > 1:
    # Read from file
    with open(sys.argv[1], 'r') as f:
        target_instances = [line.strip() for line in f if line.strip()]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'gold_answers.json'
else:
    # Default: 9 Django instances
    target_instances = [
        'django__django-10914',
        'django__django-10924',
        'django__django-11001',
        'django__django-11019',
        'django__django-11039',
        'django__django-11049',
        'django__django-11099',
        'django__django-11179',
        'django__django-11283',
    ]
    output_file = 'gold_answers_9inst.json'

gold_answers = {}

for instance_id in target_instances:
    if instance_id not in tasks_map:
        print(f"WARNING: {instance_id} not in tasks_map")
        continue

    task = tasks_map[instance_id]

    # Extract gold files and line numbers from patch
    patch = task.get('patch', '')
    file_lines = extract_changed_lines_from_patch(patch)

    gold_files = list(file_lines.keys())

    # Build gold_lines structure: {file: [line_numbers]}
    gold_lines = file_lines

    # Extract problem summary
    problem_statement = task.get('problem_statement', '')
    problem_summary = problem_statement.split('\n')[0][:100] if problem_statement else ''

    gold_answers[instance_id] = {
        'instance_id': instance_id,
        'gold_files': gold_files,
        'gold_lines': gold_lines,  # NEW: line-level gold answers
        'gold_functions': [],  # Will be filled manually if needed
        'problem_summary': problem_summary
    }

    print(f"{instance_id}:")
    print(f"  Files: {gold_files}")
    print(f"  Lines: {gold_lines}")
    print(f"  Problem: {problem_summary}")
    print()

# Save gold answers
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(gold_answers, f, indent=2, ensure_ascii=False)

print(f"Saved {len(gold_answers)} gold answers to {output_file}")
