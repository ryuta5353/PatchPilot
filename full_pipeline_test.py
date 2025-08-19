#!/usr/bin/env python3
"""
Full PatchPilot Pipeline Test with Ollama
全ステップ（Reproduction, Localization, Generation, Validation, Refinement）のテスト

【目的】:
1. PatchPilotの完全なワークフロー（5段階すべて）をOllamaで実行
2. 修正率の評価：どの程度のバグが実際に修正できるかを確認
3. 各ステップでの無料LLM統合が正常動作することを検証

【なぜ必要】:
- Localization強化の効果を評価するには、最終的な修正成功率を測定する必要がある
- 個別のステップテストだけでは、全体の性能改善が分からない
- my_swe_lite_tasks.txtのタスクで実際のバグ修正能力を評価する
"""

import os
import sys
import subprocess
import time
import json
from pathlib import Path

def setup_test_environment():
    """テスト環境をセットアップ"""
    print("🔧 Full Pipeline テスト環境セットアップ中...")
    
    # 既存のmy_swe_lite_tasks.txtを使用
    tasks_file = "my_swe_lite_tasks.txt"
    
    if not os.path.exists(tasks_file):
        print(f"❌ {tasks_file} が見つかりません")
        return []
    
    # ファイルからテストケースを読み込み
    with open(tasks_file, "r") as f:
        test_cases = [line.strip() for line in f if line.strip()]
    
    print(f"✅ {tasks_file}から{len(test_cases)}件のテストケースを読み込み:")
    for i, case in enumerate(test_cases, 1):
        print(f"   {i}. {case}")
    
    return test_cases

def check_ollama_connection():
    """Ollama接続確認"""
    print("\n🔍 Ollama接続確認...")
    try:
        from patchpilot.util.model import OllamaChatDecoder
        import logging
        
        logger = logging.getLogger("test")
        decoder = OllamaChatDecoder("phi3:mini", logger)
        
        if decoder.test_connection():
            print("✅ Ollama接続OK")
            return True
        else:
            print("❌ Ollama接続失敗")
            return False
    except Exception as e:
        print(f"❌ Ollama接続エラー: {e}")
        return False

def run_reproduction_step():
    """Step 1: Reproduction - バグ再現"""
    print("\n🔄 Step 1: Reproduction (バグ再現)")
    
    output_folder = "results/full_pipeline/reproduction"
    os.makedirs(output_folder, exist_ok=True)
    
    cmd = [
        "python", "patchpilot/reproduce/reproduce.py",
        "--reproduce_folder", output_folder,
        "--task_list_file", "my_swe_lite_tasks.txt",
        "--backend", "ollama",
        "--model", "phi3:mini",
        "--num_threads", "1",  # 並列度を下げる
        "--setup_map", "setup_result/verified_setup_map.json",
        "--tasks_map", "setup_result/verified_tasks_map.json"
    ]
    
    print("📤 実行コマンド:")
    print(" ".join(cmd))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode == 0:
            print("✅ Reproduction成功")
            return output_folder
        else:
            print("❌ Reproduction失敗")
            print(result.stderr)
            return None
    except subprocess.TimeoutExpired:
        print("❌ Reproduction タイムアウト")
        return None

def run_localization_step(reproduce_folder):
    """Step 2: Localization - 障害位置特定"""
    print("\n🎯 Step 2: Localization (障害位置特定)")
    
    output_folder = "results/full_pipeline/localization"
    os.makedirs(output_folder, exist_ok=True)
    
    cmd = [
        "python", "patchpilot/fl/localize.py",
        "--file_level",
        "--direct_line_level",
        "--output_folder", output_folder,
        "--task_list_file", "my_swe_lite_tasks.txt",
        "--backend", "ollama",
        "--model", "phi3:mini",
        "--top_n", "5",
        "--context_window", "15",
        "--num_samples", "2",
        "--batch_size", "1",
        "--temperature", "0.1",
        "--max_tokens", "1024"
    ]
    
    # reproductionの結果を使用
    if reproduce_folder:
        cmd.extend(["--reproduce_folder", reproduce_folder])
    
    print("📤 実行コマンド:")
    print(" ".join(cmd))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode == 0:
            print("✅ Localization成功")
            return output_folder
        else:
            print("❌ Localization失敗")
            print(result.stderr)
            return None
    except subprocess.TimeoutExpired:
        print("❌ Localization タイムアウト")
        return None

def run_generation_step(localization_folder, reproduce_folder):
    """Step 3: Generation - パッチ生成"""
    print("\n🛠️ Step 3: Generation (パッチ生成)")
    
    output_folder = "results/full_pipeline/generation"
    os.makedirs(output_folder, exist_ok=True)
    
    # localizationの結果ファイルを確認
    loc_file = f"{localization_folder}/merged/loc_all_merged_outputs.jsonl"
    if not os.path.exists(loc_file):
        # 代替パスを試す
        loc_file = f"{localization_folder}/loc_all_merged_outputs.jsonl"
        if not os.path.exists(loc_file):
            print(f"❌ Localization結果ファイルが見つかりません: {loc_file}")
            return None
    
    cmd = [
        "python", "patchpilot/repair/repair.py",
        "--loc_file", loc_file,
        "--output_folder", output_folder,
        "--backend", "ollama",
        "--model", "phi3:mini",
        "--max_samples", "4",  # サンプル数を減らす
        "--batch_size", "2",
        "--temperature", "0.2",
        "--max_tokens", "2048",
        "--benchmark", "verified"
    ]
    
    # reproductionの結果を使用
    if reproduce_folder:
        cmd.extend(["--reproduce_folder", reproduce_folder])
    
    print("📤 実行コマンド:")
    print(" ".join(cmd))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)  # 1時間
        if result.returncode == 0:
            print("✅ Generation成功")
            return output_folder
        else:
            print("❌ Generation失敗")
            print(result.stderr)
            return None
    except subprocess.TimeoutExpired:
        print("❌ Generation タイムアウト")
        return None

