import json
import os

fix_fail = []
func_fail = []

base_path = "/opt/orig_swebench/SWE-bench/logs/run_evaluation/final_patch/patchingagent"


for instance_id in os.listdir(base_path):

    json_path = os.path.join(base_path, instance_id, "report.json")
    if not os.path.isfile(json_path):
        continue

    with open(json_path, 'r') as f:
        data = json.load(f)

    for instance_key, instance_data in data.items():

        tests_status = instance_data.get("tests_status", {})

        pass_to_pass_failures = tests_status.get("PASS_TO_PASS", {}).get("failure", [])
        if pass_to_pass_failures:
            func_fail.append(instance_id)

        fail_to_pass_failures = tests_status.get("FAIL_TO_PASS", {}).get("failure", [])
        if fail_to_pass_failures:
            fix_fail.append(instance_id)

print("fix_fail:", fix_fail)
print(len(fix_fail))
print("func_fail:", func_fail)
print(len(func_fail))