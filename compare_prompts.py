#!/usr/bin/env python3
"""Compare prompts between baseline and repograph."""

import json
import sys

def compare_prompts(instance_id, baseline_file, repograph_file):
    # Load data
    baseline_data = None
    repograph_data = None

    with open(baseline_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            if data['instance_id'] == instance_id:
                baseline_data = data
                break

    with open(repograph_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            if data['instance_id'] == instance_id:
                repograph_data = data
                break

    if not baseline_data or not repograph_data:
        print(f"Data not found for {instance_id}")
        return

    baseline_traj = baseline_data.get('edit_loc_traj', {})
    repograph_traj = repograph_data.get('edit_loc_traj', {})

    baseline_prompt = baseline_traj.get('prompt', '')
    repograph_prompt = repograph_traj.get('prompt', '')

    print(f"\n{'='*80}")
    print(f"Instance: {instance_id}")
    print(f"{'='*80}")

    # Find sections
    baseline_sections = {}
    repograph_sections = {}

    def extract_sections(prompt):
        sections = {}
        lines = prompt.split('\n')
        current_section = None
        section_content = []

        for line in lines:
            if line.startswith('###'):
                if current_section:
                    sections[current_section] = '\n'.join(section_content)
                current_section = line.strip()
                section_content = []
            else:
                section_content.append(line)

        if current_section:
            sections[current_section] = '\n'.join(section_content)

        return sections

    baseline_sections = extract_sections(baseline_prompt)
    repograph_sections = extract_sections(repograph_prompt)

    print(f"\n### Sections in Baseline ###")
    for section_name in baseline_sections.keys():
        section_len = len(baseline_sections[section_name])
        print(f"  {section_name}: {section_len} chars")

    print(f"\n### Sections in Repograph ###")
    for section_name in repograph_sections.keys():
        section_len = len(repograph_sections[section_name])
        print(f"  {section_name}: {section_len} chars")

    # Find unique sections
    baseline_only = set(baseline_sections.keys()) - set(repograph_sections.keys())
    repograph_only = set(repograph_sections.keys()) - set(baseline_sections.keys())

    if baseline_only:
        print(f"\n### Sections only in Baseline ###")
        for section in baseline_only:
            print(f"  {section}")

    if repograph_only:
        print(f"\n### Sections only in Repograph ###")
        for section in repograph_only:
            print(f"  {section}")
            # Show content preview
            content = repograph_sections[section]
            print(f"    Content preview: {content[:500]}...")

    # Compare common sections
    print(f"\n### Size differences in common sections ###")
    common = set(baseline_sections.keys()) & set(repograph_sections.keys())
    for section in sorted(common):
        baseline_len = len(baseline_sections[section])
        repograph_len = len(repograph_sections[section])
        diff = repograph_len - baseline_len
        if diff != 0:
            print(f"  {section}:")
            print(f"    Baseline:  {baseline_len} chars")
            print(f"    Repograph: {repograph_len} chars")
            print(f"    Diff:      {diff:+d} chars")

    # Show full prompt structure
    print(f"\n### Full prompt comparison ###")
    print(f"Baseline total: {len(baseline_prompt)} chars")
    print(f"Repograph total: {len(repograph_prompt)} chars")
    print(f"Difference: {len(repograph_prompt) - len(baseline_prompt):+d} chars")

def main():
    baseline_file = 'results/localization_baseline_new2/loc_outputs.jsonl'
    repograph_file = 'results/localization_repograph_new/loc_outputs.jsonl'

    # Analyze worst case
    instance_id = 'django__django-11815'
    compare_prompts(instance_id, baseline_file, repograph_file)

if __name__ == '__main__':
    main()
