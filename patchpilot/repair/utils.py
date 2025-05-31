from patchpilot.util.postprocess_data import (
    check_code_differ_by_just_empty_lines,
    check_syntax,
    extract_python_blocks,
    fake_git_repo,
    get_diff_real_git_repo,
    lint_code,
    parse_diff_edit_commands,
    parse_edit_commands,
    split_edit_multifile_commands
)
from patchpilot.util.preprocess_data import (
    line_wrap_content,
    transfer_arb_locs_to_locs,
    get_extended_context_intervals
)
import json
from difflib import unified_diff


infer_intended_behavior_prompt = """
You are an assistant for analyzing the description of an issue. You need to infer the expected behavior of the provided code snippet based on the issue description and the code.
Here is the issue text:
--- BEGIN ISSUE ---
{issue_description}
--- END ISSUE ---

Here is the code snippet you need to analyze and infer the expected behavior:
--- BEGIN CODE ---
{code}
--- END CODE ---

{extended_code}

You should output the expected behavior of the code snippet wrapped in --- BEGIN CODE --- and --- END CODE --- in a concise manner. Here is an example of the output format:
--- BEGIN EXPECTED BEHAVIOR ---
The function foo is expected to add 1 to the argument passed in and return the result. 
The function bar is expected to return the sum of the two arguments passed in.
--- END EXPECTED BEHAVIOR  ---

"""

def construct_topn_file_context(
        file_to_locs,
        pred_files,
        file_contents,
        structure,
        context_window: int,
        loc_interval: bool = True,
        fine_grain_loc_only: bool = False,
        add_space: bool = False,
        sticky_scroll: bool = False,
        no_line_number: bool = True,
        coverage_info=None,
        **kwargs
):
    """Concatenate provided locations to form a context.

    loc: {"file_name_1": ["loc_str_1"], ...}
    """
    intended_behavior = kwargs.get("intended_behavior", False)
    commit_dict = kwargs.get("commit_dict", None)
    problem_statement = kwargs.get("problem_statement", "")
    logger = kwargs.get("logger", None)
    greedy_model = kwargs.get("greedy_model", None)
    file_loc_intervals = dict()
    file_import_intervals = dict()
    file_used_globals = dict()
    topn_content = ""

    for pred_file, locs in file_to_locs.items():
        content = file_contents[pred_file]
        line_locs, context_intervals, import_intervals, used_globals = transfer_arb_locs_to_locs(
            locs,
            structure,
            pred_file,
            context_window,
            loc_interval,
            fine_grain_loc_only,
            file_content=file_contents[pred_file] if pred_file in file_contents else "",
        )

        if len(line_locs) > 0:
            file_loc_content = line_wrap_content(
                content,
                context_intervals,
                add_space=add_space,
                no_line_number=no_line_number,
                sticky_scroll=sticky_scroll,
            )
            if commit_dict:
                if pred_file in commit_dict:
                    topn_content += f" Here are the git diff of the file in the commit that introduced the bug:\n"
                    topn_content += f"```diff\n{commit_dict[pred_file]}\n```\n"
            if not intended_behavior:
                topn_content += f"### {pred_file}\n{file_loc_content}\n\n\n"
            else:
                extended_context_intervals = get_extended_context_intervals(context_intervals, content)
                for interval_idx in range(len(context_intervals)):
                    orig_content = get_content_from_one_interval(
                        file_contents,
                        pred_file,
                        context_intervals[interval_idx],
                        add_space=add_space,
                        sticky_scroll=sticky_scroll,
                        no_line_number=no_line_number
                    )
                    if context_intervals[interval_idx] == extended_context_intervals[interval_idx]:
                        extended_content_in_prompt = ''
                    else:
                        extended_content = get_content_from_one_interval(
                            file_contents,
                            pred_file,
                            extended_context_intervals[interval_idx],
                            add_space=add_space,
                            sticky_scroll=sticky_scroll,
                            no_line_number=no_line_number
                        )
                        extended_content_in_prompt = 'Below is additional context that the LLM can reference to analyze the code snippet --- BEGIN CONTEXT ---\n' + extended_content + '\n--- END CONTEXT ---\n'
                    topn_content += f"### {pred_file}\n"
                    if context_intervals[interval_idx] not in import_intervals:
                        message = infer_intended_behavior_prompt.format(issue_description=problem_statement,
                                                                        code=orig_content,
                                                                        extended_code=extended_content_in_prompt)
                        logger.info(f"Expected behavior inference: prompting with message:\n{message}")
                        greedy_traj = greedy_model.codegen(message, num_samples=1)[0]
                        response = greedy_traj["response"]
                        try:
                            intended_behavior = \
                            response.split('--- BEGIN EXPECTED BEHAVIOR ---')[1].split('--- END EXPECTED BEHAVIOR ---')[0]
                        except:
                            intended_behavior = ""
                            logger.info(
                                f"Expected behavior inference: failed to extract the expected behavior, the response is {response}")
                            print(
                                f"Expected behavior inference: failed to extract the expected behavior, the response is {response}")
                        logger.info(f"Got response:\n{greedy_traj}")
                        topn_content += f"{orig_content}\nHere is the intended behavior of the code snippet based on the issue description and the code:\n{intended_behavior}\n"
                    else:
                        topn_content += f"{orig_content}\n"
            topn_content += '-' * 40 + '\n\n\n'
            file_loc_intervals[pred_file] = context_intervals
            file_import_intervals[pred_file] = import_intervals
            file_used_globals[pred_file] = used_globals

    return topn_content, file_loc_intervals, file_import_intervals, file_used_globals


