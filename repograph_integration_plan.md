# Repograph-PatchPilot統合計画書

## 1. エグゼクティブサマリー

本計画書は、RepographをPatchPilotのlocalizationステップに統合し、障害位置特定の精度を向上させるための実装計画を示します。

### 目標
- **主要目標**: コードグラフベースの依存関係解析により、より正確な障害位置特定を実現
- **期待効果**: 障害位置特定の精度向上、関連コードの見逃し削減、修正成功率の向上

### 背景と根拠
- **Repographの実績**: SWE-benchでAgentlessやSWE-agentとの統合により効果が実証済み
- **理論的基盤**: プログラムの依存関係グラフ解析は、ソフトウェア工学において確立された手法
- **実装の成熟度**: Repographは既にオープンソースとして公開され、複数のフレームワークで検証済み

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

**なぜ必要か**: 
- NetworkX: グラフデータ構造と操作のための基盤ライブラリ
- tree-sitter: 言語に依存しない高速な構文解析器
- pygments: 追加の字句解析とトークン化のサポート

**参考実装**:
- `Repograph/agentless/repair/repair.py:7-8` - pickleとNetworkXの使用例
- `Repograph/repograph/construct_graph.py:16,30` - tree-sitter-languagesの実装
- `Repograph/requirements.txt` - 同様の依存関係定義

**期待される効果**:
- 安定したグラフ構築基盤の確立
- 複数プログラミング言語への将来的な拡張性
- 高速な構文解析による処理時間の短縮

#### タスク1.2: Repographモジュールの移植
- `patchpilot/graph/`ディレクトリを作成
- 以下のファイルを移植・適応:
  - `construct_graph.py` → `patchpilot/graph/graph_builder.py`
  - `graph_searcher.py` → `patchpilot/graph/graph_searcher.py`
  - `utils.py` → `patchpilot/graph/graph_utils.py`

**なぜ必要か**:
- 既存のRepograph実装を活用し、開発時間を短縮
- PatchPilotの構造に合わせたモジュール配置で保守性向上
- 独立したグラフモジュールにより、他の機能への影響を最小化

**参考実装**:
- `Repograph/repograph/construct_graph.py:35-592` - CodeGraphクラスの完全実装
- `Repograph/repograph/graph_searcher.py:3-45` - グラフ探索アルゴリズム
- `Repograph/agentless/fl/localize.py:53-98` - Agentlessでの統合方法

**期待される効果**:
- 実証済みのコードベースによる安定性の確保
- モジュール化による再利用性の向上
- 段階的な機能拡張が容易に

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

**なぜこの編集を行うのか**:
- PatchPilotの既存アーキテクチャを研究開発目的で改良するため
- 現在のLLMFLクラスは単純なテキストマッチングに依存しており、コード間の依存関係を考慮していない
- グラフベースのアプローチにより、より構造的な解析が可能になる

**この編集が必要だと判断した理由**:
1. **既存の限界**: 現在のPatchPilotは文字列検索ベースで関連コードを探すため、重要な依存関係を見逃す可能性がある
2. **Repographの実績**: Agentlessフレームワークで既に実装・検証済みの手法を活用できる
3. **後方互換性**: use_graphフラグにより、既存機能を損なわずに新機能を追加できる

**参考実装**:
- `Repograph/agentless/fl/localize.py:210-236` - Agentlessでのグラフ統合実装
- `Repograph/agentless/fl/localize.py:53-98` - construct_code_graph_context関数
- `Repograph/agentless/fl/FL.py` - LLMベースのFault Localizationの基本構造

**期待される効果**:
- 呼び出し関係・参照関係に基づく正確な関連コード特定
- LLMに提供するコンテキストの質が大幅に向上（依存関係が明確になる）
- 見逃しがちな間接的な依存関係も検出可能（2-hop neighbors）
- 障害位置特定の精度が10-20%向上する可能性

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

**なぜこの編集を行うのか**:
- localize.pyは実際の障害位置特定処理を実行するエントリーポイント
- グラフ機能を実際のワークフローに統合する必要がある
- キャッシュ機能により、大規模リポジトリでの再計算を回避

**この編集が必要だと判断した理由**:
1. **パフォーマンスの問題**: グラフ構築は計算コストが高いため、キャッシュが必須
2. **実用性**: 研究段階では同じリポジトリで何度も実験するため、キャッシュで時間短縮
3. **段階的導入**: args.repo_graphフラグで機能のON/OFFを制御し、比較実験が容易

**参考実装**:
- `Repograph/agentless/repair/repair.py:514-520` - repo_graphフラグの使用例
- `Repograph/README.md:19` - キャッシュファイルの保存形式（.pkl）
- `Repograph/agentless/repair/repair.py:410-437` - グラフキャッシュの読み込み処理

**期待される効果**:
- 2回目以降の実行時間が90%以上短縮（キャッシュ利用時）
- グラフコンテキストによりLLMへのプロンプトが充実
- A/Bテストによる効果測定が容易に実施可能

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

**なぜこの編集を行うのか**:
- ユーザーが新機能を簡単に有効化/無効化できるようにする
- 実験パラメータを柔軟に調整可能にする
- 既存のCLIインターフェースとの一貫性を保つ

