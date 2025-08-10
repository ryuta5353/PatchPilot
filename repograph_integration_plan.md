# Repograph-PatchPilot統合計画書

## 1. エグゼクティブサマリー

本計画書は、RepographをPatchPilotのlocalizationステップに統合し、障害位置特定の精度を向上させるための実装計画を示します。

### 目標
- **主要目標**: コードグラフベースの依存関係解析により、より正確な障害位置特定を実現
- **期待効果**: 障害位置特定の精度向上、関連コードの見逃し削減、修正成功率の向上

## 2. 技術的アーキテクチャ

### 2.1 現在のPatchPilotアーキテクチャ
```
問題文 → Localization(FL) → Repair → Validation → Refinement
           ↑ ここにRepographを統合
```

### 2.2 統合後のアーキテクチャ
```
問題文 → [コードグラフ構築] → Localization(FL+Graph) → Repair → Validation
              ↑                        ↑
          Repograph              依存関係を考慮
```

## 3. 実装計画

### Phase 1: 基盤整備（1週目）

#### タスク1.1: 依存関係の追加
```bash
# requirements.txtに追加
networkx>=3.0
tree-sitter-languages>=1.8.0
pygments>=2.15.0
```

#### タスク1.2: Repographモジュールの移植
- `patchpilot/graph/`ディレクトリを作成
- 以下のファイルを移植・適応:
  - `construct_graph.py` → `patchpilot/graph/graph_builder.py`
  - `graph_searcher.py` → `patchpilot/graph/graph_searcher.py`
  - `utils.py` → `patchpilot/graph/graph_utils.py`

### Phase 2: Localizationモジュールの拡張（2週目）

#### タスク2.1: FL.pyの拡張
```python
# patchpilot/fl/FL.py に追加
class LLMFLWithGraph(LLMFL):
    def __init__(self, *args, use_graph=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_graph = use_graph
        self.code_graph = None
        self.graph_tags = None
    
    def build_graph(self, repo_path):
        """リポジトリのコードグラフを構築"""
        from patchpilot.graph.graph_builder import CodeGraph
        cg = CodeGraph(root=repo_path)
        files = cg.find_files([repo_path])
        self.graph_tags, self.code_graph = cg.get_code_graph(files)
    
    def get_graph_context(self, suspicious_locs):
        """疑わしい位置の依存関係コンテキストを取得"""
        from patchpilot.graph.graph_searcher import RepoSearcher
        searcher = RepoSearcher(self.code_graph)
        context = []
        for loc in suspicious_locs:
            # 1-hop, 2-hop neighborsを取得
            neighbors = searcher.two_hop_neighbors(loc['function'])
            context.append({
                'location': loc,
                'dependencies': neighbors
            })
        return context
```

#### タスク2.2: localize.pyの修正
```python
# patchpilot/fl/localize.py に追加
def localize_instance_with_graph(bug, args, ...):
    # 既存のlocalize処理
    fl_model = LLMFLWithGraph(use_graph=args.repo_graph)
    
    if args.repo_graph:
        # グラフ構築（キャッシュ機能付き）
        graph_cache_path = f"repo_structures/{instance_id}.pkl"
        if os.path.exists(graph_cache_path):
            fl_model.load_graph(graph_cache_path)
        else:
            fl_model.build_graph(repo_path)
            fl_model.save_graph(graph_cache_path)
        
        # グラフコンテキストを追加
        graph_context = fl_model.get_graph_context(suspicious_locs)
        prompt += format_graph_context(graph_context)
```

### Phase 3: CLIインターフェースの拡張（3週目）

#### タスク3.1: コマンドライン引数の追加
```python
# patchpilot/fl/localize.py
parser.add_argument("--repo_graph", action="store_true",
                   help="Enable code graph analysis for better localization")
parser.add_argument("--graph_cache_dir", default="repo_structures",
                   help="Directory to cache code graphs")
parser.add_argument("--graph_depth", type=int, default=2,
                   help="Depth of graph traversal (1-3)")
```

