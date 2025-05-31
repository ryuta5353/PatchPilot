import argparse
import concurrent.futures
import json
import os
import sys
import copy
import random
import re
import ast
from datasets import load_dataset
from tqdm import tqdm
from filelock import FileLock
from patchpilot.repair.bfs import vote_outputs_unwrap, apply_plan_step_by_step
from patchpilot.util.model import make_model
from patchpilot.util.preprocess_data import (
    get_full_file_paths_and_classes_and_functions,
    get_repo_structure,
    transfer_arb_locs_to_locs,
    find_definitions_by_name,
    find_callers_by_name,
    find_modified_functions,
    extract_file_content
)
from patchpilot.fl.FL import LLMFL
from patchpilot.util.utils import load_jsonl, setup_logger
from patchpilot.repair.utils import post_process_raw_output, post_process_raw_output_refine, construct_topn_file_context
from patchpilot.reproduce.reproduce import reproduce, ensure_directory_exists
from patchpilot.reproduce.verify import verify
from patchpilot.reproduce.task import make_swe_tasks, parse_task_list_file
from patchpilot.util.search_tool import search_func_def_with_class_and_file_schema, search_func_def_with_class_and_file

reloca_ids = []
reloca_locs = dict()
not_found_file_dict = dict()

locs_global = []

lock_path = '/tmp/lock_file'
output_file_lock = FileLock(lock_path)

num_generated_sample = 0
round_idx = 0
last_round = False
orig_verify_folder = ""

planning_example_format = """Here is an example of the output format:
--- BEGIN REASON ---
The bug is caused by the function `foo` not returning the correct value.
--- END REASON ---

--- BEGIN EXPECTED BEHAVIOR ---
The function foo should return x+1
--- END EXPECTED BEHAVIOR  ---

--- BEGIN STEPS ---
<STEP> Check the input data </STEP> <Actions to be Taken> Go through the input data in input.py to identify any anomalies </Actions to be Taken>
<STEP> Modify the output data </STEP> <Actions to be Taken> Modify the output data in output.py to match the expected output </Actions to be Taken>
--- END STEPS ---
"""


repair_example_format = """Here is an example of the output format:
```python
### mathweb/flask/app.py
<<<<<<< SEARCH
from flask import Flask
=======
import math
from flask import Flask
>>>>>>> REPLACE
```
Please note that the *SEARCH/REPLACE* edit REQUIRES PROPER INDENTATION. If you would like to add the line '        print(x)', you must fully write that out, with all those spaces before the code!
Wrap the *SEARCH/REPLACE* edit in blocks ```python...```.
"""


planning_prompt = """
We are currently solving the following issue within our repository.
Please analyze the bug,  infer the expected behavior of the code based on the issue description, provide an analysis of the reason for the bug, and then provide a step-by-step plan for repairing it.
Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken.
The actions should be wrapped in <Actions to be Taken> and </Actions to be Taken>.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided. You do not have the freedom to open the codebase and look for the bug. You should only rely on the information provided in the issue description and the code snippet.

Please develop a comprehensive plan that addresses the underlying issue described. The plan should be broad enough to apply to similar cases, not just the specific example provided in the issue description. Focus on creating a solution that can be generally applied to a range of similar scenarios, rather than just solving the specific case mentioned.
Note that if a file name or argument is provided in the issue description as an example for reproduction, other arguments may also trigger the issue. Therefore, make the fix as general as possible. Don't restrict the fix to a specific set of arguments.
You should ensure that the proposed plan fixes the code to do the expected behavior.
Choose the most general way to fix the issue, don't make any assumption of the input.
You are required to propose a plan to fix the issue with minimal modifications. Follow these guidelines:
Number of Steps: The number of steps to fix the issue should be at most 3. 
Modification: Each step should perform exactly one modification at exactly one location in the code.
Necessity: Do not modify the code unless it is necessary to fix the issue.
Your plan should outline only the steps that involve code modifications. If a step does not require a code change, do not include it in the plan.
Don't write any code in the plan.

{example}

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---
"""


planning_prompt_minimal = """
We are currently solving the following issue within our repository. Your task is to analyze the bug and infer the expected behavior based on the issue description. Provide an analysis of the reason for the bug and a step-by-step plan for repairing it. 

In fixing the bug, your focus should be on making minimal modifications that only target the bug-triggering scenario without affecting other parts of the code or functionality. Make sure that other inputs or conditions are not impacted. Modify only the specific behavior causing the bug, and do not make any broad changes unless absolutely necessary.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided. You do not have the freedom to open the codebase and look for the bug. You should only rely on the information provided in the issue description and the code snippet.

Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken, wrapped in <Actions to be Taken> and </Actions to be Taken>.

Guidelines:
1. **Minimal Modifications:** Only target the bug-triggering case. The fix should not alter other functionality unless required to fix the bug.
2. **One File Only:** Choose one file to modify, and ensure all changes are limited to that file.
3. **Step Limitation:** The number of steps should not exceed 3. 
4. **Necessity:** Do not modify the code unless it is strictly necessary to fix the issue.

If the issue mentions a specific input or argument that triggers the bug, ensure your solution only fixes the behavior for that input without assuming that other inputs require similar changes.

Only include the steps that involve necessary code changes. Do not write any code, and avoid mentioning testing or verification.
Don't write any code in the plan.
If the issue text includes a recommended fix, do not apply it directly. You should explicitly reason whether it can fix the issue. Output the reason that the recommended fix can or cannot fix the issue. You should explicitly reason whether the recommended fix keeps the same code style.
Instead, adapt it to align with the codebase's style and standards. Ensure that the patch considers interactions across different code sections, including nested structures, function calls, and data dependencies. The patch should maintain overall structural integrity, addressing the issue without unintended effects on other parts. Prefer solutions that are resilient to structural changes or future extensions.
You always need to adapt the code to the existing codebase's style and standards by considering the context of the code.
Remember that you should not write any code in the plan.

{example}

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---
"""


planning_prompt_general = """
We are currently solving the following issue within our repository.
You are a maintainer of the project. Please analyze the bug as a maintainer, since the issue description might only describe the surface-level problem. Please analyze the bug thoroughly and infer the underlying real problem that needs to be addressed, using your inherit knowledge of the project. For example, if the goal is to fix an error or warning, focus on resolving the logic that causes the error or warning rather than simply suppressing or bypassing it.
Then, provide an analysis of the reason for the bug, and then provide a step-by-step plan for repairing it.
You are required to propose a plan to fix the issue in a way that is broadly applicable and prevents similar bugs from occurring in the future.
The plan will be used to generate a comprehensive and extensive patch that addresses the issue thoroughly, modifies related areas to ensure the bug is fully resolved, and enhances the overall robustness and completeness of the solution.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided. You do not have the freedom to open the codebase and look for the bug. You should only rely on the information provided in the issue description and the code snippet.

The plan should ensure that the solution is general, preventing any similar bugs from occurring in other contexts or input variations.
Avoid making assumptions based solely on the example given in the issue description. If the issue description mentions specific cases (e.g., a particular input or argument), the fix should be applicable to all possible cases, not just the ones listed.
Your solution should aim to resolve the issue broadly and comprehensively, covering edge cases and general patterns.
Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken.
The actions should be wrapped in <Actions to be Taken> and </Actions to be Taken>.
Only provide the steps for repairing the issue, do not include any testing or verification steps in the plan.
Choose the most general way to fix the issue, avoiding specific or narrow solutions.
You are required to propose a plan to fix the issue in a way that is broadly applicable and prevents similar bugs from occurring in the future.
Generate a comprehensive and extensive patch that addresses the issue thoroughly, modifies related areas to ensure the bug is fully resolved, and enhances the overall robustness and completeness of the solution.
Number of Steps: The number of steps to fix the issue should be at most 3.
Modification: Each step should perform exactly one modification at exactly one location in the code.
Necessity: Do not modify the code unless it is necessary to fix the issue.
For example, if the issue description points out an error when handling a specific symbol (e.g., a Greek letter), the fix should apply to all such symbols and not just the specific one mentioned. Ensure that the fix solves the problem generally, for any similar input patterns.

{example}

If the issue text includes a recommended fix, do not apply it directly. You should explicitly reason whether it can fix the issue. Output the reason that the recommended fix can or cannot fix the issue. You should explicitly reason whether the recommended fix keeps the same code style.
If the issue text includes a recommended fix, do not apply it directly. Instead, adapt it to align with the codebase's style and standards. Ensure that the patch considers interactions across different code sections, including nested structures, function calls, and data dependencies. The patch should maintain overall structural integrity, addressing the issue without unintended effects on other parts. Prefer solutions that are resilient to structural changes or future extensions.
You always need to adapt the code to the existing codebase's style and standards by considering the context of the code.
Remember that you should not write any code in the plan.

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---
"""


planning_prompt_random_file = """
We are currently solving the following issue within our repository.
You are a maintainer of the project. Please analyze the bug as a maintainer, since the issue description might only describe the surface-level problem. Please analyze the bug thoroughly and infer the underlying real problem that needs to be addressed, using your inherit knowledge of the project. For example, if the goal is to fix an error or warning, focus on resolving the logic that causes the error or warning rather than simply suppressing or bypassing it.
Then, provide an analysis of the reason for the bug, and then provide a step-by-step plan for repairing it.
Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken.
The actions should be wrapped in <Actions to be Taken> and </Actions to be Taken>.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided. You do not have the freedom to open the codebase and look for the bug. You should only rely on the information provided in the issue description and the code snippet.
You should only modify the file that you have chosen to modify.

Please develop a comprehensive plan that addresses the underlying issue described. The plan should be broad enough to apply to similar cases, not just the specific example provided in the issue description. Focus on creating a solution that can be generally applied to a range of similar scenarios, rather than just solving the specific case mentioned.
Note that if a file name or argument is provided in the issue description as an example for reproduction, other arguments may also trigger the issue. Therefore, make the fix as general as possible. Don't restrict the fix to a specific set of arguments.
You should ensure that the proposed plan fixes the code to do the expected behavior.
Choose the most general way to fix the issue, don't make any assumption of the input.
You are required to propose a plan to fix the issue with minimal modifications. Follow these guidelines:
Number of Steps: The number of steps to fix the issue should be at most 3. 
Modification: Each step should perform exactly one modification at exactly one location in the code.
Necessity: Do not modify the code unless it is necessary to fix the issue.
Your plan should outline only the steps that involve code modifications. If a step does not require a code change, do not include it in the plan.
You should only modify the file that you have chosen to modify.
In each step, specify the file that need to be modified.
If the issue text includes a recommended fix, do not apply it directly. You should explicitly reason whether it can fix the issue. Output the reason that the recommended fix can or cannot fix the issue. You should explicitly reason whether the recommended fix keeps the same code style.
If the issue text includes a recommended fix, do not apply it directly. Instead, adapt it to align with the codebase's style and standards. Ensure that the patch considers interactions across different code sections, including nested structures, function calls, and data dependencies. The patch should maintain overall structural integrity, addressing the issue without unintended effects on other parts. Prefer solutions that are resilient to structural changes or future extensions.
You always need to adapt the code to the existing codebase's style and standards by considering the context of the code.
Remember that you should not write any code in the plan.

{example}

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---
"""


