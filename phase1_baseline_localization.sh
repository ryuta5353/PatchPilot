#!/bin/bash

echo "=== Phase 1: Django 43 Baseline Localization (No RepoGraph) ==="

export PYTHONPATH=$(pwd):$PYTHONPATH

python patchpilot/fl/localize.py \
    --file_level \
    --direct_line_level \
    --output_folder results/localization_phase1_baseline \
    --top_n 5 \
    --compress \
    --context_window=20 \
    --num_samples 4 \
    --num_threads 16 \
    --reproduce_folder results/reproduce \
    --task_list_file instances/test_instances_django_43.txt \
    --benchmark verified

echo "Baseline localization completed!"