#### タスク3.2: 実行スクリプトの作成
```bash
#!/bin/bash
# run_patchpilot_with_graph.sh

# Step 1: Localization with graph
python patchpilot/fl/localize.py \
    --file_level \
    --direct_line_level \
    --repo_graph \  # 新規追加
    --graph_depth 2 \  # 新規追加
    --output_folder results/localization_graph \
    --top_n 5 \
    --context_window 20 \
    --num_samples 4 \
    --benchmark verified

# Step 2: Repair (既存のまま)
python patchpilot/repair/repair.py \
    --loc_file results/localization_graph/loc_outputs.jsonl \
    --output_folder results/repair_graph \
    --refine_mod \
    --benchmark verified
```

### Phase 4: テストと評価（4週目）

#### タスク4.1: ユニットテスト作成
```python
# tests/test_graph_integration.py
import unittest
from patchpilot.graph.graph_builder import CodeGraph
from patchpilot.fl.FL import LLMFLWithGraph

class TestGraphIntegration(unittest.TestCase):
    def test_graph_construction(self):
        # グラフ構築のテスト
        pass
    
    def test_dependency_extraction(self):
        # 依存関係抽出のテスト
        pass
    
    def test_context_generation(self):
        # コンテキスト生成のテスト
        pass
```

#### タスク4.2: ベンチマーク評価
- SWE-bench-liteでの評価
- メトリクス:
  - 障害位置特定の精度（Top-1, Top-3, Top-5）
  - パッチ生成の成功率
  - 実行時間とメモリ使用量

## 4. 実装の優先順位

### 高優先度
1. グラフ構築機能の基本実装
2. Localizationへの統合
3. キャッシュ機能（大規模リポジトリ対応）

### 中優先度
1. グラフ探索の最適化
2. プロンプトテンプレートの改良
3. 並列処理の実装

### 低優先度
1. 可視化機能
2. 詳細なログ出力
3. GUI/Web インターフェース

## 5. リスクと対策

| リスク | 影響度 | 対策 |
|--------|--------|------|
| グラフ構築の計算コスト | 高 | キャッシュ機能の実装、事前計算 |
| 大規模リポジトリでのメモリ使用 | 中 | グラフの段階的構築、不要ノードの削除 |
| 既存機能への影響 | 低 | フラグによる機能の有効/無効切り替え |

## 6. 成功指標

- **技術指標**
  - 障害位置特定の精度が10%以上向上
  - False Positive率が20%以上削減
  
- **パフォーマンス指標**
  - グラフ構築時間: 中規模リポジトリで60秒以内
  - メモリ使用量: 2GB以内

## 7. タイムライン

```
Week 1: 基盤整備、依存関係の追加
Week 2: Localizationモジュールの拡張
Week 3: CLIインターフェース、実行スクリプト
Week 4: テスト、評価、ドキュメント作成
```

## 8. 次のステップ

1. 本計画書の承認
2. 開発環境のセットアップ
3. Phase 1の実装開始
4. 週次進捗レビュー

## 付録A: サンプルコード

### グラフ構築の例
```python
from patchpilot.graph.graph_builder import CodeGraph

# グラフ構築
cg = CodeGraph(root="/path/to/repo")
files = cg.find_files(["/path/to/repo"])
tags, graph = cg.get_code_graph(files)

# 依存関係の取得
from patchpilot.graph.graph_searcher import RepoSearcher
searcher = RepoSearcher(graph)
deps = searcher.two_hop_neighbors("target_function")
```

## 付録B: 設定ファイル例

```yaml
# config/graph_config.yaml
graph:
  enabled: true
  cache_dir: "repo_structures"
  max_depth: 2
  include_tests: false
  exclude_patterns:
    - "*.test.py"
    - "*_test.py"
    - "tests/*"
```