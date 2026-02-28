#!/usr/bin/env python3
"""
Analyze instances that might benefit from multi-hop call information.
Focus on:
1. Instances that failed in both baseline and RepoGraph
2. Instances with partial improvement (some levels still X)
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

    # Instances that failed in BOTH baseline and RepoGraph (all levels X)
    both_failed = [
        ("django__django-11964", "20inst"),
        ("django__django-13033", "20inst"),
        ("django__django-13158", "20inst"),
        ("django__django-13925", "20inst"),
        ("django__django-14580", "22inst"),
    ]

    # Instances with partial improvement (some levels still X even with RepoGraph)
    partial_improvement = [
        ("django__django-10914", "Func still X", "20inst"),
        ("django__django-11179", "Line still X", "20inst"),
        ("django__django-11815", "Func still X", "20inst"),
        ("django__django-12708", "Func still X", "20inst"),
        ("django__django-13028", "Func still X (Line improved)", "20inst"),
        ("django__django-13315", "Func still X", "20inst"),
        ("django__django-13401", "Func still X", "20inst"),
        ("django__django-13964", "Line still X (File improved)", "22inst"),
        ("django__django-15695", "File still X (Line improved)", "22inst"),
        ("django__django-15814", "Func, Line still X", "22inst"),
        ("django__django-15851", "File, Func still X", "22inst"),
    ]

    print("=" * 80)
    print("INSTANCES FAILED IN BOTH BASELINE AND REPOGRAPH")
    print("(Potential candidates for multi-hop improvement)")
    print("=" * 80)

    for iid, dataset_name in both_failed:
        if iid in gold_data:
            item = gold_data[iid]
            print(f"\n### {iid} ({dataset_name})")
            print(f"\nProblem Statement (first 1000 chars):")
            print(item['problem_statement'][:1000])
            print(f"\n--- Modified Files ---")
            patch = item['patch']
            files = re.findall(r'diff --git a/(.+?) b/', patch)
            for f in files:
                print(f"  - {f}")

            # Extract function/class context from patch
            print(f"\n--- Functions/Classes in Patch ---")
            contexts = re.findall(r'@@ .+? @@\s*(.+?)$', patch, re.MULTILINE)
            for ctx in contexts[:10]:  # Limit to first 10
                ctx = ctx.strip()
                if ctx:
                    print(f"  - {ctx}")
            print("-" * 40)

    print("\n" + "=" * 80)
    print("INSTANCES WITH PARTIAL IMPROVEMENT")
    print("(Some levels still failed - might benefit from deeper call graph)")
    print("=" * 80)

    for entry in partial_improvement:
        if len(entry) == 3:
            iid, status, dataset_name = entry
        else:
            continue

        if iid in gold_data:
            item = gold_data[iid]
            print(f"\n### {iid} ({dataset_name})")
            print(f"Status: {status}")
            print(f"\nProblem Statement (first 800 chars):")
            print(item['problem_statement'][:800])
            print(f"\n--- Modified Files ---")
            patch = item['patch']
            files = re.findall(r'diff --git a/(.+?) b/', patch)
            for f in files:
                print(f"  - {f}")

            # Extract function/class context from patch
            print(f"\n--- Functions/Classes in Patch ---")
            contexts = re.findall(r'@@ .+? @@\s*(.+?)$', patch, re.MULTILINE)
            seen = set()
            for ctx in contexts:
                ctx = ctx.strip()
                if ctx and ctx not in seen:
                    seen.add(ctx)
                    print(f"  - {ctx}")
            print("-" * 40)

if __name__ == '__main__':
    main()
