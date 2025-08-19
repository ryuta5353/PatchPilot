#!/usr/bin/env python3
"""
Phase 0: 無料LLMでのPatchPilot動作確認
実際のSWE-benchタスクでテスト
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def setup_test_environment():
    """テスト環境をセットアップ"""
    print("🔧 テスト環境セットアップ中...")
    
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

def test_ollama_localization():
    """Ollamaを使ったローカライゼーションをテスト"""
    print("\n🎯 Phase 0: Ollama + PatchPilot Localization テスト")
    
    # 出力フォルダ準備
    output_folder = "results/phase0_ollama_test"
    os.makedirs(output_folder, exist_ok=True)
    
    # テスト実行
    cmd = [
        "python", "patchpilot/fl/localize.py",
        "--file_level",
        "--direct_line_level", 
        "--output_folder", output_folder,
        "--task_list_file", "my_swe_lite_tasks.txt",
        "--backend", "ollama",
        "--model", "phi3:mini",
        "--top_n", "3",  # 上位3ファイルのみ
        "--context_window", "10",  # コンテキストウィンドウを小さく
        "--num_samples", "1",  # サンプル数を最小に
        "--batch_size", "1",
        "--temperature", "0.1",
        "--max_tokens", "512"  # トークン数制限
    ]
    
    print("📤 実行コマンド:")
    print(" ".join(cmd))
    print("\n⏳ 実行中（これには数分かかる場合があります）...")
    
    start_time = time.time()
    try:
        # 実行
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800  # 30分タイムアウト
        )
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"⏱️  実行時間: {execution_time:.1f}秒")
        
        if result.returncode == 0:
            print("✅ Phase 0テスト成功！")
            print("\n📊 結果概要:")
            print(f"   出力フォルダ: {output_folder}")
            
            # 結果ファイル確認
            if os.path.exists(f"{output_folder}/loc_all_merged_outputs.jsonl"):
                with open(f"{output_folder}/loc_all_merged_outputs.jsonl", "r") as f:
                    lines = f.readlines()
                print(f"   生成結果: {len(lines)}件")
            
            # ログ出力の最後の部分を表示
            if result.stdout:
                print("\n--- 実行ログ（最後の500文字） ---")
                print(result.stdout[-500:])
            
            return True
        else:
            print("❌ Phase 0テスト失敗")
            print("--- エラー出力 ---")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ タイムアウト（30分経過）")
        return False
    except Exception as e:
        print(f"❌ 実行エラー: {e}")
        return False

def analyze_results():
    """結果を分析"""
    print("\n📈 結果分析...")
    
    output_folder = "results/phase0_ollama_test"
    result_file = f"{output_folder}/loc_all_merged_outputs.jsonl"
    
    if not os.path.exists(result_file):
        print("❌ 結果ファイルが見つかりません")
        return
    
    try:
        import json
        with open(result_file, "r") as f:
            results = [json.loads(line) for line in f]
        
        print(f"📊 処理済みインスタンス: {len(results)}件")
        
        for result in results:
            instance_id = result.get("instance_id", "unknown")
            top_files = result.get("loc_outputs", {}).get("top_files", [])
            
            print(f"\n--- {instance_id} ---")
            print(f"特定されたファイル数: {len(top_files)}")
            
            if top_files:
                print("上位ファイル:")
                for i, file_info in enumerate(top_files[:3]):
                    if isinstance(file_info, dict):
                        file_path = file_info.get("file_path", "unknown")
                        score = file_info.get("score", 0)
                        print(f"  {i+1}. {file_path} (score: {score:.3f})")
                    else:
                        print(f"  {i+1}. {file_info}")
        
    except Exception as e:
        print(f"❌ 結果分析エラー: {e}")

def main():
    """メイン実行"""
    print("=== Phase 0: 無料LLM (Ollama) + PatchPilot 統合テスト ===\n")
    
    # 1. テスト環境セットアップ
    test_cases = setup_test_environment()
    
    # 2. Ollama接続確認
    print("\n🔍 Ollama接続確認...")
    try:
        from patchpilot.util.model import OllamaChatDecoder
        import logging
        
        logger = logging.getLogger("test")
        decoder = OllamaChatDecoder("phi3:mini", logger)
        
        if decoder.test_connection():
            print("✅ Ollama接続OK")
        else:
            print("❌ Ollama接続失敗")
            print("   解決方法: './setup_ollama.sh' を実行してください")
            return False
    except Exception as e:
        print(f"❌ Ollama接続エラー: {e}")
        return False
    
    # 3. 実際のテスト実行
    success = test_ollama_localization()
    
    if success:
        # 4. 結果分析
        analyze_results()
        
        print("\n🎉 Phase 0完了！")
        print("\n📋 次のステップ:")
        print("1. より多くのテストケースで検証")  
        print("2. Phase 1 (Repograph統合) の実装開始")
        print("3. codellama:7b-instructでの高精度テスト")
    else:
        print("\n❌ Phase 0失敗")
        print("   トラブルシューティング:")
        print("   1. Ollamaが正常に起動しているか確認")
        print("   2. phi3:miniモデルがダウンロード済みか確認") 
        print("   3. メモリ不足でないか確認")
    
    # 注意: my_swe_lite_tasks.txtは削除しない（ユーザーが作成したファイル）

if __name__ == "__main__":
    main()