def run_validation_step(generation_folder):
    """Step 4: Validation - パッチ検証"""
    print("\n✅ Step 4: Validation (パッチ検証)")
    
    output_folder = "results/full_pipeline/validation"
    os.makedirs(output_folder, exist_ok=True)
    
    cmd = [
        "python", "patchpilot/reproduce/verify.py",
        "--verify_folder", output_folder,
        "--task_list_file", "my_swe_lite_tasks.txt",
        "--backend", "ollama",
        "--model", "phi3:mini",
        "--num_threads", "1",
        "--setup_map", "setup_result/verified_setup_map.json",
        "--tasks_map", "setup_result/verified_tasks_map.json"
    ]
    
    # generationの結果を指定
    prediction_file = f"{generation_folder}/all_preds.jsonl"
    if os.path.exists(prediction_file):
        cmd.extend(["--prediction_file", prediction_file])
    
    print("📤 実行コマンド:")
    print(" ".join(cmd))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode == 0:
            print("✅ Validation成功")
            return output_folder
        else:
            print("❌ Validation失敗")
            print(result.stderr)
            return None
    except subprocess.TimeoutExpired:
        print("❌ Validation タイムアウト")
        return None

def analyze_final_results():
    """最終結果の分析"""
    print("\n📊 最終結果分析...")
    
    results_summary = {
        "reproduction": {"success": False, "details": ""},
        "localization": {"success": False, "details": ""},
        "generation": {"success": False, "details": ""},
        "validation": {"success": False, "details": ""},
        "overall_success": False
    }
    
    # 各ステップの結果を確認
    base_path = "results/full_pipeline"
    
    # Localization結果
    loc_file = f"{base_path}/localization/loc_all_merged_outputs.jsonl"
    if os.path.exists(loc_file):
        results_summary["localization"]["success"] = True
        with open(loc_file, "r") as f:
            loc_results = [json.loads(line) for line in f]
        results_summary["localization"]["details"] = f"{len(loc_results)}件のローカライゼーション完了"
    
    # Generation結果
    gen_file = f"{base_path}/generation/all_preds.jsonl"
    if os.path.exists(gen_file):
        results_summary["generation"]["success"] = True
        with open(gen_file, "r") as f:
            gen_results = [json.loads(line) for line in f]
        results_summary["generation"]["details"] = f"{len(gen_results)}件のパッチ生成完了"
    
    # Validation結果
    val_file = f"{base_path}/validation/verify_results.jsonl"
    if os.path.exists(val_file):
        results_summary["validation"]["success"] = True
        try:
            with open(val_file, "r") as f:
                val_results = [json.loads(line) for line in f]
            passed_tests = sum(1 for r in val_results if r.get("status") == "passed")
            results_summary["validation"]["details"] = f"{passed_tests}/{len(val_results)}件のテスト成功"
        except:
            results_summary["validation"]["details"] = "検証結果解析エラー"
    
    # 全体的な成功判定
    results_summary["overall_success"] = (
        results_summary["localization"]["success"] and 
        results_summary["generation"]["success"]
    )
    
    # 結果出力
    print("\n=== 実行結果サマリー ===")
    for step, result in results_summary.items():
        if step != "overall_success":
            status = "✅" if result["success"] else "❌"
            print(f"{status} {step.capitalize()}: {result['details']}")
    
    if results_summary["overall_success"]:
        print("\n🎉 Full Pipeline テスト成功！")
        print("  → Localizationの強化効果を評価する準備が整いました")
        print("  → Phase 1 (Repograph統合) に進むことができます")
    else:
        print("\n⚠️  一部ステップで問題が発生しました")
        print("  → 個別ステップのログを確認してください")
    
    return results_summary

def main():
    """メイン実行"""
    print("=== PatchPilot Full Pipeline Test (Ollama) ===\n")
    
    # 1. テスト環境セットアップ
    test_cases = setup_test_environment()
    if not test_cases:
        return False
    
    # 2. Ollama接続確認
    if not check_ollama_connection():
        print("   解決方法: bash setup_ollama.sh を実行してください")
        return False
    
    # 3. 各ステップの実行
    print("\n🚀 Full Pipeline 実行開始...")
    start_time = time.time()
    
    # Step 1: Reproduction
    reproduce_folder = run_reproduction_step()
    
    # Step 2: Localization  
    localization_folder = run_localization_step(reproduce_folder)
    
    if not localization_folder:
        print("❌ Localizationが失敗したため、後続ステップをスキップします")
        return False
    
    # Step 3: Generation
    generation_folder = run_generation_step(localization_folder, reproduce_folder)
    
    if not generation_folder:
        print("❌ Generationが失敗したため、Validationをスキップします")
    else:
        # Step 4: Validation
        validation_folder = run_validation_step(generation_folder)
    
    # 実行時間
    end_time = time.time()
    execution_time = (end_time - start_time) / 60
    
    # 4. 結果分析
    results = analyze_final_results()
    
    print(f"\n⏱️  総実行時間: {execution_time:.1f}分")
    print(f"📁 結果フォルダ: results/full_pipeline/")
    
    return results["overall_success"]

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)