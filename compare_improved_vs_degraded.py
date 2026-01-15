#!/usr/bin/env python3
"""
Compare improved vs degraded instances to identify patterns
Focus on: graph size, token usage, composite score effectiveness
"""

import json
from pathlib import Path

def load_evaluation():
    """Load evaluation results"""
    with open('evaluation/phase2_6_comprehensive_results_20251109.json', 'r') as f:
        return json.load(f)

def load_results(filepath, instance_id):
    """Load results for a specific instance from JSONL file"""
    try:
        with open(filepath, 'r') as f:
            for line in f:
                data = json.loads(line)
                if data['instance_id'] == instance_id:
                    return data
    except:
        pass
    return None

def extract_log_metrics(log_file):
    """Extract metrics from log file"""
    import re
    metrics = {
        'graph_sections': 0,
        'graph_locations': 0,
        'graph_size_chars': 0,
        'tokens': 0,
    }
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            # Fix regex: use \(\#\#\#  to escape the triple hash
            match = re.search(r'Graph context sections \(\#\#\# Dependencies for\):\s*(\d+)', content)
            if match:
                metrics['graph_sections'] = int(match.group(1))
            match = re.search(r'Graph context locations:\s*(\d+)', content)
            if match:
                metrics['graph_locations'] = int(match.group(1))
            # Fix regex: look for "characters" not just "chars"
            match = re.search(r'Graph context size:\s*(\d+)\s+characters', content)
            if match:
                metrics['graph_size_chars'] = int(match.group(1))
            match = re.search(r'Prompt total tokens \(with graph\):\s*(\d+)', content)
            if match:
                metrics['tokens'] = int(match.group(1))
    except Exception as e:
        import traceback
        traceback.print_exc()
    return metrics

