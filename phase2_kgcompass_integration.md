# Phase 2: KGCompass単独統合計画書
## PatchPilotへの開発文脈知識グラフ統合

---

## 1. プロジェクト概要

### 1.1 前提条件
- **Phase 1完了**: Repograph統合の結果・知見が利用可能
- **開始状態**: クリーンなPatchPilot（Repograph統合前の状態）
- **目的**: KGCompassの**開発文脈知識グラフ**を独立して統合

### 1.2 スコープ
- **対象**: KGCompassのみ（Repographは含まない）
- **統合先**: PatchPilotのLocalizationモジュール
- **期間**: 4-5週間（Neo4j設定含む）
- **検証**: 無料LLM（Ollama）+ 無料Embedding

---

## 2. KGCompass統合アーキテクチャ

### 2.1 統合後の処理フロー

```
問題文入力
    ↓
[既存] PatchPilot FL初期処理
    ↓
[新規] Neo4j知識グラフ構築/接続
    ↓
[新規] Issue/PR/コミット履歴解析
    ↓
[新規] グラフ探索による関連ファイルランキング
    ↓
[改良] 開発文脈を考慮したコンテキスト生成
    ↓
[既存] LLMへのプロンプト送信（Ollama使用）
    ↓
障害位置特定結果
```

### 2.2 ディレクトリ構造

```
patchpilot/
├── fl/
│   ├── localize.py           # [修正] KGCompassオプション追加
│   ├── FL.py                 # [修正] 知識グラフコンテキスト統合
│   └── kgcompass_fl.py       # [新規] KGCompass統合ロジック
├── kgcompass/                # [新規] KGCompass移植モジュール
│   ├── __init__.py
│   ├── knowledge_graph.py    # Neo4j操作
│   ├── embedding.py          # 無料Embeddingモデル
│   ├── fl_context.py         # FL機能のサブセット
│   ├── utils.py              # 必要なユーティリティ
│   └── github_analyzer.py    # GitHub API操作
├── docker/
│   └── neo4j/               # Neo4j Docker設定
│       ├── docker-compose.yml
│       └── init-scripts/
└── cache/
    └── kgcompass/           # グラフデータキャッシュ
```

---

## 3. 実装計画

### 3.1 Week 1: インフラ構築

#### タスク1: Neo4j環境構築

```yaml
# docker/neo4j/docker-compose.yml
version: '3.8'
services:
  neo4j:
    image: neo4j:5.11.0
    container_name: patchpilot-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/patchpilot123
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    restart: unless-stopped

volumes:
  neo4j_data:
  neo4j_logs:
```

```bash
# setup_neo4j.sh
#!/bin/bash

echo "Setting up Neo4j for KGCompass..."

# Docker Composeでサービス起動
cd docker/neo4j
docker-compose up -d

# Neo4jが起動するまで待機
echo "Waiting for Neo4j to start..."
sleep 30

# 接続テスト
python -c "
from neo4j import GraphDatabase
try:
    driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'patchpilot123'))
    with driver.session() as session:
        result = session.run('RETURN 1 as test')
        print('✅ Neo4j connection successful')
    driver.close()
except Exception as e:
    print(f'❌ Neo4j connection failed: {e}')
"
```

#### タスク2: 依存関係とEmbedding設定

```bash
# requirements_kgcompass.txt
neo4j>=5.11.0
sentence-transformers>=2.2.0
torch>=2.0.0
transformers>=4.30.0
github3.py>=4.0.0
beautifulsoup4>=4.12.0
requests>=2.31.0
html2text>=2020.1.16
```

```python
# patchpilot/kgcompass/embedding.py - 無料版
from sentence_transformers import SentenceTransformer
import torch
import numpy as np
from typing import List, Union

class FreeEmbedding:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        無料で使用できるEmbeddingモデル
        - all-MiniLM-L6-v2: 軽量・高速（90MB）
        - all-mpnet-base-v2: 高精度（440MB）
        """
        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        
        # GPU使用可能な場合は自動選択
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = self.model.to(device)
        print(f"Using device: {device}")
        
    def get_embedding(self, text: str) -> List[float]:
        """単一テキストのEmbedding生成"""
        if not text or len(text.strip()) == 0:
            # 空文字列の場合はゼロベクトル
            return [0.0] * self.model.get_sentence_embedding_dimension()
            
        # テキストを適切な長さに制限（通常512トークンまで）
        text = text[:4000]  # 安全のため4000文字で制限
        
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def get_batch_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """バッチでのEmbedding生成（効率的）"""
        if not texts:
            return []
            
        # 空文字列をフィルタリング
        processed_texts = [text[:4000] if text else "" for text in texts]
        
        embeddings = self.model.encode(
            processed_texts,
            convert_to_numpy=True,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 50
        )
        
        return embeddings.tolist()
```

