import os
import subprocess
import concurrent.futures
import json
from os.path import dirname as pdirname
from os.path import join as pjoin
import logging
from datasets import load_dataset
import traceback
from patchpilot.util.model import make_model

obtain_relevant_test_files_prompt = """
Please look through the following GitHub problem description and the unit test files in the Repository and provide a list of unit test file that you think is relevant to this problem.
That means you should only choose the unit tests files which are relevant to this problem from what I give.

### GitHub Problem Description ###
{problem_statement}

###

### Unit Tests ###
{unit_test}

###

Please only provide the full path and return at most 3 files.
The returned files should be separated by new lines ordered by most to least important and wrapped with ```
For example:
```
file1.py
file2.py
```
"""


def parse_directory_to_dict(directory_path):
    structure = {}

    for root, _, files in os.walk(directory_path):
        repo_name = os.path.basename(directory_path)
        relative_root = os.path.relpath(root, directory_path)
        if relative_root == ".":
            relative_root = repo_name
        curr_struct = structure
        for part in relative_root.split(os.sep):
            if part not in curr_struct:
                curr_struct[part] = {}
            curr_struct = curr_struct[part]
        for file_name in files:
            curr_struct[file_name] = {}

    return structure


def get_all_test_files(structure, prefix=""):
    test_files = []

    for key, value in structure.items():
        if key.lower() in ["test", "tests"]:
            dir_path = prefix + key
            test_files.extend(collect_py_files_in_subtree(value, dir_path))
        else:
            if isinstance(value, dict) and len(value) > 0:
                new_prefix = prefix + key + "/"
                test_files.extend(get_all_test_files(value, prefix=new_prefix))

    return test_files


def collect_py_files_in_subtree(sub_structure, prefix):
    results = []

    for key, value in sub_structure.items():
        if isinstance(value, dict):
            if len(value) == 0:
                if key.endswith(".py"):
                    file_path = f"{prefix}/{key}"
                    results.append(file_path)
            else:
                new_prefix = f"{prefix}/{key}"
                results.extend(collect_py_files_in_subtree(value, new_prefix))

    return results


def run_string_cmd_in_conda(
        command: str, env_name: str, cwd: str, **kwargs
) -> subprocess.CompletedProcess:
    """
    Run a complete command in a given conda environment, where the command is a string.

    This is useful when the command to be run contains &&, etc.

    NOTE: use `conda activate` instead of `conda run` in this verison, so that we can
          run commands that contain `&&`, etc.
    """
    conda_bin_path = os.getenv("CONDA_EXE")  # for calling conda
    if conda_bin_path is None:
        raise RuntimeError("Env variable CONDA_EXE is not set")
    conda_root_dir = pdirname(pdirname(conda_bin_path))
    conda_script_path = pjoin(conda_root_dir, "etc", "profile.d", "conda.sh")
    conda_cmd = f"source {conda_script_path} ; conda activate {env_name} ; {command} ; conda deactivate"
    print(f"Running command: {conda_cmd}")
    return subprocess.run(conda_cmd, cwd=cwd, shell=True, **kwargs)


def get_functionality_test_coverage(project_path, env_name) -> dict:
    structure = parse_directory_to_dict(project_path)
    test_files = get_all_test_files(structure)
    folder_name = os.path.basename(project_path)

    if folder_name.startswith("psf") and not test_files:
        test_files.append("test_requests.py")

    test_basic_command = get_test_basic_command(project_path)
    coverage_erase = "coverage erase "
    coverage_tool = "timeout -s SIGKILL 30s coverage run -m "
    coverage_combine = "coverage combine "
    coverage_dump = "coverage json -o "
    coverage_temp_path = "/opt/PatchingAgent_playground/test/coverage_folder"

    result_folder = os.path.join(coverage_temp_path, folder_name)
    if not os.path.exists(result_folder):
        os.makedirs(result_folder)

    for test_file in test_files:
        test_module = test_file
        if "django" in project_path.lower():
            coverage_tool = "coverage run "
            if test_file.startswith("tests/"):
                test_module = test_file[len("tests/"):]
            else:
                test_module = test_file

            test_module = test_module.replace('/', '.')

            if test_module.endswith(".py"):
                test_module = test_module[:-3]
        elif "sympy" in project_path.lower():
            coverage_tool = "coverage run "

        filename = os.path.basename(test_file)
        coverage_json_name = test_file.replace('/', '__*') + '.json'

        cp = run_string_cmd_in_conda(coverage_erase, env_name, cwd=project_path, capture_output=True,
                                     text=True)
        if cp.returncode != 0:
            print(cp.stderr)
            raise RuntimeError(f"Command {coverage_erase} failed.")

        coverage_run_cmd = coverage_tool + test_basic_command + test_module
        cp = run_string_cmd_in_conda(coverage_run_cmd, env_name, cwd=project_path, capture_output=True, text=True)
        if cp.returncode != 0:
            print(cp.stderr)
            raise RuntimeError(f"Command {coverage_run_cmd} failed.")

        cp = run_string_cmd_in_conda(coverage_combine, env_name, cwd=project_path, capture_output=True, text=True)
        if cp.returncode != 0:
            print(cp.stderr)

        coverage_json_cmd = coverage_dump + os.path.join(result_folder, coverage_json_name)
        cp = run_string_cmd_in_conda(coverage_json_cmd, env_name, cwd=project_path, capture_output=True,
                                     text=True)
        if cp.returncode != 0:
            print(cp.stderr)
            raise RuntimeError(f"Command {coverage_json_cmd} failed.")


