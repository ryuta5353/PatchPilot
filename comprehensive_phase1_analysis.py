#!/usr/bin/env python3
"""
Comprehensive Phase 1 Analysis Tool

Compares Baseline vs RepoGraph Composite Score Localization with detailed metrics:
- File-level hit rates
- Line-level hit rates
- Context quality metrics
- Tag usage analysis
"""

import json
import os
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Any

class Phase1Analyzer:
    def __init__(self, baseline_folder: str, composite_folder: str):
        self.baseline_folder = baseline_folder
        self.composite_folder = composite_folder
        self.baseline_results = {}
        self.composite_results = {}
        self.graph_cache = "RepoGraph_cache"

    def load_results(self, folder: str) -> Dict[str, Any]:
        """Load localization results from JSONL file"""
        results = {}
        output_file = os.path.join(folder, 'loc_outputs.jsonl')

        if not os.path.exists(output_file):
            print(f"Warning: {output_file} not found")
            return results

        with open(output_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    instance_id = data.get('instance_id')
                    if instance_id:
                        results[instance_id] = data
                except json.JSONDecodeError:
                    continue

        return results

    def load_all_results(self):
        """Load both baseline and composite results"""
        print("Loading results...")
        self.baseline_results = self.load_results(self.baseline_folder)
        self.composite_results = self.load_results(self.composite_folder)
        print(f"  Baseline: {len(self.baseline_results)} instances")
        print(f"  Composite: {len(self.composite_results)} instances")

    def evaluate_file_level(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate file-level localization"""
        stats = {
            'total': 0,
            'hits': 0,
            'ranks': [],
            'instances': {}
        }

        for instance_id, data in results.items():
            if 'file_level_results' not in data:
                continue

            stats['total'] += 1
            file_results = data['file_level_results']

            if isinstance(file_results, list) and len(file_results) > 0:
                if data.get('gold_file'):
                    gold_file = data['gold_file']
                    pred_files = []
                    for r in file_results[:5]:
                        if isinstance(r, dict) and 'file' in r:
                            pred_files.append(r['file'])
                        elif isinstance(r, str):
                            pred_files.append(r)

                    hit = 0
                    rank = -1
                    if gold_file in pred_files:
                        hit = 1
                        rank = pred_files.index(gold_file) + 1
                        stats['hits'] += 1
                        stats['ranks'].append(rank)

                    stats['instances'][instance_id] = {
                        'hit': hit,
                        'rank': rank,
                        'gold': gold_file,
                        'predictions': pred_files[:3]
                    }

        return stats

    def evaluate_line_level(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate line-level localization"""
        stats = {
            'total': 0,
            'hits': 0,
            'instances': {}
        }

        for instance_id, data in results.items():
            if 'line_level_results' not in data:
                continue

            stats['total'] += 1
            line_results = data['line_level_results']

            if isinstance(line_results, dict) and line_results:
                for file_key, lines in line_results.items():
                    if data.get('gold_line'):
                        gold_line = data['gold_line']
                        if isinstance(lines, list) and len(lines) > 0:
                            hit = 1 if gold_line in [l['line'] if isinstance(l, dict) else l for l in lines[:5]] else 0
                            if hit:
                                stats['hits'] += 1
                            stats['instances'][instance_id] = {'hit': hit}

        return stats

    def compare_results(self) -> Dict[str, Any]:
        """Compare baseline vs composite"""
        baseline_file = self.evaluate_file_level(self.baseline_results)
        composite_file = self.evaluate_file_level(self.composite_results)

        baseline_line = self.evaluate_line_level(self.baseline_results)
        composite_line = self.evaluate_line_level(self.composite_results)

        baseline_file_hit = (baseline_file['hits'] / baseline_file['total'] * 100) if baseline_file['total'] > 0 else 0
        composite_file_hit = (composite_file['hits'] / composite_file['total'] * 100) if composite_file['total'] > 0 else 0

        baseline_line_hit = (baseline_line['hits'] / baseline_line['total'] * 100) if baseline_line['total'] > 0 else 0
        composite_line_hit = (composite_line['hits'] / composite_line['total'] * 100) if composite_line['total'] > 0 else 0

        return {
            'file_level': {
                'baseline': baseline_file,
                'composite': composite_file,
                'baseline_hit': baseline_file_hit,
                'composite_hit': composite_file_hit,
                'improvement': composite_file_hit - baseline_file_hit
            },
            'line_level': {
                'baseline': baseline_line,
                'composite': composite_line,
                'baseline_hit': baseline_line_hit,
                'composite_hit': composite_line_hit,
                'improvement': composite_line_hit - baseline_line_hit
            }
        }

    def print_report(self, results: Dict[str, Any]):
        """Print comprehensive analysis report"""
        print("\n" + "="*80)
        print("PHASE 1 COMPREHENSIVE ANALYSIS REPORT")
        print("="*80)

        file_res = results['file_level']
        print(f"\n[FILE-LEVEL LOCALIZATION]")
        print(f"Baseline Hit Rate:    {file_res['baseline_hit']:6.2f}%  ({file_res['baseline']['hits']:2d}/{file_res['baseline']['total']:2d})")
        print(f"Composite Hit Rate:   {file_res['composite_hit']:6.2f}%  ({file_res['composite']['hits']:2d}/{file_res['composite']['total']:2d})")
        imp_pct = (file_res['improvement']/file_res['baseline_hit']*100) if file_res['baseline_hit'] > 0 else 0
        print(f"Improvement:          {file_res['improvement']:6.2f}pp  ({imp_pct:+6.1f}%)")

        line_res = results['line_level']
        print(f"\n[LINE-LEVEL LOCALIZATION]")
        print(f"Baseline Hit Rate:    {line_res['baseline_hit']:6.2f}%  ({line_res['baseline']['hits']:2d}/{line_res['baseline']['total']:2d})")
        print(f"Composite Hit Rate:   {line_res['composite_hit']:6.2f}%  ({line_res['composite']['hits']:2d}/{line_res['composite']['total']:2d})")
        imp_pct = (line_res['improvement']/line_res['baseline_hit']*100) if line_res['baseline_hit'] > 0 else 0
        print(f"Improvement:          {line_res['improvement']:6.2f}pp  ({imp_pct:+6.1f}%)")

        common = set(file_res['baseline']['instances'].keys()) & set(file_res['composite']['instances'].keys())
        improvements = []
        regressions = []

        for inst in common:
            base = file_res['baseline']['instances'][inst]
            comp = file_res['composite']['instances'][inst]
            if comp['hit'] > base['hit']:
                improvements.append(inst)
            elif comp['hit'] < base['hit']:
                regressions.append(inst)

        print(f"\n[INSTANCE-LEVEL CHANGES]")
        print(f"Improvements:  {len(improvements):2d} instances")
        print(f"Regressions:   {len(regressions):2d} instances")
        print(f"No change:     {len(common) - len(improvements) - len(regressions):2d} instances")

        if improvements:
            print(f"\nTop 10 Improvements:")
            for inst in improvements[:10]:
                print(f"  - {inst}")

        if regressions:
            print(f"\nTop 10 Regressions:")
            for inst in regressions[:10]:
                print(f"  - {inst}")

        print("\n" + "="*80)

def main():
    analyzer = Phase1Analyzer(
        'results/localization_phase1_baseline',
        'results/localization_phase1_composite'
    )

    analyzer.load_all_results()
    results = analyzer.compare_results()
    analyzer.print_report(results)

    with open('phase1_analysis_detailed.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print("\nDetailed results saved to: phase1_analysis_detailed.json")

if __name__ == '__main__':
    main()