planning_prompt_poc_feedback = """
We are currently solving the following issue within our repository.
You are a maintainer of the project. Please analyze the bug as a maintainer, since the issue description might only describe the surface-level problem. Please analyze the bug thoroughly and infer the underlying real problem that needs to be addressed, using your inherit knowledge of the project. For example, if the goal is to fix an error or warning, focus on resolving the logic that causes the error or warning rather than simply suppressing or bypassing it.
Then, provide an analysis of the reason for the bug, and then provide a step-by-step plan for repairing it.
Begin each step with the mark <STEP> and end with </STEP>. For each step, provide a clear and concise description of the action to be taken.
The actions should be wrapped in <Actions to be Taken> and </Actions to be Taken>.
Only provide the steps of code modifications for repairing the issue in the plan, do not include any testing or verification steps in the plan.
Do not include any localizations in the plan. You are only required to provide a plan to do code changes based on the issue description and the code provided. You do not have the freedom to open the codebase and look for the bug. You should only rely on the information provided in the issue description and the code snippet.

Generate a detailed plan to address the issue, avoiding overly general solutions. Analyze the scope of the critical variable by reasoning about the specific values that should and should not be affected. 
Identify the situations the patch should handle and explicitly outline the scenarios it should avoid. Ensure the patch directly targets the issue without impacting unrelated code or values.
For example:
    If the issue can be triggered by an empty string, explicitly evaluate whether similar inputs like None, an empty list, or other falsy values can also trigger the issue. The plan should only affect the variable causing the issue. If None does not trigger the issue, the patch should not modify its behavior.
    If the issue is caused by a specific integer, evaluate whether other integers also cause the problem. Adjust the scope of the variable to match the values capable of triggering the issue while ensuring unrelated cases remain unaffected.
Infer the logical root cause of the issue and design the patch to fix the problem. Pay attention to conditions to ensure the patch avoids fixing too few situations or unintentionally affecting unrelated ones. 

Please develop a comprehensive plan that addresses the underlying issue described. The plan should be broad enough to apply to similar cases, not just the specific example provided in the issue description. Focus on creating a solution that can be generally applied to a range of similar scenarios, rather than just solving the specific case mentioned.
Note that if a file name or argument is provided in the issue description as an example for reproduction, other arguments may also trigger the issue. Therefore, make the fix as general as possible. Don't restrict the fix to a specific set of arguments.
You should ensure that the proposed plan fixes the code to do the expected behavior.
You are required to propose a plan to fix the issue with minimal modifications. Follow these guidelines:
Number of Steps: The number of steps to fix the issue should be at most 2. 
Modification: Each step should perform exactly one modification at exactly one location in the code.
Necessity: Do not modify the code unless it is necessary to fix the issue.
Your plan should outline only the steps that involve code modifications. If a step does not require a code change, do not include it in the plan.
Don't write any code in the plan.

{example}

#Now the issue is as follows:

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---

{feedback}
"""


vote_patch_prompt = """
We are currently addressing the following issue in our repository. Several candidate patches have been proposed to resolve this issue. Your task is to evaluate each patch in detail and select the one that offers the most effective and general solution.

Analyze the issue and provided patchs according to the following guidelines, you should look each patch at give each patch a score, output the score for each patch:

## Reason about the Scope (5 points):
Reason about the scope of the critical variable, considering the values that should and should not be affected. What situations should the patch handle, and what should it avoid? Ensure the patch correctly targets the issue without impacting unrelated code or values. Score based on the accuracy of the scope.
You should always explicitly infer the scope of the critical variable, output the exact scope of values that should and should not be affected.
It is not a negative factor if the patch introduces complexity logic.

Example:
For instance, if the issue can be triggered by an empty string, you need to explicitly consider whether it can also be triggered by None, an empty list, or other similar values. Prefer patches that only modify the variable triggering the issue. If None does not trigger the issue, the patch should not alter the behavior of None. 
Similarly, if an integer in the issue causes the problem, explicitly evaluate whether other integers can also trigger the issue. Prioritize patches that adjust the scope of the variable in a way that matches the specific values capable of triggering the issue, without impacting unrelated cases.

## Correctness (5 points):
Infer the logical root cause of the issue. Ensure the proposed patch fixes the issue as described in the problem statement and behaves as expected. 

## Reusability of Existing Functions (2 points):
Favor patches that reuse existing functions or utilities.

## Logic Changes(5 points):
If a patch reorders checks, it should get 0 points for this criteria.
You should always explicitly infer whether the checks are reordered and output the result.
If a patch broaden the scope of checks unnecessarily, it should get 0 points for this criteria. 
You should always explicitly infer whether the checks are broadened and output the result.
If a patch doesn't fix the issue completely, it should get 0 points for this criteria.

## Consideration of Structural Interactions (5 points):
Ensure that the patch handles interactions between different parts of the code, such as nested structures, function calls, or data dependencies.
The patch should maintain the integrity of the overall structure while addressing the issue, ensuring that changes in one part do not inadvertently affect other parts. 
Prefer solutions that are robust against changes in the structure or future extensions.

# Minimal Patch (2 points):
The patch should be minimal, only addressing the specific issue described in the problem statement. Avoid making unnecessary changes or introducing new functionality.

## Type (2 points):
If the patch involves checking or modifying the type of the variable, you should consider the context, and prefer types specific to the python project over general ones.

After evaluating each patch based on these criteria, conclude your analysis by stating:
"The best choice is s," where s is the integer ID of the patch you believe is the best option.

Your analysis should not involve copying any code from the patches.
Your analysis should not have any code snippets.
You should compare each patch and score each patch.

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below are some code segments, each from a relevant file. One or more of these files may contain bugs.
--- BEGIN FILE ---
{content}
--- END FILE ---

Here are the candidate patches:
--- BEGIN PATCHES ---
{patches}
--- END PATCHES ---
"""


poc_info_prompt = """
Here is the code that reproduces the bug, called a proof of concept (POC).:
--- BEGIN POC ---
{poc_code}
--- END POC ---

--- BEGIN STDOUT ---
{stdout}
--- END STDOUT ---

--- BEGIN STDERR ---
{stderr}
--- END STDERR ---
"""


search_failed_functionality_test_prompt = """
You are analyzing a failed unit test, and your objective is to retrieve the code of the test function that reported this failure. You should call search_func_def_with_class_and_file function call that can locate the function's definition based on specific parameters.

The function call takes two arguments:

function_name - the name of the test function associated with the failure (this is required).
class_name - the name of the class containing the function, if applicable (optional but preferred for scoped searching). Return only the class name, not the fully qualified class name. Do not include any module or package names in your response, just the class name.

Here is the failed unit test:
--- BEGIN TEST ---
{test_result}
--- END TEST ---
"""


codeql_impact_analysis_prompt = """
Here are the code segments that may be affected by the patch:
--- BEGIN CODE ---
{affected_code}
--- END CODE ---
"""


# a prompt for llm to attack the patch by edge cases
edge_case_prompt = """
You need to analyse and attack a patch aimed at fixing a bug in the codebase.

Here is the original issue that the patch wants to fix:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Here is the related code after applying the patch
--- BEGIN CODE ---
```
{content}
```
--- END CODE ---

Here is the patch that aims to fix the issue that may be incomplete or incorrect:
--- BEGIN PATCH ---
{diff}
--- END PATCH ---

You need to output: 
1. what edge cases can break the patch, consider complex cases such as nested structures and recursive patterns, for example, if the patch fixes an issue with an empty string, consider whether None, an empty list, or partially empty data structures might also trigger the bug.
2. why the patch is incomplete or incorrect, whether the interaction between the patched part and other parts of the codebase is not handled properly
3. whether the patch only fixes the issue for the specific case mentioned in the issue description or for all similar cases
4. whether the patch follows the codebase's style and standards, using the proper variable types, error or warning types, and adhering to the established format
"""


review_patch_prompt = """
You are a reviewer for a patch aimed at fixing a bug in the codebase. If the patch is complete and correct, approve it by outputting 'approved'. If the patch is incomplete or incorrect, generate additional *SEARCH/REPLACE* edits to address the issue.
Only generate *SEARCH/REPLACE* edits if the patch is incomplete or incorrect. If the patch is complete and correct, output 'approved'.

Pay attention to these aspects:

1. **Completeness and Consistency**: Ensure the patch is fully implemented. If a method is changed (e.g., reading a file), related methods (e.g., writing a file) also need similar adjustments. This avoids inconsistencies in behavior across similar functionalities. Note that some times the corresponding methods may be inherited from a parent class, so you may need to explicitly implement the function in the current class. 

2. **Edge cases **: Think about edge cases that may not be covered by the patch. For example, if the patch fixes an issue with a specific input, consider whether other inputs might trigger the same bug. Include handling for these cases as necessary. For example, if the patch fixes an issue with an empty string, consider whether None, an empty list, or partially empty data structure might also trigger the bug.

3. **Output and Return Format**: Ensure the modified methods maintain consistent output and return values, adhering to the codebase's established format. You should carefully consider which variable type, error or warning type you should use, referencing similar functions in the codebase for guidance.

4. **Complex Situations**: Check whether the patch can effectively handle complex cases such as nested structures and recursive patterns. 

{example}

Here is the issue text:
--- BEGIN ISSUE ---
{problem_statement}
--- END ISSUE ---

Below is the file after the patch has been applied:
--- BEGIN FILE ---
```
{content}
```
--- END FILE ---

Here is the patch that aims to fix the issue that may be incomplete or incorrect:
--- BEGIN PATCH ---
{diff}
--- END PATCH ---

{affected_code}

You need to first reason about each aspect of **Completeness and Consistency**, **Edge cases **, **Output and Return Format**, **Generalization Beyond Stated Problem**, **Complex Situations**, then generate *SEARCH/REPLACE* edits or output 'approved'.
"""


def weighted_sampling(models, weights):
    return random.choices(models, weights, k=1)[0]


