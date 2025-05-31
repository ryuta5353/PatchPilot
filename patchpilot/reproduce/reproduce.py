import argparse
import json
import os
import concurrent.futures

from patchpilot.reproduce.task import make_swe_tasks
from patchpilot.util.utils import setup_logger, ensure_directory_exists
from patchpilot.util.model import make_model
from patchpilot.reproduce.task import parse_task_list_file


def check_existing_reproduce_ids(reproduce_path):
    instance_ids = set()

    for root, _, files in os.walk(reproduce_path):
        for file in files:
            if file.endswith('issue_parsing_report_0.json'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                    except Exception as e:
                        print(f"Error loading {file_path}: {e}")
                        return instance_ids
                if 'instance_id' in data:
                    instance_ids.add(data['instance_id'])
    return instance_ids

execution_output_template="""
Here are the stderr and stdout of the PoC you generated last time:
--- Begin Execution Output ---
{execution_output}
--- End Execution Output ---
"""

errors_template="""
### Errors ###
Here are some errors of the PoC you generated last time, please pay attention to them and do not make the same mistakes again.
--- Begin Errors ---
{reason}
--- End Errors ---
"""
last_time_poc_code_template = """
### PoC Generated Last Time ###
Here is the PoC you generated last time:
--- Begin PoC ---
{last_time_poc_code}
--- End PoC ---
"""

parse_poc_oracle_prompt = """
Please review the following GitHub issue description to determine if it contains a PoC or an oracle. If it does, return the PoC or oracle. If there is no Poc, try to generate a PoC in a single Python file that can reproduce the bug described in the issue.

Definitions:
poc (Proof of Concept): The code that triggers or demonstrates the bug. If a proposed fix is in the issue description, you should not include it in the PoC. If some code snippets of the original project are mentioned in the issue description, you should try to compose code that executes the code in the original project to trigger the bug. Do not do not create new code that independently introduce or simulate the bug behavior. The poc could be Python code, a command-line script, or another form of code. Return it as a dictionary where the key is the file name, and the value is the code.
Oracle: A criterion for determining the presence of a bug. It should include both the expected behavior and the wrong behavior, which can be described using tracebacks or descriptive sentences from the issue description.
Expected Behavior: The correct behavior that should occur when the code is executed.
Wrong Behavior: The incorrect behavior that occurs when the code is executed, indicating the presence of a bug.
Extract the expected behavior and wrong behavior directly from the issue description. Ensure that both behaviors are relevant to the PoC. If the expected behavior is not explicitly mentioned, leave it empty.
PLEASE ONLY OUTPUT THE JSON RESPONSE.
If the wrong behavior is a traceback, please output of a summarized version of the traceback, including the most critical part of error message containing the error type instead of the whole error message. 
### GitHub issue description ###
--- Begin Issue Description ---
{problem_statement}
--- End Issue Description ---

{last_time_poc_code}

{execution_output}

{reason}

Response Format:
Example 1:
{{
    "poc": {{
        "poc_code.py":"PoC code here"
    }},
    "oracle": "Oracle description here",
    "expected_behavior": "Expected behavior description here",
    "wrong_behavior": "Wrong behavior description here",
}}
Example 2:
{{
    "poc": {{
        "poc_code1.py":"PoC code part 1 here (in python)",
        "poc_code2.sh":"PoC code part 2 here (in bash)"
    }},
    "oracle": "",
    "expected_behavior": "",
    "wrong_behavior": "Wrong behavior description here",
}}
For the Poc, you should pay attention to the escape characters in the code. For example, if the code contains double quotes, you should escape them with a backslash. Ensure that the Poc can be loaded as a JSON dictionary.
"""

optimize_poc_prompt = """
The provided Raw Code is still incomplete or contains errors. Please help me process this Raw Code. It could be Python code, a command-line script, or another form of code. My goal is to receive a version of the Raw Code that can be directly executed, so please clean out any irrelevant information and return only the necessary code.
When generating a script to reproduce the issue, please use the specific classes or functions mentioned in the issue description from the original project to trigger the bug. If some code snippets of the original project are mentioned in the issue description, you should interact with the specific classes, functions, or code segments mentioned in the issue description from the original project to trigger the bug. However, do not create new code that independently introduce or simulate the bug behavior.
You tried to generate a PoC last time, but it was incomplete or contained errors. Please pay attention to the errors and try to avoid them this time.

{last_time_poc_code}

{execution_output}

{reason}

### Raw Code ###
Here is the Raw Code you need to process:
--- Begin Raw Code ---
{raw_poc_code}
--- End Raw Code ---

### GitHub issue description ###
--- Begin Issue Description ---
{problem_statement}
--- End Issue Description ---

If the raw code contains some input prompt, like $ or > in an interactive console, remove them. If the raw code contains some output, like the output of a command, remove them. 

If the Raw Code is a single Python file, we will store it as a .py file and run it using Python 3. If the provided Raw Code is already complete and executable in a python file, try not to change it. 
If the Raw Codee uses Python 2, convert it to Python 3 syntax. 
If the Raw Code uses some library functions without importing them, add the necessary import statements.
If the Raw Code is written as a Jupyter Notebook snippet or executed in a Python console, transform it into a fully runnable Python file, also add the necessary print statements to display the output. 
If only a function or a class is provided, use the parameters mentioned in the issue description to construct a valid function call. 
If the Raw Code only contains multiple python files without other types of code, you should try to merge them into a single file, add the neccesary code to ensure that the code can be executed in the correct order.
If the Raw Code is a bash script, you should turn it into a Python script.
If the raw code contains multiple files, including Python and bash, you should merge them into a single Python file, add the neccesary code to ensure that the code can be executed in the correct order.
If the raw code contains multiple files, including Python and bash, you should merge them into a single Python file, add the neccesary code to ensure that the code can be executed in the correct order, use python to create files, directory or create a subprocess to execute the bash code.

Instead of only checking whether the final result is correct and printing "BUG REPRODUCED" or "BUG ABSENT", please also print out intermediate values and critical calculation steps that are relevant to the bug to aid in debugging and understanding the failure.

Return the result in a JSON format with the following three fields:

is_complete: A boolean indicating whether the Raw Code is complete and can be executed without any missing parts.
poc_code: The executable code after processing. Return it as a dictionary where the key is the file name, and the value is the code
type: The language type of the code.

If the provided Raw Code is empty, set is_complete to false, set type to \"unknown\" and poc_code to an empty dictionary.
PLEASE ONLY OUTPUT THE JSON RESPONSE.
You should pay attention to the escape characters in the json output. For example, if the poc_code contains double quotes, you should escape them with a backslash. Ensure that the output can be loaded as a JSON dictionary.



Response Format:
Example 1:
{{
    "is_complete": true,
    "type": "python",
    "poc_code": {{
        "poc_code.py":"PoC code here"
    }}
}}
Example 2:
{{
    "is_complete": false,
    "type": "python",
    "poc_code": {{
        "poc_code.py":"PoC code here"
    }}
}}
"""

poc_for_patch_prompt = """
You should specifically generate a PoC that can bypass the patch and still trigger the bug based on the issue description.
You should first consider the corner cases that the patch fails to cover and then generate a PoC that can bypass the patch.
Here is the patch code:
--- Begin Patch Code ---
{patch_code}
--- End Patch Code ---
"""

previous_poc_prompt = """

--- Begin PoC ---
{previous_poc}
--- End PoC ---

"""

patch_context_prompt = """
Here is the related code that contains the bug
--- BEGIN CODE ---
```
{patch_context}
```
--- END CODE ---
"""

one_more_poc_prompt = """
Please generate one more PoC that can trigger a similar or related bug based on the issue description.
For example, if the patch fixes an issue with an empty string, consider whether None, an empty list, or partially empty data structures might also trigger the bug.
For example, if the bug is about an error in the addition operation, you can consider whether this bug also occurs in the subtraction, multiplication, or division operations. 
You should generate a PoC that is different from the existing PoCs.
You should consider the corner cases that the existing PoCs fail to cover. Consider complex cases such as nested structures and recursive patterns, for example, if the patch fixes an issue with an empty string, consider whether None, an empty list, or partially empty data structures might also trigger the bug.
Here are existing PoCs that can successfully trigger the bug:

--- Begin Existing PoCs ---
{previous_pocs}
--- End Existing PoCs ---

Here is the issue description:
--- Begin Issue Description ---
{problem_statement}
--- End Issue Description ---

{poc_for_patch}

{patch_context}

{last_time_poc_code}

{execution_output}

{reason}


Return the result in a JSON format with the following three fields:

is_complete: A boolean indicating whether the generated poc code is complete and can be executed without any missing parts.
poc_code: The executable code after processing. Return it as a dictionary where the key is the file name, and the value is the code
type: The language type of the code.
is_multi: A boolean indicating whether the generated poc code contains multiple files. If the generated poc code contains multiple files, set is_multi to true, otherwise set it to false.
Oracle: A criterion for determining the presence of a bug. It should include both the expected behavior and the wrong behavior, which can be described using tracebacks or descriptive sentences from the issue description.
Expected Behavior: The correct behavior that should occur when the code is executed.
Wrong Behavior: The incorrect behavior that occurs when the code is executed, indicating the presence of a bug.


Return the poc_code in json format, return it as a dictionary where the key is the file name (poc_code.py), and the value is the code. You should pay attention to the escape characters in the code. For example, if the code contains double quotes, you should escape them with a backslash. Ensure that the PoC can be loaded as a JSON dictionary.
The generated poc should be a single Python file named poc_code.py. 
PLEASE ONLY OUTPUT THE JSON RESPONSE.

Response Format:
Example 1:
{{
    "is_complete": false,
    "type": "python",
    "is_multi": false,
    "poc_code": {{
        "poc_code.py":"PoC code here"
    }}
    "oracle_description": "Oracle description here",
    "expected_behavior": "Expected behavior description here",
    "wrong_behavior": "Wrong behavior description here",
}}

Example 2:
{{
    "is_complete": false,
    "type": "python",
    "is_multi": true,
    "poc_code": {{
        "poc_code.py":"PoC code here"
    }}
    "oracle_description": "Oracle description here",
    "expected_behavior": "Expected behavior description here",
    "wrong_behavior": "Wrong behavior description here",
}}
"""

judge_execution_result_prompt = """
You are a developer assigned to investigate a bug. You've been provided with a script intended to reproduce a specific wrong behavior. However, the script may contain errors, so its output may or may not reflect the wrong behavior described in the issue. Your task is to determine whether the Script Output is related to the wrong behavior.

Task: Evaluate if the Script Output is manifests the wrong behavior described in the Raw Issue Description.

The Script Code generates the Script Output, but it may be incomplete or contain errors, which could lead to output unrelated to the wrong behavior.
The Script Output does not need to be an exact match to the wrong behavior, as long as the nature of the error aligns with the description. But it should manifest the same bug as described in the issue.
When evaluating whether a script successfully reproduces an issue, ensure that the script uses the specific classes, functions, or code segments mentioned in the issue description from the original project to trigger the bug. You should explicitly reason whether the bug lies in code in the original project or just simulated by the script independently. If the bug is simulated by the script independently, you should not consider the output as relevant to the wrong behavior and output "No".
You should not assume that there is other output that is not shown in the Script Output. The Script Output is the only output you should consider. You should not assume that a plot is generated by the script.

### Raw Issue Description ###
--- Begin Raw Issue Description ---
{issue_description}
--- End Raw Issue Description ---

### Script Code ###
--- Begin Script Code ---
{poc_code}
--- End Script Code ---

### Script Output ###
--- Begin Script Output ---
{execution_output}
--- End Script Output ---

Please analyze whether the Script Output manifests the wrong behavior, and provide your judgment along with a clear explanation of your reasoning.

Here is a sample response:
<reasoning>Some reasoning process..</reasoning>
<judgement>Yes</judgement>
"""

# the current commit should be the commit that the bug is fixed (or not even introduced, e.g., the parent of the bug introducing commit)
judge_commit_output_prompt = """
You are a developer tasked with verifying whether a bug has been addressed in a Current commit. You have been provided with the following:

- **Raw Issue Description**: A detailed description of the bug.
- **Proof of Concept (PoC) Code**: The script intended to reproduce the bug.
- **Current Commit Output**:
    - **stdout**: Standard output from running the PoC on the Current commit.
    - **stderr**: Standard error from running the PoC on the Current commit.

### Raw Issue Description ###
--- Begin Raw Issue Description ---
{issue_description}
--- End Raw Issue Description ---

### Proof of Concept (PoC) Code ###
--- Begin PoC Code ---
{poc_code}
--- End PoC Code ---

### Current Commit Output ###
--- Begin Current Commit stdout ---
{bug_parent_stdout}
--- End Current Commit stdout ---

--- Begin Current Commit stderr ---
{bug_parent_stderr}
--- End Current Commit stderr ---

**Task**: Analyze the provided information to determine the status of the bug in the current commit. Choose one of the following options and provide a clear explanation for your judgment:

1. **Bug Fixed**: The current commit's PoC output matches the expected behavior, indicating that the bug has been resolved.
2. **Bug Still Present**: The current commit's PoC output still triggers the same bug as described in the issue.
3. **Unrelated Output**: The current commit's PoC output does not relate to the issue description, for example, the output indicates that the poc tiggers a different bug.

**Sample Response 1**:
<reasoning>The stderr in the current commit still shows the same error as described in the issue, indicating that the bug has not been fixed.</reasoning>
<judgement>Bug Still Present</judgement>

**Sample Response 1**:
<reasoning>The stdout in the current commit shows that the bug has been fixed. The output matches the expected behavior described in the issue.</reasoning>
<judgement>Bug Fixed</judgement>

**Sample Response 3**:
<reasoning>The stderr in the current commit shows a different error than the one described in the issue. </reasoning>
<judgement>Unrelated Output</judgement>
"""
def clean_and_parse_json(text, default):
    start = text.find("{")
    end = text.rfind("}") + 1
    
    # Extract the JSON part
    json_text = text[start:end]
    
    # Parse the JSON
    try:
        parsed_json = json.loads(json_text)
    except json.JSONDecodeError:
        return default
        
    return parsed_json

class LLMRP:
    def __init__(
            self,
            instance_id,
            problem_statement,
            model_name,
            backend,
            logger,
    ):
        self.instance_id = instance_id
        self.problem_statement = problem_statement
        self.max_tokens = 4096
        self.model_name = model_name
        self.backend = backend
        self.logger = logger

    def clean_and_parse_json(self, text, default):
        start = text.find("{")
        end = text.rfind("}") + 1
        
        # Extract the JSON part
        json_text = text[start:end]
        
        # Parse the JSON
        try:
            parsed_json = json.loads(json_text)
        except json.JSONDecodeError:
            self.logger.error(f"Failed to parse JSON: {json_text}")
            return default
            
        return parsed_json

    def parse_issue(self, last_time_poc_code_prompt, execution_output_prompt, errors_prompt):
        message = parse_poc_oracle_prompt.format(
            problem_statement=self.problem_statement,
            last_time_poc_code=last_time_poc_code_prompt,
            execution_output=execution_output_prompt,
            reason=errors_prompt,
        ).strip()
        self.logger.info(f"prompting with message:\n{message}")
        print(f"prompting with message:\n{message}")
        self.logger.info("=" * 80)
        print("=" * 80)

        model = make_model(
            model=self.model_name,
            backend=self.backend,
            logger=self.logger,
            max_tokens=self.max_tokens,
            temperature=0,
            batch_size=1,
        )
        traj = model.codegen(message, num_samples=1)[0]
        self.logger.info(f"Got response:\n{traj}")
        traj["prompt"] = message
        raw_output = traj["response"]
        print(raw_output)
        default_result = {
            "poc": {"poc_code.py": ""},
            "oracle": "",
            "expected_behavior": "",
            "wrong_behavior": "",
        }
        result = self.clean_and_parse_json(raw_output, default_result)
        return result


def judge_commit_output(model, issue_description: str, poc_code: str, bug_parent_out: dict, logger):
    # let llm judge the output of poc in the parent commit
    # 1.the same as the expected behavior, 2. still tiggers the same bug, 3. has nothing to do with the issue description
    message = judge_commit_output_prompt.format(
        issue_description=issue_description,
        poc_code=poc_code,
        bug_parent_stdout=bug_parent_out["stdout"],
        bug_parent_stderr=bug_parent_out["stderr"],
    )

    logger.info(f"Prompting with message:\n{message}")
    traj = model.codegen(message, num_samples=1)[0]
    raw_output = traj["response"]
    logger.info(f"Generated trajectory: {traj}")
    try:
        judge_result = raw_output.split("<judgement>")[1].split("</judgement>")[0]
    except:
        logger.error(f"Failed to parse judgement: {raw_output}")
        print(f"Failed to parse judgement: {raw_output}")
    try:
        reasoning = raw_output.split("<reasoning>")[1].split("</reasoning>")[0]
    except:
        logger.error(f"Failed to parse reasoning: {raw_output}")
        print(f"Failed to parse reasoning: {raw_output}")
        reasoning = "Failed to parse reasoning"
    if "Bug Fixed" in judge_result:
        return 1, reasoning
    elif "Bug Still Present" in judge_result:
        return 2, reasoning
    elif "Unrelated Output" in judge_result: 
        return 3, reasoning
    else:
        return 3, "Failed to parse judgement"


def reproduce_instance(task, args, existing_instance_ids):
    instance_id = task.task_id
    log_file = os.path.join(
        args.reproduce_folder, "reproduce_logs", f"{instance_id}.log"
    )
    logger = setup_logger(log_file)
    logger.info(f"Processing bug {instance_id}")

    if instance_id in existing_instance_ids:
        print(f"Skip reproducing existing instance_id: {instance_id}")
        logger.info(f"Skip reproducing existing instance_id: {instance_id}")
        return

    logger.info(f"================ reproducing {instance_id} ================")
    problem_statement = task.problem_statement

    rp = LLMRP(
        instance_id,
        problem_statement,
        args.model,
        args.backend,
        logger,
    )
    retry = 0
    reason = ""
    if_match = False
    last_time_poc_code = ""
    execution_output = {}
    # Generate POC with Retry
    while not if_match and retry < 7: # what if we let it go crazy?
        print(f"Retry reprouce {retry} for instance {instance_id}")
        logger.info(f"Retry reprouce {retry} for instance {instance_id}")
        execution_output_prompt=""
        last_time_poc_code_prompt=""
        errors_prompt=""
        if last_time_poc_code:
            last_time_poc_code_prompt=last_time_poc_code_template.format(last_time_poc_code=json.dumps(last_time_poc_code, indent=4))
        if execution_output:
            execution_output_prompt=execution_output_template.format(execution_output=json.dumps(execution_output, indent=4))
        if reason:
            errors_prompt=errors_template.format(reason=reason)
        result = rp.parse_issue(last_time_poc_code_prompt, execution_output_prompt, errors_prompt)
        message = optimize_poc_prompt.format(
            raw_poc_code=json.dumps(result.get('poc', ""), indent=4),
            problem_statement=problem_statement,
            last_time_poc_code=last_time_poc_code_prompt,
            execution_output=execution_output_prompt,
            reason=errors_prompt,
        ).strip()
        rp.logger.info(f"Instance: {instance_id}, prompting with message:\n{message}")
        print(f"Instance: {instance_id}, prompting with message:\n{message}")
        rp.logger.info("=" * 80)
        print("=" * 80)

        model = make_model(
            model=rp.model_name,
            backend=rp.backend,
            logger=rp.logger,
            max_tokens=rp.max_tokens,
            temperature=0,
            batch_size=1,
        )
        traj = model.codegen(message, num_samples=1)[0]
        rp.logger.info(f"Got response:\n{traj}")
        traj["prompt"] = message
        default_poc_description = {
                "is_complete": False,
                "type": "unknown",
                "poc_code": {},
            }
        poc_description = rp.clean_and_parse_json(traj["response"], default_poc_description)       
        if len(poc_description["poc_code"]) != 1:
            poc_description["is_multi"] = True
        else:
            poc_description["is_multi"] = False
        poc_info = {
            "instance_id": instance_id,
            "result": {
                "poc": poc_description,
                "oracle": {
                    "oracle_description": result.get('oracle', ""),
                    "expected_behavior": result.get('expected_behavior', ""),
                    "wrong_behavior": result.get('wrong_behavior', ""),
                    "issue_description": problem_statement,
                    "reasoning": "",
                    "execution_output": {
                        "stdout": "",
                        "stderr": "",
                    },
                }
            }
        }
        poc_info, execution_output = execute_reproduce_instance(task, args, poc_info)
        if_match = poc_info["result"]["oracle"]["exec_match_wrong_behavior"]
        last_time_poc_code = poc_info["result"]["poc"]["poc_code"]
        reason = poc_info["result"]["oracle"]["if_match_reasoning"]
        retry += 1
    
    poc_info["result"]["retry"] = retry
    # If the poc is said to match the wrong behavior, get the coverage information (file, function, line number)
    if if_match:
        coverage = task.get_poc_coverage(poc_info)
        if coverage:
            poc_info["result"]["coverage"] = coverage
            coverage_except_test = coverage.split('\n')
            for cov in coverage_except_test:
                if 'tests' in cov:
                    del coverage_except_test[coverage_except_test.index(cov)]
            if len(coverage_except_test) < 10 and 'No data' not in coverage:
                poc_info["result"]["oracle"]["exec_match_wrong_behavior"] = False
                poc_info["result"]["oracle"]["if_match_reasoning"] = "coverage too short "
                

    # If the poc is said to match the wrong behavior, try to get the commit that introduced the bug
    if if_match:
        try_bisect_num = 0
        start_commit = task.commit
        judge = 2
        reasoning='No reasoning'
        while judge==2 and try_bisect_num < 4:
            commit_info = task.get_bug_introducing_commit_info(poc_info, start_commit, task.commit)
            try_bisect_num += 1
            if commit_info:
                bug_parent_out={"stdout":commit_info.get("parent_commit_stdout", ""), "stderr":commit_info.get("parent_commit_stderr", "")}
                print(bug_parent_out)
                judge, reasoning=judge_commit_output(model, problem_statement, last_time_poc_code, bug_parent_out, logger)
                start_commit=commit_info["parent_commit"]
            else:
                judge=3
                reasoning="We've reached the 0-th commit, but the bug is still present."
        if judge==1:
            print("The bug is fixed in commit {}".format(start_commit))
            commit_info["bug_fixed"]=True
            commit_info['try_bisect_num']=try_bisect_num
            commit_info["parent_commit_good_reasoning"]=reasoning     
            poc_info["result"]["commit_info"] = commit_info
        else:
            commit_info["bug_fixed"]=False
            commit_info['try_bisect_num']=try_bisect_num
            if reasoning:
                commit_info["parent_commit_good_reasoning"]=reasoning     
            poc_info["result"]["commit_info"] = commit_info
    
    issue_id_folder = os.path.join(args.reproduce_folder, task.task_id)
    ensure_directory_exists(issue_id_folder)
    poc_output_file = os.path.join(issue_id_folder, "issue_parsing_report_0.json")
    with open(poc_output_file, "w") as ft:
        json.dump(poc_info, ft, indent=4)
    print("execute reproducer for issue {} success! The result is in {}.".format(task.task_id, poc_output_file))


def generate_one_more_poc(task, args, patch='', patch_context='') -> bool:
    instance_id = task.task_id
    log_file = os.path.join(
        args.reproduce_folder, "reproduce_logs", f"{instance_id}.log"
    )
    logger = setup_logger(log_file)
    logger.info(f"Generating one more poc for {instance_id}")
    issue_id_folder = os.path.join(args.reproduce_folder, task.task_id)
    ensure_directory_exists(issue_id_folder)
    poc_index = 0
    existing_poc_codes = []
    while os.path.exists(os.path.join(issue_id_folder, f"issue_parsing_report_{poc_index}.json")): 
        with open(os.path.join(issue_id_folder, f"issue_parsing_report_{poc_index}.json"), "r") as f:
            poc_info = json.load(f)
        if poc_info["result"]["oracle"]["exec_match_wrong_behavior"] == False:
            print("The first PoC does not match the wrong behavior. Skip generating one more PoC.")
            return
        existing_poc_codes.append(poc_info["result"]["poc"]["poc_code"])
        poc_index += 1
    previous_poc_prompt = ""
    for poc in existing_poc_codes:
        previous_poc_prompt += previous_poc_prompt.format(previous_poc=poc)
    poc_for_patch_prompt = ''
    if patch:
        poc_for_patch_prompt = poc_for_patch_prompt.format(patch_code=patch)

    retry = 0
    if_match = False
    last_time_poc_code = ""
    execution_output = {}
    reason = ""
    while not if_match and retry < 7:
        print(f"Retry reprouce {retry} for instance {instance_id}")
        logger.info(f"Retry reprouce {retry} for instance {instance_id}")
        execution_output_prompt=""
        last_time_poc_code_prompt=""
        errors_prompt=""
        if last_time_poc_code:
            last_time_poc_code_prompt=last_time_poc_code_template.format(last_time_poc_code=json.dumps(last_time_poc_code, indent=4))
        if execution_output:
            execution_output_prompt=execution_output_template.format(execution_output=json.dumps(execution_output, indent=4))
        if reason:
            errors_prompt=errors_template.format(reason=reason)
        if patch_context:
            patch_context = patch_context_prompt.format(patch_context=patch_context)
        message = one_more_poc_prompt.format(
            previous_pocs=previous_poc_prompt,
            problem_statement=task.problem_statement,
            poc_for_patch=poc_for_patch_prompt,
            patch_context=patch_context,
            last_time_poc_code=last_time_poc_code_prompt,
            execution_output=execution_output_prompt,
            reason=errors_prompt,
        ).strip()

        model = make_model(
            model=args.model,
            logger=logger,
            max_tokens=4096,
            backend=args.backend,
            temperature=0,
            batch_size=1,
        )
        traj = model.codegen(message, num_samples=1)[0]
        traj["prompt"] = message
        default_poc_description = {
                "is_complete": False,
                "type": "unknown",
                "is_multi": False,
                "poc_code": {},
                "wrong_behavior": "",
                "expected_behavior": "",
                "oracle": "",
            }
        poc_description = clean_and_parse_json(traj["response"], default_poc_description)
        oracle_description=poc_description.get("oracle_description", "")
        expected_behavior=poc_description.get("expected_behavior", "")
        wrong_behavior=poc_description.get("wrong_behavior", "")
        poc_info = {
                        "instance_id": instance_id,
                        "result": {
                            "poc": poc_description,
                            "oracle": {
                                "oracle_description": oracle_description,
                                "expected_behavior": expected_behavior,
                                "wrong_behavior": wrong_behavior,
                                "issue_description": task.problem_statement,
                                "reasoning": "",
                                "execution_output": {
                                    "stdout": "",
                                    "stderr": "",
                                },
                            }
                        }
                    }
        # reset the git repo
        poc_info, execution_output = execute_reproduce_instance(task, args, poc_info)
        if_match = poc_info["result"]["oracle"]["exec_match_wrong_behavior"]
        last_time_poc_code = poc_info["result"]["poc"]["poc_code"]
        reason = poc_info["result"]["oracle"]["if_match_reasoning"]
        retry += 1
    
    if if_match:        
        poc_output_file = os.path.join(issue_id_folder, f"issue_parsing_report_{poc_index}.json")
        with open(poc_output_file, "w") as ft:
            json.dump(poc_info, ft, indent=4)
            print("Got EXTRA reproducer for issue {} success! The result is in {}.".format(task.task_id, poc_output_file))
            return True
    else:
        print("Failed to generate one more PoC for issue {}.".format(task.task_id))
        return False


def execute_reproduce_instance(task, args, poc_info):
    is_setup = task.setup_project()
    if not is_setup:
        poc_info["result"]["setup"] = False
    else:
        poc_info["result"]["setup"] = True
    
    # poc is empty or could not be executed (not a single python file)
    if (not poc_info["result"]["poc"]["poc_code"]) or (not task.is_execute(poc_info)):
        poc_info["result"]["oracle"]["exec_match_wrong_behavior"] = False
        poc_info["result"]["oracle"]["execution_output"] = {
            "stdout": "",
            "stderr": "",
        }
        poc_info["result"]["oracle"]["if_match_reasoning"] = "poc code is empty or could not be executed, no match"
        print("instance {} poc code is empty or could not be executed, no match".format(task.task_id))
        print("issue description: {}".format(task.problem_statement))
        return poc_info, {}
    # poc is not empty
    else:
        poc_code_dict = poc_info["result"]["poc"]["poc_code"]
        _, poc_code = next(iter(poc_code_dict.items()))
        task.dump_poc(poc_code)
        execution_output = task.execute_poc(poc_info)
        poc_info["result"]["oracle"]["execution_output"] = execution_output
        log_file = os.path.join(
            args.reproduce_folder, "reproduce_logs", f"{task.task_id}.log"
        )
        logger = setup_logger(log_file)
        rp = LLMRP(
            task.task_id,
            task.problem_statement,
            args.model,
            args.backend,
            logger,
        )
        message = judge_execution_result_prompt.format(
            issue_description=task.problem_statement,
            poc_code=poc_info["result"]["poc"]["poc_code"],
            execution_output=execution_output
        ).strip()
        rp.logger.info(f"Instance: {task.task_id}, prompting with message:\n{message}")
        print(f"Instance: {task.task_id}, prompting with message:\n{message}")
        rp.logger.info("=" * 80)
        print("=" * 80)

        model = make_model(
            model=rp.model_name,
            backend=rp.backend,
            logger=rp.logger,
            max_tokens=rp.max_tokens,
            temperature=0,
            batch_size=1,
        )
        traj = model.codegen(message, num_samples=1)[0]
        rp.logger.info(f"Got response:\n{traj}")
        traj["prompt"] = message
        raw_output = traj["response"]
        print(raw_output)
        judge_result = ""
        try:
            judge_result = raw_output.split("<judgement>")[1].split("</judgement>")[0]
        except:
            logger.error(f"Failed to parse judgement: {raw_output}")
            print(f"Failed to parse judgement: {raw_output}")
        if "yes" in judge_result.lower():
            poc_info["result"]["oracle"]["exec_match_wrong_behavior"] = True
        else:
            poc_info["result"]["oracle"]["exec_match_wrong_behavior"] = False
        reasoning = ""
        try:
            reasoning = raw_output.split("<reasoning>")[1].split("</reasoning>")[0]
        except:
            logger.error(f"Failed to parse reasoning: {raw_output}")
            print(f"Failed to parse reasoning: {raw_output}")
            reasoning = "Failed to parse reasoning"
        poc_info["result"]["oracle"]["if_match_reasoning"] = reasoning
    return poc_info, execution_output


def reproduce(args):
    existing_instance_ids = (
        check_existing_reproduce_ids(args.reproduce_folder)
    )

    if args.num_threads == 1:
        for task in args.tasks_list:
            reproduce_instance(
                task, args, existing_instance_ids
            )
    else:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.num_threads
        ) as executor:
            futures = [
                executor.submit(
                    reproduce_instance,
                    task,
                    args,
                    existing_instance_ids
                )
                for task in args.tasks_list
            ]
            concurrent.futures.wait(futures)
            # for future in futures:
            #     result = future.result()  # this will raise an exception if the task generated an exception


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--reproduce_folder", type=str, required=True)
    parser.add_argument(
        "--setup_map",
        type=str,
        help="Path to json file that contains the setup information of the projects.",
    )
    parser.add_argument(
        "--tasks_map",
        type=str,
        help="Path to json file that contains the tasks information.",
    )
    parser.add_argument(
        "--task_list_file",
        type=str,
        help="Path to the file that contains all tasks ids to be run.",
    )
    parser.add_argument(
        "--match_partial_paths",
        action="store_true",
        help="Whether to match model generated files based on subdirectories of original repository if no full matches can be found",
    )
    parser.add_argument(
        "--num_threads",
        type=int,
        default=1,
        help="Number of threads to use for creating API requests",
    )
    parser.add_argument("--target_id", type=str)
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-2024-08-06",
    )
    parser.add_argument(
        "--backend", type=str, default="openai", choices=["openai", "deepseek", "claude"]
    )

    args = parser.parse_args()

    assert (not "deepseek" in args.model) or (
            args.backend == "deepseek"
    ), "Must specify `--backend deepseek` if using a DeepSeek model"

    assert (not "claude" in args.model) or (
            args.backend == "claude"
    ), "Must specify `--backend claude` if using a Claude model"

    os.makedirs(os.path.join(args.reproduce_folder, "reproduce_logs"), exist_ok=True)

    # write the arguments
    with open(f"{args.reproduce_folder}/reproduce_args.json", "w") as f:
        json.dump(vars(args), f, indent=4)

    assert not (args.target_id is not None and args.task_list_file is not None), "Cannot specify both task and task-list."
    all_task_ids = []
    if args.task_list_file is not None:
        all_task_ids = parse_task_list_file(args.task_list_file)
    elif args.target_id is not None:
        all_task_ids = [args.target_id]
    assert len(all_task_ids) > 0, "No task ids to run."

    args.tasks_list = make_swe_tasks(all_task_ids, args.setup_map, args.tasks_map)

    reproduce(args)


if __name__ == "__main__":
    main()