**この編集が必要だと判断した理由**:
1. **実験の柔軟性**: graph_depthの調整により、精度とパフォーマンスのトレードオフを探索可能
2. **ユーザビリティ**: 既存のPatchPilotユーザーが慣れ親しんだ形式で新機能を利用可能
3. **キャッシュ管理**: cache_dirの指定により、異なる実験設定でのキャッシュを分離

**参考実装**:
- `Repograph/agentless/fl/localize.py:353-355` - Agentlessのコマンドライン引数
- `Repograph/repograph/graph_searcher.py:19-45` - depth引数を使用したグラフ探索
- `Repograph/run_repograph_agentless.sh:1-9` - 実際の使用例

**期待される効果**:
- 研究者が様々な設定で簡単に実験を実施可能
- グラフの深さ調整により、必要な情報量とコスト（時間・メモリ）のバランスを最適化
- 既存ユーザーの学習コストを最小化

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

**なぜこの編集を行うのか**:
- 新機能を含む完全な実行パイプラインを提供
- 研究者が即座に実験を開始できるようにする
- ベストプラクティスの設定を文書化

**この編集が必要だと判断した理由**:
1. **再現性**: 実験設定を明確にし、他の研究者が結果を再現可能に
2. **利便性**: 複雑なコマンドラインオプションをスクリプト化し、ミスを防ぐ
3. **比較実験**: グラフあり/なしの実行スクリプトを分けることで、効果測定が容易

**参考実装**:
- `Repograph/run_repograph_agentless.sh` - Agentlessの実行スクリプト全体
- `Repograph/run_repograph_sweagent.sh` - SWE-agentの実行スクリプト
- `patchpilot/README.md:84-145` - PatchPilotの既存の実行コマンド

**期待される効果**:
- 新規ユーザーでも5分以内に実験を開始可能
- 設定ミスによる実験の失敗を防止
- バッチ実行やCI/CDパイプラインへの統合が容易

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

**なぜこの編集を行うのか**:
- 新機能の正確性と安定性を保証する
- リグレッションを防ぎ、継続的な改善を可能にする
- コードの品質を維持し、バグの早期発見を実現

**この編集が必要だと判断した理由**:
1. **品質保証**: 研究コードであっても、テストがなければ信頼性が低下
2. **デバッグ効率**: 問題発生時に原因箇所を素早く特定可能
3. **将来の拡張**: テストがあることで、安心して機能追加や改善が可能

**参考実装**:
- `Repograph/SWE-agent/tests/test_env.py` - 環境テストの実装例
- `Repograph/SWE-agent/tests/test_parsing.py` - パース処理のテスト
- `patchpilot/useful_scripts/test_loc.py` - Localizationのテスト参考

**期待される効果**:
- バグの早期発見により、デバッグ時間を50%削減
- コードの信頼性向上により、実験結果の信憑性が向上
- 他の研究者がコードを理解・拡張しやすくなる

#### タスク4.2: ベンチマーク評価
- SWE-bench-liteでの評価
- メトリクス:
  - 障害位置特定の精度（Top-1, Top-3, Top-5）
  - パッチ生成の成功率
  - 実行時間とメモリ使用量

**なぜこの編集を行うのか**:
- 新機能の効果を定量的に測定する
- 研究成果として論文に記載可能なデータを取得
- 既存手法との比較により、改善度を明確化

**この編集が必要だと判断した理由**:
1. **学術的価値**: 定量的評価なしには研究成果として認められない
2. **最適化の指針**: メトリクスにより、どこを改善すべきかが明確になる
3. **ベースライン確立**: 将来の改善を測定するための基準値を設定

**参考実装**:
- `Repograph/SWE-agent/evaluation/evaluation.py` - 評価フレームワーク
- `patchpilot/useful_scripts/generate_csv.py` - 結果集計スクリプト
- `patchpilot/useful_scripts/get_pass_at_each_round.py` - 成功率測定
- SWE-bench論文 - 評価メトリクスの定義

**期待される効果**:
- 障害位置特定精度の10-20%向上を数値で実証
- 論文投稿に必要な実験データの取得
- 改善すべき課題の明確化と次の研究方向の決定

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

| リスク | 影響度 | 対策 | 参考事例 |
|--------|--------|------|----------|
| グラフ構築の計算コスト | 高 | キャッシュ機能の実装、事前計算 | Repograph/README.md:19のキャッシュ戦略 |
| 大規模リポジトリでのメモリ使用 | 中 | グラフの段階的構築、不要ノードの削除 | construct_graph.py:293-328の最適化 |
| 既存機能への影響 | 低 | フラグによる機能の有効/無効切り替え | Agentlessのrepo_graphフラグ実装 |

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

**実装の参考元**:
- `Repograph/repograph/construct_graph.py:562-579` - main関数での使用例
- `Repograph/agentless/fl/localize.py:68-98` - 実際の統合例

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

**設定の参考元**:
- `Repograph/SWE-agent/config/default.yaml` - 設定構造の例
- `Repograph/repograph/construct_graph.py:547-550` - ファイルフィルタリング

## 参考文献

1. **Repograph公式リポジトリ**: https://github.com/[repograph-repo]
2. **SWE-bench論文**: "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?"
3. **Agentlessフレームワーク**: https://github.com/OpenAutoCoder/Agentless
4. **PatchPilot論文**: "PatchPilot: A Stable and Cost-Efficient Agentic Patching Framework"