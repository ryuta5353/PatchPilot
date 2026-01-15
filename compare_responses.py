#!/usr/bin/env python3
"""Compare actual LLM responses between improved vs degraded instances."""

import json

def get_responses(instance_id, file_path):
    """Extract raw LLM responses from results file."""
    with open(file_path, 'r') as f:
        for line in f:
            data = json.loads(line)
            if data['instance_id'] == instance_id:
                traj = data.get('edit_loc_traj', {})
                responses = traj.get('response', [])
                return responses
    return None

def main():
    baseline_file = 'results/localization_baseline_new2/loc_outputs.jsonl'
    repograph_file = 'results/localization_repograph_new/loc_outputs.jsonl'

    # 改善インスタンス
    improved = [
        ('django__django-11422', 0.0, 11.1),
        ('django__django-11564', 3.3, 6.7),
        ('django__django-11742', 0.0, 17.6),
    ]

    # 悪化インスタンス
    degraded = [
        ('django__django-11815', 100.0, 0.0),
        ('django__django-11630', 50.0, 6.2),
        ('django__django-11848', 57.1, 28.6),
    ]

    print("="*80)
    print("IMPROVED INSTANCES")
    print("="*80)

    for instance_id, baseline_recall, repograph_recall in improved:
        print(f"\n[{instance_id}] ({baseline_recall:.1%} → {repograph_recall:.1%})")

        baseline_responses = get_responses(instance_id, baseline_file)
        repograph_responses = get_responses(instance_id, repograph_file)

        print(f"  Baseline responses: {len(baseline_responses) if baseline_responses else 0} samples")
        if baseline_responses:
            for i, resp in enumerate(baseline_responses[:2]):
                preview = resp[:100] if resp else "(empty)"
                print(f"    Sample {i}: {preview}...")

        print(f"  Repograph responses: {len(repograph_responses) if repograph_responses else 0} samples")
        if repograph_responses:
            for i, resp in enumerate(repograph_responses[:2]):
                preview = resp[:100] if resp else "(empty)"
                print(f"    Sample {i}: {preview}...")

    print("\n" + "="*80)
    print("DEGRADED INSTANCES")
    print("="*80)

    for instance_id, baseline_recall, repograph_recall in degraded:
        print(f"\n[{instance_id}] ({baseline_recall:.1%} → {repograph_recall:.1%})")

        baseline_responses = get_responses(instance_id, baseline_file)
        repograph_responses = get_responses(instance_id, repograph_file)

        print(f"  Baseline responses: {len(baseline_responses) if baseline_responses else 0} samples")
        if baseline_responses:
            for i, resp in enumerate(baseline_responses[:2]):
                preview = resp[:100] if resp else "(empty)"
                print(f"    Sample {i}: {preview}...")

        print(f"  Repograph responses: {len(repograph_responses) if repograph_responses else 0} samples")
        if repograph_responses:
            for i, resp in enumerate(repograph_responses[:2]):
                preview = resp[:100] if resp else "(empty)"
                print(f"    Sample {i}: {preview}...")

        # 詳細比較
        if baseline_responses and repograph_responses:
            baseline_lines = set()
            for resp in baseline_responses:
                for line in resp.split('\n'):
                    if 'line: ' in line:
                        try:
                            line_num = int(line.split('line: ')[1].strip())
                            baseline_lines.add(line_num)
                        except:
                            pass

            repograph_lines = set()
            for resp in repograph_responses:
                for line in resp.split('\n'):
                    if 'line: ' in line:
                        try:
                            line_num = int(line.split('line: ')[1].strip())
                            repograph_lines.add(line_num)
                        except:
                            pass

            print(f"\n  Line numbers extracted:")
            print(f"    Baseline: {sorted(baseline_lines)} (total: {len(baseline_lines)})")
            print(f"    Repograph: {sorted(repograph_lines)} (total: {len(repograph_lines)})")

if __name__ == '__main__':
    main()
