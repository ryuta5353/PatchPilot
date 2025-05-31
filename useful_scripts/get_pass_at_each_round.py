import subprocess

command_template = (
    "python -m swebench.harness.run_evaluation "
    "--predictions_path /opt/PatchingAgent/results_30_diverse/repair/output_{i}_processed.jsonl "
    "--max_workers 40 "
    "--run_id results_30_diverse_output_{i}_processed"
)

for i in range(10):
    command = command_template.format(i=i)
    print(f"Running: {command}")
    subprocess.run(command, shell=True, check=True)
    
print("All commands completed.")
