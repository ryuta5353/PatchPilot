import argparse
import argparse
import json
from datasets import load_dataset
from aiolimiter import AsyncLimiter
from jinja2 import Template
import copy
from multiprocessing import Pool, cpu_count
from functools import partial
import subprocess
import traceback

from patchpilot.util.utils_for_swe import *
from patchpilot.reproduce.prompt import *
from patchpilot.model_zoo.src.model_zoo.litellm_model import LiteLLMModel

def remove_container(container_id):
    try:
        run_command_in_container(container_id, "sync")  # flush fs just in case
        subprocess.run(["docker", "rm", "-f", container_id], check=True)
        print(f"Container {container_id} removed.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to remove container {container_id}: {e}")

def parse_pre_post_conditions(response):
    preconditions = ""
    post_conditions = ""
    declaration = ""
    content = response.choices[0].message.content
    lines = content.split("\n")
    current_section = None
    for line in lines:
        if "<declaration>" in line:
            current_section = "declaration"
        elif "</declaration>" in line:
            current_section = None
        elif "<preconditions>" in line:
            current_section = "preconditions"
        elif "</preconditions>" in line:
            current_section = None
        elif "<postconditions>" in line:
            current_section = "postconditions"
        elif "</postconditions>" in line:
            current_section = None
        else:
            if current_section == "preconditions":
                preconditions += line + "\n"
            elif current_section == "postconditions":
                post_conditions += line + "\n"
            elif current_section == "declaration":
                declaration += line + "\n"
    return preconditions, post_conditions, declaration

def inject_conditions(function_info):
    def get_indentation(line):
        return line[:len(line) - len(line.lstrip())]

    def adjust_indent_block(block_str, target_indent):
        lines = block_str.splitlines()
        if not lines:
            return []
        min_indent = min(len(get_indentation(line)) for line in lines if line.strip())
        adjusted = [target_indent + line[min_indent:] if line.strip() else "" for line in lines]
        return adjusted

    orig_code_lines = function_info["orig_code"].splitlines(keepends=True)
    declaration = function_info["declaration"]
    pre_conditions = function_info["pre_conditions"]
    post_conditions = function_info["post_conditions"]

    new_lines = orig_code_lines.copy()

    # 1. Replace the declaration (first line)
    orig_indent = get_indentation(orig_code_lines[0])
    decl_lines = adjust_indent_block(declaration, orig_indent)
    new_lines[0:1] = [line + "\n" for line in decl_lines]  # Replace the first line

    # 2. Insert pre-conditions after the (possibly multi-line) declaration
    decl_line_count = len(decl_lines)
    indent_for_pre = get_indentation(new_lines[decl_line_count]) if len(new_lines) > decl_line_count else "    "
    pre_lines = adjust_indent_block(pre_conditions, indent_for_pre)
    new_lines[decl_line_count:decl_line_count] = [line + "\n" for line in pre_lines]

    # 3. Insert post-conditions before last non-empty indented line (typically before return)
    insert_idx = len(new_lines) - 1
    for i in reversed(range(decl_line_count + 1, len(new_lines))):
        if new_lines[i].strip():
            insert_idx = i
            break
    post_lines = adjust_indent_block(post_conditions, indent_for_pre)
    new_lines[insert_idx:insert_idx] = [line + "\n" for line in post_lines]

    return "".join(new_lines)


def get_pre_post_conditions(function, problem_statement, model, feedback=None):
    preconditions = ""
    post_conditions = ""
    declaration = ""
    precondition_and_postcondition_template = Template(precondition_and_postcondition_user_prompt)
    prompt = precondition_and_postcondition_template.render(problem_statement=problem_statement, function=function, feedback=feedback)
    message = [{"role": "system", "content": precondition_and_postcondition_system_prompt},{"role": "user", "content": prompt}]
    response = model.query_once(messages=message)
    if response:
        preconditions, post_conditions, declaration = parse_pre_post_conditions(response)
    else:
        print(f"Failed to get pre/post conditions for function, {response}")
    return preconditions, post_conditions, declaration

def assertion_triggered(output):
    if "AssertionError" in output:
        return True
    return False