def get_content_from_one_interval(
        file_contents,
        pred_file,
        interval,
        add_space: bool = False,
        sticky_scroll: bool = False,
        no_line_number: bool = True,
):
    content = file_contents[pred_file]
    file_loc_content = line_wrap_content(
        content,
        [interval],
        add_space=add_space,
        no_line_number=no_line_number,
        sticky_scroll=sticky_scroll,
    )
    return file_loc_content


def post_process_raw_output_refine(
    raw_output_text, file_contents, logger, file_loc_intervals, repo, base_commit, base_patch_diff):
    """
    Post-process the raw output text from the repair tool.

    Arguments:
    raw_output_text: The raw output text from the repair tool. A string.
    file_contents: A dictionary with the modified file by the patch as key and file content as values. It's the file content before applying the patch.
    logger: A logger object.
    file_loc_intervals: A dictionary with file paths as keys and lists of line intervals as values.
    repo: A string with the name of the github repo.
    base_commit: A string with the commit hash of the base commit.
    base_patch_diff: A string with the diff of the base commit.

    Returns:
    git_diffs: A string with the git diff of the proposed changes.
    raw_git_diffs: A string with the raw git diff of the proposed changes.
    content: A string with the content of the edited file.
    check_success: A boolean indicating whether the linting and syntax checking were successful.
    errors: A set of error messages.
    """
    git_diffs = ""
    raw_git_diffs = ""
    lint_success = False
    check_success = False
    errors = set()
    prev_errors = set()
    edited_files, new_contents, contents = [], [], []
    differ_by_empty_lines = False
    try:
        file_to_contents = {}
        for file in file_loc_intervals:
            file_to_contents[file] = file_contents[file]
        edited_files, new_contents = _post_process_multifile_repair(
            raw_output_text,
            file_contents,
            logger,
            file_loc_intervals,
            diff_format=True,
        )
        contents = [file_contents[edited_file] for edited_file in edited_files]
        assert len(edited_files) == len(new_contents)
        assert len(edited_files) == len(contents)
        for i, edited_file in enumerate(edited_files):
            file_to_contents[edited_file] = new_contents[i]
                     
        # file_to_contents only records modification of the edited file by the current patch, we need to apply base_patch_diff to maintain the changes in other files.
        git_diff = get_diff_real_git_repo("playground", file_to_contents, repo, base_commit, base_patch_diff)

        raw_git_diffs += "\n" + git_diff.replace(
            "\ No newline at end of file\n", ""
        )

        syntax_success = True
        syntax_errors = set()
        for new_content in new_contents:
            syntax_success_i, syntax_error =  check_syntax(new_content)
            syntax_success = syntax_success and syntax_success_i
            if syntax_error:
                syntax_errors.add(syntax_error)
        if not syntax_success:
            print("Syntax checking failed.")
            errors=syntax_errors
            return git_diffs, raw_git_diffs, contents, check_success, errors, edited_files, new_contents, differ_by_empty_lines
        
        lint_success = True
        for i in range(len(contents)):
            if i < len(new_contents):
                lint_success_i, prev_errors_i, errors_i = lint_code(
                    "playground", "test.py", new_contents[i], contents[i]
                )
                lint_success = lint_success and lint_success_i
                prev_errors.update(prev_errors_i)
                errors.update(errors_i)

        differ_by_empty_lines = check_code_differ_by_just_empty_lines(
            new_contents, contents
        )
        print(git_diff)
        print(lint_success, prev_errors, errors, differ_by_empty_lines)
        
        logger.info(f"git diff: {git_diff}")
        logger.info(f"{lint_success}, {prev_errors}, {errors}, {differ_by_empty_lines}")

        logger.info(f"{differ_by_empty_lines = }")
        if syntax_success and not differ_by_empty_lines:
            git_diffs = raw_git_diffs
        else:
            git_diffs = ""  # no need to evaluate
    except Exception as e:
        print(raw_output_text)
        print(e)
    
    if lint_success and syntax_success:
        check_success = True
        
    errors.difference_update(prev_errors)

    return git_diffs, raw_git_diffs, contents, check_success, errors, edited_files, new_contents, differ_by_empty_lines


