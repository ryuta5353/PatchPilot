#!/bin/bash

echo "🚀 Ollama環境セットアップ開始"

# Ollamaがインストールされているかチェック
if ! command -v ollama &> /dev/null; then
    echo "📥 Ollamaをインストール中..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "✅ Ollama既にインストール済み"
fi

# Ollamaサーバー起動
echo "🖥️  Ollamaサーバー起動中..."
ollama serve &
OLLAMA_PID=$!
echo "Ollama PID: $OLLAMA_PID"

# 起動待機
echo "⏳ Ollamaサーバー起動待機..."
sleep 10

# 軽量モデル（phi3:mini）をダウンロード（約2GB）
echo "📦 phi3:miniモデル（軽量版）をダウンロード中..."
ollama pull phi3:mini

# より強力なモデル（codellama:7b-instruct）をダウンロード（オプション、約4GB）
echo "📦 codellama:7b-instructモデル（推奨版）をダウンロード中..."
echo "これは時間がかかる場合があります..."
ollama pull codellama:7b-instruct

# 利用可能なモデル一覧表示
echo "📋 インストール済みモデル一覧："
ollama list

echo "✅ Ollamaセットアップ完了！"
echo ""
echo "🔧 使用方法："
echo "  軽量版: python patchpilot/fl/localize.py --model_backend ollama --model phi3:mini"
echo "  高性能版: python patchpilot/fl/localize.py --model_backend ollama --model codellama:7b-instruct"
echo ""
echo "🛑 停止方法: kill $OLLAMA_PID"