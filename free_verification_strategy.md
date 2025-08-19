# 無料LLM検証戦略ガイド
## PatchPilot + Repograph/KGCompass 統合での費用効率的な検証

---

## 1. 無料リソース構成

### 1.1 完全無料構成（推奨）

| コンポーネント | 無料ソリューション | 容量/制限 | 備考 |
|--------------|------------------|-----------|------|
| **LLM推論** | Ollama (ローカル) | 無制限 | 4-8GB RAM必要 |
| **Embedding** | Sentence-Transformers | 無制限 | CPUでも動作 |
| **Neo4j** | Docker Community版 | 無制限 | ローカル実行 |
| **GitHub API** | Personal Token | 5000 req/hour | 無料アカウント |

### 1.2 バックアップ無料構成

| コンポーネント | バックアップ | 制限 | 使用ケース |
|--------------|-------------|------|-----------|
| **LLM推論** | Google Gemini 1.5 Flash | 15 RPM | Ollama障害時 |
| **Embedding** | Hugging Face Inference | 1000 req/day | 大量処理時 |

---

## 2. 実装戦略

### 2.1 段階的モデル選択

```python
# patchpilot/util/free_model_manager.py
import os
import time
from typing import Optional, Dict, Any

class FreeModelManager:
    """無料モデルの管理と自動切り替え"""
    
    def __init__(self):
        self.ollama_available = self._check_ollama()
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        self.daily_quota = {
            'gemini_requests': 0,
            'hf_requests': 0
        }
        self.last_reset = time.time()
        
    def get_best_available_model(self, task_type: str = 'generation'):
        """利用可能な最適モデルを選択"""
        self._reset_daily_quota_if_needed()
        
        if task_type == 'generation':
            return self._get_generation_model()
        elif task_type == 'embedding':
            return self._get_embedding_model()
        else:
            raise ValueError(f"Unknown task type: {task_type}")
    
    def _get_generation_model(self) -> Dict[str, Any]:
        """生成タスク用モデル選択"""
        if self.ollama_available:
            return {
                'type': 'ollama',
                'model': 'codellama:7b-instruct',
                'endpoint': 'http://localhost:11434',
                'cost': 0,
                'reliability': 'high'
            }
        elif self.gemini_api_key and self.daily_quota['gemini_requests'] < 900:
            return {
                'type': 'gemini',
                'model': 'gemini-1.5-flash',
                'cost': 0,
                'reliability': 'medium'
            }
        else:
            return {
                'type': 'mock',
                'model': 'simple_heuristic',
                'cost': 0,
                'reliability': 'low'
            }
    
    def _get_embedding_model(self) -> Dict[str, Any]:
        """Embeddingタスク用モデル選択"""
        # 常にローカルSentence-Transformersを優先
        return {
            'type': 'sentence_transformers',
            'model': 'all-MiniLM-L6-v2',
            'device': 'cuda' if self._cuda_available() else 'cpu',
            'cost': 0,
            'reliability': 'high'
        }
    
    def _check_ollama(self) -> bool:
        """Ollamaの利用可能性チェック"""
        import requests
        try:
            response = requests.get('http://localhost:11434/api/tags', timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def _cuda_available(self) -> bool:
        """CUDA利用可能性チェック"""
        try:
            import torch
            return torch.cuda.is_available()
        except:
            return False
```

### 2.2 コスト効率的な実行戦略

```python
# patchpilot/util/cost_optimizer.py
class CostOptimizer:
    """コストを最小化する実行戦略"""
    
    def __init__(self, budget: Dict[str, int] = None):
        self.budget = budget or {
            'gemini_requests': 800,  # 余裕を持って800/日
            'hf_requests': 900,      # 900/日
            'max_instances': 10      # 1日の最大検証インスタンス数
        }
        self.usage = {key: 0 for key in self.budget}
    
    def optimize_test_plan(self, test_instances: list) -> Dict:
        """テスト計画の最適化"""
        # 重要度に基づく優先順位付け
        prioritized = self._prioritize_instances(test_instances)
        
        # 予算内での最適な実行計画
        execution_plan = {
            'high_priority': prioritized[:3],   # 必須テスト
            'medium_priority': prioritized[3:7], # 推奨テスト
            'low_priority': prioritized[7:],     # オプション
            'fallback_strategy': self._get_fallback_strategy()
        }
        
        return execution_plan
    
    def _prioritize_instances(self, instances: list) -> list:
        """インスタンスの優先順位付け"""
        # SWE-bench-liteから代表的なケースを選択
        priority_order = [
            'django__django-11001',  # Django ORM関連
            'sympy__sympy-15011',     # 数式処理
            'scikit-learn__scikit-learn-13496',  # ML関連
            'requests__requests-3362', # HTTP関連
            'matplotlib__matplotlib-18869'  # 可視化関連
        ]
        
        # 優先順位順に並び替え
        prioritized = []
        for priority_instance in priority_order:
            if priority_instance in instances:
                prioritized.append(priority_instance)
        
        # 残りを追加
        for instance in instances:
            if instance not in prioritized:
                prioritized.append(instance)
        
        return prioritized
    
    def _get_fallback_strategy(self) -> Dict:
        """フォールバック戦略"""
        return {
            'ollama_down': 'Use mock generation with simple heuristics',
            'no_gpu': 'Use CPU-only models with reduced batch size',
            'api_limit': 'Cache previous results and use interpolation',
            'memory_limit': 'Process instances sequentially with cleanup'
        }
```