def patch_crosshair(container_id):
    """
    Patch CrossHair's auditwall to allow all events by overriding the reject function.
    This function auto-detects the Python 3.x version used inside the testbed environment.
    """
    new_code = """
def reject(event: str, args: Tuple) -> None:
    # Allow all events.
    pass
    """

    # Detect the correct Python 3.x version in the container
    cmd = "ls /opt/miniconda3/envs/testbed/lib | grep '^python3\\.'"
    output = run_command_in_container(container_id, cmd)
    lines = output.strip().splitlines()
    if not lines:
        print("Failed to detect Python version in container.")
        return

    python_version = lines[0]  # e.g. python3.9
    auditwall_path = f"/opt/miniconda3/envs/testbed/lib/{python_version}/site-packages/crosshair/auditwall.py"

    try:
        patch_function(container_id, auditwall_path, "reject", new_code)
    except Exception as e:
        print(f"Failed to patch crosshair: {e}")


def install_crosshair(container_id):
    res = run_command_in_container(container_id, "python -m pip install crosshair-tool")
    if "error" in res.lower():
        print(f"Failed to install crosshair-tool in container: {container_id}")
        print(res)
        return False
    return True

def prepare_env(container_id):
    if not install_crosshair(container_id):
        print("Failed to install crosshair-tool.")
        return False
    patch_crosshair(container_id)
    return True

def setup_container(instance_id):
    docker_image = get_instance_docker_image(instance_id)
    container_id = get_container(docker_image)
    if not container_id:
        raise ValueError(f"Container not found for instance_id: {instance_id}")
    return container_id

def generate_conditions_for_functions(container_id, functions_info, problem_statement, model, poc_code, retry):
    generated_function_info = {}
    feedback = ""
    assertion_triggered_flag = False
    retried = 0

    while not assertion_triggered_flag and retried < retry:
        reset(container_id)
        retried += 1
        # For each function, obtain pre and post conditions
        for function in functions_info:
            code = function[4]
            pre_conditions, post_conditions, declaration = get_pre_post_conditions(code, problem_statement, model, feedback)
            if not pre_conditions or not post_conditions:
                print(f"Pre-conditions or post-conditions not found for function")
                continue
            key = f"{function[0]}__xx__{function[1]}"
            generated_function_info[key] = {
                "pre_conditions": pre_conditions,
                "post_conditions": post_conditions,
                "declaration": declaration,
                "file_name": function[1],
                "function_name": function[0],
                "orig_code": function[4],
                "injected_code": "",
            }
        # Inject conditions and patch each function
        for function_key, function_info in generated_function_info.items():
            injected_code = inject_conditions(function_info)
            generated_function_info[function_key]["injected_code"] = injected_code
            patch_function(container_id, function_info["file_name"], function_info["function_name"], injected_code)
        # Exit loop if no poc code is provided
        if not poc_code:
            break
        poc_output = run_poc(container_id, poc_code)
        feedback = poc_output
        if assertion_triggered(poc_output):
            print("Assertion triggered before patch")
            assertion_triggered_flag = True
            break

    return generated_function_info, assertion_triggered_flag, feedback

def update_functions_after_patch(container_id, generated_function_info):
    after_patch_info = {}
    for function_key, function_info in generated_function_info.items():
        new_func_code = get_function_from_file(container_id, function_info["file_name"], function_info["function_name"])
        updated_info = copy.deepcopy(function_info)
        updated_info["orig_code"] = new_func_code
        injected_code = inject_conditions(updated_info)
        updated_info["injected_code"] = injected_code
        after_patch_info[function_key] = updated_info
        patch_function(container_id, updated_info["file_name"], updated_info["function_name"], injected_code)
    return after_patch_info

def process_poc_after_patch(container_id, poc_code):
    if not poc_code:
        return None, None
    poc_output = run_poc(container_id, poc_code)
    triggered = assertion_triggered(poc_output)
    if triggered:
        print("Assertion triggered after patch")
    return poc_output, triggered