def get_test_basic_command(project_path) -> str:
    TEST_PYLINT = "pytest --no-header -rA --tb=no -p no:cacheprovider "
    TEST_ASTROPY_PYTEST = "pytest --no-header -rA --tb=no -p no:cacheprovider "
    TEST_DJANGO_NO_PARALLEL = "./tests/runtests.py --verbosity 2 "
    TEST_SEABORN = "pytest --no-header -rA "
    TEST_PYTEST = "pytest -rA "
    TEST_SPHINX = "pytest -rA "
    TEST_SYMPY_VERBOSE = "bin/test -C --verbose "
    TEST_MATPLOTLIB = "pytest --no-header -rA --tb=no -p no:cacheprovider "
    TEST_MWASKOM = "pytest --no-header -rA "
    TEST_PALLETS = "pytest --no-header -rA --tb=no -p no:cacheprovider "
    TEST_PSF = "pytest --no-header -rA --tb=no -p no:cacheprovider "
    TEST_XARRAY = "pytest --no-header -rA --tb=no -p no:cacheprovider "
    if "pytest" in project_path:
        return TEST_PYTEST
    elif "astropy" in project_path:
        return TEST_ASTROPY_PYTEST
    elif "django" in project_path:
        return TEST_DJANGO_NO_PARALLEL
    elif "seaborn" in project_path:
        return TEST_SEABORN
    elif "pylint" in project_path:
        return TEST_PYLINT
    elif "sphinx" in project_path:
        return TEST_SPHINX
    elif "sympy" in project_path:
        return TEST_SYMPY_VERBOSE
    elif "matplotlib" in project_path:
        return TEST_MATPLOTLIB
    elif "mwaskom" in project_path:
        return TEST_MWASKOM
    elif "pallets" in project_path:
        return TEST_PALLETS
    elif "psf" in project_path:
        return TEST_PSF
    elif "xarray" in project_path:
        return TEST_XARRAY
    else:
        return TEST_PYLINT


def run_coverage_for_project(project_path: str):
    last_dir_name = os.path.basename(os.path.normpath(project_path))
    env_name = "setup_" + last_dir_name

    structure = parse_directory_to_dict(project_path)
    test_files = get_all_test_files(structure)

    if last_dir_name.startswith("psf") and not test_files:
        test_files.append("test_requests.py")

    if not test_files:
        return

    get_functionality_test_coverage(project_path, env_name)


def parse_model_return_lines(content: str) -> list[str]:
    if content:
        return content.strip().split("\n")


def setup_logger(log_file):
    logger = logging.getLogger(log_file)
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(formatter)

    logger.addHandler(fh)
    return logger


def get_functionality_test_llm(bug) -> dict:
    instance_id = bug["instance_id"]
    problem_statement = bug["problem_statement"]

    project_path = os.path.join("/opt/SWE-bench/testbed/", instance_id)
    structure = parse_directory_to_dict(project_path)
    test_files = get_all_test_files(structure)

    if instance_id.startswith("psf") and not test_files:
        test_files.append("test_requests.py")

    logger = "/home/yuheng/ucsb/PatchingAgent/results_func_test/llm_find/logs/{}.txt".format(instance_id)
    logger = setup_logger(logger)
    logger.info(test_files)
    message = obtain_relevant_test_files_prompt.format(
        problem_statement=problem_statement,
        unit_test=test_files,
    )
    model = make_model(
        model="gpt-4o-2024-08-06",
        backend="openai",
        logger=logger,
        temperature=0.3,
    )
    raw_trajs = model.codegen(message, num_samples=1)
    # traj = model.codegen(message, num_samples=num_samples)[0]
    raw_outputs = [raw_traj["response"] for raw_traj in raw_trajs]
    traj = {
        "prompt": message,
        "response": raw_outputs,
    }
    model_found_files_raw = []
    for raw_output in raw_outputs:
        model_found_files_raw.extend(parse_model_return_lines(raw_output))

    return model_found_files_raw



def main():

    swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")

    results_dict = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
        future_to_bug = {}

        for bug in swe_bench_data:
            future = executor.submit(get_functionality_test_llm, bug)
            future_to_bug[future] = bug

        for future in concurrent.futures.as_completed(future_to_bug):
            current_bug = future_to_bug[future]
            instance_id = current_bug["instance_id"]
            try:
                result_value = future.result()
            except Exception as exc:
                traceback.print_exc()

            else:
                results_dict[instance_id] = result_value

    with open("results_func_test/llm_find/result.json", "w") as f:
        json.dump(results_dict, f)


if __name__ == "__main__":
    main()
