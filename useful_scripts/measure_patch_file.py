import re
import pandas as pd
import json
import libcst as cst

map_id_to_patch_loc = {}


def extract_diff_info(diff_text):
    file_changes = {}
    file_diff_pattern = re.compile(r'(diff --git a/(.*?) b/.*?)((?=diff --git a/)|\Z)', re.DOTALL)
    for file_diff in file_diff_pattern.finditer(diff_text):
        full_diff = file_diff.group(1)
        file_name = file_diff.group(2)

        line_changes = []
        line_num_pattern = re.compile(r'@@ -\d+,\d+ \+(\d+),(\d+) @@')
        for match in line_num_pattern.finditer(full_diff):
            start_line = int(match.group(1))
            line_changes.append(start_line)

        file_changes[file_name] = line_changes

    return file_changes


# get a map from instance id to real patched locations
splits = {'dev': 'data/dev-00000-of-00001.parquet', 'test': 'data/test-00000-of-00001.parquet'}
df_test = pd.read_parquet("hf://datasets/princeton-nlp/SWE-bench_Lite/" + splits["test"])
# print(df_test.head())
for index, row in df_test.iterrows():
    # print(f'now processing {index}')
    # print(row['instance_id'])
    # print(row['patch'])
    modifications = extract_diff_info(row['patch'])
    map_id_to_patch_loc[row['instance_id']] = modifications
    # for file, changes in modifications.items():
    #     print(f"File Name: {file}")
    #     print(f"Line Changes: {changes}")

instance_patch_file_incorrect = []
with open("86.jsonl", 'r') as f:
    for line in f:
        data = json.loads(line)
        instance_id = data['instance_id']
        model_patch = data['model_patch']
        if instance_id not in map_id_to_patch_loc:
            instance_patch_file_incorrect.append(instance_id)
            continue
        for file in map_id_to_patch_loc[instance_id]:
            if file not in model_patch:
                instance_patch_file_incorrect.append(instance_id)
                continue
print(len(instance_patch_file_incorrect))
print(instance_patch_file_incorrect)