### 3.2 Week 2: 知識グラフ構築

#### タスク3: KGCompass核心機能の移植

```python
# patchpilot/kgcompass/knowledge_graph.py
from neo4j import GraphDatabase
import json
from .embedding import FreeEmbedding
from typing import Dict, List, Any

class KnowledgeGraph:
    def __init__(self, uri="bolt://localhost:7687", user="neo4j", password="patchpilot123"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.embedder = FreeEmbedding()
        
    def initialize_for_instance(self, instance_id: str):
        """インスタンス専用のグラフ領域を初期化"""
        self.instance_id = instance_id
        self.clear_instance_data(instance_id)
        self._create_indexes()
        
    def build_knowledge_graph(self, issue_data: Dict, repo_path: str):
        """メイン知識グラフ構築処理"""
        print(f"Building knowledge graph for instance: {self.instance_id}")
        
        # 1. ルートIssueノード作成
        self._create_root_issue(issue_data)
        
        # 2. GitHub Issue/PR情報を取得・追加（簡略版）
        self._add_related_issues_simple(issue_data, repo_path)
        
        # 3. コード構造の基本情報を追加
        self._add_basic_code_structure(repo_path)
        
        print("Knowledge graph construction completed")
        
    def _create_root_issue(self, issue_data: Dict):
        """ルートIssueノードの作成"""
        with self.driver.session() as session:
            # Embeddingを生成
            content = issue_data.get('problem_statement', '')
            embedding = self.embedder.get_embedding(content)
            
            session.execute_write(
                self._create_root_issue_tx,
                self.instance_id,
                issue_data.get('instance_id', ''),
                content,
                embedding
            )
    
    @staticmethod
    def _create_root_issue_tx(tx, instance_id, title, content, embedding):
        query = """
        CREATE (root:Issue:Root {
            instance_id: $instance_id,
            id: 'root',
            title: $title,
            content: $content,
            embedding: $embedding,
            created_at: datetime()
        })
        """
        tx.run(query, 
               instance_id=instance_id,
               title=title, 
               content=content, 
               embedding=embedding)
    
    def rank_files_by_context(self, max_results: int = 20) -> List[Dict]:
        """開発文脈に基づくファイルランキング"""
        with self.driver.session() as session:
            results = session.execute_read(
                self._rank_files_query,
                self.instance_id,
                max_results
            )
            return results
    
    @staticmethod
    def _rank_files_query(tx, instance_id, max_results):
        # 簡略化されたランキングクエリ
        query = """
        MATCH (root:Root {instance_id: $instance_id})
        MATCH (f:File)
        OPTIONAL MATCH path = shortestPath((root)-[*1..3]-(f))
        WHERE path IS NOT NULL
        WITH f, length(path) as distance,
             gds.similarity.cosine(root.embedding, f.embedding) as similarity
        RETURN f.path as file_path,
               similarity * (0.85 ^ distance) as score
        ORDER BY score DESC
        LIMIT $max_results
        """
        result = tx.run(query, instance_id=instance_id, max_results=max_results)
        return [{"file_path": record["file_path"], "score": record["score"]} 
                for record in result]
```

#### タスク4: GitHub情報解析（簡略版）

```python
# patchpilot/kgcompass/github_analyzer.py
import os
import re
from typing import List, Dict, Optional
from github import Github

class SimpleGitHubAnalyzer:
    """GitHub情報の簡略解析（API制限を考慮）"""
    
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.getenv('GITHUB_TOKEN')
        self.github = Github(self.github_token) if self.github_token else None
        
    def extract_references_from_text(self, text: str, repo_path: str) -> List[Dict]:
        """テキストからコード参照を抽出（静的解析）"""
        references = []
        
        # パターン1: ファイルパス（例：src/main.py）
        file_patterns = re.findall(r'\b[\w/]+\.py\b', text)
        for pattern in file_patterns:
            full_path = os.path.join(repo_path, pattern)
            if os.path.exists(full_path):
                references.append({
                    'type': 'file',
                    'path': pattern,
                    'confidence': 0.8
                })
        
        # パターン2: 関数名（例：def calculate_something）
        func_patterns = re.findall(r'\b[a-zA-Z_]\w*\([^)]*\)', text)
        for pattern in func_patterns:
            func_name = pattern.split('(')[0]
            references.append({
                'type': 'function',
                'name': func_name,
                'confidence': 0.6
            })
        
        return references
    
    def get_minimal_issue_context(self, repo_name: str, issue_title: str) -> Dict:
        """最小限のIssue文脈情報を取得"""
        if not self.github:
            return {'related_issues': [], 'commits': []}
            
        try:
            repo = self.github.get_repo(repo_name)
            
            # タイトルの類似性で関連Issueを検索（最大5件）
            similar_issues = []
            for issue in repo.get_issues(state='all')[:20]:  # API制限を考慮
                if self._calculate_title_similarity(issue_title, issue.title) > 0.3:
                    similar_issues.append({
                        'number': issue.number,
                        'title': issue.title,
                        'state': issue.state
                    })
                if len(similar_issues) >= 5:
                    break
                    
            return {
                'related_issues': similar_issues,
                'commits': []  # 簡略版ではコミット解析をスキップ
            }
            
        except Exception as e:
            print(f"GitHub API error: {e}")
            return {'related_issues': [], 'commits': []}
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """簡単なタイトル類似度計算"""
        words1 = set(title1.lower().split())
        words2 = set(title2.lower().split())
        
        if not words1 or not words2:
            return 0.0
            
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)
```

