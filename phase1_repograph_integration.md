# Phase 1: Repograph単独統合計画書
## PatchPilotへの構造的コードグラフ統合

---

## 1. プロジェクト概要

### 1.1 目的
PatchPilotのLocalizationフェーズに、Repographの**コード構造グラフ**機能を統合し、関数・クラス間の依存関係を活用した障害位置特定精度の向上を図る。

### 1.2 スコープ
- **対象**: Repographのみ（KGCompassは含まない）
- **統合先**: PatchPilotのLocalizationモジュール
- **期間**: 3-4週間
- **検証**: 無料LLM（Ollama）を使用

---

## 2. Repograph統合アーキテクチャ

### 2.1 統合後の処理フロー

```
問題文入力
    ↓
[既存] PatchPilot FL初期処理
    ↓
[新規] Repographグラフ構築/キャッシュ読込
    ↓
[新規] 疑わしい関数の依存関係探索
    ↓
[改良] 依存関係を考慮したコンテキスト生成
    ↓
[既存] LLMへのプロンプト送信（Ollama使用）
    ↓
障害位置特定結果
```

### 2.2 ディレクトリ構造

```
patchpilot/
├── fl/
│   ├── localize.py           # [修正] Repographオプション追加
│   ├── FL.py                 # [修正] グラフコンテキスト統合
│   └── repograph_fl.py       # [新規] Repograph統合ロジック
├── repograph/                # [新規] Repographモジュール
│   ├── __init__.py
│   ├── graph_builder.py      # construct_graph.pyから移植
│   ├── graph_searcher.py     # graph_searcher.pyから移植
│   └── utils.py              # 必要なユーティリティ
└── cache/
    └── repograph/            # グラフキャッシュ保存先
```

---

## 3. 実装計画

### 3.1 Week 1: 基盤構築

#### タスク1: 環境準備と依存関係

```bash
# requirements_repograph.txt
networkx>=3.0
tree-sitter-languages>=1.8.0
pygments>=2.15.0
grep-ast>=0.3.0
```

```bash
# インストールコマンド
pip install -r requirements_repograph.txt
```

#### タスク2: Repographモジュール移植

```python
# patchpilot/repograph/graph_builder.py
from pathlib import Path
import networkx as nx
from tree_sitter_languages import get_language, get_parser
import pickle
import json

class CodeGraph:
    def __init__(self, root_path, cache_dir="cache/repograph"):
        self.root = Path(root_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.graph = nx.MultiDiGraph()
        
    def build_or_load_graph(self, instance_id):
        """グラフ構築またはキャッシュから読み込み"""
        cache_file = self.cache_dir / f"{instance_id}.pkl"
        
        if cache_file.exists():
            print(f"Loading cached graph for {instance_id}")
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        
        print(f"Building new graph for {instance_id}")
        graph = self._build_graph()
        
        # キャッシュ保存
        with open(cache_file, 'wb') as f:
            pickle.dump(graph, f)
        
        return graph
    
    def _build_graph(self):
        """実際のグラフ構築処理"""
        # Repograph/repograph/construct_graph.pyから移植
        pass
```

### 3.2 Week 2: PatchPilot統合

#### タスク3: FL.pyの拡張

```python
# patchpilot/fl/repograph_fl.py
from patchpilot.repograph.graph_builder import CodeGraph
from patchpilot.repograph.graph_searcher import RepoSearcher

class RepographEnhancedFL:
    def __init__(self, repo_path, use_cache=True):
        self.repo_path = repo_path
        self.code_graph = CodeGraph(repo_path)
        self.use_cache = use_cache
        
    def enhance_context_with_dependencies(self, suspicious_functions, instance_id):
        """依存関係を使ってコンテキストを拡張"""
        # グラフ構築/読み込み
        graph_data = self.code_graph.build_or_load_graph(instance_id)
        graph = graph_data['graph']
        tags = graph_data['tags']
        
        # 依存関係探索
        searcher = RepoSearcher(graph)
        enhanced_context = []
        
        for func_name in suspicious_functions:
            # 1-hop, 2-hop neighborsを取得
            neighbors_1 = searcher.one_hop_neighbors(func_name)
            neighbors_2 = searcher.two_hop_neighbors(func_name)
            
            context_info = {
                'function': func_name,
                'direct_dependencies': neighbors_1,
                'indirect_dependencies': neighbors_2,
                'call_chain': self._get_call_chain(graph, func_name)
            }
            enhanced_context.append(context_info)
        
        return enhanced_context
    
    def _get_call_chain(self, graph, func_name, max_depth=3):
        """関数の呼び出しチェーンを取得"""
        # 実装
        pass
```

#### タスク4: localize.pyへの統合

