import argparse
import concurrent.futures
import json
import os
import pickle
from datasets import load_dataset
from patchpilot.util.preprocess_data import (
    transfer_arb_locs_to_locs,
    get_full_file_paths_and_classes_and_functions,
)

from patchpilot.fl.FL import LLMFL
from patchpilot.repair.repair import poc_info_prompt
from patchpilot.reproduce.task import parse_task_list_file
from patchpilot.util.preprocess_data import (
    filter_none_python,
    filter_out_test_files,
)
from patchpilot.util.utils import (
    load_existing_instance_ids,
    load_json,
    load_jsonl,
    setup_logger, ensure_directory_exists,
    coverage_to_dict,
)
from get_repo_structure.get_repo_structure import (
    get_project_structure_from_scratch,
)

# SET THIS IF YOU WANT TO USE THE PREPROCESSED FILES
PROJECT_STRUCTURE = os.environ.get("PROJECT_STRUCTURE", None)


def localize_instance(
        bug, args, swe_bench_data, start_file_locs, existing_instance_ids
):
    instance_id = bug["instance_id"]
    log_file = os.path.join(
        args.output_folder, "localization_logs", f"{instance_id}.log"
    )
    if args.target_id is not None:
        if args.target_id != bug["instance_id"]:
            return

    logger = setup_logger(log_file)
    logger.info(f"Processing bug {instance_id}")

    if bug["instance_id"] in existing_instance_ids:
        logger.info(f"Skipping existing instance_id: {bug['instance_id']}")
        return

    if PROJECT_STRUCTURE is not None:
        project_file = os.path.join(PROJECT_STRUCTURE, bug["instance_id"] + ".json")
        file_json = load_json(project_file)

    else:
        # we need to get the project structure directly
        file_json = get_project_structure_from_scratch(
            bug["repo"], bug["base_commit"], bug["instance_id"], "playground"
        )
    if args.repo_graph:
        code_graph = pickle.load(
            open(os.path.join(args.code_graph_dir, f"{instance_id}.pkl"), "rb")
        )
        graph_tags = json.load(
            open(os.path.join(args.code_graph_dir, f"tags_{instance_id}.json"), "r")
        )

    coverage_info = {
        "coverage_dict": {},
        "commit_info": {},
    }
    reproduce_info = ""
    if args.reproduce_folder:
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
                    std_out = repro_result_dict.get('oracle', {}).get('execution_output', {}).get('stdout', {})
                    std_err = repro_result_dict.get('oracle', {}).get('execution_output', {}).get('stderr', {})
                    coverage_raw = repro_result_dict.get('coverage', "")
                    coverage_dict = coverage_to_dict(coverage_raw)
                    if len(coverage_dict) < 3:
                        coverage_dict = {}
                    commit_info = repro_result_dict.get('commit_info', {})
                    reproduce_info = poc_info_prompt.format(poc_code=poc_code, stdout=std_out, stderr=std_err)
                    if args.use_coverage:
                        coverage_info = {
                            "coverage_dict": coverage_dict,
                            "commit_info": commit_info,
                        }
                    else:
                        coverage_info = {
                            "coverage_dict": {},
                            "commit_info": commit_info,
                        }
            except:
                logger.error(f"failed to load reproduce info from {reproduce_output_file}")
                print(f"failed to load reproduce info from {reproduce_output_file}")

    logger.info(f"================ localize {instance_id} ================")

    bench_data = [x for x in swe_bench_data if x["instance_id"] == instance_id][0]
    problem_statement = bench_data["problem_statement"]
    structure = file_json["structure"]

    filter_none_python(structure)  # some basic filtering steps

    # filter out test files (unless its pytest)
    if not file_json["instance_id"].startswith("pytest"):
        filter_out_test_files(structure)

    found_files = []
    found_related_locs = []
    found_edit_locs = []
    additional_artifact_loc_file = None
    additional_artifact_loc_related = None
    additional_artifact_loc_edit_location = None
    file_traj, related_loc_traj, edit_loc_traj = {}, {}, {}

    # step 0: give llm a chance to search for a string in the problem statement
    search_str_with_file = dict()
    fl = LLMFL(
        file_json["instance_id"],
        structure,
        problem_statement,
        args.model,
        args.backend,
        logger,
        args.match_partial_paths,
        args.temperature
    )
    search_str_with_file = fl.search_in_problem_statement(reproduce_info)

    # file level localization
    if args.file_level:
        fl = LLMFL(
            file_json["instance_id"],
            structure,
            problem_statement,
            args.model,
            args.backend,
            logger,
            args.match_partial_paths,
            args.temperature
        )
        found_files, additional_artifact_loc_file, file_traj = fl.localize(
            mock=args.mock,
            match_partial_paths=args.match_partial_paths,
            search_res_files=search_str_with_file,
            num_samples=args.num_samples,
            top_n=args.top_n,
            coverage_info=coverage_info
        )
    else:
        # assume start_file is provided
        for locs in start_file_locs:
            if locs["instance_id"] == file_json["instance_id"]:
                found_files = locs["found_files"]
                additional_artifact_loc_file = locs["additional_artifact_loc_file"]
                file_traj = locs["file_traj"]
                if "found_related_locs" in locs:
                    found_related_locs = locs["found_related_locs"]
                    additional_artifact_loc_related = locs[
                        "additional_artifact_loc_related"
                    ]
                    related_loc_traj = locs["related_loc_traj"]
                break
    # 
    if args.direct_line_level:
        pred_files = found_files[: args.top_n]
        fl = LLMFL(
            instance_id,
            structure,
            problem_statement,
            args.model,
            args.backend,
            logger,
            args.match_partial_paths,
            args.temperature
        )
        (
            found_edit_locs,
            additional_artifact_loc_edit_location,
            edit_loc_traj,
        ) = fl.localize_line_from_files(
            pred_files,
            num_samples=args.num_samples,
        )
        additional_artifact_loc_edit_location = [additional_artifact_loc_edit_location]

    # related class, functions, global var localization
    if args.related_level and not args.direct_line_level:
        if len(found_files) != 0:
            pred_files = found_files[: args.top_n]
            fl = LLMFL(
                file_json["instance_id"],
                structure,
                problem_statement,
                args.model,
                args.backend,
                logger,
                args.match_partial_paths,
                args.temperature
            )
            if args.compress:
                (
                    found_related_locs,
                    additional_artifact_loc_related,
                    related_loc_traj,
                ) = fl.localize_function_from_compressed_files(
                    pred_files, mock=args.mock, num_samples=args.num_samples, coverage_info=coverage_info
                )
                additional_artifact_loc_related = [additional_artifact_loc_related]
            else:
                assert False, "Not implemented yet."

    coarse_found_locs = {}
    for i, pred_file in enumerate(pred_files):
        if len(found_related_locs) > i:
            coarse_found_locs[pred_file] = found_related_locs[i]

    if args.fine_grain_line_level and not args.direct_line_level:
        # Only supports the following args for now

        pred_files = found_files[: args.top_n]
        fl = LLMFL(
            instance_id,
            structure,
            problem_statement,
            args.model,
            args.backend,
            logger,
            args.match_partial_paths,
            args.temperature
        )
        (
            found_edit_locs,
            additional_artifact_loc_edit_location,
            edit_loc_traj,
        ) = fl.localize_line_from_coarse_function_locs(
            pred_files,
            coarse_found_locs,
            context_window=args.context_window,
            add_space=args.add_space,
            code_graph=args.repo_graph,
            no_line_number=args.no_line_number,
            sticky_scroll=args.sticky_scroll,
            mock=args.mock,
            num_samples=args.num_samples,
            coverage_info=coverage_info
        )
        additional_artifact_loc_edit_location = [additional_artifact_loc_edit_location]

    if args.review_level:
        # step 4: review the results
        # First merge the found_edit_locs
        found_edit_locs_merged = [""] * args.top_n
        for i in range(args.top_n):
            for sample_index in range(len(found_edit_locs)):
                if sample_index < len(found_edit_locs) and i < len(found_edit_locs[sample_index]):
                    # Check if the inner list contains at least one element to access index [0]
                    if found_edit_locs[sample_index][i] and isinstance(found_edit_locs[sample_index][i], list) and found_edit_locs[sample_index][i][0] is not None:
                            found_edit_locs_merged[i] += found_edit_locs[sample_index][i][0] + "\n"

        files, _, _ = get_full_file_paths_and_classes_and_functions(structure)

        # Construct file contents
        file_contents = dict()

        pred_files = found_files[: args.top_n]
        for i, pred_file in enumerate(pred_files):
            content = None

            for file_content in files:
                if file_content[0] == pred_file:
                    content = "\n".join(file_content[1])
                    file_contents[pred_file] = content
                    break

            assert content is not None, f"{pred_file} file not found"

        file_loc_intervals = {}
        for i, tmp_pred_file in enumerate(pred_files):
            if len(found_edit_locs_merged) > i:
                _, context_intervals, _, _ = transfer_arb_locs_to_locs(
                    found_edit_locs_merged[i],
                    None,
                    found_files[i],
                    args.context_window,
                    True,
                    False,
                    file_content=file_contents[tmp_pred_file]
                    if tmp_pred_file in file_contents
                    else "",
                )
            else:
                context_intervals = []  # default values.

            file_loc_intervals[tmp_pred_file] = context_intervals

        all_context_len = 0
        for intervals in file_loc_intervals.values():
            for interval in intervals:
                all_context_len += interval[1] - interval[0]
        logger.info('=====================================')
        logger.info("all_context_len:"+str(all_context_len))
        logger.info('=====================================')
        print('=====================================')
        print("all_context_len", all_context_len)
        print('=====================================')
        if all_context_len < 300:
            # search for more context
            # construct the message of previous search results
            last_search_results = "### Previous search results ###\n"
            last_search_results += "Your previous search results are not complete, you should provide more locations. You should return the original locations and also at least 3 extra locations.\n"
            last_search_results += "You should return at least 4 location from the following files that are not in the original locations:\n"
            # repeat to emphasize the importance of the search
            last_search_results += "You should return at least 4 location from the following files that are not in the original locations:\n"
            for i, pred_file in enumerate(pred_files):
                last_search_results += f"File {pred_file}\n"
            last_search_results += "\nThe previous search results are:\n"
            for i, pred_file in enumerate(pred_files):
                last_search_results += f"File {pred_file}:\n"
                for sample_index in range(len(found_edit_locs)):
                    last_search_results += found_edit_locs[sample_index][i][0] + "\n"
            print("last_search_results", last_search_results)
            print("Scope of search too limited, searching for more context")
        else:
            # review the results
            last_search_results = "### Previous search results ###\n"
            last_search_results += "Your previous search results are here, you should review your results and see if they are right.\n"
            last_search_results += "If you think they are right, you should return the original locations\n"
            # repeat to emphasize the importance of the search
            last_search_results += "If you think you made a mistake, then please regenerate the locations:\n"
            for i, pred_file in enumerate(pred_files):
                last_search_results += f"File {pred_file}\n"
            last_search_results += "\nThe previous search results are:\n"
            for i, pred_file in enumerate(pred_files):
                last_search_results += f"File {pred_file}:\n"
                for sample_index in range(len(found_edit_locs)):
                    last_search_results += found_edit_locs[sample_index][i][0] + "\n"
            print("last_search_results", last_search_results)
            print("Do the review!")

        fl = LLMFL(
            file_json["instance_id"],
            structure,
            problem_statement,
            args.model,
            args.backend,
            logger,
            args.match_partial_paths,
            args.temperature
        )
        (
            found_edit_locs_extra,
            additional_artifact_loc_edit_location_extra,
            edit_loc_traj_extra,
        ) = fl.localize_line_from_coarse_function_locs(
            pred_files,
            coarse_found_locs,
            context_window=args.context_window,
            add_space=args.add_space,
            code_graph=args.repo_graph,
            no_line_number=args.no_line_number,
            sticky_scroll=args.sticky_scroll,
            mock=args.mock,
            num_samples=args.num_samples,
            coverage_info=coverage_info,
            last_search_results=last_search_results
        )
        additional_artifact_loc_edit_location += additional_artifact_loc_edit_location_extra
        edit_loc_traj['prompt2'] = edit_loc_traj_extra['prompt']
        edit_loc_traj['response2'] = edit_loc_traj_extra['response']
        edit_loc_traj['usage2'] = edit_loc_traj_extra['usage']

        if all_context_len < 300:
            for i in range(len(found_edit_locs_extra)):
                # Check if i is within the bounds of found_edit_locs
                if i < len(found_edit_locs):
                    for j in range(len(found_edit_locs_extra[i])):
                        # Check if j is within the bounds of found_edit_locs[i] and that both lists contain at least one element at index 0
                        if j < len(found_edit_locs[i]) and found_edit_locs[i][j] and found_edit_locs_extra[i][j] and len(found_edit_locs[i][j]) > 0 and len(found_edit_locs_extra[i][j]) > 0:
                            found_edit_locs[i][j][0] += '\n' + found_edit_locs_extra[i][j][0]
                            found_edit_locs[i][j][0] = found_edit_locs[i][j][0].strip()
        else:
            found_edit_locs = found_edit_locs_extra

    with open(args.output_file, "a") as f:
        f.write(
            json.dumps(
                {
                    "instance_id": file_json["instance_id"],
                    "found_files": found_files,
                    "search_result": search_str_with_file,
                    "additional_artifact_loc_file": additional_artifact_loc_file,
                    "file_traj": file_traj,
                    "found_related_locs": found_related_locs,
                    "additional_artifact_loc_related": additional_artifact_loc_related,
                    "related_loc_traj": related_loc_traj,
                    "found_edit_locs": found_edit_locs,
                    "additional_artifact_loc_edit_location": additional_artifact_loc_edit_location,
                    "edit_loc_traj": edit_loc_traj,
                }
            )
            + "\n"
        )