def crosshair_check_local(generated_function_info, timeout):
    def dedent_code(code: str) -> str:
        lines = code.splitlines()

        # Skip empty or all-whitespace lines for indent analysis
        non_empty_lines = [line for line in lines if line.strip()]
        if not non_empty_lines:
            return code  # nothing to dedent

        # Find the minimum indentation (count of leading spaces) across non-empty lines
        import re
        indents = [len(re.match(r'^[ \t]*', line).group()) for line in non_empty_lines]
        min_indent = min(indents)

        # Dedent each line by min_indent, but don't strip completely empty lines
        dedented_lines = [
            line[min_indent:] if len(line) >= min_indent else line
            for line in lines
        ]
        return "\n".join(dedented_lines)
    

    crosshair_results = {}
    assertion_triggered_by_crosshair = False

    for function_key, function_info in generated_function_info.items():
        # Create a temporary file for the function code.
        temp_file = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8")
        try:
            temp_file.write(dedent_code(function_info["injected_code"]))
            temp_file.close()

            # Use the temporary file name (with .py extension) directly for the command.
            temp_file_name = temp_file.name

            # Construct the Crosshair command using the file name.
            crosshair_command = (
                f"crosshair check --analysis_kind=asserts "
                f"--per_path_timeout={timeout} --per_condition_timeout={timeout} {temp_file_name}"
            )

            # Set PYTHONPATH so that the temporary file's directory is included.
            env = os.environ.copy()
            temp_dir = os.path.dirname(temp_file_name)
            if "PYTHONPATH" in env:
                env["PYTHONPATH"] = temp_dir + os.pathsep + env["PYTHONPATH"]
            else:
                env["PYTHONPATH"] = temp_dir

            # Run the Crosshair command.
            result = subprocess.run(crosshair_command, shell=True, capture_output=True, text=True, env=env)
            crosshair_output = result.stdout.strip() + "\n" + result.stderr.strip()

            if not crosshair_output.strip():
                print(f"Crosshair output is empty for file: {temp_file_name}")
                crosshair_results[function_key] = "No output"
            else:
                if assertion_triggered(crosshair_output):
                    print(f"Assertion triggered for file: {temp_file_name}")
                    assertion_triggered_by_crosshair = True
                crosshair_results[function_key] = crosshair_output
        finally:
            # Ensure the temporary file is removed.
            os.remove(temp_file.name)
    return crosshair_results, assertion_triggered_by_crosshair


def crosshair_check_in_container(container_id, generated_function_info, timeout):
    crosshair_results = {}
    assertion_triggered_by_crosshair = False

    for function_key, function_info in generated_function_info.items():
        # Use the file name directly from the function info.
        module_name = path_to_module_name(container_id, function_info["file_name"])
        crosshair_command = (
            f"crosshair check --analysis_kind=asserts --per_path_timeout={timeout} "
            f"--per_condition_timeout={timeout} {module_name}.{function_info['function_name']}"
        )
        crosshair_output = run_command_in_container(container_id, crosshair_command)
        if not crosshair_output.strip():
            print(f"Crosshair output is empty for file: {function_key}")
            crosshair_results[function_key] = "No output"
        else:
            if assertion_triggered(crosshair_output):
                print(f"Assertion triggered for file: {function_key}")
                assertion_triggered_by_crosshair = True
            crosshair_results[function_key] = crosshair_output
    return crosshair_results, assertion_triggered_by_crosshair

def run_crosshair(container_id, generated_function_info, timeout, local):
    if local:
        return crosshair_check_local(generated_function_info,timeout)
    else:
        return crosshair_check_in_container(container_id, generated_function_info, timeout)


