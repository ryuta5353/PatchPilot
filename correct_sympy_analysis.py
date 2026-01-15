#!/usr/bin/env python3
import os
import re
from pathlib import Path

base_dir = "results/localization_base_sympy10_20251103/localization_logs"
composite_dir = "results/localization_composite_score_sympy10_20251104/localization_logs"

print("="*140)
print("SymPy 10 - BASELINE vs COMPOSITE SCORE - CORRECTED")
print("="*140)

def get_instances_corrected(log_dir):
    data = {}
    for log_file in os.listdir(log_dir):
        if not log_file.endswith('.log'):
            continue
        instance_id = Path(log_file).stem
        full_path = os.path.join(log_dir, log_file)
        
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
            # Find the FINAL API call (最後の prompt_tokens)
            token_matches = list(re.finditer(r"'prompt_tokens':\s*(\d+)", content))
            if token_matches:
                # Get the LAST one (final API call)
                final_api_tokens = int(token_matches[-1].group(1))
            else:
                final_api_tokens = 0
            
            graph_match = re.search(r'Graph context size: (\d+) characters', content)
            graph_size = int(graph_match.group(1)) if graph_match else 0
            
            fallback = "FALLBACK TRIGGERED" in content
            
            data[instance_id] = {
                'api_tokens': final_api_tokens,
                'graph_size': graph_size,
                'fallback': fallback
            }
    return data

base_data = get_instances_corrected(base_dir)
composite_data = get_instances_corrected(composite_dir)

# Find common instances
common = set(base_data.keys()) & set(composite_data.keys())

print(f"\nBase instances: {len(base_data)}")
print(f"Composite instances: {len(composite_data)}")
print(f"Common instances: {len(common)}")

print("\n" + "="*140)
print("CORRECTED COMPARISON (Using FINAL API call)")
print("="*140)
print(f"{'Instance':<40} {'Baseline':<15} {'Composite':<15} {'Delta':<15} {'Graph Size':<15} {'% Increase':<10}")
print("-" * 140)

deltas = []
for instance in sorted(common):
    b_tokens = base_data[instance]['api_tokens']
    c_tokens = composite_data[instance]['api_tokens']
    delta = c_tokens - b_tokens
    graph_size = composite_data[instance]['graph_size']
    
    if b_tokens > 0:
        percent = (delta / b_tokens) * 100
    else:
        percent = 0
    
    deltas.append(delta)
    
    graph_mb = graph_size / 1024 / 1024
    
    print(f"{instance:<40} {b_tokens:<15,} {c_tokens:<15,} {delta:<15,} {graph_mb:<15.2f} {percent:<10.1f}%")

print("\n" + "="*140)
print("STATISTICS")
print("="*140)
print(f"Instances compared: {len(deltas)}")
print(f"Min delta: {min(deltas):,} tokens")
print(f"Max delta: {max(deltas):,} tokens")
print(f"Avg delta: {sum(deltas) // len(deltas):,} tokens")
print(f"Total delta: {sum(deltas):,} tokens")

print("\n" + "="*140)
print("GRAPH TOKEN USAGE INSIGHTS")
print("="*140)
for instance in sorted(common, key=lambda x: composite_data[x]['graph_size'], reverse=True)[:3]:
    c_tokens = composite_data[instance]['api_tokens']
    b_tokens = base_data[instance]['api_tokens']
    graph_size = composite_data[instance]['graph_size']
    
    # Estimate graph tokens (3 chars per token)
    est_graph_tokens = graph_size // 3
    actual_graph_tokens = c_tokens - b_tokens
    
    print(f"\n{instance}:")
    print(f"  Graph context size: {graph_size:,} chars ({graph_size/1024/1024:.2f} MB)")
    print(f"  Baseline tokens: {b_tokens:,}")
    print(f"  Composite tokens: {c_tokens:,}")
    print(f"  **Actual graph tokens in API: {actual_graph_tokens:,}**")
    print(f"  Est. from chars (3 chars/token): {est_graph_tokens:,}")