def extract_diff_lines(patch_text):
    # Store line numbers for deleted and added lines
    # for deleted lines, we store the line number in the original file
    old_lines = set()
    new_lines = set()

    # Regex to match the hunk header (e.g., @@ -1018,8 +1018,9 @@)
    hunk_header_pattern = re.compile(r"@@ -(\d+),\d+ \+(\d+),\d+ @@")

    # Split the patch into lines for easier processing
    lines = patch_text.splitlines()

    # Initialize line counters
    old_line = new_line = None

    # Process each line in the patch
    for line in lines:
        # Match hunk headers to update line numbers
        match = hunk_header_pattern.match(line)
        if match:
            old_line = int(match.group(1))  # Start line number in the original file
            new_line = int(match.group(2))  # Start line number in the modified file
            continue

        if line.startswith('---') or line.startswith('+++'):
            continue

        # Process deletions
        if line.startswith('-'):
            old_lines.add(old_line)
            new_lines.add(new_line)
            old_line += 1  # Move to the next line in the original file

        # Process additions
        elif line.startswith('+'):
            new_lines.add(new_line)
            old_lines.add(old_line)
            new_line += 1  # Move to the next line in the modified file

        # Process context lines (not modified, so increase both counters)
        else:
            old_line += 1
            new_line += 1

    return old_lines, new_lines


def get_top_level_node(node):
    if hasattr(node, 'parent') and isinstance(node.parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return get_top_level_node(node.parent)
    return node


def get_node_intervals(node, changed_lines):
    if hasattr(node, 'body'):
        body = node.body
        start_line = getattr(node, 'lineno', None)

        # Check if body is a list to safely access body[-1]
        if isinstance(body, list) and body:
            end_line = getattr(body[-1], 'end_lineno', getattr(node, 'end_lineno', None))
        else:
            # If body is not a list, use end_lineno directly from the node if available
            end_line = getattr(node, 'end_lineno', None)

        # Check if any line in changed_lines is within the start and end lines of the node
        if start_line and end_line and any(start_line <= line <= end_line for line in changed_lines):
            top_level_node = get_top_level_node(node)
            top_start_line = getattr(top_level_node, 'lineno', None)

            # Check if top_level_node.body is a list to access top_level_node.body[-1] safely
            if hasattr(top_level_node, 'body') and isinstance(top_level_node.body, list) and top_level_node.body:
                top_end_line = getattr(top_level_node.body[-1], 'end_lineno', getattr(top_level_node, 'end_lineno', None))
            else:
                top_end_line = getattr(top_level_node, 'end_lineno', None)

            return (top_start_line-1, top_end_line)
    return None


def extract_top_level_intervals(source_code, changed_lines):
    tree = ast.parse(source_code)
    intervals = []

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

    for node in ast.walk(tree):
        interval = get_node_intervals(node, changed_lines)
        if interval:
            intervals.append(interval)

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start_line = getattr(node, 'lineno', None)
            end_line = getattr(node, 'end_lineno', None)
            if start_line and end_line:
                intervals.append((start_line-1, end_line))

    unique_intervals = sorted(set(intervals))
    return unique_intervals


def merge_intervals(intervals):
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = []

    for interval in sorted_intervals:
        if not merged or merged[-1][1] < interval[0] - 1:
            merged.append(interval)
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], interval[1]))

    return merged


def parse_git_diff_to_dict(diff_text: str) -> dict[str, str]:
    diff_dict = {}
    current_file = None
    current_diff = []

    # Regular expression to match the filename line in git diff output
    file_pattern = re.compile(r'^diff --git a\/(.+?) b\/(.+)$')

    for line in diff_text.splitlines():
        # Check if the line matches a new file entry
        file_match = file_pattern.match(line)
        if file_match:
            # Save the diff of the previous file (if any)
            if current_file and current_diff:
                diff_dict[current_file] = '\n'.join(current_diff)

            # Update the current file and reset the diff accumulator
            current_file = file_match.group(1)
            current_diff = [line]  # Start with the current line
        elif current_file:
            # If within a file diff, accumulate diff content
            current_diff.append(line)

    # Handle the last file's diff (if any)
    if current_file and current_diff:
        diff_dict[current_file] = '\n'.join(current_diff)

    return diff_dict


