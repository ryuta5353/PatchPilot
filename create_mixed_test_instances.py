#!/usr/bin/env python3
"""
Create a mixed test instance file from common instances
Select a few from each project for balanced testing
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
    
    # Select instances: balanced selection from each project
    selected = []
    
    # Django: 5 instances
    if 'django' in by_project:
        instances = sorted(by_project['django'], key=lambda x: x[1])
        selected.extend([inst[0] for inst in instances[::len(instances)//5][:5]])
    
    # Matplotlib: 2 instances
    if 'matplotlib' in by_project:
        instances = sorted(by_project['matplotlib'], key=lambda x: x[1])
        selected.extend([inst[0] for inst in instances[::2][:2]])
    
    # Scikit-learn: 2 instances
    if 'scikit-learn' in by_project:
        instances = sorted(by_project['scikit-learn'], key=lambda x: x[1])
        selected.extend([inst[0] for inst in instances[::3][:2]])
    
    # Astropy: 1 instance
    if 'astropy' in by_project:
        instances = by_project['astropy']
        selected.append(instances[0][0])
    
    # Sphinx-doc: 1 instance
    if 'sphinx-doc' in by_project:
        instances = by_project['sphinx-doc']
        selected.append(instances[0][0])
    
    # Pytest-dev: 1 instance
    if 'pytest-dev' in by_project:
        instances = by_project['pytest-dev']
        selected.append(instances[0][0])
    
    # Scikit-learn extra: 1 more
    if 'scikit-learn' in by_project:
        instances = sorted(by_project['scikit-learn'], key=lambda x: x[1])
        if len(instances) > 2:
            selected.append(instances[-1][0])
    
    # Sort for consistency
    selected = sorted(list(set(selected)))
    
    # Write to file
    output_file = 'instances/test_instances_mixed_phase1.txt'
    os.makedirs('instances', exist_ok=True)
    
    with open(output_file, 'w') as f:
        for instance in selected:
            f.write(instance + '\n')
    
    # Print summary
    print("="*80)
    print("MIXED TEST INSTANCE SET CREATED")
    print("="*80)
    print(f"\nFile: {output_file}")
    print(f"Total instances: {len(selected)}\n")
    
    from collections import Counter
    projects = Counter(inst.split('__')[0] for inst in selected)
    
    for project in sorted(projects.keys()):
        count = projects[project]
        print(f"  {project}: {count}")
        # Show instances from this project
        proj_instances = [inst for inst in selected if inst.split('__')[0] == project]
        for inst in proj_instances:
            size_mb = os.path.getsize(os.path.join(graph_cache_dir, f"tags_{inst}.json")) / (1024 * 1024)
            print(f"    - {inst} ({size_mb:.1f}MB)")
    
    print("\n" + "="*80)
    print("Ready for reproduce -> localization pipeline")
    print("="*80)

if __name__ == '__main__':
    main()