def formal_verification(instance_id, poc_code, problem_statement, patch_diff, timeout, retry, model, local=True):
    try:
        result = {}
        result["before_patch_crosshair_output"] = {}
        result["after_patch_crosshair_output"] = {}
        result["problem_statement"] = problem_statement

        # 1. Set up the environment
        container_id = setup_container(instance_id)
        functions_info = parse_modified_functions_from_diff(container_id, patch_diff)
        if not local:
            prepare_env(container_id)


        # 2. Generate conditions and perform pre-patch poc test
        generated_function_info, pre_patch_assertion_triggered, poc_feedback = generate_conditions_for_functions(
            container_id, functions_info, problem_statement, model, poc_code, retry
        )
        if poc_code:
            result["before_patch_poc_output"] = poc_feedback
            result["before_patch_assertion_triggered"] = pre_patch_assertion_triggered
        else:
            result["before_patch_assertion_triggered"] = None

        result["before_patch_function_info"] = generated_function_info

        # 3. Run Crosshair before applying patch
        crosshair_before, crosshair_asserted = run_crosshair(container_id, generated_function_info, timeout, local)
        result["before_patch_crosshair_output"] = crosshair_before
        if crosshair_asserted:
            result["before_patch_assertion_triggered_by_crosshair"] = True

        # 4. Reset container and apply the patch
        reset(container_id)
        apply_diff(container_id, patch_diff)

        # 5. Update function info after patch and reinject conditions
        after_patch_function_info = update_functions_after_patch(container_id, generated_function_info)
        result["after_patch_function_info"] = after_patch_function_info

        # 6. Post-patch poc test
        poc_output_after, post_patch_asserted = process_poc_after_patch(container_id, poc_code)
        if poc_code:
            result["after_patch_poc_output"] = poc_output_after
            result["after_patch_assertion_triggered"] = post_patch_asserted
        else:
            result["after_patch_assertion_triggered"] = None

        # 7. Run Crosshair after applying patch
        crosshair_after, crosshair_asserted_after = run_crosshair(container_id, after_patch_function_info, timeout, local)
        result["after_patch_crosshair_output"] = crosshair_after
        if crosshair_asserted_after:
            result["after_patch_assertion_triggered_by_crosshair"] = True

        # 8. Clean up the container and return result
        remove_container(container_id)
        return result
    except Exception as e:
        print(f"Error during formal verification: {e}")
        print("Traceback:")
        print(traceback.format_exc())
        with open(f"formal_verification_error_{instance_id}.log", "a") as log_file:
            log_file.write(f"Error during formal verification for instance {instance_id}: {e}\n")
            log_file.write(traceback.format_exc())
        # Clean up the container if it exists
        remove_container(container_id)

        return {
            "error": str(e),
            "instance_id": instance_id,
            "poc_code": poc_code,
            "problem_statement": problem_statement,
            "patch_diff": patch_diff
        }

    
def get_poc_code(instance_id, reproduce_folder):
    poc_code = ""
    poc_code_path = f"{reproduce_folder}/{instance_id}/issue_parsing_report_0.json"
    with open(poc_code_path, "r") as file:
        reproduce_res = json.load(file)
        # successfully_reproduced = reproduce_res.get("result", {}).get("poc",{}).get("oracle", {}).get("exec_match_wrong_behavior", False)
        # if successfully_reproduced:
        poc_code = reproduce_res.get("result", {}).get("poc",{}).get("poc_code", {}).get("poc.py", "")
    return poc_code

def evaluate(
    reproduce_folder: str,
    benchmark: str,
    timeout: int,
    retry: int,
    model_name: str,
    instance_id: str,
    output_dir: str,
    patch_file: str = None,
):
    # Load external patch map if a patch_file is provided
    patch_map = {}
    if patch_file:
        with open(patch_file, 'r') as pf:
            for line in pf:
                entry = json.loads(line)
                patch_map[entry["instance_id"]] = entry["model_patch"]

    print(f"Evaluating reproduce_folder={reproduce_folder}, benchmark={benchmark}")
    limiter = AsyncLimiter(60)
    model = LiteLLMModel(model=model_name, limiter=limiter, temperature=1)

    # Load the chosen benchmark
    if benchmark == "lite":
        data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    elif benchmark == "verified":
        data = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    else:
        raise ValueError(f"Unsupported benchmark: {benchmark}")

    for inst in data:
        iid = inst["instance_id"]
        if instance_id and iid != instance_id:
            continue

        # Determine which patch to apply: external override or the golden patch
        if patch_file and iid in patch_map:
            patch_to_apply = patch_map[iid]
        else:
            patch_to_apply = inst["patch"]

        problem_statement = inst["problem_statement"]
        poc_code = get_poc_code(iid, reproduce_folder)
        out_path = os.path.join(output_dir, f"{iid}.json")
        if os.path.exists(out_path):
            print(f"Skipping {iid}, output already exists.")
            continue

        # Run the formal verification workflow
        result = formal_verification(
            instance_id=iid,
            poc_code=poc_code,
            problem_statement=problem_statement,
            patch_diff=patch_to_apply,
            timeout=timeout,
            retry=retry,
            model=model,
            local=True
        )

        # Save the result
        with open(out_path, "w") as f:
            json.dump(result, f, indent=4)
        print(f"Saved evaluation for {iid}")