### 3.3 Week 3: PatchPilot統合

#### タスク5: FL統合ロジック

```python
# patchpilot/fl/kgcompass_fl.py
from patchpilot.kgcompass.knowledge_graph import KnowledgeGraph
from patchpilot.kgcompass.github_analyzer import SimpleGitHubAnalyzer
import os

class KGCompassEnhancedFL:
    def __init__(self, repo_path: str, github_token: str = None):
        self.repo_path = repo_path
        self.kg = KnowledgeGraph()
        self.github_analyzer = SimpleGitHubAnalyzer(github_token)
        
    def enhance_context_with_knowledge_graph(self, issue_data: Dict, instance_id: str) -> Dict:
        """知識グラフを使ってコンテキストを拡張"""
        
        # 1. 知識グラフ初期化・構築
        self.kg.initialize_for_instance(instance_id)
        self.kg.build_knowledge_graph(issue_data, self.repo_path)
        
        # 2. ファイルランキング取得
        ranked_files = self.kg.rank_files_by_context(max_results=20)
        
        # 3. コンテキスト情報の構築
        context_info = {
            'knowledge_graph_files': ranked_files,
            'github_context': self._get_github_context(issue_data),
            'code_references': self._extract_code_references(issue_data)
        }
        
        return context_info
    
    def _get_github_context(self, issue_data: Dict) -> Dict:
        """GitHub情報の取得"""
        repo_name = self._extract_repo_name(issue_data)
        issue_title = issue_data.get('problem_statement', '')
        
        return self.github_analyzer.get_minimal_issue_context(repo_name, issue_title)
    
    def _extract_code_references(self, issue_data: Dict) -> List[Dict]:
        """問題文からコード参照を抽出"""
        problem_statement = issue_data.get('problem_statement', '')
        return self.github_analyzer.extract_references_from_text(
            problem_statement, self.repo_path
        )
    
    def _extract_repo_name(self, issue_data: Dict) -> str:
        """インスタンスIDからリポジトリ名を抽出"""
        instance_id = issue_data.get('instance_id', '')
        # 例：django__django-11001 -> django/django
        if '__' in instance_id:
            org, repo_and_num = instance_id.split('__', 1)
            repo = repo_and_num.split('-')[0]
            return f"{org}/{repo}"
        return ""
```

#### タスク6: localize.py統合

```python
# patchpilot/fl/localize.py への追加
def main():
    parser = argparse.ArgumentParser()
    # 既存の引数...
    
    # KGCompass関連の引数
    parser.add_argument("--use_kgcompass", action="store_true",
                       help="Enable KGCompass knowledge graph analysis")
    parser.add_argument("--neo4j_uri", default="bolt://localhost:7687",
                       help="Neo4j database URI")
    parser.add_argument("--github_token", 
                       help="GitHub token for accessing repository metadata")
    parser.add_argument("--kg_max_files", type=int, default=15,
                       help="Maximum number of files from knowledge graph")
    
    args = parser.parse_args()
    
    # 既存の処理...
    
    if args.use_kgcompass:
        print("🔍 Enhancing with KGCompass knowledge graph...")
        
        # KGCompass統合
        kgcompass_fl = KGCompassEnhancedFL(
            repo_path=repo_path,
            github_token=args.github_token
        )
        
        kg_context = kgcompass_fl.enhance_context_with_knowledge_graph(
            issue_data, instance_id
        )
        
        # 知識グラフの結果をプロンプトに統合
        prompt = add_knowledge_graph_context_to_prompt(prompt, kg_context)
        
        print(f"📊 Knowledge graph provided {len(kg_context['knowledge_graph_files'])} ranked files")
```

### 3.4 Week 4: 検証とテスト

#### タスク7: 統合テストスクリプト

