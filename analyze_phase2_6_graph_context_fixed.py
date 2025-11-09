#!/usr/bin/env python3
"""
Analyze graph context usage for Phase 2-6 evaluation (Fixed version)
Extract: graph context size, token counts, sections, items
"""

import os
import re
from pathlib import Path

def extract_log_data(log_file):
    """Extract graph context metrics from a single log file"""
    data = {
        'instance_id': Path(log_file).stem,
        'graph_enabled': False,
        'graph_context_generated': False,
        'graph_context_size': 0,
        'graph_context_sections': 0,
        'graph_context_locations': 0,
        'prompt_tokens_with_graph': 0,
    }

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()

            # Check if graph is enabled
            if 'Repo graph enabled: True' in content or 'Graph context enabled: True' in content:
                data['graph_enabled'] = True

            # Extract graph context size
            match = re.search(r'Generated graph context:\s*(\d+)\s*characters', content)
            if match:
                data['graph_context_generated'] = True
                data['graph_context_size'] = int(match.group(1))

            # Extract graph context sections
            match = re.search(r'Graph context sections \(\#\#\# Dependencies for\):\s*(\d+)', content)
            if match:
                data['graph_context_sections'] = int(match.group(1))

            # Extract graph context locations (alternative pattern)
            match = re.search(r'Graph context items \(Dependencies for\):\s*(\d+)', content)
            if match:
                data['graph_context_sections'] = int(match.group(1))

            match = re.search(r'Graph context locations:\s*(\d+)', content)
            if match:
                data['graph_context_locations'] = int(match.group(1))

            # Extract prompt tokens
            match = re.search(r'Prompt total tokens \(with graph\):\s*(\d+)', content)
            if match:
                data['prompt_tokens_with_graph'] = int(match.group(1))

    except Exception as e:
        print(f"Error reading {log_file}: {e}")

    return data

def analyze_directory(log_dir):
    """Analyze all logs in a directory"""
    results = []

    if not os.path.exists(log_dir):
        print(f"Directory not found: {log_dir}")
        return results

    for log_file in sorted(os.listdir(log_dir)):
        if log_file.endswith('.log'):
            full_path = os.path.join(log_dir, log_file)
            data = extract_log_data(full_path)
            results.append(data)

    return results

def main():
    print("Phase 2-6 Graph Context Usage Analysis (Fixed)")
    print("="*80)

    # Phase 2-6 Repograph logs
    log_dir = 'results/localization_repo_10inst_phase2_6_20251109/localization_logs'
    results = analyze_directory(log_dir)

    if not results:
        print("No logs found.")
        return

    # Analyze results
    with_graph = [r for r in results if r['graph_enabled']]
    with_context = [r for r in results if r['graph_context_generated']]

    print("\n" + "="*80)
    print("Phase 2-6 Repograph (with Greedy Dynamic Token Allocation)")
    print("="*80)

    print(f"\nTotal instances analyzed: {len(results)}")
    print(f"With graph enabled: {len(with_graph)} ({len(with_graph)/len(results)*100:.1f}%)")
    print(f"With graph context generated: {len(with_context)} ({len(with_context)/len(results)*100:.1f}%)")

    if with_context:
        print(f"\nGraph Context Metrics (for {len(with_context)} instances with context):")

        sizes = [r['graph_context_size'] for r in with_context if r['graph_context_size'] > 0]
        if sizes:
            print(f"  Context Size (characters):")
            print(f"    Min:   {min(sizes):,}")
            print(f"    Max:   {max(sizes):,}")
            print(f"    Avg:   {sum(sizes) // len(sizes):,}")
            print(f"    Total: {sum(sizes):,}")

        tokens = [r['prompt_tokens_with_graph'] for r in with_context if r['prompt_tokens_with_graph'] > 0]
        if tokens:
            print(f"  Prompt Tokens (with graph):")
            print(f"    Min:   {min(tokens):,} tokens")
            print(f"    Max:   {max(tokens):,} tokens")
            print(f"    Avg:   {sum(tokens) // len(tokens):,} tokens")
            budget_used = sum(tokens) / len(tokens) / 30740 * 100
            print(f"    Avg utilization: {budget_used:.1f}% of 30740 token budget")

        sections = [r['graph_context_sections'] for r in with_context if r['graph_context_sections'] > 0]
        if sections:
            print(f"  Graph Context Sections:")
            print(f"    Min:   {min(sections)}")
            print(f"    Max:   {max(sections)}")
            print(f"    Avg:   {sum(sections) / len(sections):.1f}")
            print(f"    Total: {sum(sections)}")

    # Detailed table
    print(f"\nDetailed Results (sorted by token usage):")
    print(f"{'Instance':<40} {'Enabled':<10} {'Context':<10} {'Tokens':<10} {'Sections':<10}")
    print("-" * 80)

    for r in sorted(with_context, key=lambda x: x['prompt_tokens_with_graph'], reverse=True):
        print(f"{r['instance_id']:<40} {'YES':<10} {r['graph_context_size']:,<10} {r['prompt_tokens_with_graph']:<10} {r['graph_context_sections']:<10}")

    # Summary for instances without graph
    without_graph = [r for r in results if not r['graph_enabled']]
    if without_graph:
        print(f"\nInstances without graph context ({len(without_graph)}):")
        for r in sorted(without_graph, key=lambda x: x['instance_id']):
            print(f"  {r['instance_id']}")

    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)
    print(f"✓ Graph context generation rate: {len(with_context)}/{len(results)} ({len(with_context)/len(results)*100:.1f}%)")
    if with_context:
        avg_tokens = sum(t['prompt_tokens_with_graph'] for t in with_context if t['prompt_tokens_with_graph'] > 0) / len([t for t in with_context if t['prompt_tokens_with_graph'] > 0])
        print(f"✓ Average token usage per instance: {avg_tokens:.0f} tokens")
        print(f"✓ Average token budget utilization: {avg_tokens / 30740 * 100:.1f}%")

if __name__ == '__main__':
    main()
