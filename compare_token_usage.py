#!/usr/bin/env python3
"""
Compare token usage between Baseline and RepoGraph
Calculate actual graph context token consumption
"""

import os
import re
import json
from collections import defaultdict
from pathlib import Path

def extract_all_api_tokens(log_file):
    """
    Extract all prompt tokens from API responses in log
    Returns list of token counts
    """
    tokens = []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # Find all API response JSON patterns with prompt_tokens
            # Pattern: 'prompt_tokens': NNNN within usage dictionary
            matches = re.findall(r"'prompt_tokens':\s*(\d+)", content)
            tokens = [int(m) for m in matches]
                
    except Exception as e:
        print(f"Error reading {log_file}: {e}")
    
    return tokens

def main():
    baseline_dir = "results/localization_baseline_phase1/localization_logs"
    repograph_dir = "results/localization_repograph_phase1/localization_logs"
    
    # Load baseline and repograph results
    baseline_results = {}
    repograph_results = {}
    
    print("="*120)
    print("TOKEN COMPARISON: BASELINE vs REPOGRAPH (Phase 1)")
    print("="*120)
    
    # Load baseline
    if os.path.exists(baseline_dir):
        for log_file in sorted(os.listdir(baseline_dir)):
            if log_file.endswith('.log'):
                tokens = extract_all_api_tokens(os.path.join(baseline_dir, log_file))
                instance_id = Path(log_file).stem
                baseline_results[instance_id] = tokens
    
    # Load repograph
    if os.path.exists(repograph_dir):
        for log_file in sorted(os.listdir(repograph_dir)):
            if log_file.endswith('.log'):
                tokens = extract_all_api_tokens(os.path.join(repograph_dir, log_file))
                instance_id = Path(log_file).stem
                repograph_results[instance_id] = tokens
    
    print(f"\nBaseline instances with API calls: {len([k for k,v in baseline_results.items() if v])}")
    print(f"RepoGraph instances with API calls: {len([k for k,v in repograph_results.items() if v])}")
    
    # Find common instances
    common_instances = set(baseline_results.keys()) & set(repograph_results.keys())
    print(f"Common instances: {len(common_instances)}")
    
    print("\n" + "="*120)
    print("DETAILED COMPARISON (First API call)")
    print("="*120)
    print(f"{'Instance':<40} {'Baseline':<15} {'RepoGraph':<15} {'Graph Delta':<15} {'Delta %':<10}")
    print("-" * 120)
    
    graph_tokens_all = []
    
    for instance_id in sorted(common_instances):
        baseline_tokens = baseline_results[instance_id]
        repograph_tokens = repograph_results[instance_id]
        
        # Compare first API call (localization request)
        if baseline_tokens and repograph_tokens:
            b_first = baseline_tokens[0]  # First API call
            r_first = repograph_tokens[0]  # First API call
            
            graph_delta = r_first - b_first
            graph_tokens_all.append(graph_delta)
            
            if b_first > 0:
                delta_percent = (graph_delta / b_first) * 100
            else:
                delta_percent = 0
            
            print(f"{instance_id:<40} {b_first:<15,} {r_first:<15,} {graph_delta:<15,} {delta_percent:<10.1f}%")
    
    # Statistics
    if graph_tokens_all:
        print("\n" + "="*120)
        print("GRAPH TOKEN STATISTICS (Token delta: RepoGraph - Baseline)")
        print("="*120)
        print(f"Instances compared: {len(graph_tokens_all)}")
        print(f"Min graph tokens added: {min(graph_tokens_all):,}")
        print(f"Max graph tokens added: {max(graph_tokens_all):,}")
        print(f"Avg graph tokens added: {sum(graph_tokens_all) // len(graph_tokens_all):,}")
        print(f"Total graph tokens (all instances): {sum(graph_tokens_all):,}")
        
        # Calculate percentiles
        sorted_tokens = sorted(graph_tokens_all)
        median = sorted_tokens[len(sorted_tokens) // 2]
        p75 = sorted_tokens[int(len(sorted_tokens) * 0.75)]
        p90 = sorted_tokens[int(len(sorted_tokens) * 0.9)]
        print(f"Median graph tokens: {median:,}")
        print(f"75th percentile: {p75:,}")
        print(f"90th percentile: {p90:,}")
        
        # Recommendation
        print("\n" + "="*120)
        print("PHASE 2-6 RECOMMENDATION")
        print("="*120)
        avg_graph_tokens = sum(graph_tokens_all) // len(graph_tokens_all)
        max_graph_tokens = max(graph_tokens_all)
        
        # Safe limits with different margins
        safe_limit_80 = int(max_graph_tokens * 0.8)
        safe_limit_60 = int(max_graph_tokens * 0.6)
        safe_limit_p90 = int(p90 * 1.2)
        
        print(f"\nAverage graph tokens: {avg_graph_tokens:,} tokens")
        print(f"Maximum graph tokens: {max_graph_tokens:,} tokens")
        print(f"90th percentile: {p90:,} tokens")
        
        print(f"\nRecommended max_tokens_for_graph:")
        print(f"  Conservative (80% of max): {safe_limit_80:,} tokens")
        print(f"  Balanced (p90 * 1.2): {safe_limit_p90:,} tokens")
        print(f"  Aggressive (60% of max): {safe_limit_60:,} tokens")

if __name__ == '__main__':
    main()