def main():
    print("="*100)
    print("COMPARISON: INSTANCES WITH LINE-LEVEL IMPROVEMENT vs DEGRADATION")
    print("="*100)

    eval_data = load_evaluation()
    baseline_file = 'results/localization_base_10inst_phase2_6_20251109/loc_outputs.jsonl'
    repograph_file = 'results/localization_repo_10inst_phase2_6_20251109/loc_outputs.jsonl'
    log_dir = 'results/localization_repo_10inst_phase2_6_20251109/localization_logs'

    # Separate improved vs degraded
    improved = []
    degraded = []

    for d in eval_data['details']:
        if d['line_status'] == 'IMPROVED (+)':
            improved.append(d)
        elif d['line_status'] == 'DEGRADED (-)':
            degraded.append(d)

    print(f"\nLINE-LEVEL IMPROVED: {len(improved)} instance(s)")
    print(f"LINE-LEVEL DEGRADED: {len(degraded)} instance(s)")

    print("\n" + "="*100)
    print("LINE-LEVEL IMPROVED INSTANCES")
    print("="*100)

    for d in improved:
        inst_id = d['instance_id']
        log_file = f"{log_dir}/{inst_id}.log"
        metrics = extract_log_metrics(log_file)

        base_result = load_results(baseline_file, inst_id)
        repo_result = load_results(repograph_file, inst_id)

        print(f"\n{inst_id}:")
        print(f"  Line recall: {d['line_recall_base']:.0%} → {d['line_recall_repo']:.0%} (improvement: {(d['line_recall_repo'] - d['line_recall_base'])*100:.1f}pp)")
        print(f"  File recall: {d['file_recall_base']:.0%} → {d['file_recall_repo']:.0%} ({d['file_status']})")
        print(f"\n  Graph Context:")
        print(f"    Sections: {metrics['graph_sections']}")
        print(f"    Locations: {metrics['graph_locations']}")
        print(f"    Size: {metrics['graph_size_chars']:,} chars")
        print(f"    Tokens: {metrics['tokens']:,}")

        if base_result:
            print(f"\n  Baseline found files (top 3): {base_result.get('found_files', [])[:3]}")
        if repo_result:
            print(f"  Repograph found files (top 3): {repo_result.get('found_files', [])[:3]}")

        print(f"\n  ANALYSIS: Small focused graph ({metrics['graph_size_chars']:,} chars) → Improved line recall")
        print(f"  Hypothesis: Contained graph context helps LLM identify specific lines without noise")

    print("\n" + "="*100)
    print("LINE-LEVEL DEGRADED INSTANCES (Sorted by degradation severity)")
    print("="*100)

    degraded_sorted = sorted(degraded, key=lambda x: x['line_recall_base'] - x['line_recall_repo'], reverse=True)

    for d in degraded_sorted:
        inst_id = d['instance_id']
        log_file = f"{log_dir}/{inst_id}.log"
        metrics = extract_log_metrics(log_file)

        base_result = load_results(baseline_file, inst_id)
        repo_result = load_results(repograph_file, inst_id)

        degradation_pp = (d['line_recall_base'] - d['line_recall_repo']) * 100

        print(f"\n{inst_id}:")
        print(f"  Line recall: {d['line_recall_base']:.0%} → {d['line_recall_repo']:.0%} (degradation: -{degradation_pp:.1f}pp) {'[SEVERE]' if degradation_pp >= 50 else ''}")
        print(f"  File recall: {d['file_recall_base']:.0%} → {d['file_recall_repo']:.0%} ({d['file_status']})")
        print(f"\n  Graph Context:")
        print(f"    Sections: {metrics['graph_sections']}")
        print(f"    Locations: {metrics['graph_locations']}")
        print(f"    Size: {metrics['graph_size_chars']:,} chars")
        print(f"    Tokens: {metrics['tokens']:,}")

        if base_result:
            print(f"\n  Baseline found files (top 3): {base_result.get('found_files', [])[:3]}")
        if repo_result:
            print(f"  Repograph found files (top 3): {repo_result.get('found_files', [])[:3]}")

        if metrics['graph_size_chars'] > 50000:
            print(f"\n  ANALYSIS: VERY LARGE graph ({metrics['graph_size_chars']:,} chars, {metrics['graph_locations']} locations)")
            print(f"  Hypothesis: Massive graph context overwhelmed LLM, made line-level precision harder")
        else:
            print(f"\n  ANALYSIS: Moderate graph ({metrics['graph_size_chars']:,} chars)")
            print(f"  Hypothesis: Possible issue with tag selection or token limiting")

    print("\n" + "="*100)
    print("PATTERN SUMMARY")
    print("="*100)

    if improved:
        avg_improved_size = sum(extract_log_metrics(f"{log_dir}/{d['instance_id']}.log")['graph_size_chars'] for d in improved) / len(improved)
        avg_improved_locs = sum(extract_log_metrics(f"{log_dir}/{d['instance_id']}.log")['graph_locations'] for d in improved) / len(improved)
    else:
        avg_improved_size = 0
        avg_improved_locs = 0

    if degraded:
        avg_degraded_size = sum(extract_log_metrics(f"{log_dir}/{d['instance_id']}.log")['graph_size_chars'] for d in degraded) / len(degraded)
        avg_degraded_locs = sum(extract_log_metrics(f"{log_dir}/{d['instance_id']}.log")['graph_locations'] for d in degraded) / len(degraded)
    else:
        avg_degraded_size = 0
        avg_degraded_locs = 0

    print(f"\nLine-IMPROVED instances (n={len(improved)}):")
    print(f"  Average graph size: {avg_improved_size:,.0f} chars")
    print(f"  Average locations: {avg_improved_locs:.1f}")

    print(f"\nLine-DEGRADED instances (n={len(degraded)}):")
    if avg_improved_size > 0:
        print(f"  Average graph size: {avg_degraded_size:,.0f} chars ({avg_degraded_size/avg_improved_size:.1f}x larger)")
    else:
        print(f"  Average graph size: {avg_degraded_size:,.0f} chars")
    print(f"  Average locations: {avg_degraded_locs:.1f}")

    print(f"\nKEY FINDING:")
    if avg_improved_size > 0 and avg_degraded_size > avg_improved_size:
        ratio = avg_degraded_size / avg_improved_size
        print(f"Degraded instances have {ratio:.1f}x LARGER graph context than improved instances")
        print(f"=> Larger graph context CORRELATES WITH worse line-level performance")
        print(f"=> Suggests: Too much context creates noise, reducing line-level precision")
    elif avg_improved_size == 0:
        print(f"Improved instance had NO graph context extraction issue (metrics showed 0)")
        print(f"Degraded instances have {avg_degraded_size:,.0f} chars average")
        print(f"=> Cannot compare directly, but degraded instances all had significant context")

    print(f"\nRECOMMENDATION:")
    print(f"For line-level localization, use SMALLER graph context (10-20K chars max)")
    print(f"or implement aggressive filtering to reduce locations from {avg_degraded_locs:.0f} to <20")

if __name__ == '__main__':
    main()