```python
# patchpilot/fl/localize.py の修正
import argparse
from patchpilot.fl.repograph_fl import RepographEnhancedFL

def main():
    parser = argparse.ArgumentParser()
    # 既存の引数...
    
    # Repograph関連の引数を追加
    parser.add_argument("--use_repograph", action="store_true",
                       help="Enable Repograph code structure analysis")
    parser.add_argument("--graph_depth", type=int, default=2,
                       help="Depth of dependency graph exploration")
    parser.add_argument("--graph_cache_dir", default="cache/repograph",
                       help="Directory for caching code graphs")
    
    args = parser.parse_args()
    
    # 既存の処理...
    
    if args.use_repograph:
        # Repographによる拡張
        repograph_fl = RepographEnhancedFL(repo_path)
        dependency_context = repograph_fl.enhance_context_with_dependencies(
            suspicious_functions, instance_id
        )
        
        # プロンプトにコンテキストを追加
        prompt = add_dependency_context_to_prompt(prompt, dependency_context)
```

### 3.3 Week 3: 無料LLM統合と検証

#### タスク5: Ollama設定

```bash
# setup_ollama.sh
#!/bin/bash

# Ollamaインストール確認
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# CodeLlamaモデルダウンロード
ollama pull codellama:7b-instruct

# サーバー起動
ollama serve &

echo "Ollama setup complete!"
```

#### タスク6: 無料モデルアダプター実装

```python
# patchpilot/util/free_model.py
import requests
import json

class OllamaModel:
    def __init__(self, model_name="codellama:7b-instruct"):
        self.model = model_name
        self.base_url = "http://localhost:11434"
        
    def generate(self, prompt, max_tokens=2048):
        """Ollamaを使用した生成"""
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": max_tokens
                }
            }
        )
        
        if response.status_code == 200:
            return response.json()["response"]
        else:
            raise Exception(f"Ollama error: {response.status_code}")
    
    def test_connection(self):
        """接続テスト"""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except:
            return False
```

---

## 4. 検証計画

### 4.1 テストデータセット

```python
# test_instances.txt
# SWE-bench-liteから5件を選択
django__django-11001
django__django-11019  
django__django-11039
django__django-11049
django__django-11099
```

### 4.2 評価スクリプト

```bash
#!/bin/bash
# run_repograph_evaluation.sh

# ベースライン（Repographなし）
python patchpilot/fl/localize.py \
    --file_level \
    --direct_line_level \
    --output_folder results/baseline \
    --task_list_file test_instances.txt \
    --free_model ollama

# Repograph統合版
python patchpilot/fl/localize.py \
    --file_level \
    --direct_line_level \
    --use_repograph \
    --graph_depth 2 \
    --output_folder results/with_repograph \
    --task_list_file test_instances.txt \
    --free_model ollama

# 結果比較
python evaluate_results.py \
    --baseline results/baseline \
    --enhanced results/with_repograph
```

### 4.3 評価メトリクス

```python
# evaluate_results.py
def evaluate_localization(predictions, ground_truth):
    metrics = {
        'top1_accuracy': 0,
        'top3_accuracy': 0,
        'top5_accuracy': 0,
        'mean_reciprocal_rank': 0
    }
    
    for pred, truth in zip(predictions, ground_truth):
        # Top-k accuracy計算
        if truth in pred[:1]:
            metrics['top1_accuracy'] += 1
        if truth in pred[:3]:
            metrics['top3_accuracy'] += 1
        if truth in pred[:5]:
            metrics['top5_accuracy'] += 1
            
        # MRR計算
        if truth in pred:
            rank = pred.index(truth) + 1
            metrics['mean_reciprocal_rank'] += 1/rank
    
    # 平均化
    n = len(predictions)
    for key in metrics:
        metrics[key] /= n
        
    return metrics
```

---

## 5. 成功基準

### 5.1 技術的成功基準
- ✅ Repographグラフ構築が30秒以内で完了
- ✅ キャッシュによる2回目以降の読み込みが1秒以内
- ✅ Ollamaでの推論が動作
- ✅ メモリ使用量が8GB以内

### 5.2 性能的成功基準
- 📊 Top-5精度が**ベースライン比+10%以上**向上
- 📊 少なくとも3/5のテストケースで改善
- 📊 False Positiveが増加しない

---

## 6. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| グラフが大きすぎる | メモリ不足 | 深さ制限、ファイル数制限 |
| Ollamaが遅い | 検証に時間がかかる | より小さいモデル（phi3）使用 |
| 依存関係が複雑 | 精度低下 | 重要度でフィルタリング |

---

## 7. 次のステップ（Phase 2準備）

Phase 1（Repograph統合）が成功した後：

1. **結果の文書化**
   - 精度向上の数値
   - 成功/失敗ケースの分析
   - 学んだ教訓

2. **クリーンな状態の準備**
   - Repograph統合をブランチに保存
   - mainブランチをクリーンな状態に戻す

3. **Phase 2（KGCompass統合）開始**
   - 別ブランチで独立して実装
   - Phase 1の知見を活用

---

## 8. 実装チェックリスト

- [ ] Week 1
  - [ ] 依存関係インストール
  - [ ] Repographモジュール移植
  - [ ] グラフ構築動作確認
  - [ ] キャッシュ機能実装

- [ ] Week 2  
  - [ ] FL.py拡張
  - [ ] localize.py統合
  - [ ] プロンプト生成改良
  - [ ] 統合テスト

- [ ] Week 3
  - [ ] Ollama設定
  - [ ] 評価実行
  - [ ] 結果分析
  - [ ] レポート作成