# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PatchPilot is a rule-based planning patching framework for automated software bug fixing. It implements a five-component workflow: Reproduction, Localization, Generation, Validation, and Refinement. The system is designed to be stable and cost-efficient while maintaining high performance on SWE-bench benchmarks.

## Core Architecture

### Main Components

1. **Reproduction Module** (`patchpilot/reproduce/`)
   - `reproduce.py`: Main entry point for bug reproduction
   - `verify.py`: Patch validation and testing
   - `task.py`: SWE-bench task management
   - `formal_verification.py`: Formal verification utilities

2. **Localization Module** (`patchpilot/fl/`)
   - `localize.py`: Multi-level fault localization
   - `FL.py`: LLM-based fault localization implementation

3. **Repair Module** (`patchpilot/repair/`)
   - `repair.py`: Main patch generation logic with refinement capabilities
   - `bfs.py`: Breadth-first search for patch exploration
   - `utils.py`: Post-processing and context construction utilities

4. **Utility Module** (`patchpilot/util/`)
   - `model.py`: Language model abstraction layer
   - `api_requests.py`: API request handling
   - `preprocess_data.py`: Data preprocessing utilities
   - `search_tool.py`: Code search functionality
   - `utils_for_swe.py`: SWE-bench specific utilities

5. **Model Zoo** (`patchpilot/model_zoo/`)
   - Provides abstractions for different LLM backends (Anthropic, OpenAI, LiteLLM, VLLM)

## Development Commands

### Environment Setup
```bash
# Activate conda environment (if using Docker)
conda activate patchpilot

# Set Python path
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Configure API keys
export ANTHROPIC_API_KEY=your_key  # For Claude
export OPENAI_API_KEY=your_key     # For OpenAI
```

### Running Components

**Reproduction:**
```bash
python patchpilot/reproduce/reproduce.py \
    --reproduce_folder results/reproduce \
    --num_threads 50 \
    --setup_map setup_result/verified_setup_map.json \
    --tasks_map setup_result/verified_tasks_map.json \
    --task_list_file swe_verify_tasks.txt
```

**Localization:**
```bash
python patchpilot/fl/localize.py \
    --file_level --direct_line_level \
    --output_folder results/localization \
    --top_n 5 --compress \
    --context_window=20 \
    --num_samples 4 --num_threads 16
```

**Repair with Refinement:**
```bash
python patchpilot/repair/repair.py \
    --loc_file results/localization/merged/loc_all_merged_outputs.jsonl \
    --output_folder results/repair \
    --max_samples 12 --batch_size 4 \
    --refine_mod --benchmark verified
```

### Testing

No formal test framework is configured. Validation is performed through:
- `patchpilot/reproduce/verify.py` for patch verification
- SWE-bench evaluation harness for final testing

## Key Configuration Files

- `setup_result/verified_setup_map.json`: Repository setup configurations
- `setup_result/verified_tasks_map.json`: Task definitions and test commands
- `swe_verify_tasks.txt`: List of task instances to process

## Important Notes

- The system uses Docker-in-Docker for SWE-bench evaluation (requires `--privileged` flag)
- Results are automatically cached; rerunning commands will resume from previous state
- The `--refine_mod` flag enables PatchPilot's unique refinement component for improved patch quality
- Batch processing with early stopping is controlled via `--batch_size` parameter