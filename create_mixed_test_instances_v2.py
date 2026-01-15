#!/usr/bin/env python3
"""
Create a mixed test instance file with at least 2 per project
"""

import json
import os

def load_verified_setup_map():
    """Load verified_setup_map.json"""
    with open('setup_result/verified_setup_map.json', 'r') as f:
        return json.load(f)

def main():
    verified_map = load_verified_setup_map()
    
    # Collect instances by project that have graph files
    from collections import defaultdict
    by_project = defaultdict(list)
    
    graph_cache_dir = "RepoGraph_cache"
    for instance_id in verified_map.keys():
        graph_file = os.path.join(graph_cache_dir, f"tags_{instance_id}.json")
        if os.path.exists(graph_file):
            project = instance_id.split('__')[0]
            size_mb = os.path.getsize(graph_file) / (1024 * 1024)
            by_project[project].append((instance_id, size_mb))
    
    # Select at least 2 instances per project (or all if fewer than 2)
    selected = []
    
    for project in sorted(by_project.keys()):
        instances = sorted(by_project[project], key=lambda x: x[1])
        
        # Determine how many to select
        if len(instances) == 1:
            # Only 1 available, take it
            num_to_select = 1
        elif project in ['django', 'matplotlib', 'scikit-learn', 'astropy', 'sphinx-doc']:
            # Main projects: take at least 2-3
            if project == 'django':
                num_to_select = 6  # Django has 43, so take 6
            elif project == 'matplotlib':
                num_to_select = min(3, len(instances))  # Has 7
            elif project == 'scikit-learn':
                num_to_select = min(3, len(instances))  # Has 9
            elif project == 'astropy':
                num_to_select = min(2, len(instances))  # Has 4
            elif project == 'sphinx-doc':
                num_to_select = min(2, len(instances))  # Has 3
            else:
                num_to_select = 2
        else:
            # Other projects: take 2 if available
            num_to_select = min(2, len(instances))
        
        # Select evenly distributed instances
        if num_to_select == 1:
            selected.append(instances[0][0])
        elif num_to_select >= len(instances):
            # Take all
            selected.extend([inst[0] for inst in instances])
        else:
            # Take evenly distributed
            step = max(1, len(instances) // num_to_select)
            selected.extend([instances[i][0] for i in range(0, len(instances), step)[:num_to_select]])
    
    # Sort for consistency
    selected = sorted(list(set(selected)))
    
    # Write to file
    output_file = 'instances/test_instances_mixed_phase1_v2.txt'
    os.makedirs('instances', exist_ok=True)
    
    with open(output_file, 'w') as f:
        for instance in selected:
            f.write(instance + '\n')
    
    # Print summary
    print("="*80)
    print("MIXED TEST INSTANCE SET V2 (At least 2 per project)")
    print("="*80)
    print(f"\nFile: {output_file}")
    print(f"Total instances: {len(selected)}\n")
    
    from collections import Counter
    projects = Counter(inst.split('__')[0] for inst in selected)
    
    for project in sorted(projects.keys()):
        count = projects[project]
        print(f"[{project}] {count} instances")
        # Show instances from this project with sizes
        proj_instances = sorted([inst for inst in selected if inst.split('__')[0] == project])
        for inst in proj_instances:
            size_mb = os.path.getsize(os.path.join(graph_cache_dir, f"tags_{inst}.json")) / (1024 * 1024)
            print(f"  - {inst} ({size_mb:.1f}MB)")
    
    print(f"\n" + "="*80)
    print(f"Total: {len(selected)} instances")
    total_size = sum(os.path.getsize(os.path.join(graph_cache_dir, f"tags_{inst}.json")) 
                     for inst in selected) / (1024 * 1024)
    print(f"Total graph size: {total_size:.1f} MB")
    print("="*80)

if __name__ == '__main__':
    main()