def post_process_raw_output(
    raw_output_text, file_contents, logger, file_loc_intervals, if_diff_format=False, not_found_file_dict=None, instance_id=None
):
    """
    Post-process the raw output text from the repair tool.

    Arguments:
    raw_output_text: The raw output text from the repair tool. A string.
    file_contents: A dictionary with file paths as keys and file contents as values.
    logger: A logger object.
    file_loc_intervals: A dictionary with file paths as keys and lists of line intervals as values.
    args: A Namespace object with the following attributes:
        diff_format: A boolean indicating whether the repair tool uses diff format.

    Returns:
    git_diffs: A string with the git diff of the proposed changes.
    raw_git_diffs: A string with the raw git diff of the proposed changes.
    content: A string with the content of the edited file.
    check_success: A boolean indicating whether the linting and syntax checking were successful.
    """
    git_diffs = ""
    raw_git_diffs = ""
    lint_success = False
    check_success = False
    errors = set()
    prev_errors = set()
    differ_by_empty_lines = False
    edited_files, new_contents, contents = [], [], []
    try:
        edited_files, new_contents = _post_process_multifile_repair(
            raw_output_text,
            file_contents,
            logger,
            file_loc_intervals,
            diff_format=if_diff_format,
        )
        contents = [file_contents[edited_file] for edited_file in edited_files]
        if contents:
            git_diff = fake_git_repo("playground", edited_files, contents, new_contents)
            
            raw_git_diffs += "\n" + git_diff.replace("\ No newline at end of file\n", "")

            syntax_success = True
            syntax_errors = set()
            for new_content in new_contents:
                syntax_success_i, syntax_error =  check_syntax(new_content)
                syntax_success = syntax_success and syntax_success_i
                if syntax_error:
                    syntax_errors.add(syntax_error)
            if not syntax_success:
                print("Syntax checking failed.")
                errors=syntax_errors
                return git_diffs, raw_git_diffs, contents, check_success, errors, edited_files, new_contents, differ_by_empty_lines
            
            lint_success = True
            for i in range(len(contents)):
                if i < len(new_contents):
                    lint_success_i, prev_errors_i, errors_i = lint_code(
                        "playground", "test.py", new_contents[i], contents[i]
                    )
                    lint_success = lint_success and lint_success_i
                    prev_errors.update(prev_errors_i)
                    errors.update(errors_i)

            differ_by_empty_lines = check_code_differ_by_just_empty_lines(
                new_contents, contents
            )
            print(git_diff)
            print(lint_success, prev_errors, errors, differ_by_empty_lines)
            
            logger.info(f"git diff: {git_diff}")
            logger.info(f"{lint_success}, {prev_errors}, {errors}, {differ_by_empty_lines}")

            logger.info(f"{differ_by_empty_lines = }")
            if syntax_success and not differ_by_empty_lines:
                git_diffs = raw_git_diffs
            else:
                git_diffs = ""  # no need to evaluate
        else:
            print("Failed to extract the edited file.")
            errors.add("Failed to extract the edited file.")
            print(f'raw_output_text: {raw_output_text}')
            if isinstance(not_found_file_dict, dict) and instance_id:
                if instance_id in not_found_file_dict:
                    not_found_file_dict[instance_id] += "\n" + "\n".join([edited_file for edited_file in edited_files])
                else:
                    not_found_file_dict[instance_id] = "\n" + "\n".join([edited_file for edited_file in edited_files])
    except Exception as e:
        print(raw_output_text)
        print(e)
    
    if lint_success and syntax_success:
        check_success = True
        
    errors.difference_update(prev_errors)

    return git_diffs, raw_git_diffs, contents, check_success, errors, edited_files, new_contents, differ_by_empty_lines


