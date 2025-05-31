import ast
import os
import subprocess
import uuid
import sys
sys.setrecursionlimit(10000)

repo_to_top_folder = {
    "django/django": "django",
    "sphinx-doc/sphinx": "sphinx",
    "scikit-learn/scikit-learn": "scikit-learn",
    "sympy/sympy": "sympy",
    "pytest-dev/pytest": "pytest",
    "matplotlib/matplotlib": "matplotlib",
    "astropy/astropy": "astropy",
    "pydata/xarray": "xarray",
    "mwaskom/seaborn": "seaborn",
    "psf/requests": "requests",
    "pylint-dev/pylint": "pylint",
    "pallets/flask": "flask",
}


def apply_patch(repo_path, patch_content):
    """Apply the provided patch to the local git repository.
    :param repo_path: Path to the local git repository
    :param patch_content: Patch content to apply
    :return: None
    """
    try:
        # Apply the patch to the provided repository path
        print(f"Applying patch to repository at {repo_path}...")
        patch_file = os.path.join(repo_path, "patch.diff")
        with open(patch_file, "w") as file:
            file.write(patch_content)
        subprocess.run(["git", "-C", repo_path, "apply", "patch.diff"], check=True)
        print("Patch applied successfully.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running git command: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def checkout_commit(repo_path, commit_id):
    """Checkout the specified commit in the given local git repository.
    :param repo_path: Path to the local git repository
    :param commit_id: Commit ID to checkout
    :return: None
    """
    try:
        # Change directory to the provided repository path and checkout the specified commit
        print(f"Checking out commit {commit_id} in repository at {repo_path}...")
        subprocess.run(["git", "-C", repo_path, "checkout", commit_id], check=True)
        print("Commit checked out successfully.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running git command: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def clone_repo(repo_name, repo_playground):
    try:

        print(
            f"Cloning repository from https://github.com/{repo_name}.git to {repo_playground}/{repo_to_top_folder[repo_name]}..."
        )
        subprocess.run(
            [
                "git",
                "clone",
                f"https://github.com/{repo_name}.git",
                f"{repo_playground}/{repo_to_top_folder[repo_name]}",
            ],
            check=True,
        )
        print("Repository cloned successfully.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running git command: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def get_project_structure_from_scratch(
    repo_name, commit_id, instance_id, repo_playground, **kwargs
):
    model_patch = kwargs.get("model_patch", "")
    
    # Generate a temperary folder and add uuid to avoid collision
    repo_playground = os.path.join(repo_playground, str(uuid.uuid4()))

    # assert playground doesn't exist
    assert not os.path.exists(repo_playground), f"{repo_playground} already exists"

    # create playground
    os.makedirs(repo_playground)

    clone_repo(repo_name, repo_playground)
    checkout_commit(f"{repo_playground}/{repo_to_top_folder[repo_name]}", commit_id)
    if model_patch:
        apply_patch(f"{repo_playground}/{repo_to_top_folder[repo_name]}", model_patch)
    structure = create_structure(f"{repo_playground}/{repo_to_top_folder[repo_name]}")
    # clean up
    subprocess.run(
        ["rm", "-rf", f"{repo_playground}/{repo_to_top_folder[repo_name]}"], check=True
    )
    d = {
        "repo": repo_name,
        "base_commit": commit_id,
        "structure": structure,
        "instance_id": instance_id,
    }
    return d


# check whether the node is at global level by checking whether it is at module level
def is_global_node(node, module):
    for child in ast.iter_child_nodes(module):
        if child == node:
            return True
    return False


def find_global_vars_in_function(function_node, global_vars):
    used_globals = []

    # Collect all local variables in the function (assignments)
    local_vars = set()
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    local_vars.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                local_vars.add(node.target.id)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                local_vars.add(node.target.id)

    # All global variable uses that are not local variables
    for node in ast.walk(function_node):
        if isinstance(node, ast.Name) and node.id in global_vars and node.id not in local_vars:
            used_globals.append(f"{node.id} = {global_vars[node.id]}")  # Add to list with the format 'aaa = bbb'

    return used_globals


def splice_intervals(intervals):
    # intervals inclusive
    if not intervals:
        return []

    # Sort the intervals based on the starting value of each tuple
    intervals.sort(key=lambda interval: interval[0])

    spliced_intervals = [intervals[0]]

    for current in intervals[1:]:
        last = spliced_intervals[-1]

        # Check if there is overlap or the gap between intervals is less than or equal to 10
        if current[0] <= last[1] or current[0] - last[1] <= 10:
            # If there is overlap or small gap, merge the intervals
            spliced_intervals[-1] = (last[0], max(last[1], current[1]))
        else:
            # If there is no overlap or small gap, just add the current interval to the result list
            spliced_intervals.append(current)

    return spliced_intervals


def parse_python_file(file_path, file_content=None):
    """Parse a Python file to extract class and function definitions with their line numbers.
    :param file_path: Path to the Python file.
    :return: Class names, function names, and file contents
    """
    if file_content is None:
        try:
            with open(file_path, "r") as file:
                file_content = file.read()
                parsed_data = ast.parse(file_content)
        except Exception as e:  # Catch all types of exceptions
            print(f"Error in file {file_path}: {e}")
            return [], [], "", [], []
    else:
        try:
            parsed_data = ast.parse(file_content)
        except Exception as e:  # Catch all types of exceptions
            print(f"Error in file {file_path}: {e}")
            return [], [], "", [], []

    class_info = []
    function_names = []
    class_methods = set()
    global_vars = {}
    imports = []
    import_interval = []
    # first get all global variables and imports, they will be used in the next steps
    for node in ast.walk(parsed_data):
        # global variables (Assign nodes && at module level)
        if isinstance(node, ast.Assign) and is_global_node(node, parsed_data):
            for target in node.targets:
                if isinstance(target, ast.Name):  
                    value = ast.unparse(node.value)  
                    global_vars[target.id] = value

        # import statements
        elif isinstance(node, ast.Import) and is_global_node(node, parsed_data):
            for alias in node.names:
                imports.append(f"import {alias.name}")
            import_interval.append((node.lineno, node.end_lineno))
        elif isinstance(node, ast.ImportFrom) and is_global_node(node, parsed_data):
            module = node.module if node.module else ""
            for alias in node.names:
                imports.append(f"from {module} import {alias.name}")
            import_interval.append((node.lineno, node.end_lineno))
    for node in ast.walk(parsed_data):
        if isinstance(node, ast.ClassDef):
            methods = []
            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    used_globals = find_global_vars_in_function(n, global_vars)
                    methods.append(
                        {
                            "name": n.name,
                            "start_line": n.lineno,
                            "end_line": n.end_lineno,
                            "text": file_content.splitlines()[
                                n.lineno - 1 : n.end_lineno
                            ],
                            "used_globals": used_globals,
                        }
                    )
                    class_methods.add(n.name)
            class_info.append(
                {
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                    "text": file_content.splitlines()[
                        node.lineno - 1 : node.end_lineno
                    ],
                    "methods": methods,
                }
            )
        elif isinstance(node, ast.FunctionDef) and not isinstance(
            node, ast.AsyncFunctionDef
        ):
            if node.name not in class_methods:
                used_globals = find_global_vars_in_function(node, global_vars)
                function_names.append(
                    {
                        "name": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "text": file_content.splitlines()[
                            node.lineno - 1 : node.end_lineno
                        ],
                        "used_globals": used_globals,
                    }
                )
    import_interval =  splice_intervals(import_interval)

    return class_info, function_names, file_content.splitlines(), imports, import_interval


def create_structure(directory_path):
    """Create the structure of the repository directory by parsing Python files.
    :param directory_path: Path to the repository directory.
    :return: A dictionary representing the structure.
    """
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
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                class_info, function_names, file_lines, imports, import_interval = parse_python_file(file_path)
                curr_struct[file_name] = {
                    "classes": class_info,
                    "functions": function_names,
                    "text": file_lines,
                    "imports": imports,
                    "import_interval": import_interval,
                }
            else:
                curr_struct[file_name] = {}

    return structure