def localize(args):
    if args.benchmark == "lite":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    elif args.benchmark == "verified":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    elif args.benchmark == "full":
        swe_bench_data = load_dataset("princeton-nlp/SWE-bench", split="test")
    else:
        swe_bench_data = None
    start_file_locs = load_jsonl(args.start_file) if args.start_file else None
    existing_instance_ids = (
        load_existing_instance_ids(args.output_file) if args.skip_existing else set()
    )
    all_task_ids = []
    if args.task_list_file is not None:
        all_task_ids = parse_task_list_file(args.task_list_file)
    elif args.target_id is not None:
        all_task_ids = [args.target_id]
    else:
        for bug in swe_bench_data:
            all_task_ids.append(bug["instance_id"])

    if args.num_threads == 1:
        for bug in swe_bench_data:
            if bug["instance_id"] in all_task_ids:
                localize_instance(
                    bug, args, swe_bench_data, start_file_locs, existing_instance_ids
                )
    else:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.num_threads
        ) as executor:
            futures = [
                executor.submit(
                    localize_instance,
                    bug,
                    args,
                    swe_bench_data,
                    start_file_locs,
                    existing_instance_ids,
                )
                for bug in swe_bench_data if bug["instance_id"] in all_task_ids
            ]
            concurrent.futures.wait(futures)