def _post_process_multifile_repair(
    raw_output: str,
    file_contents: dict[str, str],
    logger,
    file_loc_intervals: dict[str, list],
    diff_format=False,
)-> tuple[list[str], list[str]]:
    edit_multifile_commands = extract_python_blocks(raw_output)
    edited_files = []
    new_contents = []
    try:
        file_to_commands = split_edit_multifile_commands(edit_multifile_commands, diff_format=diff_format)
    except Exception as e:
        logger.error(e)
        return edited_files, new_contents
    logger.info("=== file_to_commands: ===")
    logger.info(json.dumps(file_to_commands, indent=2))

    
    for edited_file_key in file_to_commands:
        edited_file = ""
        new_content = ""
        try:
            logger.info(f"=== edited_file: {edited_file_key} ===")
            edit_commands = file_to_commands[edited_file_key]
            logger.info("=== edit_commands: ===")
            for c in edit_commands:
                logger.info(c)
                logger.info("\n" + "-" * 40)
            edited_file = eval(edited_file_key)  # convert '"file.py"' to 'file.py'
            content = file_contents[edited_file]
            if diff_format:
                new_content, replaced = parse_diff_edit_commands(
                    edit_commands, content, file_loc_intervals[edited_file]
                )
            else:
                new_content = parse_edit_commands(edit_commands, content)
        except Exception as e:
            logger.error(e)
            edited_file = ""
            new_content = ""

        if edited_file == "" or new_content == "":
            continue
        edited_files.append(edited_file)
        new_contents.append(new_content)
        diff = list(
            unified_diff(
                content.split("\n"),
                new_content.split("\n"),
                fromfile=edited_file,
                tofile=edited_file,
                lineterm="",
            )
        )

        logger.info(f"extracted patch:")
        logger.info("\n".join(diff))

    return edited_files, new_contents


def apply_search_replace(
    raw_output: str,
    content: str,
)-> str:
    edit_multifile_commands = extract_python_blocks(raw_output)
    try:
        file_to_commands = split_edit_multifile_commands(edit_multifile_commands, diff_format=True)
    except Exception as e:
        return content
    all_edit_commands = []
    for edited_file_key in file_to_commands:
        all_edit_commands += file_to_commands[edited_file_key]
        
    content_interval = [(0, len(content.splitlines()))]
    new_content, replaced = parse_diff_edit_commands(
        all_edit_commands, content, content_interval
    )
    return new_content