def process_loc(loc, args, swe_bench_data, prev_generations):
    
    instance_id = loc["instance_id"]
    log_file = os.path.join(
        args.output_folder, "repair_logs", f"{instance_id}.log"
    )
    logger = setup_logger(log_file)

    greedy_model = make_model(
        model=args.model,
        logger=logger,
        max_tokens=4096,
        backend=args.backend,
        temperature=0,
        batch_size=1,
    )

    # check if the patch has been generated, skip if it has been generated
    found = False
    # we should just check the raw_output_file
    
    for entry in prev_generations:
        if entry["instance_id"] == instance_id:
            generated_for_instance = len(entry["git_diffs"])
            if generated_for_instance >= num_generated_sample + args.batch_size:
                found = True
            break

    if found:
        logger.info(f"skipping {instance_id} since patch already generated")
        print(f"skipping {instance_id} since patch already generated")
        return None

    raw_outputs, traj, git_diffs, raw_git_diffs = (
        [],
        [],
        [],
        [],
    )
    
    # get the original repro info, including poc code, stdout, stderr, and commit info
    poc_code = ""
    poc_orig_std_out = ""
    poc_orig_std_err = ""
    commit_dict = {}
    if os.path.exists(args.reproduce_folder):
        reproduce_issue_id_folder = os.path.join(args.reproduce_folder, instance_id)
        ensure_directory_exists(reproduce_issue_id_folder)
        reproduce_output_file = os.path.join(reproduce_issue_id_folder, "issue_parsing_report_0.json")
        if os.path.exists(reproduce_output_file):
            try:
                with open(reproduce_output_file, 'r') as f:
                    reproduce_info_dict = json.load(f)
                repro_result_dict = reproduce_info_dict.get('result', {})
                oracle_dict = repro_result_dict.get('oracle', {})
                exec_match_wrong_behavior = oracle_dict.get('exec_match_wrong_behavior', False)
                if exec_match_wrong_behavior:
                    poc_code = next(iter(repro_result_dict.get('poc', {}).get('poc_code', {}).values()))
                    poc_orig_std_out = repro_result_dict.get('oracle', {}).get('execution_output',{}).get('stdout', {})
                    poc_orig_std_err = repro_result_dict.get('oracle', {}).get('execution_output',{}).get('stderr', {})
                commit_info = repro_result_dict.get('commit_info', {})
                bug_fixed = commit_info.get('bug_fixed', False)
                if bug_fixed:
                    git_diff = commit_info.get('git_diff', {})
                    commit_dict = parse_git_diff_to_dict(git_diff)
            except Exception as e:
                logger.error(f"failed to load reproduce info from {reproduce_output_file}")
                print(f"failed to load reproduce info from {reproduce_output_file}")
                raise e

    logger.info(f"================ repairing {instance_id} ================")

    if len(loc["found_files"]) == 0:
        return None

    pred_files = loc["found_files"][: args.top_n]
    bench_data = [x for x in swe_bench_data if x["instance_id"] == instance_id][0]
    problem_statement = bench_data["problem_statement"]
    base_patch_diff = ""
    failded_poc_output_reason_prompt = ""
    if args.refine_mod:
        # For refine_mod, we need to apply the best patch so far to the content, which modifies the content
        sample_idx = -1
        did_relocate = False
        if args.best_patch_file and os.path.exists(args.best_patch_file):
            best_patches = load_jsonl(args.best_patch_file)
            for entry in best_patches:
                if entry["instance_id"] == instance_id:
                    base_patch_diff = entry["model_patch"]
                    sample_idx = entry["sample_idx"]
                    did_relocate = entry.get("reloca", False)
                    break
    
    if base_patch_diff and (instance_id not in reloca_ids) and not did_relocate:
        structure = get_repo_structure(
            instance_id, bench_data["repo"], bench_data["base_commit"], "playground", model_patch=base_patch_diff
        )
    else:
        structure = get_repo_structure(
            instance_id, bench_data["repo"], bench_data["base_commit"], "playground"
        )
    files,  classes, functions = get_full_file_paths_and_classes_and_functions(structure)

    poc_code_prompt = ""
    base_patch_prompt = ""
    poc_execution_output_after_patch = ""
    verify_reason = ""
    functionality_newly_failed = ""
    functionality_fail_increase = 0
    functionality_newly_failed_prompt = ""
    functionality_test_fail_diff_whole = ""
    if args.refine_mod:
        # some prompt specific to the refine_mod
        if os.path.exists(orig_verify_folder+f"/samples_{sample_idx}/{instance_id}/verify_outputs.json"):
            with open(orig_verify_folder+f"/samples_{sample_idx}/{instance_id}/verify_outputs.json", "r") as f:
                verify_outputs = json.load(f)
                functionality_test_fail_diff_whole = verify_outputs["result"]["functionality_test_fail_diff_whole"]
                functionality_newly_failed = verify_outputs["result"]["functionality_test_fail_diff_only_func"]
                functionality_fail_increase = max(verify_outputs["result"]["functionality_test_fail_num"]["new_failed_tests_num"]
                    - verify_outputs["result"]["functionality_test_fail_num"]["old_failed_tests_num"], 0) 
                # first failed poc code and feedback
                for i in range(len(verify_outputs["result"]["poc_test_succeed_llm"])): 
                    if not verify_outputs["result"]["poc_test_succeed_llm"][i]:
                        poc_execution_output_after_patch = verify_outputs["result"]["poc_execution_output"][i]
                        verify_reason = verify_outputs["result"]["llm_judgement_reason"][i]
                        poc_code = verify_outputs["result"]["poc_code"][i]

        if base_patch_diff:
            base_patch_prompt = f"Here is the previous patch that aims to fix the bug:\n{base_patch_diff}, this patch didn't fix the bug or introduces a new bug."
        if poc_code:
            poc_code_prompt = f"Here is the poc code that triggers the bug:\n{poc_code}"
        if verify_reason:
            verify_reason = f"Here is the reason that the poc still triggers the bug:\n{verify_reason}"
        if poc_execution_output_after_patch or verify_reason:   
            failded_poc_output_reason_prompt = f"""
            Here is the feedback of the failed poc verification after applying the patch:\n 
            You need to solve the problems in the patch that caused the poc or functionality test to fail.
            Here is the poc execution output:
            {str(poc_execution_output_after_patch)}
            {verify_reason}
            """

        # get the code of the newly failed functionality test, only get 3 for now since otherwise the prompt will be too long
        failed_functionality_test_info = dict()
        searched_func_test=0
        if functionality_newly_failed and functionality_fail_increase > 0:
            for func_test in functionality_newly_failed.splitlines():
                if searched_func_test >= 3:
                    break
                searched_func_test += 1
                ask_llm_for_search_prompt = search_failed_functionality_test_prompt.format(
                    test_result=func_test
                )
                logger.info(f"prompting with message:\n{ask_llm_for_search_prompt}")

                if args.backend == "openai":
                    # directly use openai to finish tool_call
                    tool_model = make_model(
                        model="o3-mini-2025-01-31",
                        backend="openai",
                        logger=logger,
                        max_tokens=4096,
                        temperature=0,
                        batch_size=1,
                    )
                    traj = tool_model.codegen(ask_llm_for_search_prompt, num_samples=1,
                                              tools=[search_func_def_with_class_and_file_schema])[0]
                elif args.backend == "claude":
                    traj = greedy_model.codegen_litellm(ask_llm_for_search_prompt, num_samples=1, tools=[search_func_def_with_class_and_file_schema])[0]
                elif args.backend == "deepseek":
                    # directly use openai to finish tool_call
                    tool_model = make_model(
                        model="o3-mini",
                        backend="openai",
                        logger=logger,
                        max_tokens=4096,
                        temperature=0,
                        batch_size=1,
                    )
                    traj = tool_model.codegen(ask_llm_for_search_prompt, num_samples=1,
                                              tools=[search_func_def_with_class_and_file_schema])[0]
                else:
                    raise ValueError(f"Backend {args.backend} is not supported")
                if traj:
                    logger.info(f"Response for search for functionality test:\n{str(traj)}")
                    if "tool_call" in traj and traj["tool_call"]:
                        for tool_call in traj["tool_call"]:
                            if tool_call.function.name == "search_func_def_with_class_and_file":
                                try:
                                    arguments = tool_call.function.arguments
                                    argument_dict = json.loads(arguments)
                                except Exception as e:
                                    raise e
                                if argument_dict and isinstance(argument_dict, dict):
                                    class_name = argument_dict.get("class_name", "")
                                    function_name = argument_dict.get("function_name", "")
                                    if function_name:
                                        found_file_name, found_class_name, function_code = search_func_def_with_class_and_file(structure=structure, function_name=function_name, class_name=class_name)
                                        failed_functionality_test_info[function_name] = {"class_name": found_class_name, "file_name": found_file_name, "function_code": function_code}
                                        break
            
            for function_name, info in failed_functionality_test_info.items():
                for task in args.tasks_list:
                    if task.task_id == instance_id:
                        test_cmd = task.test_cmd
                        match_string = f'{function_name} and {info["file_name"]}'
                        if info["class_name"]:
                            match_string += f' and {info["class_name"]}'
                        if 'pytest' in test_cmd:
                            test_cmd_one_func = f"pytest --no-header -rA --tb=short -v -p no:cacheprovider -k \'{match_string}\'"
                        elif 'tox' in test_cmd:
                            test_cmd_one_func = test_cmd.split('--')[0]
                            test_cmd_one_func += f' -- --no-header -rA --tb=short -v -p no:cacheprovider -k \'{match_string}\''
                        else:
                            test_cmd_one_func = ''
                        if test_cmd_one_func:
                            task.reset_project()
                            task.apply_patch(base_patch_diff)
                            output = task.execute_functionality_test_only_fail(test_cmd_one_func)
                            output['stdout']=output['stdout'][-500:]
                            output['stderr']=output['stderr'][-500:]
                            info["function_test_output"] = output

            for function_name, info in failed_functionality_test_info.items():
                functionality_newly_failed_prompt += f"\nHere is the failed functionality test code:\n{info['function_code']}\n"
                if "function_test_output" in info:
                    functionality_newly_failed_prompt += f"\nHere is the output of the failed functionality test:\n{str(info['function_test_output'])}\n"
        
        # We also provide the original output of the failed functionality test
        if functionality_newly_failed and functionality_fail_increase > 0:
            functionality_newly_failed_prompt += f"\nHere are the failed functionality tests:\n\n\n{functionality_test_fail_diff_whole}\n"
        
    feedback_prompt = base_patch_prompt + poc_code_prompt + failded_poc_output_reason_prompt + functionality_newly_failed_prompt

    # Construct file contents
    file_contents = dict()
    # pred_files are the files that we have localized
    for i, pred_file in enumerate(pred_files):
        content = None
        # files are all files in the repo, index 0 is the file name, index 1 is the content
        for file_content in files:
            if file_content[0] == pred_file:
                content = "\n".join(file_content[1])
                file_contents[pred_file] = content
                break

        assert content is not None, f"{pred_file} file not found"
    
    # If we need to redo localization for the current instance, we discard the previous best patch (as it was based on the previous localization)
    if args.refine_mod and ( (instance_id in reloca_ids) or did_relocate ):
        
        file_loc_intervals = {}
        for i, pred_file in enumerate(pred_files):
            if len(loc['found_edit_locs']) > i:
                _, context_intervals, _, _ = transfer_arb_locs_to_locs(
                    loc['found_edit_locs'][i],
                    None,
                    pred_files[i],
                    args.context_window,
                    True,
                    False,
                    file_content=file_contents[pred_file]
                    if pred_file in file_contents
                    else "",
                )
            else:
                context_intervals = []  # default values.

            file_loc_intervals[pred_file] = context_intervals
        previous_loc_prompt = f"Here are the previous localization results for the issue:\n"
        for i, pred_file in enumerate(pred_files):
            if file_loc_intervals.get(pred_file):
                previous_loc_prompt += f"File {pred_file}: Line interval {file_loc_intervals.get(pred_file)}\n"
        additional_prompt = 'The previous localization and patch may not have addressed all the relevant code for the issue. Your task is to analyze the current patch and identify any related code segments that are not covered by the current localization results but are still relevant to fixing the issue.'
        additional_prompt += previous_loc_prompt
        additional_prompt += feedback_prompt
        print(f"Redoing localization for the current instance {instance_id}")
        logger.info(f"Redoing localization for the current instance {instance_id}")
        modified_funcs=find_modified_functions(base_patch_diff, structure)
        modified_funcs_to_callers = {}
        modified_funcs_to_same_name_funcs = {}
        files, classes, functions = get_full_file_paths_and_classes_and_functions(structure)
        if modified_funcs and len(modified_funcs) <= 3:
            for func in modified_funcs:
                all_callers = find_callers_by_name(func, structure)
                all_callers = all_callers[:3]
                for caller in all_callers:
                    if caller['file'] not in loc['found_files']:
                        if func not in modified_funcs_to_callers:
                            modified_funcs_to_callers[func] = []
                        modified_funcs_to_callers[func].append(caller)
                all_defs = find_definitions_by_name(func, structure)
                for all_def in all_defs:
                    if all_def['file'] not in loc['found_files']:
                        if func not in modified_funcs_to_same_name_funcs:
                            modified_funcs_to_same_name_funcs[func] = []
                        modified_funcs_to_same_name_funcs[func].append(all_def)
        additional_prompt += "\nHere are the callers of the modified functions, and the functions that may be related to the modified functions\n"
        for func, callers in modified_funcs_to_callers.items():
            for caller in callers:
                additional_prompt += f"For modified function {func}, we found a caller in File {caller['file']}: Line interval {caller['start_line']}-{caller['end_line']}, caller function {caller.get('caller_name','unknown')}\n"
                additional_prompt += f"Here is the content of the caller function:\n" + extract_file_content(files,caller['file'], caller['start_line'], caller['end_line']) + "\n"
        for func, same_name_funcs in modified_funcs_to_same_name_funcs.items():
            for same_name_func in same_name_funcs:
                additional_prompt += f"For modified function {func}, we found a function with the same name in File {same_name_func['file']}: Line interval {same_name_func['start_line']}-{same_name_func['end_line']}\n"
                additional_prompt += f"Here is the content of the function:\n" + extract_file_content(files,same_name_func['file'], same_name_func['start_line'], same_name_func['end_line']) + "\n"
        loc = redo_localization(instance_id, args, logger, loc, additional_prompt, problem_statement, structure, not_found_file_dict=not_found_file_dict)
        # get the new localization results
        pred_files = loc["found_files"]
        file_contents = dict()
        # pred_files are the files that we have localized
        for i, pred_file in enumerate(pred_files):
            content = None

            # files are all files in the repo, index 0 is the file name, index 1 is the content
            for file_content in files:
                if file_content[0] == pred_file:
                    content = "\n".join(file_content[1])
                    file_contents[pred_file] = content
                    break

            assert content is not None, f"{pred_file} file not found"
        file_loc_intervals = {}
        for i, pred_file in enumerate(pred_files):
            if len(loc['found_edit_locs']) > i:
                _, context_intervals, _, _ = transfer_arb_locs_to_locs(
                    loc['found_edit_locs'][i],
                    None,
                    pred_files[i],
                    args.context_window,
                    True,
                    False,
                    file_content=file_contents[pred_file]
                    if pred_file in file_contents
                    else "",
                )
            else:
                context_intervals = []  # default values.
        global reloca_locs
        reloca_locs[instance_id] = loc  # save the new localization results
        base_patch_diff = ""

    # Construct top-n file context
    file_to_edit_locs = dict()
    for i, pred_file in enumerate(pred_files):
        if "found_edit_locs" in loc and len(loc["found_edit_locs"]) > i:
            file_to_edit_locs[pred_file] = loc["found_edit_locs"][i]

    num_diff_lines = 0
    for file_name in file_to_edit_locs:
        if commit_dict and file_name in commit_dict:
            num_diff_lines += len(commit_dict[file_name].splitlines())
    if num_diff_lines > 180:
        logger.info(f"We don't use the commit diff since the diff is too large, num_diff_lines: {num_diff_lines}")
        commit_dict = {}

    topn_content, file_loc_intervals, _, _ = construct_topn_file_context(
        file_to_edit_locs,
        pred_files,
        file_contents,
        structure,
        context_window=args.context_window,
        loc_interval=args.loc_interval,
        fine_grain_loc_only=args.fine_grain_loc_only,
        add_space=args.add_space,
        sticky_scroll=args.sticky_scroll,
        no_line_number=True,
        commit_dict=commit_dict,
        intended_behavior=args.intended_behavior,
        problem_statement=problem_statement,
        logger=logger,
        greedy_model=greedy_model,
    )

    if topn_content.strip() == "":
        return None
    if args.diverse:
        # construct the context for function granularity
        file_to_edit_locs_func = copy.deepcopy(file_to_edit_locs)
        for file_name, locs in file_to_edit_locs_func.items():
            locs_list = locs.splitlines()
            locs_list_without_line = [line if 'line:' not in line else '' for line in locs_list]
            locs_without_line = '\n'.join(locs_list_without_line)
            file_to_edit_locs_func[file_name] = locs_without_line
        topn_content_func_gran, file_loc_intervals_func, _, _ = construct_topn_file_context(
            file_to_edit_locs_func,
            pred_files,
            file_contents,
            structure,
            context_window=args.context_window,
            loc_interval=args.loc_interval,
            fine_grain_loc_only=args.fine_grain_loc_only,
            add_space=args.add_space,
            sticky_scroll=args.sticky_scroll,
            no_line_number=True,
            commit_dict=commit_dict,
            intended_behavior=args.intended_behavior,
            greedy_model=greedy_model,
            logger=logger,
            problem_statement=problem_statement,
        )

    plannings = []
    example = planning_example_format
    
    # with verifier, get batch_size plans and generate batch_size patches, let verifier to find one patch that can pass the verification
    # note that for the last batch, args.batch_size may be modified to be smaller
    if args.sample_mod or base_patch_diff == "":
        message_get_plan = planning_prompt_random_file.format(
            problem_statement=problem_statement,
            content=topn_content.rstrip(),
            example=example,
            files=' '.join(file_loc_intervals.keys())
        ).strip()
    elif args.refine_mod:
        content = topn_content.rstrip()
        if instance_id in reloca_ids or did_relocate:
            feedback_prompt += '\n The previous patch may have targeted incorrect locations, such as the wrong lines, functions, or files. Your need to carefully evaluate and double-check to propose a plan that patches the correct locations to effectively resolve the issue.'
            feedback_prompt += '\n Note that the provided previous patch is just for reference, we will not apply it to the codebase. You need to propose a new patch based on the current code context.'
        message_get_plan = planning_prompt_poc_feedback.format(
            problem_statement=problem_statement,
            content=content,
            example=example,
            feedback=feedback_prompt,
        ).strip()
    else:
        raise ValueError("invalid mode, must be sample_mod or refine_mod")
    
    planning_trajs = []
    # get one greedy plan for the first batch
    if num_generated_sample == 0:
        logger.info(f"prompting with message:\n{message_get_plan}")
        print('generating greedy plan')
        planning_trajs = greedy_model.codegen(message_get_plan, num_samples=1)
        logger.info(f"Got response:\n{planning_trajs}")

    # get one greedy plan for fixing the bug in a general way
    if num_generated_sample == 0 and args.batch_size > 1:
        message_general = planning_prompt_general.format(
            problem_statement=problem_statement,
            content=topn_content.rstrip(),
            example=example,
        ).strip()
        print('generating big plan')
        logger.info(f"prompting with message:\n{message_general}")
        planning_trajs += greedy_model.codegen(message_general, num_samples=1)
        logger.info(f"Got response:\n{planning_trajs}")

    # get one greedy plan for fixing the bug with minimal modifications
    if num_generated_sample == 0 and args.batch_size > 2:
        message_minimal = planning_prompt_minimal.format(
            problem_statement=problem_statement,
            content=topn_content.rstrip(),
            example=example,
        ).strip()
        print('generating minimal plan')
        logger.info(f"prompting with message:\n{message_minimal}")
        planning_trajs += greedy_model.codegen(message_minimal, num_samples=1)
        logger.info(f"Got response:\n{planning_trajs}")

    # extra diversity by randomly select model for openai (gpt-4o, o1-mini), granularity, and prompt (general/minimal/normal)
    if args.diverse:
        cur_batch_left_sample_num = 0
        if num_generated_sample == 0:
            if args.batch_size > 3:
                cur_batch_left_sample_num = args.batch_size-3
        else:
            cur_batch_left_sample_num = args.batch_size

        if args.backend == "openai":
            availabel_model = {'gpt-4o': 0.8, 'o1-mini': 0.2}
        elif args.backend == "claude":
            availabel_model = {'claude-3-5-sonnet-20241022': 1}
        elif args.backend == "deepseek":
            availabel_model = {'deepseek-reasoner': 1}
        else:
            raise NotImplementedError(f"backend {args.backend} not implemented for diverse sampling")

        granularity = {'func':0.3, 'line':0.7}
        prompt_template = {'general':0.15, 'minimal':0.15, 'normal':0.7}
        include_reproduce_info = {'yes':0.5, 'no':0.5}

        # generate samples in the current batch
        for i in range(cur_batch_left_sample_num):
            model_sample = weighted_sampling(list(availabel_model.keys()), list(availabel_model.values()))
            granularity_sample = weighted_sampling(list(granularity.keys()), list(granularity.values()))
            prompt_sample = weighted_sampling(list(prompt_template.keys()), list(prompt_template.values()))
            include_reproduce_info_sample = weighted_sampling(list(include_reproduce_info.keys()), list(include_reproduce_info.values()))
            logger.info(f"model_sample: {model_sample}, granularity_sample: {granularity_sample}, prompt_sample: {prompt_sample}, include_reproduce_info_sample: {include_reproduce_info_sample}")
            print(f"model_sample: {model_sample}, granularity_sample: {granularity_sample}, prompt_sample: {prompt_sample}, include_reproduce_info_sample: {include_reproduce_info_sample}")
            if granularity_sample == 'func':
                topn_content_sample = topn_content_func_gran
            else:
                topn_content_sample = topn_content

            if prompt_sample == 'general':
                message = planning_prompt_general.format(
                    problem_statement=problem_statement,
                    content=topn_content_sample.rstrip(),
                    example=example,
                ).strip()
            elif prompt_sample == 'minimal':
                message = planning_prompt_minimal.format(
                    problem_statement=problem_statement,
                    content=topn_content_sample.rstrip(),
                    example=example,
                ).strip()
            else: # normal
                message = planning_prompt_random_file.format(
                    problem_statement=problem_statement,
                    content=topn_content_sample.rstrip(),
                    example=example,
                    files=' '.join(file_loc_intervals.keys())
                ).strip()
            # if the instance is reproduced, 50% possibility to provide the reproduce info
            if include_reproduce_info_sample == 'yes':
                reproduce_info = ""
                if poc_code:
                    reproduce_info = poc_info_prompt.format(poc_code=poc_code, stdout=poc_orig_std_out, stderr=poc_orig_std_err)
                    message += reproduce_info

            logger.info(f"prompting with message:\n{message}")
            planning_trajs += make_model(
                model=model_sample,
                logger=logger,
                max_tokens=4096,
                backend=args.backend,
                temperature=1,
                batch_size=1,
            ).codegen(message, num_samples=1)
            logger.info(f"Got response:\n{planning_trajs}")
    # no extra diversity
    else:
        # sample batch_size plans                    
        model_sample = make_model(
            model=args.model,
            logger=logger,
            max_tokens=4096,
            backend=args.backend,
            temperature=1,
            batch_size=args.batch_size,
        )
        logger.info(f"prompting with message:\n{message_get_plan}")
        if num_generated_sample == 0:
            if args.batch_size > 3:
                planning_trajs += model_sample.codegen(message_get_plan, num_samples=args.batch_size-3)
        else:
            planning_trajs = model_sample.codegen(message_get_plan, num_samples=args.batch_size)
        logger.info(f"Got response:\n{planning_trajs}")

    for planning_traj in planning_trajs:
        reasoning_and_planning = planning_traj["response"]
        planning = ""
        try:
            planning = reasoning_and_planning.split("--- BEGIN STEPS ---")[1].split("--- END STEPS ---")[0]
        except:
            logger.error(f"plan format error, the response is {reasoning_and_planning}")
            print(f"plan format error, the response is {reasoning_and_planning}")
        if planning:
            plannings.append(planning)
    patch_candidates = []
    if args.diverse:
        for planning in plannings:
            model_sample = weighted_sampling(list(availabel_model.keys()), list(availabel_model.values()))
            granularity_sample = weighted_sampling(list(granularity.keys()), list(granularity.values()))
            granularity_sample = 'func'
            if granularity_sample == 'func':
                topn_content_sample = topn_content_func_gran
                file_loc_intervals_sample = file_loc_intervals_func
            else:
                topn_content_sample = topn_content
                file_loc_intervals_sample = file_loc_intervals
            patch_candidates += apply_plan_step_by_step(log_file, model_sample, planning, problem_statement, topn_content_sample,
                    args.backend, file_loc_intervals_sample, file_contents, granularity_sample, instance_id=instance_id, feedback_prompt=feedback_prompt, not_found_file_dict=not_found_file_dict)
    else:
        for planning in plannings:
            patch_candidates += apply_plan_step_by_step(log_file, args.model, planning, problem_statement, topn_content,
                                            args.backend, file_loc_intervals, file_contents, instance_id=instance_id, feedback_prompt=feedback_prompt, not_found_file_dict=not_found_file_dict)

    git_diffs = []
    raw_git_diffs = []
    count = num_generated_sample
    # post process, generate patch and metadata
    for patch_candidate in patch_candidates:
        print(f"trying the {count + 1}-th sample ...")
        count += 1
        did_relocalization = False
        if args.best_patch_file and os.path.exists(args.best_patch_file):
            best_patches = load_jsonl(args.best_patch_file)
            for entry in best_patches:
                if entry["instance_id"] == instance_id:
                    base_patch_diff = entry["model_patch"]
                    did_relocalization = entry.get("reloca", False)
                    break
        print(f"The final patch for the {count}-th sample:")
        if instance_id in reloca_ids or base_patch_diff == "" or did_relocalization: # refine mod or did reloca
            # If we did relocalization, we did not apply the best patch so far to the content
            git_diff, raw_git_diff, _, _, _, _, _, _ = post_process_raw_output(
            patch_candidate, file_contents, logger, file_loc_intervals, True
            )
        else:
            git_diff, raw_git_diff, _, _, _, _, _, _ = post_process_raw_output_refine(
                patch_candidate, file_contents, logger, file_loc_intervals, bench_data["repo"], bench_data["base_commit"], base_patch_diff
            )
        git_diffs.append(git_diff)
        raw_git_diffs.append(raw_git_diff)
    
    raw_outputs = [patch_candidate for patch_candidate in patch_candidates]
    
    # save generated patches to file
    # use lock to prevent multiple threads from writing to the same file at the same time
    with output_file_lock:
        if os.path.exists(args.output_file):
            prev_generations = load_jsonl(args.output_file)
            found = False
            for entry in prev_generations:
                if entry["instance_id"] == instance_id:
                    found = True
                    entry["raw_output"].extend(raw_outputs)
                    entry["git_diffs"].extend(git_diffs)
                    entry["raw_git_diffs"].extend(raw_git_diffs)
                    break
            if found:
                with open(args.output_file, "w") as f:
                    for entry in prev_generations:
                        f.write(json.dumps(entry) + "\n")
                    f.flush()
            else:  # previous generations do not contain the current instance, add it
                with open(args.output_file, "a") as f:
                    f.write(
                        json.dumps(
                            {
                                "instance_id": instance_id,
                                "raw_output": raw_outputs,
                                "git_diffs": git_diffs,
                                "raw_git_diffs": raw_git_diffs,
                            }
                        )
                        + "\n"
                    )
                    f.flush()
        else:
            # write the first instance
            with open(args.output_file, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "instance_id": instance_id,
                            "raw_output": raw_outputs,
                            "git_diffs": git_diffs,
                            "raw_git_diffs": raw_git_diffs,
                        }
                    )
                    + "\n"
                )
                f.flush()


