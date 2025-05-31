import os
import json

import re
import pandas as pd
import json
import sys

# get a map from instance id to real patched locations
map_id_to_patch_loc={}

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

splits = {'dev': 'data/dev-00000-of-00001.parquet', 'test': 'data/test-00000-of-00001.parquet'}
df_test = pd.read_parquet("hf://datasets/princeton-nlp/SWE-bench_Verified/" + splits["test"])
for index, row in df_test.iterrows():
    modifications = extract_diff_info(row['patch'])
    map_id_to_patch_loc[row['instance_id']]=modifications



# see what reproducer gives us
only_stdout = []
said_match = []
retry_multiple = []
one_time = []
commit_said_correct={}
commit_correct=[]
not_setup = []
not_cover_real_files = []
not_cover_real_files_covers = {}
def process_json_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            instance_id = data.get("instance_id")
            setup = data.get("result", {}).get("setup", {})
            if str(setup)=='False':
                not_setup.append(instance_id)
            if data.get("result", {}).get("oracle", {}).get("execution_output") == "":
                return
            exec_stdout = data.get("result", {}).get("oracle", {}).get("execution_output", {}).get("stdout")
            exec_stderr = data.get("result", {}).get("oracle", {}).get("execution_output", {}).get("stderr")
            if exec_stdout != "" and exec_stderr == "":
                only_stdout.append(instance_id)
            stderr_match_wrong_behavior = data.get("result", {}).get("oracle", {}).get("exec_match_wrong_behavior")
            if stderr_match_wrong_behavior == True:
                said_match.append(instance_id)
                retry_num= data.get("result", {}).get("retry",1)
                if retry_num > 1:
                    retry_multiple.append(instance_id)
                else:
                    one_time.append(instance_id)
            coverage = data.get("result", {}).get("coverage")
            if coverage and stderr_match_wrong_behavior:
                real_files =  [real_file for real_file in map_id_to_patch_loc[instance_id]]
                if_cover_correct= True
                for real_mod_file in real_files:
                    if real_mod_file not in coverage:
                        if_cover_correct= False
                        break
                if not if_cover_correct:
                    not_cover_real_files.append(instance_id)
                    not_cover_real_files_covers[instance_id]=coverage
            commit_info = data.get("result", {}).get("commit_info")
            if commit_info:
                bug_fix= commit_info.get("bug_fixed", False)
                if bug_fix:
                    commit_diff = commit_info.get("git_diff")
                    commit_diff_line_num = len(commit_diff.split("\n"))
                    commit_said_correct[instance_id]=commit_diff_line_num
                changed_files = commit_info.get("changed_files", [])
                
                real_files =  [real_file for real_file in map_id_to_patch_loc[instance_id]]
                if_commit_correct= True
                for real_mod_file in real_files:
                    if real_mod_file not in changed_files:
                        if_commit_correct= False
                        break
                if if_commit_correct:
                    commit_correct.append(instance_id)
        except json.JSONDecodeError:
            print(f"failed to parse json: {file_path}")


def traverse_directory(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                process_json_file(file_path)

if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]) or len(sys.argv) >3:
    print("Usage: python measure_repro.py <directory_path>")
    sys.exit(1)
directory_path = sys.argv[1]
 
traverse_directory(directory_path)
print("said_match number: ", len(said_match))
# print("said_match: ", said_match)
# print("retry_multiple number: ", len(retry_multiple))
# print("retry_multiple: ", retry_multiple)
# print("one_time number: ", len(one_time))
# print("one_time: ", one_time)
print("not_setup number: ", len(not_setup))
print("not_setup: ", not_setup)
# print("commit_said_correct number: ", len(commit_said_correct))
# print("commit_said_correct: ", commit_said_correct)
# print("commit_correct number: ", len(commit_correct))
# print("commit_correct: ", commit_correct)
# print("Not cover_real_files number: ", len(not_cover_real_files))
# print("Not cover_real_files: ", not_cover_real_files)
# covered_less_than_10=[]
# covered_more_than_10=[]
# no_data=[]
# for instance in not_cover_real_files_covers:
#     # print("instance", instance)
#     if "No data" in not_cover_real_files_covers[instance]:
#         no_data.append(instance)
#         # print("no data")
#         continue
#     if len(not_cover_real_files_covers[instance].splitlines()) < 10:
#         covered_less_than_10.append(instance)
#         print("===================================")
#         print("covers", not_cover_real_files_covers[instance])
#     else:
#         # print("===================================")
#         # print(instance)
#         #print("covers", not_cover_real_files_covers[instance])
#         covered_more_than_10.append(instance)
#     # print("covers", not_cover_real_files_covers[instance])
# print("covered_less_than_10 number: ", len(covered_less_than_10))
# print("covered_more_than_10 number: ", len(covered_more_than_10))
# print("covered_less_than_10: ", covered_less_than_10)
# print("no_data number: ", len(no_data))
# timeout = []
# no_data_no_timeout=[]
# for instance in no_data:
#     # print(instance)
#     # print("===================================")
#     # print("no_data: ", not_cover_real_files_covers[instance])
#     if "Timeout" in not_cover_real_files_covers[instance]:
#         timeout.append(instance)
#     else:
#         no_data_no_timeout.append(instance)
# print("no_data_no_timeout number: ", len(no_data_no_timeout))
# print("no_data_no_timeout: ", no_data_no_timeout)
# print("timeout number: ", len(timeout))
# print("timeout: ", timeout)