def _parallel_worker(
    inst: dict,
    reproduce_folder: str,
    timeout: int,
    retry: int,
    model_name: str,
    output_dir: str,
    patch_map: dict,
    patch_file: str,
):
    """
    Worker function for parallel evaluation.
    Runs formal_verification for a single instance and writes result to disk.
    """
    iid = inst["instance_id"]
    # choose patch: external override if present, else golden patch
    if patch_file and iid in patch_map:
        patch_to_apply = patch_map[iid]
    else:
        patch_to_apply = inst["patch"]

    # load problem statement and PoC code
    problem_statement = inst["problem_statement"]
    poc_code = get_poc_code(iid, reproduce_folder)

    # call the main verification routine
    result = formal_verification(
        instance_id=iid,
        poc_code=poc_code,
        problem_statement=problem_statement,
        patch_diff=patch_to_apply,
        timeout=timeout,
        retry=retry,
        model=LiteLLMModel(model=model_name, limiter=AsyncLimiter(60), temperature=1),
        local=(patch_file is None),
    )

    # ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{iid}.json")
    # write result
    with open(out_path, "w") as f:
        json.dump(result, f, indent=4)
    print(f"Finished evaluation for instance: {iid}")

def parallel_evaluate(
    reproduce_folder: str,
    benchmark: str,
    timeout: int,
    retry: int,
    model_name: str,
    instance_id_filter: str,
    output_dir: str,
    patch_file: str = None,
    num_processes: int = 1,
):
    """
    Multi‐process evaluation entry point.
    Spawns worker processes to handle each instance in parallel.
    """
    # load external patch overrides if provided
    patch_map = {}
    if patch_file:
        with open(patch_file, "r") as pf:
            for line in pf:
                entry = json.loads(line)
                patch_map[entry["instance_id"]] = entry["model_patch"]

    # load dataset
    if benchmark == "lite":
        data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    elif benchmark == "verified":
        data = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    else:
        raise ValueError(f"Unsupported benchmark: {benchmark}")

    # apply instance filter if present
    if instance_id_filter:
        data = [inst for inst in data if inst["instance_id"] == instance_id_filter]
    else:
        data = list(data)

    # bind fixed arguments into a picklable worker
    worker_fn = partial(
        _parallel_worker,
        reproduce_folder=reproduce_folder,
        timeout=timeout,
        retry=retry,
        model_name=model_name,
        output_dir=output_dir,
        patch_map=patch_map,
        patch_file=patch_file,
    )

    # launch pool
    processes = num_processes if num_processes > 0 else cpu_count()
    with Pool(processes=processes) as pool:
        pool.map(worker_fn, data)

    print("All evaluations completed.")


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate script for patch reproduction.")
    parser.add_argument("--reproduce-folder", type=str, required=True, help="Path to the folder containing reproduction results.")
    parser.add_argument("--benchmark", type=str, default="lite", choices=["lite", "verified"])
    parser.add_argument("--timeout", type=int, default=20, help="Timeout for the evaluation in seconds.")
    parser.add_argument("--retry", type=int, default=3, help="Number of retries for generating pre and post conditions.")
    parser.add_argument("--model_name", type=str, default="o4-mini", help="model name to use for generating pre and post conditions.")
    parser.add_argument("--instance-id", type=str, default="", help="Instance ID for the evaluation.")
    parser.add_argument("--output-dir", type=str, default="./formal_verification_evaluation", help="Directory to save the evaluation results.")
    parser.add_argument("--num-processes", type=int, default=1, help="Number of processes to use for evaluation.")
    parser.add_argument("--patch-file", type=str, help="Path to the patch file to apply.")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.num_processes and args.num_processes > 1:
        parallel_evaluate(
            reproduce_folder=args.reproduce_folder,
            benchmark=args.benchmark,
            timeout=args.timeout,
            retry=args.retry,
            model_name=args.model_name,
            instance_id_filter=args.instance_id,
            output_dir=args.output_dir,
            num_processes=args.num_processes,
            patch_file=args.patch_file
        )
    else:
        evaluate(
            args.reproduce_folder,
            args.benchmark,
            args.timeout,
            args.retry,
            args.model_name,
            args.instance_id,
            args.output_dir,
            args.patch_file
        )