def redo_localization(instance_id, args, logger, loc, additional_prompt, problem_statement, structure, not_found_file_dict=None):
    def merge_edit_locs(found_edit_locs, loc):
        for i, edit_loc in enumerate(found_edit_locs):
            if edit_loc[0] and i < len(loc["found_edit_locs"]):
                loc["found_edit_locs"][i] = loc["found_edit_locs"][i]+'\n'+edit_loc[0]
            else:
                loc["found_edit_locs"].append(edit_loc[0])
        return loc
    
    pred_files=copy.deepcopy(loc["found_files"])
    found_related_locs=loc["found_related_locs"]
    coarse_found_locs = dict()
    num_samples=3
    
    # search
    fl = LLMFL(
        instance_id,
        structure,
        problem_statement,
        args.model,
        args.backend,
        logger,
        True,
        1,
    )
    search_str_with_file = dict()
    search_str_with_file = fl.search_in_problem_statement(additional_prompt)
    loc_file_add_prompt = additional_prompt + 'Please localize the related files that are NOT COVERED by the current localization results. DO NOT include the files that are already covered by the current localization results. RETURN at most TWO files that are most likely to contain the bug.'
    loc_file_add_prompt += f"Here are the files that are already localized: {pred_files}."
    loc_file_add_prompt += f"If all the files are already localized, please return an empty string."
    if instance_id in not_found_file_dict:
        loc_file_add_prompt += f"Here are the files that are not found in the current codebase but were mentioned during generation: {not_found_file_dict[instance_id]}. You should pay more attention to these files.\n You should consider this file as very important to fix the bug."
    
    # reloca files
    new_loca_files_prompt = ""
    newly_found_files, _, _ = fl.localize(
        mock=False,
        match_partial_paths=True,
        search_res_files=search_str_with_file,
        num_samples=1,
        top_n=args.top_n,
        coverage_info=dict(),
        additional_info=loc_file_add_prompt
    )
    for file in newly_found_files:
        if file not in pred_files:
            new_loca_files_prompt += f"Here is a newly found file: {file}, you should pay more attention to this file.\n"
            pred_files.append(file)
    
    # reloca functions
    loc_func_add_prompt = additional_prompt + 'Please localize the related functions and Classes that are NOT COVERED by the current localization results. Do not include the functions and Classes that are already covered by the current localization results.' + new_loca_files_prompt
    found_related_locs_new = []   
    (
        found_related_locs_new,
        _,
        _,
    ) = fl.localize_function_from_compressed_files(
        pred_files, mock=args.mock, num_samples=args.num_samples, coverage_info=dict(), additional_info=loc_func_add_prompt,
    )
    for i,related_locs in enumerate(found_related_locs_new):
        if i < len(found_related_locs):
            found_related_locs[i][0] = found_related_locs_new[i][0]+'\n'+related_locs[0]
        else:
            found_related_locs.append(related_locs)

    # reloca lines
    loc_line_add_prompt = additional_prompt + 'Remember that you need to identify the related function, class or lines that are NOT COVERED by the current localization results. Do not include the functions, classes or lines that are already covered by the current localization results. If you are not sure about the line number, just return the Class or function name.'
    for i,related_locs in enumerate(found_related_locs):
        coarse_found_locs[pred_files[i]] = related_locs
    (
        found_edit_locs,
        additional_artifact_loc_edit_location,
        edit_loc_traj,
    ) = fl.localize_line_from_coarse_function_locs(
        pred_files,
        coarse_found_locs,
        context_window=20,
        add_space=False,
        code_graph=False,
        code_graph_context=None,
        no_line_number=False,
        sticky_scroll=False,
        mock=False,
        num_samples=num_samples,
        coverage_info=None,
        last_search_results = loc_line_add_prompt
    )
    # found_edit_locs
    loc['found_files']=pred_files
    loc['found_related_locs'] = found_related_locs
    if num_samples > 1:
        for found_edit_locs_sample in found_edit_locs:
            loc = merge_edit_locs(found_edit_locs_sample, loc)
    else:
        loc = merge_edit_locs(found_edit_locs, loc)
    return loc
    