```bash
#!/bin/bash
# test_kgcompass_integration.sh

echo "=== KGCompass統合テスト ==="

# 1. Neo4j起動確認
if ! docker ps | grep -q patchpilot-neo4j; then
    echo "🚀 Starting Neo4j..."
    cd docker/neo4j && docker-compose up -d
    sleep 30
fi

# 2. 接続テスト
python -c "
from patchpilot.kgcompass.knowledge_graph import KnowledgeGraph
try:
    kg = KnowledgeGraph()
    print('✅ Neo4j connection successful')
except Exception as e:
    print(f'❌ Connection failed: {e}')
    exit(1)
"

# 3. Embeddingモデルテスト
python -c "
from patchpilot.kgcompass.embedding import FreeEmbedding
emb = FreeEmbedding()
result = emb.get_embedding('test text')
print(f'✅ Embedding model working, dimension: {len(result)}')
"

# 4. 小規模テスト実行
echo "django__django-11001" > mini_test_kg.txt

python patchpilot/fl/localize.py \
    --use_kgcompass \
    --neo4j_uri bolt://localhost:7687 \
    --task_list_file mini_test_kg.txt \
    --output_folder results/kgcompass_test \
    --free_model ollama

echo "=== テスト完了 ==="
```

### 3.5 Week 5: 評価と比較

#### タスク8: Phase 1との比較

```python
# compare_phases.py
import json
from pathlib import Path

def compare_repograph_vs_kgcompass():
    """Phase 1 (Repograph) vs Phase 2 (KGCompass) の比較"""
    
    # 結果ファイル読み込み
    repograph_results = load_results("results/phase1_repograph/")
    kgcompass_results = load_results("results/phase2_kgcompass/")
    baseline_results = load_results("results/baseline/")
    
    comparison = {
        'baseline': evaluate_metrics(baseline_results),
        'repograph': evaluate_metrics(repograph_results),
        'kgcompass': evaluate_metrics(kgcompass_results)
    }
    
    # 改善度計算
    for approach in ['repograph', 'kgcompass']:
        comparison[approach]['improvement'] = {
            metric: comparison[approach][metric] - comparison['baseline'][metric]
            for metric in ['top1_acc', 'top5_acc', 'mrr']
        }
    
    # 強み・弱みの分析
    comparison['analysis'] = analyze_strengths_weaknesses(
        repograph_results, kgcompass_results
    )
    
    # 結果保存
    with open('phase_comparison_report.json', 'w') as f:
        json.dump(comparison, f, indent=2)
    
    return comparison

def analyze_strengths_weaknesses(repograph_results, kgcompass_results):
    """各手法の強み・弱みを分析"""
    analysis = {
        'repograph_better': [],  # Repographが優れているケース
        'kgcompass_better': [],  # KGCompassが優れているケース
        'both_good': [],         # 両方とも良いケース
        'both_poor': []          # 両方とも悪いケース
    }
    
    # 個別ケース分析
    for instance_id in repograph_results:
        r_score = repograph_results[instance_id]['top5_acc']
        k_score = kgcompass_results[instance_id]['top5_acc']
        
        if r_score > k_score + 0.1:
            analysis['repograph_better'].append(instance_id)
        elif k_score > r_score + 0.1:
            analysis['kgcompass_better'].append(instance_id)
        elif r_score > 0.5 and k_score > 0.5:
            analysis['both_good'].append(instance_id)
        else:
            analysis['both_poor'].append(instance_id)
    
    return analysis
```

---

## 4. 成功基準

### 4.1 技術的成功基準
- ✅ Neo4j知識グラフ構築が60秒以内で完了
- ✅ GitHub API制限内での情報取得
- ✅ 無料Embeddingモデルでの意味的類似度計算
- ✅ メモリ使用量が12GB以内（Neo4j含む）

### 4.2 性能的成功基準
- 📊 Top-5精度が**ベースライン比+12%以上**向上
- 📊 少なくとも3/5のテストケースで改善
- 📊 Phase 1 (Repograph)との差異を明確化

---

## 5. Phase 1からの学習活用

### 5.1 活用できる知見
- プロンプト生成の改良方法
- Ollamaモデルの最適設定
- 評価メトリクスとテストケース
- キャッシュ戦略

### 5.2 改善点
- より効率的なグラフ構築
- API制限を考慮した設計
- メモリ使用量の最適化

---

## 6. 次のステップ（研究の総括）

Phase 2完了後：

1. **比較分析レポート作成**
   - 構造的グラフ vs 開発文脈グラフ
   - それぞれの適用場面の特定

2. **論文執筆準備**
   - 両アプローチの定量的比較
   - 相補的な特性の発見

3. **ハイブリッドアプローチの検討**
   - 両手法の組み合わせ可能性
   - 最適な統合戦略