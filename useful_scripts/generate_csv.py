import json
import pandas as pd
import os

# Simulating file loading, replace this with actual file loading logic
def load_json(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

# Placeholder for the json file names
json_files = [f'agentless.results_30_diverse_output_{i}_processed.json' for i in range(10)]

# Dictionary to hold data for each file
resolved_ids_per_round = {}

# List of specific instance_ids to include in the DataFrame
specific_instance_ids = [
    "django__django-11422", "django__django-14999", "django__django-15388",
    "django__django-11964", "matplotlib__matplotlib-25311", "sympy__sympy-18189",
    "sphinx-doc__sphinx-11445", "django__django-13933", "sympy__sympy-24102",
    "django__django-13028", "sympy__sympy-21612", "sympy__sympy-20590",
    "pytest-dev__pytest-5413", "pytest-dev__pytest-7490", "pallets__flask-4992",
    "matplotlib__matplotlib-24970", "pytest-dev__pytest-6116", "django__django-14730",
    "pallets__flask-5063", "django__django-12113", "django__django-14855",
    "matplotlib__matplotlib-25498", "django__django-14672", "django__django-12453",
    "matplotlib__matplotlib-23964", "django__django-12700", "sympy__sympy-15609",
    "sympy__sympy-18087", "django__django-16910", "pylint-dev__pylint-7080"
]

# Load the JSON data from each file and collect the resolved_ids
for i, file_name in enumerate(json_files):
    # Assuming load_json() is the function to load your JSON data
    data = load_json(file_name)
    resolved_ids = data.get('resolved_ids', [])
    
    # Collect only the ids that are in the specific instance_ids list
    filtered_ids = [id for id in resolved_ids if id in specific_instance_ids]
    
    # Store the filtered ids for this round
    resolved_ids_per_round[i] = set(filtered_ids)

# Initialize the DataFrame with the specific_instance_ids as the index
df = pd.DataFrame(index=specific_instance_ids)

# Populate the DataFrame
for i in range(10):
    df[i] = [1 if id in resolved_ids_per_round[i] else 0 for id in specific_instance_ids]

# Load final_patch_res_10_functionality.json and get the "resolved_ids"
final_patch_file = 'patchingagent.results_30_diverse_final.json'
final_patch_data = load_json(final_patch_file)
final_patch_ids = set(final_patch_data.get('resolved_ids', []))

# Add the 'final_patch' column, marking only for ids already in the dataframe
df['final_patch'] = [1 if id in final_patch_ids else 0 for id in specific_instance_ids]

# Save the dataframe as a CSV
csv_output_path = 'resolved_ids_with_final_patch_specific_instances_diverse.csv'
df.to_csv(csv_output_path)

print(csv_output_path)