---

## 3. メモリ・計算最適化

### 3.1 システム要件と推奨構成

```yaml
# システム要件
minimum:
  ram: "8GB"
  disk: "50GB"
  cpu: "4 cores"
  models: ["phi3:mini", "all-MiniLM-L6-v2"]
  
recommended:
  ram: "16GB"
  disk: "100GB"
  cpu: "8 cores"
  gpu: "6GB VRAM (optional)"
  models: ["codellama:7b-instruct", "all-mpnet-base-v2"]
  
optimal:
  ram: "32GB"
  disk: "200GB"
  cpu: "16 cores"
  gpu: "12GB VRAM"
  models: ["codellama:13b-instruct", "all-mpnet-base-v2"]
```

### 3.2 メモリ効率化テクニック

```python
# patchpilot/util/memory_optimizer.py
import gc
import torch
from typing import Any

class MemoryOptimizer:
    """メモリ使用量の最適化"""
    
    @staticmethod
    def cleanup_after_instance():
        """インスタンス処理後のクリーンアップ"""
        # Pythonガベージコレクション
        gc.collect()
        
        # PyTorchキャッシュクリア
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
    @staticmethod
    def optimize_batch_size(available_memory_gb: float, model_size: str) -> int:
        """利用可能メモリに基づくバッチサイズ最適化"""
        if model_size == "7b":
            if available_memory_gb >= 16:
                return 4
            elif available_memory_gb >= 8:
                return 2
            else:
                return 1
        elif model_size == "13b":
            if available_memory_gb >= 32:
                return 2
            else:
                return 1
        else:  # mini models
            if available_memory_gb >= 8:
                return 8
            else:
                return 4
    
    @staticmethod
    def monitor_memory_usage():
        """メモリ使用量の監視"""
        import psutil
        
        memory = psutil.virtual_memory()
        return {
            'total_gb': memory.total / (1024**3),
            'available_gb': memory.available / (1024**3),
            'used_percent': memory.percent,
            'warning': memory.percent > 85
        }
```

---

## 4. 評価データセット最適化

### 4.1 スマートなテストケース選択

```python
# evaluation/smart_test_selection.py
class SmartTestSelector:
    """効率的なテストケース選択"""
    
    def __init__(self):
        # SWE-bench-liteから多様性を重視した選択
        self.core_test_set = [
            # 異なるプログラミング言語パラダイム
            'django__django-11001',      # ORM/Database
            'sympy__sympy-15011',         # 数値計算
            'matplotlib__matplotlib-18869', # 可視化
            'requests__requests-3362',    # ネットワーク
            'scikit-learn__scikit-learn-13496'  # 機械学習
        ]
        
        self.extended_test_set = [
            # 追加の多様性
            'pandas__pandas-22378',       # データ処理
            'pytest__pytest-5692',       # テストフレームワーク
            'flask__flask-4992',          # ウェブフレームワーク
            'numpy__numpy-14138',         # 数値計算基盤
            'pillow__pillow-6423'         # 画像処理
        ]
    
    def get_test_plan(self, available_time_hours: float, budget_level: str) -> Dict:
        """利用可能時間と予算に基づくテスト計画"""
        
        if budget_level == "minimal" or available_time_hours < 4:
            return {
                'instances': self.core_test_set[:3],
                'estimated_time': '2-3 hours',
                'coverage': 'basic_functionality'
            }
        elif budget_level == "standard" or available_time_hours < 8:
            return {
                'instances': self.core_test_set,
                'estimated_time': '4-6 hours',
                'coverage': 'core_scenarios'
            }
        else:
            return {
                'instances': self.core_test_set + self.extended_test_set[:3],
                'estimated_time': '8-12 hours',
                'coverage': 'comprehensive'
            }
    
    def estimate_processing_time(self, instances: list, model_type: str) -> float:
        """処理時間の推定"""
        base_time_per_instance = {
            'phi3:mini': 10,      # 10分/インスタンス
            'codellama:7b': 15,   # 15分/インスタンス
            'codellama:13b': 25,  # 25分/インスタンス
            'gemini': 5           # 5分/インスタンス（API速度）
        }
        
        time_per_instance = base_time_per_instance.get(model_type, 15)
        return len(instances) * time_per_instance / 60  # 時間単位で返す
```