def repair(args):
    if args.benchmark == "lite":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    elif args.benchmark == "verified":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    else:
        raise ValueError(f"benchmark {args.benchmark} not supported")
    task_ids_to_repair = args.task_ids_to_repair
    assert len(task_ids_to_repair) > 0, "No task ids to run."
    print(f"all task ids: {task_ids_to_repair}")
    locs = [loc for loc in locs_global if loc.get('instance_id') in task_ids_to_repair]
    
    if len(locs) == 0:
        print("No task ids to run.")
        exit(0)
    
    with open(f"{args.output_folder}/used_locs.jsonl", "w") as f:
        for loc in locs:
            f.write(json.dumps(loc) + "\n")
            
    prev_generations = []
    if os.path.exists(args.raw_output_file):
        prev_generations = load_jsonl(args.raw_output_file)
        
    
    if args.num_threads == 1:
        for loc in tqdm(locs, total=len(locs)):
            process_loc(loc, args, swe_bench_data, prev_generations)
    else:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.num_threads
        ) as executor:
            futures = {
                executor.submit(process_loc, loc, args, swe_bench_data, prev_generations): loc
                for loc in locs
            }
            for future in tqdm(
                    concurrent.futures.as_completed(futures), total=len(locs)
            ):
                result = future.result()


def post_process_repair(args):
    """
    apply some diff formatting.
    """
    raw_outputs = load_jsonl(args.raw_output_file)

    for raw_output in raw_outputs:
        git_diff = ""
        raw_git_diff = ""
        instance_id = raw_output["instance_id"]
        if instance_id not in args.task_ids_to_repair:
            continue
        skip=False
        if os.path.exists(args.output_file):
            with open(args.output_file, "r") as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("instance_id") == instance_id:
                        # If a match is found, skip further processing
                        skip=True
                        break
        if skip:
            continue

        if raw_output["raw_output"] == "":
            with open(args.output_file, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "model_name_or_path": "PatchingPilot",
                            "instance_id": instance_id,
                            "model_patch": "",
                        }
                    )
                    + "\n"
                )
            continue

        if args.select_id == -1:
            # Use the last generation
            assert False, "not implemented for now"
        else:
            # Use the indexed generation
            generation_idx = args.select_id
            if generation_idx >= len(raw_output["git_diffs"]) or generation_idx >= len(raw_output["raw_git_diffs"]):
                continue
            git_diff = raw_output["git_diffs"][generation_idx]
            raw_git_diff = raw_output["raw_git_diffs"][generation_idx]       
        
        print(f"The patch for the {generation_idx}-th patch in post process:")
        print(f'model_patch: {git_diff.lstrip()}')
        
        with open(args.output_file, "a") as f:
            f.write(
                json.dumps(
                    {
                        "model_name_or_path": "PatchingPilot",
                        "instance_id": instance_id,
                        "model_patch": git_diff.lstrip(),
                        "raw_model_patch": raw_git_diff.lstrip(),
                    }
                )
                + "\n"
            )


def get_line_change_num(patch):
    lines = patch.split("\n")
    line_change_num = 0
    for line in lines:
        if line.startswith("+") or line.startswith("-"):
            line_change_num += 1
    return line_change_num


def get_final_patch_instance(args, instance_id, locs, final_patches, final_ranks, all_predictions):
        patches = all_predictions[instance_id]
        min_value = min(patches.values())
        final_ranks[instance_id] = min_value
        min_patches = [patch for patch in patches if patches[patch] == min_value]
        if len(min_patches) == 1:
            final_patches[instance_id] = min_patches[0]
        elif len(min_patches) > 1:
            # use llm to vote
            loc = [loc for loc in locs if loc["instance_id"] == instance_id][0]
            break_tie(args, loc, instance_id, final_patches, min_patches)


def break_tie(args, loc, instance_id, final_patches, min_patches):
    log_file = os.path.join(
        args.output_folder, "rerank_by_verification", instance_id, f"break_tie.log"
    )
    ensure_directory_exists(os.path.join(
        args.output_folder, "rerank_by_verification", instance_id
    ))
    logger = setup_logger(log_file)

    # get all the information needed
    if args.benchmark == "lite":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    elif args.benchmark == "verified":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    else:
        raise ValueError(f"benchmark {args.benchmark} not supported")
    bench_data = [x for x in swe_bench_data if x["instance_id"] == instance_id][0]
    problem_statement = bench_data["problem_statement"]
    pred_files = loc["found_files"][: args.top_n]
    structure = get_repo_structure(
        instance_id, bench_data["repo"], bench_data["base_commit"], "playground"
    )
    files, _, _ = get_full_file_paths_and_classes_and_functions(structure)
    file_contents = dict()
    for i, pred_file in enumerate(pred_files):
        content = None

        for file_content in files:
            if file_content[0] == pred_file:
                content = "\n".join(file_content[1])
                file_contents[pred_file] = content
                break

        assert content is not None, f"{pred_file} file not found"

    # Construct top-n file context
    file_to_edit_locs = dict()
    for i, pred_file in enumerate(pred_files):
        if "found_edit_locs" in loc and len(loc["found_edit_locs"]) > i:
            file_to_edit_locs[pred_file] = loc["found_edit_locs"][i]

    # let llm vote
    patch_candidate_prompt = ''
    # line_change_scores=[]
    for i, patch_candidate in enumerate(min_patches):
        patch_candidate_prompt += f"--- BEGIN PATCH {i + 1} ---\n{patch_candidate}\n--- END PATCH {i + 1} ---\n"

    model = make_model(
        model=args.model,
        logger=logger,
        max_tokens=4096,
        backend=args.backend,
        temperature=0.8,
        batch_size=len(min_patches),
    )
    message = vote_patch_prompt.format(
        problem_statement=problem_statement,
        content="",#topn_content.rstrip(),
        patches=patch_candidate_prompt,
    ).strip()
    logger.info(f"Instance_id {instance_id}: voting with breaktie message:\n{message}")
    vote_results = [0] * len(min_patches)
    while sum(vote_results) == 0:
        vote_traj = model.codegen(message, num_samples=1)
        vote_outputs = [vote_traj["response"] for vote_traj in vote_traj]
        vote_results = vote_outputs_unwrap(vote_outputs, len(min_patches))
    logger.info(f"Instance_id {instance_id}: voting results:\n{vote_results}")
    best_one_idx = sorted(range(len(vote_results)), key=lambda i: vote_results[i], reverse=True)[0]
    final_patches[instance_id] = min_patches[best_one_idx]
    logger.info(f"Instance_id {instance_id}: best one patch:\n{final_patches[instance_id]}")


