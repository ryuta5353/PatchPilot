# Phase 0: 無料LLM (Ollama) 統合

PatchPilotに無料のOllamaバックエンドを統合し、基本動作を確認するフェーズです。

## 🚀 セットアップ手順

### 1. Ollama環境構築

```bash
# Ollamaをインストールしてモデルをダウンロード
bash setup_ollama.sh
```

このスクリプトは以下を実行します：
- Ollamaのインストール（初回のみ）
- サーバー起動
- `phi3:mini` (2GB) - 軽量高速モデル
- `codellama:7b-instruct` (4GB) - 高性能モデル

### 2. 統合テスト

```bash
# 基本的な接続・生成テスト
python test_ollama_integration.py
```

期待される出力：
```
✅ Ollama接続成功
✅ モデル作成成功
✅ レスポンス受信成功
🎉 全テスト完了！
```

### 3. Localizationのみテスト

```bash
# Localizationステップのみの動作確認
python phase0_test.py
```

### 4. 全ステップ統合テスト

```bash
# 完全なPatchPilotワークフロー（Reproduction→Localization→Generation→Validation）
python full_pipeline_test.py
```

## 📋 使用方法

### 基本的なローカライゼーション実行

```bash
# 軽量モデル使用
python patchpilot/fl/localize.py \
    --file_level \
    --direct_line_level \
    --backend ollama \
    --model phi3:mini \
    --task_list_file your_tasks.txt \
    --output_folder results/ollama_test

# 高性能モデル使用
python patchpilot/fl/localize.py \
    --file_level \
    --direct_line_level \
    --backend ollama \
    --model codellama:7b-instruct \
    --task_list_file your_tasks.txt \
    --output_folder results/ollama_test
```

### 推奨パラメータ

| パラメータ | phi3:mini | codellama:7b | 説明 |
|-----------|-----------|--------------|------|
| `--temperature` | 0.1 | 0.1 | 決定性を重視 |
| `--max_tokens` | 512 | 1024 | トークン制限 |
| `--batch_size` | 1 | 1 | メモリ節約 |
| `--num_samples` | 1-2 | 1 | 生成数 |

## 🔧 トラブルシューティング

### Ollama接続エラー

```
❌ Ollama接続失敗
```

**解決方法：**
1. Ollamaサーバーが起動しているか確認
   ```bash
   ollama serve
   ```

2. モデルがダウンロード済みか確認
   ```bash
   ollama list
   ```

3. 必要に応じてモデル再ダウンロード
   ```bash
   ollama pull phi3:mini
   ollama pull codellama:7b-instruct
   ```

### メモリ不足エラー

```
OutOfMemoryError または プロセス強制終了
```

**解決方法：**
1. より軽量なモデルを使用
   ```bash
   ollama pull phi3:mini  # 2GB
   ```

2. バッチサイズを削減
   ```bash
   --batch_size 1 --num_samples 1
   ```

3. コンテキストウィンドウを縮小
   ```bash
   --context_window 10 --max_tokens 256
   ```

### レスポンス品質の問題

**phi3:miniの出力が不十分な場合：**
- `codellama:7b-instruct`に切り替え
- `--temperature` を 0.1-0.3 に調整
- `--max_tokens` を増加

## 📊 性能比較

| モデル | サイズ | 速度 | 品質 | 推奨用途 |
|--------|-------|------|------|----------|
| phi3:mini | 2GB | ⚡⚡⚡ | ⭐⭐ | 初期テスト、高速実行 |
| codellama:7b-instruct | 4GB | ⚡⚡ | ⭐⭐⭐⭐ | 本格的な検証 |

## 🎯 Phase 0の成功基準

### Localizationテスト（phase0_test.py）
- [x] Ollamaバックエンドが正常動作
- [x] 少なくとも1つのSWE-benchタスクでLocalization完了
- [x] メモリ使用量が適切（8GB以内）
- [x] 実行時間が実用的（10分以内/タスク）

### 全ステップテスト（full_pipeline_test.py）
- [ ] Reproduction→Localization→Generation→Validationが全て完了
- [ ] 少なくとも1つのタスクでパッチ生成まで成功
- [ ] 修正成功率が測定可能
- [ ] 全体実行時間が1時間以内

## 📈 次のステップ

Phase 0が成功したら：

1. **より多くのテストケース**で検証
2. **Phase 1: Repograph統合**の実装開始
3. **異なるプロンプト戦略**の実験

---

## 📁 作成されたファイル

- `patchpilot/util/model.py` - OllamaChatDecoder追加
- `setup_ollama.sh` - Ollama環境構築スクリプト
- `test_ollama_integration.py` - 基本統合テスト
- `phase0_test.py` - 実際のSWE-benchテスト

## 🔍 デバッグ用コマンド

```bash
# Ollamaステータス確認
ollama list
curl http://localhost:11434/api/tags

# PatchPilotログ確認
ls results/phase0_ollama_test/localization_logs/

# 結果ファイル確認
cat results/phase0_ollama_test/loc_all_merged_outputs.jsonl
```