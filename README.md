# 🛠️ PatchPilot: A Stable and Cost-Efficient Agentic Patching Framework

<p align="center">
    <a href="https://arxiv.org/abs/2502.02747"><img src="https://img.shields.io/badge/arXiv-2502.02747-b31b1b.svg?style=for-the-badge">
    <a href="https://opensource.org/license/mit/"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge">
</p>

<p align="center">
    🔍&nbsp;<a href="#overview">Overview</a>
    | 🛠️&nbsp;<a href="#installation">Installation</a>
    | 🚀&nbsp;<a href="#quick-start">Quick Start</a>
    | 📝&nbsp;<a href="#citation">Citation</a>
</p>

## News

- 🎉 **[May 2025]** PatchPilot accepted at ICML 2025!
- 🚀 **[May 2025]** PatchPilot code are now open-sourced!
- 🚀 **[February 2025]** PatchPilot achieves superior performance on bench while maintaining low cost (< $1 per instance)!
- 📄 **[February 2025]** PatchPilot paper is available on arXiv!

## Overview

### 🛠️ PatchPilot: Balancing Efficacy, Stability, and Cost-Efficiency

PatchPilot is an innovative rule-based planning patching tool that strikes the excellent balance between patching efficacy, stability, and cost-efficiency. 

**Key Innovations:**
- **🎯 Five-Component Workflow**: Reproduction, Localization, Generation, Validation, and **Refinement** 
- **💰 Cost-Efficient**: Less than $1 per instance while maintaining high performance
- **🔒 High Stability**: More stable than agent-based planning methods
- **⚡ Superior Performance**: Outperforms existing open-source methods on SWE-bench

### 🏗️ Architecture Overview

PatchPilot's workflow consists of five specialized components:

1. **🔄 Reproduction**: Reproduce the reported bug to understand the issue
2. **🔍 Localization**: Identify problematic code locations with multi-level analysis
3. **⚡ Generation**: Generate high-quality patch candidates
4. **🛡️ Validation**: Validate patches through comprehensive testing
5. **✨ Refinement**: Unique refinement step to improve patch quality

## Installation

### 🐳 Docker Setup (Recommended)

1. **Pull the Docker image:**
```bash
docker pull 3rdn4/patchpilot_verified:v1
```

2. **Run the container with Docker-in-Docker support:**
```bash
docker run --privileged -v /var/run/docker.sock:/var/run/docker.sock -it 3rdn4/patchpilot_verified:v1
```
> Note: `--privileged -v /var/run/docker.sock:/var/run/docker.sock` is required for Docker-in-Docker functionality used by SWE-bench.

3. **Set up the environment inside the container:**
```bash
cd /opt
git clone git@github.com:ucsb-mlsec/PatchPilot.git
cd PatchPilot
conda activate patchpilot
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

4. **Configure API keys:**
```bash
# For Anthropic Claude
export ANTHROPIC_API_KEY=your_anthropic_key_here

# OR for OpenAI
export OPENAI_API_KEY=your_openai_key_here
```

## Quick Start

### 🔄 1. Reproduction

First, reproduce the bugs to understand the issues:

```bash
python patchpilot/reproduce/reproduce.py \
    --reproduce_folder results/reproduce \
    --num_threads 50 \
    --setup_map setup_result/verified_setup_map.json \
    --tasks_map setup_result/verified_tasks_map.json \
    --task_list_file swe_verify_tasks.txt
```

### 🔍 2. Localization

#### Step 1: Multi-Level Localization
```bash

python patchpilot/fl/localize.py \
    --file_level \
    --related_level \
    --fine_grain_line_level \
    --review_level \
    --output_folder results/localization \
    --top_n 5 \
    --compress \
    --context_window=20 \
    --temperature 0.7 \
    --match_partial_paths \
    --reproduce_folder results/reproduce \
    --task_list_file swe_verify_tasks.txt \
    --num_samples 4 \
    --num_threads 16 \
    --benchmark verified
```

#### Step 2: Merge Localization Results
```bash
python patchpilot/fl/localize.py \
    --merge \
    --output_folder results/localization/merged \
    --start_file results/localization/loc_outputs.jsonl \
    --num_samples 4
```

### ⚡ 3. Repair and Validation

Generate patches with integrated validation:

```bash
python patchpilot/repair/repair.py \
    --loc_file results/localization/merged/loc_all_merged_outputs.jsonl \
    --output_folder results/repair \
    --loc_interval \
    --top_n=5 \
    --context_window=20 \
    --max_samples 12 \
    --batch_size 4 \
    --benchmark verified \
    --reproduce_folder results/reproduce \
    --verify_folder results/verify \
    --setup_map setup_result/verified_setup_map.json \
    --tasks_map setup_result/verified_tasks_map.json \
    --num_threads 16 \
    --task_list_file swe_verify_tasks.txt \
    --refine_mod \
    --benchmark verified
```

### 📊 4. Evaluation

Run SWE-bench evaluation on the generated patches:

```bash
cd /opt/orig_swebench/SWE-bench
conda activate swe_bench

python -m swebench.harness.run_evaluation \
    --predictions_path [path_to_best_patches_round_2.jsonl] \
    --max_workers 16 \
    --run_id [experiment_name]
```

## Configuration Parameters

| Parameter | Description |
|-----------|-------------|
| `--max_samples` | Total number of patch samples to generate per instance |
| `--batch_size` | Number of samples generated per batch (early stopping if validation passes) |
| `--num_threads` | Number of parallel processing threads |
| `--task_list_file` | File containing instances to be fixed |
| `--loc_file` | Output file from the localization step |
| `--backend` | Model backend (claude, openai, etc.) |
| `--model` | Specific model version |
| `--loc_interval` | Provide multiple context intervals vs. min-max range only |
| `--top_n` | Number of files to consider as context |
| `--context_window` | Lines of context around localized code |
| `--refine_mod` | Enable PatchPilot's unique refinement component |

### 🔄 Resuming Interrupted Experiments

If an experiment is interrupted, simply rerun the same command - PatchPilot will resume from where it left off. For different experiments, clean the folders or use different output directories.


## 📝 Citation

If you find PatchPilot useful in your research, please cite our paper:

```bibtex
@article{li2025patchpilot,
  title={PatchPilot: A Stable and Cost-Efficient Agentic Patching Framework},
  author={Li, Hongwei and Tang, Yuheng and Wang, Shiqi and Guo, Wenbo},
  journal={arXiv preprint arXiv:2502.02747},
  year={2025}
}
```

---

<p align="center">
    Made with ❤️ by the UCSB ML Security Team
</p>