def get_rank_from_verify_info(args, verify_info, model_patch) -> float:
    if model_patch.strip() == "":
        return sys.maxsize
    poc_test_succeed_llm = verify_info["result"].get('poc_test_succeed_llm', [])
    poc_test_succeed_rule = verify_info["result"].get('poc_test_succeed_rule', [])
    num_failed_poc_llm = len([x for x in poc_test_succeed_llm if not x])
    num_failed_poc_rule = len([x for x in poc_test_succeed_rule if not x])
    increased_failed_tests = 0
    if not args.no_func:
        increased_failed_tests = verify_info["result"]["functionality_test_fail_num"][
                "new_failed_tests_num"] - verify_info["result"]["functionality_test_fail_num"][
                    "old_failed_tests_num"]
    rank = num_failed_poc_llm + max(0, increased_failed_tests)*0.1
    return rank


def rerank_by_verification(args, num_generated_sample_before, num_generated_sample, best_patch_file=None):
    # key is the instance_id, value is also a dict, with key being the patch and value being the rank (listed above)
    all_predictions = dict()

    # key is the instance_id, value is the patch        
    final_patches = dict()
    # key is the instance_id, value is the rank
    final_ranks = dict()

    # also output a file containing the final patch passing all verifications (for debugging)

    patches_passed_all_verifications = dict()
    
    # also output a file containing the final patch passing all functionality tests (for debugging)
    
    patches_passed_all_functionality_tests_no_poc = dict()
    
    global reloca_ids
    reloca_ids = []

    for i in range(num_generated_sample_before, num_generated_sample):
        with open(args.raw_output_file.replace(
                ".jsonl", f"_{i}_processed.jsonl"), "r") as f:
            for line in f:
                result = json.loads(line)
                instance_id = result["instance_id"]
                if instance_id not in args.task_ids_to_repair:
                    continue
                if "model_patch" in result:
                    verify_file = args.verify_folder + os.path.join(f"/samples_{i}", instance_id, "verify_outputs.json")
                    if os.path.exists(verify_file):
                        print("checking the verification file", verify_file)
                        with open(verify_file, "r") as f:
                            verify_info = json.load(f)
                        model_patch = result["model_patch"]
                        rank = get_rank_from_verify_info(args, verify_info, model_patch)                     
                    else:
                        rank = sys.maxsize
                if instance_id not in all_predictions:
                    all_predictions[instance_id] = {result["model_patch"]: rank}
                else:
                    # if there are multiple patches that are exactly the same, we only keep the one with the smallest rank, since the verification res may be unstable
                    all_predictions[instance_id][result["model_patch"]] = min(rank, all_predictions[instance_id].get(
                        result["model_patch"], sys.maxsize))

    if best_patch_file:
        with open(best_patch_file, "r") as f:
            for line in f:
                result = json.loads(line)
                instance_id = result["instance_id"]
                if instance_id not in args.task_ids_to_repair:
                    continue
                previous_best_index = result["sample_idx"]
                previous_best_patch = result["model_patch"]
                # we need to get the rank of the previous best patch
                verify_file = args.verify_folder + os.path.join(f"/samples_{previous_best_index}", instance_id, "verify_outputs.json")
                if os.path.exists(verify_file):
                    print("checking the verification file", verify_file)
                    with open(verify_file, "r") as f:
                        verify_info = json.load(f)
                    rank = get_rank_from_verify_info(args, verify_info, previous_best_patch)                          
                else:
                    rank = sys.maxsize

                # no patch is generated in the current round
                if instance_id not in all_predictions:
                    all_predictions[instance_id] = {previous_best_patch: rank}
                    reloca_ids.append(instance_id)                    
                else:
                    ranks_this_round = [rank for patch, rank in all_predictions[instance_id].items()]
                    all_predictions[instance_id][previous_best_patch] = min(rank, all_predictions[instance_id].get(
                        previous_best_patch, sys.maxsize))
                    #if the previous best patch is better than all the patches in the current round and the rank is not 0, we need to relocalize
                    if min(ranks_this_round) >= rank and rank!=0: 
                        reloca_ids.append(instance_id)

    # decide the final patches and break ties
    ensure_directory_exists(os.path.join(args.output_folder, "rerank_by_verification"))
    if args.num_threads == 1:
        for instance_id in tqdm(all_predictions, total=len(args.task_ids_to_repair)):
            get_final_patch_instance(args, instance_id, locs_global, final_patches, final_ranks, all_predictions)
    else:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.num_threads
        ) as executor:
            futures = {
                executor.submit(get_final_patch_instance, args, instance_id, locs_global, final_patches, final_ranks, all_predictions): instance_id
                for instance_id in all_predictions
            }
            for future in tqdm(
                    concurrent.futures.as_completed(futures), total=len(args.task_ids_to_repair)
            ):
                result = future.result()

    # save the patch that pass checks
    for instance_id in all_predictions:
        # we need to get the verify_info to check if the poc is executed
        verify_file = args.verify_folder + os.path.join(f"/samples_0", instance_id, "verify_outputs.json")
        has_poc = False
        if os.path.exists(verify_file):
            verify_info = json.load(open(verify_file, "r"))
            if verify_info["result"]["poc_is_executed"]:
                has_poc = True
        if final_ranks[instance_id] == 0:
            patches_passed_all_verifications[instance_id] = final_patches[instance_id]
        if final_ranks[instance_id] == 0 and not has_poc:
            patches_passed_all_functionality_tests_no_poc[instance_id] = final_patches[instance_id]
    # get the indices of the final patches (which sample they are from)
    final_patch_indices = dict()

    for i in range(num_generated_sample):
        with open(args.raw_output_file.replace(".jsonl", f"_{i}_processed.jsonl"), "r") as f:
            for line in f:
                result = json.loads(line)
                if result["instance_id"] in final_patch_indices:
                    continue
                instance_id = result["instance_id"]
                if "model_patch" in result and instance_id in final_patches:
                    if result["model_patch"] == final_patches[instance_id]:
                        final_patch_indices[instance_id] = i
    return final_patches, patches_passed_all_verifications, patches_passed_all_functionality_tests_no_poc, final_ranks, final_patch_indices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loc_file", type=str, required=True)
    parser.add_argument("--top_n", type=int, default=1)
    parser.add_argument("--loc_interval", action="store_true")
    parser.add_argument("--context_window", type=int, default=10)
    parser.add_argument("--max_samples", type=int, default=20, help="Sampling budget.")
    parser.add_argument("--batch_size", type=int, default=-1)
    parser.add_argument(
        "--select_id",
        type=int,
        default=-1,
        help="Index the selected samples during post-processing.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-2024-08-06",
    )
    parser.add_argument(
        "--backend", type=str, default="openai", choices=["openai", "deepseek", "claude"]
    )
    parser.add_argument("--output_folder", type=str, required=True)
    parser.add_argument("--add_space", action="store_true")
    parser.add_argument("--fine_grain_loc_only", action="store_true")
    parser.add_argument("--sticky_scroll", action="store_true")
    parser.add_argument("--planning", action="store_true")
    parser.add_argument("--intended_behavior", action="store_true")
    parser.add_argument("--n_plan", type=int, default=3)
    parser.add_argument(
        "--task_list_file",
        type=str,
        help="Path to the file that contains all tasks ids to be run.",
    )
    parser.add_argument("--target_id", type=str)
    # args for reproduce and verify
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

    parser.add_argument("--verify_folder", type=str)
    parser.add_argument("--reproduce_folder", type=str)
    # args for sampleing/refinement
    parser.add_argument("--sample_mod", action="store_true")
    parser.add_argument("--refine_mod", action="store_true")
    parser.add_argument("--refine_for_nopoc", action="store_true")
    parser.add_argument("--reloca_for_nopoc", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--no_func", action="store_true")
    parser.add_argument("--benchmark", type=str, default="lite", choices=["lite", "verified"])
    parser.add_argument(
        "--num_threads",
        type=int,
        default=1,
        help="Number of threads to use for creating API requests",
    )
    parser.add_argument(
        "--mock", action="store_true", help="Mock run to compute prompt tokens."
    )
    parser.add_argument(
        "--diverse", action="store_true", help="extra diverse when doing sampling"
    )

    args = parser.parse_args()

    # if sample_mod and refine_mod are both true or both false, we will use sample_mod by default
    if args.sample_mod == args.refine_mod:
        args.sample_mod = True
    if args.batch_size > args.max_samples:
        args.batch_size = args.max_samples
    if args.batch_size < 1:
        args.batch_size = args.max_samples
    print("genearting samples:", args.max_samples)
    print("batch size:", args.batch_size)

    ensure_directory_exists(args.output_folder)
    with open(f"{args.output_folder}/args.json", "w") as f:
        json.dump(vars(args), f, indent=4)
        
    global locs_global
    locs_global = load_jsonl(args.loc_file)

    assert not (args.target_id is not None and args.task_list_file is not None), "Cannot specify both task and task-list."
    if args.task_list_file is not None:
        all_task_ids = parse_task_list_file(args.task_list_file)
    elif args.target_id is not None:
        all_task_ids = [args.target_id]
    else:
        all_task_ids = [loc["instance_id"] for loc in locs_global]
    
    assert len(all_task_ids) > 0, "No task ids to run."
    args.all_task_ids = all_task_ids
    args.task_ids_to_repair = all_task_ids

    assert (args.tasks_map is not None) and (args.setup_map is not None) and (args.verify_folder is not None) and (
                args.reproduce_folder is not None), "Must specify `--tasks_map`, `--setup_map`, `--verify_folder`, and `--reproduce_folder` if using `--repro_and_verify`"
    args.repro_output_file = os.path.join(args.output_folder, "reproduce_outputs.json")
    args.tasks_list = make_swe_tasks(all_task_ids, args.setup_map,
                                        args.tasks_map)  # these are tasks compatible with repro and verify
    args.patch_folder = args.output_folder
    args.num_samples = args.max_samples
    args.deduplicate = True
    args.plausible = True
    args.best_patch_file = None
    args.repro_output_file = os.path.join(args.reproduce_folder, "reproduce_outputs.json")
    ensure_directory_exists(os.path.join(args.reproduce_folder, "reproduce_logs"))

    assert (not "deepseek" in args.model) or (
            args.backend == "deepseek"
    ), "Must specify `--backend deepseek` if using a DeepSeek model"

    assert (not "claude" in args.model) or (
            args.backend == "claude"
    ), "Must specify `--backend claude` if using a Claude model"
    ensure_directory_exists(args.output_folder)
    ensure_directory_exists(os.path.join(args.output_folder, "repair_logs"))

    args.output_file = os.path.join(args.output_folder, "output.jsonl")
    args.raw_output_file = args.output_file
    global orig_verify_folder
    orig_verify_folder = args.verify_folder
    global round_idx
    global num_generated_sample
    global reloca_ids
    global reloca_locs
    global last_round

    # repair and post-process
    # reproduce
    print(" ################### reproducing ##################### ")
    reproduce(args)
    print(" ################### reproduce finished ##################### ")

    # batch generation and verification
    finish_gen_ids = []

    while num_generated_sample < args.max_samples:
        num_generated_sample_before = num_generated_sample
        if args.max_samples - num_generated_sample <= args.batch_size:
            args.batch_size = args.max_samples - num_generated_sample
            last_round = True
        print(f"already generated {num_generated_sample} examples")
        print(f"generating the {num_generated_sample + 1}th to {num_generated_sample + args.batch_size}th examples in round {round_idx}")
        repair(args)  # output.jsonl should have all generations in this round
        for i in range(args.batch_size):
            args.output_file = args.raw_output_file.replace(
                ".jsonl", f"_{num_generated_sample + i}_processed.jsonl"
            )
            args.select_id = num_generated_sample + i
            # do postprocess and save the processed output file to f"_{num_generated_sample+i}_processed.jsonl"
            post_process_repair(args)

        # for each output file in the round, do verification
            args.patch_file = args.output_file
            args.verify_folder = orig_verify_folder + f"/samples_{num_generated_sample+i}"
            ensure_directory_exists(args.verify_folder)
            print(f"=================== verifying the patch_file {args.patch_file} ===================")
            verify(args)

        # update round_idx and num_generated_sample
        args.output_file = args.raw_output_file  # reset the output file

        num_generated_sample += args.batch_size

        #if refine mode, rerank the patches by verification results for each round, save the results for each round
        if args.refine_mod:
            args.verify_folder = orig_verify_folder
            best_patches = dict()
            patches_passed_all_verifications = dict()
            patches_passed_all_functionality_tests_no_poc = dict()
            best_ranks = dict()
            final_patch_indices = dict()
            reloca_ids = []
            if os.path.exists(os.path.join(args.output_folder, f"best_patches_round_{round_idx}.jsonl")):
                print(f"best_patches_round_{round_idx}.jsonl already exists, skip reranking")
                # Read data from the existing file
                with open(os.path.join(args.output_folder, f"best_patches_round_{round_idx}.jsonl"), "r") as f:
                    for line in f:
                        result = json.loads(line)
                        instance_id = result["instance_id"]
                        best_patches[instance_id] = result["model_patch"]
                        best_ranks[instance_id] = result["rank"]
                        tmp_verify_folder = orig_verify_folder + f"/samples_{result['sample_idx']}"
                        verify_file = os.path.join(tmp_verify_folder, instance_id, "verify_outputs.json")
                        if os.path.exists(verify_file):
                            verify_info = json.load(open(verify_file, "r"))
                            if  result["rank"] == 0 and not verify_info["result"]["poc_is_executed"]:
                                patches_passed_all_functionality_tests_no_poc[instance_id] = result["model_patch"]
                        if result["rank"]==0:
                            patches_passed_all_verifications[instance_id] = result["model_patch"]
                        final_patch_indices[instance_id] = result["sample_idx"]
                        if result.get("reloca", False):
                            reloca_ids.append(instance_id)
                        reloca_loc = result.get('reloca_loc', None)
                        if reloca_loc:
                            for i, loc in enumerate(locs_global):
                                if loc['instance_id'] == instance_id:
                                    locs_global[i] = reloca_loc
                                    break
                            
            elif round_idx == 0:
                best_patches, patches_passed_all_verifications, patches_passed_all_functionality_tests_no_poc, best_ranks, final_patch_indices = rerank_by_verification(
                    args, 0, num_generated_sample)
            else:
                best_patches, patches_passed_all_verifications, patches_passed_all_functionality_tests_no_poc, best_ranks, final_patch_indices = rerank_by_verification(
                    args, 0, num_generated_sample, args.best_patch_file)

            finish_gen_ids_before = [id for id in finish_gen_ids]
            
            # If no poc and func test all pass, we don't need to refine the patch
            # don't need to refine the patch if it has no poc and all functionality tests pass
            if not args.refine_for_nopoc:
                for instance_id in patches_passed_all_functionality_tests_no_poc:
                    if args.reloca_for_nopoc:
                        have_relocated = False
                        if args.best_patch_file and os.path.exists(args.best_patch_file):
                            with open(args.best_patch_file, "r") as previous_best_patch_file:
                                for line in previous_best_patch_file:
                                    result = json.loads(line)
                                    if result["instance_id"] in instance_id:
                                        have_relocated = result.get("reloca", False)
                                        break
                        if not have_relocated:
                            reloca_ids.append(instance_id)
                        else:
                            finish_gen_ids.append(instance_id)
                    else:
                        finish_gen_ids.append(instance_id)

            # if the patch pass all verifications, we generate a poc specificly for the patch
            for instance_id in patches_passed_all_verifications:
                if instance_id in patches_passed_all_functionality_tests_no_poc:
                    continue
                task_list = [task for task in args.tasks_list if task.task_id == instance_id]
                if task_list == []:
                    continue
                task = task_list[0]
                task.patched_diff = patches_passed_all_verifications[instance_id]
                finish_gen_ids.append(instance_id)
            
            args.task_ids_to_repair = [id for id in args.task_ids_to_repair if id not in finish_gen_ids]
            args.tasks_list = [task for task in args.tasks_list if task.task_id not in finish_gen_ids]
            
            # if we did relocalization, and the best patch is a patch generated in the current round (not the previous best patch), we need to save the relocalization result
            reloca_res_to_save = dict()
            for instance_id in reloca_locs:
                previous_best_index = -1
                if args.best_patch_file and os.path.exists(args.best_patch_file):
                    with open(args.best_patch_file, "r") as previous_best_patch_file:
                        for line in previous_best_patch_file:
                            result = json.loads(line)
                            if result["instance_id"] == instance_id:
                                previous_best_index = result["sample_idx"]
                                break
                if final_patch_indices[instance_id] == previous_best_index:
                    continue
                reloca_res_to_save[instance_id] = reloca_locs[instance_id]
                for i, loc in enumerate(locs_global):
                    if loc['instance_id'] == instance_id:
                        locs_global[i] = reloca_locs[instance_id]
                        break
            
            reloca_locs=dict()
            
            with open(os.path.join(args.output_folder, f"best_patches_round_{round_idx}.jsonl"), "w") as f:
                for instance_id in best_patches:
                    result = {
                        "model_name_or_path": "patchingagent",
                        "instance_id": instance_id,
                        "model_patch": best_patches[instance_id],
                        "rank": best_ranks[instance_id],
                        "sample_idx": final_patch_indices[instance_id],
                        "reloca": instance_id in reloca_ids,
                        "reloca_loc": reloca_res_to_save.get(instance_id, None)
                    }
                    f.write(json.dumps(result) + "\n")
                if finish_gen_ids_before and args.best_patch_file and os.path.exists(args.best_patch_file):
                    with open(args.best_patch_file, "r") as previous_best_patch_file:
                        for line in previous_best_patch_file:
                            result = json.loads(line)
                            if result["instance_id"] in finish_gen_ids_before:
                                f.write(json.dumps(result) + "\n")
            args.best_patch_file = os.path.join(args.output_folder, f"best_patches_round_{round_idx}.jsonl")
            print(f"=================== Generating the best_patch_file {args.best_patch_file} ===================")

            with open(os.path.join(args.output_folder, f"patches_passed_all_verifications_round_{round_idx}.jsonl"), "w") as f:
                for instance_id in patches_passed_all_verifications:
                    result = {
                        "model_name_or_path": "patchingagent",
                        "instance_id": instance_id,
                        "model_patch": patches_passed_all_verifications[instance_id],
                    }
                    f.write(json.dumps(result) + "\n")
            with open(os.path.join(args.output_folder, f"patches_passed_all_functionality_tests_no_poc_round_{round_idx}.jsonl"), "w") as f:
                for instance_id in patches_passed_all_functionality_tests_no_poc:
                    result = {
                        "model_name_or_path": "patchingagent",
                        "instance_id": instance_id,
                        "model_patch": patches_passed_all_functionality_tests_no_poc[instance_id],
                    }
                    f.write(json.dumps(result) + "\n")
                     
        if args.task_ids_to_repair == []:
            break
        round_idx += 1

    # if sample_mod, only rerank after all samples are generated
    if args.sample_mod:
        args.verify_folder = orig_verify_folder
        if os.path.exists(os.path.join(args.output_folder, "final_patches.jsonl")):
            print("final_patches.jsonl already exists, skip reranking")
        else:               
            final_patches, patches_passed_all_verifications, patches_passed_all_functionality_tests_no_poc, final_ranks, final_patch_indices = rerank_by_verification(
                args, 0, num_generated_sample)
            with open(os.path.join(args.output_folder, "final_patches.jsonl"), "w") as f:
                for instance_id in final_patches:
                    result = {
                        "model_name_or_path": "patchingagent",
                        "instance_id": instance_id,
                        "model_patch": final_patches[instance_id],
                        "rank": final_ranks[instance_id],
                        "sample_idx": final_patch_indices[instance_id]
                    }
                    f.write(json.dumps(result) + "\n")
            with open(os.path.join(args.output_folder, "patches_passed_all_verifications.jsonl"), "w") as f:
                for instance_id in patches_passed_all_verifications:
                    result = {
                        "model_name_or_path": "patchingagent",
                        "instance_id": instance_id,
                        "model_patch": patches_passed_all_verifications[instance_id],
                    }
                    f.write(json.dumps(result) + "\n")
            with open(os.path.join(args.output_folder, "patches_passed_all_functionality_tests.jsonl"), "w") as f:
                for instance_id in patches_passed_all_functionality_tests_no_poc:
                    result = {
                        "model_name_or_path": "patchingagent",
                        "instance_id": instance_id,
                        "model_patch": patches_passed_all_functionality_tests_no_poc[instance_id],
                    }
                    f.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
