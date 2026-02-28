#!/usr/bin/env python3
"""Generate pkl files from RepoGraph tags for instances listed in a txt file."""

import json
import pickle
import networkx as nx
import os
import shutil
import sys

def tag_to_graph(tags):
    """Convert tags to NetworkX graph."""
    G = nx.MultiDiGraph()
    for tag in tags:
        G.add_node(tag['name'], category=tag['category'], info=tag['info'],
                   fname=tag['fname'], line=tag['line'], kind=tag['kind'])

    for tag in tags:
        if tag['category'] == 'class':
            class_funcs = tag['info'].split('\t')
            for f in class_funcs:
                if f.strip():
                    G.add_edge(tag['name'], f.strip())

    tags_ref = [tag for tag in tags if tag['kind'] == 'ref']
    tags_def = [tag for tag in tags if tag['kind'] == 'def']
    for tag in tags_ref:
        for tag_def in tags_def:
            if tag['name'] == tag_def['name']:
                G.add_edge(tag['name'], tag_def['name'])
    return G

# Read instance list from txt file
if len(sys.argv) > 1:
    instance_list_file = sys.argv[1]
else:
    instance_list_file = 'test_instances_10.txt'

print(f'Reading instances from: {instance_list_file}')

with open(instance_list_file, 'r') as f:
    instances = [line.strip() for line in f if line.strip()]

print(f'Found {len(instances)} instances')
print('=' * 80)

success_count = 0
fail_count = 0

for instance_id in instances:
    print(f'\nProcessing {instance_id}...')

    tags_file = f'RepoGraph_cache/tags_{instance_id}.json'
    pkl_file = f'cache/code_graphs/{instance_id}.pkl'
    dest_tags_file = f'cache/code_graphs/tags_{instance_id}.json'

    # Check if tags file exists
    if not os.path.exists(tags_file):
        print(f'  ✗ Tags file not found: {tags_file}')
        fail_count += 1
        continue

    try:
        # Load tags
        with open(tags_file, 'r', encoding='utf-8') as f:
            tags = json.load(f)

        # Generate graph
        G = tag_to_graph(tags)

        # Save pkl
        with open(pkl_file, 'wb') as f:
            pickle.dump(G, f)

        # Copy tags file to cache (if not already there)
        if not os.path.exists(dest_tags_file):
            shutil.copy(tags_file, dest_tags_file)

        print(f'  ✓ Generated: Nodes={len(G.nodes)}, Edges={len(G.edges)}')
        success_count += 1

    except Exception as e:
        print(f'  ✗ Error: {e}')
        fail_count += 1

print('\n' + '=' * 80)
print(f'Summary: {success_count} success, {fail_count} failed')
print('=' * 80)
print(f'PKL files created in cache/code_graphs/')
