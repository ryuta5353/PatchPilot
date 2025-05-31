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
    modifications = extract_diff_info(row['patch'])
    map_id_to_patch_loc[row['instance_id']] = modifications

instances_retrieve_files_incomplete = []
instances_lineno_incomplete = []
has_search_result = []
aaanum = 0

loc_res_file = input("Enter the location of the loc_outputs.jsonl file: ")
# parse the log of agentless to find retrieved locations
with open(loc_res_file, 'r',
          encoding='utf-8') as file:
    for line in file:
        aaanum = aaanum + 1
        print(aaanum)
        data = json.loads(line)
        instance_id = data['instance_id']
        file_line_dict = {}
        retrieved_files = data['found_files'][:5]
        # search_result = data["search_result"]
        # if search_result:
        #     has_search_result.append(instance_id)
        print(retrieved_files)

        for edit_locs_set in data['found_edit_locs']:
            for index, edit_locs in enumerate(edit_locs_set):
                line_numbers = re.findall(r'line:\s*(\d+)', edit_locs[0])
                for line_num in line_numbers:
                    # map file to line numbers
                    line_num = int(line_num)
                    if data['found_files'][index] not in file_line_dict:
                        file_line_dict[data['found_files'][index]] = set()
                    for i in range(-20, 21):
                        file_line_dict[data['found_files'][index]].add(line_num + i)
                if line_numbers == [] and data['found_files'][index] not in file_line_dict:
                    # if edit_locs[0] != '':
                    file_line_dict[data['found_files'][index]] = set()

        # check whether all real patched files and linenos are included in the retrieved context
        incomplete_lineno = 0
        for real_mod_file in map_id_to_patch_loc[data['instance_id']]:
            if real_mod_file not in file_line_dict:
                instances_retrieve_files_incomplete.append(data['instance_id'])
                instances_lineno_incomplete.append(data['instance_id'])
                break

            for real_line_num in map_id_to_patch_loc[data['instance_id']][real_mod_file]:
                if real_line_num not in file_line_dict[real_mod_file]:
                    instances_lineno_incomplete.append(data['instance_id'])
                    incomplete_lineno = 1
                    break
            if incomplete_lineno == 1:
                break

print("instances_retrieve_files_incomplete: ", instances_retrieve_files_incomplete)
print(len(instances_retrieve_files_incomplete))

print("instances_lineno_incomplete: ", instances_lineno_incomplete)
print(len(instances_lineno_incomplete))