### 4.2 増分評価戦略

```python
# evaluation/incremental_evaluation.py
class IncrementalEvaluator:
    """増分的な評価実行"""
    
    def __init__(self, results_dir: str = "results/incremental"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def run_incremental_test(self, test_instances: list, approaches: list):
        """段階的にテストを実行し、結果を保存"""
        
        for i, instance in enumerate(test_instances, 1):
            print(f"\n=== Processing instance {i}/{len(test_instances)}: {instance} ===")
            
            for approach in approaches:
                result_file = self.results_dir / f"{approach}_{instance}.json"
                
                if result_file.exists():
                    print(f"✅ Skipping {approach} for {instance} (already exists)")
                    continue
                
                try:
                    # 実際のテスト実行
                    result = self._run_single_test(instance, approach)
                    
                    # 結果保存
                    with open(result_file, 'w') as f:
                        json.dump(result, f, indent=2)
                    
                    print(f"✅ Completed {approach} for {instance}")
                    
                    # メモリクリーンアップ
                    MemoryOptimizer.cleanup_after_instance()
                    
                except Exception as e:
                    print(f"❌ Failed {approach} for {instance}: {e}")
                    # エラーも記録
                    error_result = {'error': str(e), 'timestamp': time.time()}
                    with open(result_file, 'w') as f:
                        json.dump(error_result, f, indent=2)
            
            # 中間結果の分析
            self._analyze_intermediate_results(i, test_instances[:i])
    
    def _analyze_intermediate_results(self, completed: int, instances: list):
        """中間結果の分析"""
        print(f"\n📊 Intermediate Analysis ({completed}/{len(instances)} completed):")
        
        # 各アプローチの成功率
        for approach in ['baseline', 'repograph', 'kgcompass']:
            success_count = len([
                f for f in self.results_dir.glob(f"{approach}_*.json")
                if not json.load(f.open()).get('error')
            ])
            print(f"  {approach}: {success_count}/{completed} successful")
```

---

## 5. 自動化スクリプト

### 5.1 完全自動実行スクリプト

```bash
#!/bin/bash
# automated_verification.sh

set -e

echo "🚀 PatchPilot自動検証開始"

# 設定
PROJECT_ROOT=$(pwd)
RESULTS_DIR="$PROJECT_ROOT/results/automated_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

# ログ設定
exec 1> >(tee -a "$RESULTS_DIR/execution.log")
exec 2> >(tee -a "$RESULTS_DIR/error.log")

echo "📝 検証ログ: $RESULTS_DIR/execution.log"

# 1. 環境チェック
echo "🔍 環境チェック..."
python scripts/check_environment.py || {
    echo "❌ 環境チェック失敗"
    exit 1
}

# 2. テストインスタンス選択
echo "📋 テストインスタンス選択..."
python scripts/select_test_instances.py \
    --budget minimal \
    --time_limit 4 \
    --output "$RESULTS_DIR/test_instances.txt"

# 3. Phase 1: Repograph統合テスト
echo "🔧 Phase 1: Repograph統合テスト..."
python patchpilot/fl/localize.py \
    --use_repograph \
    --free_model ollama \
    --task_list_file "$RESULTS_DIR/test_instances.txt" \
    --output_folder "$RESULTS_DIR/phase1_repograph" \
    --batch_size 1 \
    --max_samples 2

# 4. Phase 2: KGCompass統合テスト
echo "🧠 Phase 2: KGCompass統合テスト..."
# Neo4j起動
cd docker/neo4j && docker-compose up -d && cd "$PROJECT_ROOT"
sleep 30

python patchpilot/fl/localize.py \
    --use_kgcompass \
    --free_model ollama \
    --task_list_file "$RESULTS_DIR/test_instances.txt" \
    --output_folder "$RESULTS_DIR/phase2_kgcompass" \
    --batch_size 1 \
    --max_samples 2

# 5. ベースライン比較
echo "📊 ベースライン実行..."
python patchpilot/fl/localize.py \
    --free_model ollama \
    --task_list_file "$RESULTS_DIR/test_instances.txt" \
    --output_folder "$RESULTS_DIR/baseline" \
    --batch_size 1 \
    --max_samples 2

# 6. 結果分析
echo "📈 結果分析..."
python scripts/analyze_results.py \
    --baseline "$RESULTS_DIR/baseline" \
    --repograph "$RESULTS_DIR/phase1_repograph" \
    --kgcompass "$RESULTS_DIR/phase2_kgcompass" \
    --output "$RESULTS_DIR/final_report.json"

# 7. レポート生成
echo "📄 レポート生成..."
python scripts/generate_report.py \
    --results "$RESULTS_DIR/final_report.json" \
    --output "$RESULTS_DIR/verification_report.md"

echo "✅ 自動検証完了"
echo "📁 結果ディレクトリ: $RESULTS_DIR"
echo "📄 レポート: $RESULTS_DIR/verification_report.md"

# クリーンアップ
docker-compose -f docker/neo4j/docker-compose.yml down

echo "🎉 検証完了！"
```

