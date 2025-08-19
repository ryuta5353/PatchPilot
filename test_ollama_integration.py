#!/usr/bin/env python3
"""
Phase 0: Ollama統合テストスクリプト
PatchPilotでの無料LLM動作確認

【目的】:
1. Ollamaサーバーとの接続をテスト
2. PatchPilotのmodel.pyで追加したOllamaChatDecoderが正常動作するかテスト
3. 簡単なプロンプトでレスポンス生成をテスト

【なぜ必要】:
- 実際のSWE-benchタスク（時間がかかる）を実行する前に
- 基本的な統合が動作することを素早く確認するため
"""

import sys
import logging
from pathlib import Path

# PatchPilotのパスを追加
sys.path.append(str(Path(__file__).parent))

from patchpilot.util.model import make_model, OllamaChatDecoder

def test_ollama_connection():
    """Ollamaサーバーとの接続をテスト"""
    print("🔍 Ollama接続テスト...")
    
    # ダミーロガー作成
    logger = logging.getLogger("test")
    logger.setLevel(logging.INFO)
    
    # Ollamaデコーダー作成
    decoder = OllamaChatDecoder(
        name="phi3:mini",
        logger=logger,
        temperature=0.1,
        max_new_tokens=100
    )
    
    # 接続テスト
    if decoder.test_connection():
        print("✅ Ollama接続成功")
        return True
    else:
        print("❌ Ollama接続失敗")
        print("   解決方法:")
        print("   1. 'ollama serve' でサーバーを起動")
        print("   2. 'ollama pull phi3:mini' でモデルをダウンロード")
        return False

def test_model_generation():
    """モデル生成機能をテスト"""
    print("\n🧠 モデル生成テスト...")
    
    # ダミーロガー作成
    logger = logging.getLogger("test")
    
    # make_model関数でモデル作成
    try:
        model = make_model(
            model="phi3:mini",
            backend="ollama",
            logger=logger,
            temperature=0.1,
            max_tokens=200
        )
        print("✅ モデル作成成功")
    except Exception as e:
        print(f"❌ モデル作成失敗: {e}")
        return False
    
    # 簡単なコード生成テスト
    test_prompt = """
以下のPythonコードの問題点を特定してください：

```python
def calculate_sum(numbers):
    total = 0
    for i in range(len(numbers)):
        total += numbers[i]
    return total

result = calculate_sum([1, 2, 3, 4, 5])
print(result)
```

問題点があれば修正案を提案してください。
"""
    
    try:
        print("📤 プロンプト送信中...")
        responses = model.codegen(test_prompt, num_samples=1)
        
        if responses and len(responses) > 0:
            response = responses[0]
            print("✅ レスポンス受信成功")
            print(f"📊 使用量: {response['usage']}")
            print(f"📝 レスポンス長: {len(response['response'])}文字")
            print("\n--- レスポンス内容 (最初の300文字) ---")
            print(response['response'][:300])
            if len(response['response']) > 300:
                print("...")
            print("--- レスポンス終了 ---\n")
            return True
        else:
            print("❌ レスポンス受信失敗")
            return False
            
    except Exception as e:
        print(f"❌ 生成エラー: {e}")
        return False

def test_both_models():
    """phi3:miniとcodellama:7b-instructの両方をテスト"""
    print("\n🔄 複数モデルテスト...")
    
    models_to_test = ["phi3:mini", "codellama:7b-instruct"]
    logger = logging.getLogger("test")
    
    for model_name in models_to_test:
        print(f"\n--- {model_name} テスト ---")
        
        try:
            model = make_model(
                model=model_name,
                backend="ollama", 
                logger=logger,
                temperature=0.1,
                max_tokens=50
            )
            
            # 簡単なテストプロンプト
            prompt = "Hello! Please respond with 'Model working correctly.'"
            responses = model.codegen(prompt, num_samples=1)
            
            if responses and len(responses) > 0:
                print(f"✅ {model_name}: 正常動作")
                print(f"   レスポンス: {responses[0]['response'][:100]}")
            else:
                print(f"❌ {model_name}: レスポンス取得失敗")
                
        except Exception as e:
            print(f"❌ {model_name}: エラー - {e}")

def main():
    """メインテスト実行"""
    print("=== Phase 0: PatchPilot + Ollama 統合テスト ===\n")
    
    # 1. 接続テスト
    if not test_ollama_connection():
        print("\n❌ 接続テストに失敗しました。先にOllamaをセットアップしてください。")
        return False
    
    # 2. モデル生成テスト
    if not test_model_generation():
        print("\n❌ モデル生成テストに失敗しました。")
        return False
    
    # 3. 複数モデルテスト
    test_both_models()
    
    print("\n🎉 全テスト完了！")
    print("\n次のステップ:")
    print("1. 実際のSWE-benchタスクでテストする")
    print("2. Phase 1 (Repograph統合) を開始する")
    
    return True

if __name__ == "__main__":
    main()