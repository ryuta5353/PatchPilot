#!/usr/bin/env python3
"""
Analyze improved/worsened instances from localization evaluation.
"""

import json
import re
import sys
import io
from datasets import load_dataset

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def main():
    # Load dataset
    print("Loading SWE-bench dataset...")
    dataset = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    gold_data = {item['instance_id']: item for item in dataset}

    # Improved instances (RepoGraph > Baseline)
    improved = [
        ("django__django-11133", "Line improved", "20inst"),
        ("django__django-11999", "All improved (File, Func, Line)", "20inst"),
        ("django__django-12125", "File improved", "20inst"),
        ("django__django-13028", "Line improved", "20inst"),
        ("django__django-13658", "Func improved", "20inst"),
        ("django__django-13964", "File improved", "22inst"),
        ("django__django-15695", "Line improved", "22inst"),
    ]

    # Worsened instances (RepoGraph < Baseline)
    worsened = [
        ("django__django-13590", "Line worsened", "20inst"),
        ("django__django-14999", "Func worsened", "22inst"),
    ]

    print("=" * 80)
    print("IMPROVED INSTANCES (RepoGraph > Baseline)")
    print("=" * 80)

    for iid, change, dataset_name in improved:
        if iid in gold_data:
            item = gold_data[iid]
            print(f"\n### {iid} ({dataset_name})")
            print(f"Change: {change}")
            print(f"\nProblem Statement (first 800 chars):")
            print(item['problem_statement'][:800])
            print(f"\n--- Modified Files ---")
            patch = item['patch']
            files = re.findall(r'diff --git a/(.+?) b/', patch)
            for f in files:
                print(f"  - {f}")
            print("-" * 40)

    print("\n" + "=" * 80)
    print("WORSENED INSTANCES (RepoGraph < Baseline)")
    print("=" * 80)

    for iid, change, dataset_name in worsened:
        if iid in gold_data:
            item = gold_data[iid]
            print(f"\n### {iid} ({dataset_name})")
            print(f"Change: {change}")
            print(f"\nProblem Statement (first 800 chars):")
            print(item['problem_statement'][:800])
            print(f"\n--- Modified Files ---")
            patch = item['patch']
            files = re.findall(r'diff --git a/(.+?) b/', patch)
            for f in files:
                print(f"  - {f}")
            print("-" * 40)

if __name__ == '__main__':
    main()
