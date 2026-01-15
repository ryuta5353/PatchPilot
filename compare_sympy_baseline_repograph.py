#!/usr/bin/env python3
import os
import re
from pathlib import Path

base_dir = "results/localization_base_sympy10_20251103/localization_logs"
composite_dir = "results/localization_composite_score_sympy10_20251104/localization_logs"

print("="*140)
print("SymPy 10 - BASELINE vs COMPOSITE SCORE comparison")
print("="*140)

# Extract all instances and tokens
def get_instances(log_dir):
    data = {}
    for log_file in os.listdir(log_dir):
        if not log_file.endswith('.log'):
            continue
        instance_id = Path(log_file).stem
        full_path = os.path.join(log_dir, log_file)
        
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
            token_matches = re.findall(r"'prompt_tokens':\s*(\d+)", content)
            api_tokens = int(token_matches[0]) if token_matches else 0
            
            graph_match = re.search(r'Graph context size: (\d+) characters', content)
            graph_size = int(graph_match.group(1)) if graph_match else 0
            
            fallback = "FALLBACK TRIGGERED" in content
            
            data[instance_id] = {
                'api_tokens': api_tokens,
                'graph_size': graph_size,
                'fallback': fallback
            }
    return data

base_data = get_instances(base_dir)
composite_data = get_instances(composite_dir)

# Find common instances
common = set(base_data.keys()) & set(composite_data.keys())

print(f"\nBase instances: {len(base_data)}")
print(f"Composite instances: {len(composite_data)}")
print(f"Common instances: {len(common)}")

print("\n" + "="*140)
print("DETAILED COMPARISON (First API call tokens)")
print("="*140)
print(f"{'Instance':<40} {'Baseline':<15} {'Composite':<15} {'Delta':<15} {'Graph Size':<15} {'Fallback?':<10}")
print("-" * 140)

deltas = []
for instance in sorted(common):
    b_tokens = base_data[instance]['api_tokens']
    c_tokens = composite_data[instance]['api_tokens']
    delta = c_tokens - b_tokens
    graph_size = composite_data[instance]['graph_size']
    fallback = composite_data[instance]['fallback']
    
    deltas.append(delta)
    
    graph_mb = graph_size / 1024 / 1024
    fallback_str = "YES" if fallback else "NO"
    
    print(f"{instance:<40} {b_tokens:<15,} {c_tokens:<15,} {delta:<15,} {graph_mb:<15.2f} {fallback_str:<10}")

print("\n" + "="*140)
print("STATISTICS")
print("="*140)
print(f"Instances compared: {len(deltas)}")
print(f"Min delta: {min(deltas):,} tokens")
print(f"Max delta: {max(deltas):,} tokens")
print(f"Avg delta: {sum(deltas) // len(deltas):,} tokens")
print(f"Total delta: {sum(deltas):,} tokens")

# Find instances with positive delta and graph
good_instances = []
for instance in sorted(common):
    delta = composite_data[instance]['api_tokens'] - base_data[instance]['api_tokens']
    graph_size = composite_data[instance]['graph_size']
    fallback = composite_data[instance]['fallback']
    
    if delta > 100 and not fallback and graph_size > 0:
        good_instances.append((instance, graph_size, delta))

if good_instances:
    print("\n" + "="*140)
    print("INSTANCES WITH MEANINGFUL GRAPH DELTA (>100 tokens) AND NO FALLBACK")
    print("="*140)
    for instance, graph_size, delta in sorted(good_instances, key=lambda x: x[1], reverse=True):
        print(f"{instance:<40} Graph: {graph_size:,} chars ({graph_size/1024/1024:.2f}MB)  Delta: {delta:,} tokens")

