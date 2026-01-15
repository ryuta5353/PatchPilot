#!/usr/bin/env python3
"""
RepoGraph construct_graph.py wrapper for PatchPilot

使用方法:
    python generate_graphs.py <instance_list_file> <output_dir>

例:
    python generate_graphs.py test_instances_django_43.txt cache/code_graphs
"""

import os
import sys
import json
import subprocess
from pathlib import Path

def generate_graph(repo_dir, output_dir, instance_id):
    """
    Generate graph.pkl and tags.json for a single instance
    """
    print(f"Generating graph for {instance_id}...")
    
    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Run construct_graph.py
    cmd = [sys.executable, "RepoGraph/repograph/construct_graph.py", repo_dir]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        print(result.stdout)
        
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return False
        
        # Move generated files to output directory
        graph_file = "graph.pkl"
        tags_file = "tags.json"
        
        if os.path.exists(graph_file):
            new_graph = os.path.join(output_dir, f"{instance_id}.pkl")
            os.rename(graph_file, new_graph)
            print(f"✓ Saved graph to {new_graph}")
        
        if os.path.exists(tags_file):
            new_tags = os.path.join(output_dir, f"tags_{instance_id}.json")
            os.rename(tags_file, new_tags)
            print(f"✓ Saved tags to {new_tags}")
        
        return True
        
    except subprocess.TimeoutExpired:
        print(f"Timeout for {instance_id}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    
    instance_file = sys.argv[1]
    output_dir = sys.argv[2]
    
    # Read instance list
    with open(instance_file, 'r') as f:
        instances = [line.strip() for line in f if line.strip()]
    
    print(f"Found {len(instances)} instances")
    
    # Generate graphs
    success = 0
    failed = 0
    
    for instance_id in instances:
        # Construct testbed path
        repo_dir = f"/opt/SWE-bench/testbed/{instance_id}"
        
        if not os.path.exists(repo_dir):
            print(f"✗ Testbed not found: {repo_dir}")
            failed += 1
            continue
        
        if generate_graph(repo_dir, output_dir, instance_id):
            success += 1
        else:
            failed += 1
    
    print(f"\n=== Summary ===")
    print(f"Success: {success}")
    print(f"Failed: {failed}")

if __name__ == "__main__":
    main()