def merge(args):
    """Merge predicted locations."""
    start_file_locs = load_jsonl(args.start_file)

    # Dump each location sample.
    for st_id in range(args.num_samples):
        en_id = st_id
        merged_locs = []
        for locs in start_file_locs:
            merged_found_locs = []
            if "found_edit_locs" in locs and len(locs["found_edit_locs"]):
                merged_found_locs = [
                    "\n".join(x) for x in locs["found_edit_locs"][st_id]
                ]
            merged_locs.append({**locs, "found_edit_locs": merged_found_locs})
        with open(
                f"{args.output_folder}/loc_merged_{st_id}-{en_id}_outputs.jsonl", "w"
        ) as f:
            for data in merged_locs:
                f.write(json.dumps(data) + "\n")

    # Pair wise merge
    for st_id in range(0, args.num_samples - 1, 2):
        en_id = st_id + 1
        print(f"Merging sample {st_id} and {en_id}...")
        merged_locs = []
        for locs in start_file_locs:
            merged_found_locs = []
            if "found_edit_locs" in locs and len(locs["found_edit_locs"]):
                merged_found_locs = [
                    "\n".join(x) for x in locs["found_edit_locs"][st_id]
                ]
                for sample_found_locs in locs["found_edit_locs"][st_id + 1: en_id + 1]:
                    for i, file_found_locs in enumerate(sample_found_locs):
                        if isinstance(file_found_locs, str):
                            merged_found_locs[i] += "\n" + file_found_locs
                        else:
                            merged_found_locs[i] += "\n" + "\n".join(file_found_locs)
            merged_locs.append({**locs, "found_edit_locs": merged_found_locs})
        with open(
                f"{args.output_folder}/loc_merged_{st_id}-{en_id}_outputs.jsonl", "w"
        ) as f:
            for data in merged_locs:
                f.write(json.dumps(data) + "\n")

    ### Merge all
    all_merged_locs = []
    print("Merging all samples...")
    for locs in start_file_locs:
        merged_found_locs = []
        if "found_edit_locs" in locs and len(locs["found_edit_locs"]):
            merged_found_locs = ["\n".join(x) for x in locs["found_edit_locs"][0]]
            for sample_found_locs in locs["found_edit_locs"][1:]:
                for i, file_found_locs in enumerate(sample_found_locs):
                    if isinstance(file_found_locs, str):
                        merged_found_locs[i] += "\n" + file_found_locs
                    else:
                        merged_found_locs[i] += "\n" + "\n".join(file_found_locs)
        all_merged_locs.append({**locs, "found_edit_locs": merged_found_locs})
    with open(f"{args.output_folder}/loc_all_merged_outputs.jsonl", "w") as f:
        for data in all_merged_locs:
            f.write(json.dumps(data) + "\n")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--output_folder", type=str, required=True)
    parser.add_argument("--output_file", type=str, default="loc_outputs.jsonl")
    parser.add_argument(
        "--start_file",
        type=str,
        help="""previous output file to start with to reduce
        the work, should use in combination without --file_level""",
    )
    parser.add_argument("--file_level", action="store_true")
    parser.add_argument("--related_level", action="store_true")
    parser.add_argument("--fine_grain_line_level", action="store_true")
    parser.add_argument("--direct_line_level", action="store_true")
    parser.add_argument("--review_level", action="store_true")
    parser.add_argument("--top_n", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--num_samples", type=int, default=1)
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--add_space", action="store_true")
    parser.add_argument("--no_line_number", action="store_true")
    parser.add_argument("--sticky_scroll", action="store_true")
    parser.add_argument("--repo_graph", action="store_true")
    parser.add_argument("--code_graph_dir", type=str, default=None)
    parser.add_argument("--reproduce_folder", type=str)
    parser.add_argument("--use-coverage", action="store_true")
    parser.add_argument(
        "--match_partial_paths",
        action="store_true",
        help="Whether to match model generated files based on subdirectories of original repository if no full matches can be found",
    )
    parser.add_argument("--context_window", type=int, default=10)
    parser.add_argument(
        "--num_threads",
        type=int,
        default=1,
        help="Number of threads to use for creating API requests",
    )
    parser.add_argument("--target_id", type=str)
    parser.add_argument(
        "--task_list_file",
        type=str,
        help="Path to the file that contains all tasks ids to be run.",
    )
    parser.add_argument(
        "--skip_existing",
        action="store_true",
        help="Skip localization of instance id's which already contain a localization in the output file.",
    )
    parser.add_argument(
        "--mock", action="store_true", help="Mock run to compute prompt tokens."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-2024-08-06",
    )
    parser.add_argument(
        "--backend", type=str, default="openai", choices=["openai", "deepseek", "claude"]
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="lite",
        choices=["lite", "verified", "full"],
    )

    args = parser.parse_args()

    import os

    args.output_file = os.path.join(args.output_folder, args.output_file)

    assert (
            not os.path.exists(args.output_file) or args.skip_existing
    ), "Output file already exists and not set to skip existing localizations"

    assert not (
            args.file_level and args.start_file
    ), "Cannot use both file_level and start_file"

    assert not (
            args.file_level and args.fine_grain_line_level and not args.related_level
    ), "Cannot use both file_level and fine_grain_line_level without related_level"

    assert not (
            (not args.file_level) and (not args.start_file)
    ), "Must use either file_level or start_file"

    assert (not "deepseek" in args.model) or (
            args.backend == "deepseek"
    ), "Must specify `--backend deepseek` if using a DeepSeek model"

    assert (not "claude" in args.model) or (
            args.backend == "claude"
    ), "Must specify `--backend claude` if using a Claude model"

    os.makedirs(os.path.join(args.output_folder, "localization_logs"), exist_ok=True)
    os.makedirs(args.output_folder, exist_ok=True)

    # write the arguments
    with open(f"{args.output_folder}/args.json", "w") as f:
        json.dump(vars(args), f, indent=4)

    if args.merge:
        merge(args)
    else:
        localize(args)


if __name__ == "__main__":
    main()