### 5.2 環境チェックスクリプト

```python
# scripts/check_environment.py
import subprocess
import sys
import json
from pathlib import Path

def check_ollama():
    """Ollamaの確認"""
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
        if 'codellama:7b-instruct' in result.stdout:
            return {'status': 'ok', 'model': 'codellama:7b-instruct'}
        elif 'phi3:mini' in result.stdout:
            return {'status': 'ok', 'model': 'phi3:mini'}
        else:
            return {'status': 'no_model', 'available': result.stdout.split('\n')}
    except FileNotFoundError:
        return {'status': 'not_installed'}

def check_memory():
    """メモリの確認"""
    import psutil
    memory = psutil.virtual_memory()
    available_gb = memory.available / (1024**3)
    
    if available_gb >= 8:
        return {'status': 'sufficient', 'available_gb': available_gb}
    else:
        return {'status': 'insufficient', 'available_gb': available_gb, 'required': 8}

def check_dependencies():
    """依存関係の確認"""
    required_packages = [
        'networkx', 'torch', 'transformers', 'sentence-transformers',
        'neo4j', 'requests', 'github3.py'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing.append(package)
    
    return {'missing': missing, 'status': 'ok' if not missing else 'missing_packages'}

def main():
    """環境チェックのメイン処理"""
    checks = {
        'ollama': check_ollama(),
        'memory': check_memory(),
        'dependencies': check_dependencies()
    }
    
    print("🔍 環境チェック結果:")
    print(json.dumps(checks, indent=2))
    
    # 致命的な問題のチェック
    fatal_issues = []
    
    if checks['ollama']['status'] == 'not_installed':
        fatal_issues.append("Ollamaがインストールされていません")
    elif checks['ollama']['status'] == 'no_model':
        fatal_issues.append("Ollamaモデルがありません（codellama:7b-instructまたはphi3:miniが必要）")
    
    if checks['memory']['status'] == 'insufficient':
        fatal_issues.append(f"メモリ不足: {checks['memory']['available_gb']:.1f}GB < 8GB")
    
    if checks['dependencies']['missing']:
        fatal_issues.append(f"パッケージ不足: {', '.join(checks['dependencies']['missing'])}")
    
    if fatal_issues:
        print("\n❌ 致命的な問題:")
        for issue in fatal_issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("\n✅ 環境チェック成功")
        sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 6. コスト削減のベストプラクティス

### 6.1 キャッシュ戦略

1. **LLM応答キャッシュ**: 同じプロンプトの応答を保存
2. **Embeddingキャッシュ**: 計算済みベクトルの再利用
3. **グラフキャッシュ**: 構築済みグラフの永続化
4. **中間結果キャッシュ**: 部分結果の保存・再利用

### 6.2 実行時間最適化

1. **バッチ処理**: 複数インスタンスの同時処理
2. **並列実行**: CPU/GPUリソースの最大活用
3. **早期終了**: 明らかな失敗ケースの早期検出
4. **スマートサンプリング**: 代表的なケースでの検証

この戦略により、**完全無料で信頼性の高い検証**が可能になります。

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"id": "1", "content": "Repograph\u5358\u72ec\u7d71\u5408\u30d7\u30e9\u30f3\u4f5c\u6210\uff08\u7b2c1\u30d5\u30a7\u30fc\u30ba\uff09", "status": "completed"}, {"id": "2", "content": "Repograph\u7d71\u5408\u5b8c\u4e86\u5f8c\u306eKGCompass\u5358\u72ec\u7d71\u5408\u30d7\u30e9\u30f3", "status": "completed"}, {"id": "3", "content": "\u7121\u6599LLM\u3092\u4f7f\u7528\u3057\u305f\u691c\u8a3c\u65b9\u6cd5\u306e\u8a73\u7d30\u5316", "status": "completed"}]