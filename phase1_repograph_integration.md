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
- **検証**: OpenAI APIを使用（gpt-4o-mini推奨）

---

## 2. Repograph統合アーキテクチャ

### 2.1 統合後の処理フロー

```
問題文入力
    ↓
[既存] PatchPilot FL初期処理（ファイルレベル特定）
    ↓
[新規] Repographグラフ・構造情報の構築/読込
    ↓
[改良] LLMFL.localize_line_from_files()にグラフコンテキスト追加
    ↓
[新規] 依存関係を考慮したプロンプト生成
    ↓
[既存] LLMへのプロンプト送信
    ↓
障害位置特定結果
```

### 2.2 ディレクトリ構造

```
patchpilot/
├── fl/
│   ├── localize.py           # [修正] --repo_graph オプション追加
│   ├── FL.py                 # [修正] グラフコンテキスト統合メソッド追加
│   └── repograph_utils.py    # [新規] Repograph統合ユーティリティ
├── repograph/                # [新規] Repographモジュール移植
│   ├── __init__.py
│   ├── construct_graph.py    # RepoGraph/repograph/から移植
│   ├── graph_searcher.py     # RepoGraph/repograph/から移植
│   └── utils.py              # RepoGraph/repograph/から移植
└── cache/
    └── code_graphs/          # グラフキャッシュ保存先
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
tqdm>=4.64.0
```

```bash
# インストールコマンド
pip install -r requirements_repograph.txt
```

#### タスク2: Repographモジュール移植

RepoGraph/repographフォルダ全体をpatchpilot/repographに移植：

```bash
# 移植コマンド
cp -r RepoGraph/repograph/ patchpilot/
touch patchpilot/repograph/__init__.py
```

移植後の修正点：
1. `construct_graph.py`の`from utils import create_structure`を`from .utils import create_structure`に修正
2. `__init__.py`で必要なクラスをエクスポート

### 3.2 Week 2: PatchPilot統合

#### タスク3: FL.pyの拡張

Agentlessの実装パターンに従って、既存の`LLMFL`クラスを拡張：

```python
# patchpilot/fl/repograph_utils.py
import pickle
import json
from copy import deepcopy
from tqdm import tqdm

def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    """Agentless localize.py:26-51から移植"""
    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':
            tags.append(tag)
        if len(tags) >= max_tags:
            break

    for i, tag in enumerate(tags):
        print(f"Retrieving graph for {i}/{len(tags)}")
        path = tag['rel_fname'].split('/')
        s = deepcopy(structure)
        for p in path:
            s = s[p]
        for txt in s['functions']:
            if tag['line'] >= txt['start_line'] and tag['line'] <= txt['end_line']:
                one_hop_tags.append((txt, tag['rel_fname']))
        for txt in s['classes']:
            for func in txt['methods']:
                if tag['line'] >= func['start_line'] and tag['line'] <= func['end_line']:
                    func['text'].insert(0, txt['text'][0])
                    one_hop_tags.append((func, tag['rel_fname']))
    return one_hop_tags

def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure):
    """Agentless localize.py:53-100から移植"""
    graph_context = ""

    graph_item_format = """
### Dependencies for {func}
{dependencies}
"""
    tag_format = """
location: {fname} lines {start_line} - {end_line}
name: {name}
contents:
{contents}

"""
    for item in found_related_locs:
        code_graph_context = ""
        item = item[0].splitlines()
        for loc in tqdm(item):
            if loc.startswith("class: ") and "." not in loc:
                loc = loc[len("class: ") :].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )
            elif loc.startswith("function: ") and "." not in loc:
                loc = loc[len("function: ") :].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )
            elif "." in loc:
                loc = loc.split(".")[-1].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                for t, fname in tags:
                    code_graph_context += tag_format.format(
                        **t,
                        fname=fname,
                        contents="\n".join(t['text'])
                    )
            graph_context += graph_item_format.format(func=loc, dependencies=code_graph_context)
    return graph_context
```

#### タスク4: localize.pyへの統合

PatchPilotの既存パターンに従った統合：

```python
# patchpilot/fl/localize.py の修正点

# 1. import追加
from patchpilot.fl.repograph_utils import construct_code_graph_context

# 2. argparse引数追加
parser.add_argument("--repo_graph", action="store_true",
                   help="Enable Repograph code structure analysis")
parser.add_argument("--code_graph_dir", default="cache/code_graphs",
                   help="Directory for cached code graphs")

# 3. localize_instance()関数内でグラフ読み込み追加（Line 61-67付近）
if args.repo_graph:
    code_graph = pickle.load(
        open(os.path.join(args.code_graph_dir, f"{instance_id}.pkl"), "rb")
    )
    graph_tags = json.load(
        open(os.path.join(args.code_graph_dir, f"tags_{instance_id}.json"), "r")
    )

# 4. LLMFL.localize_line_from_files()呼び出し時にグラフ情報を渡す（Line 190-198付近）
if args.repo_graph:
    # グラフコンテキストを構築
    graph_context = construct_code_graph_context(
        found_edit_locs, code_graph, graph_tags, structure
    )
    # FL.pyに渡すパラメータに追加
    fl.graph_context = graph_context
```

### 3.3 Week 3: 検証と評価

#### タスク5: OpenAI API設定確認

```bash
# OpenAI API設定確認
echo "Checking OpenAI API configuration..."

# 環境変数確認
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY not set"
    exit 1
fi

# API接続テスト
python -c "
import openai
import os
openai.api_key = os.getenv('OPENAI_API_KEY')
try:
    response = openai.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': 'test'}],
        max_tokens=5
    )
    print('✅ OpenAI API connection successful')
except Exception as e:
    print(f'❌ OpenAI API connection failed: {e}')
    exit 1
"

echo "OpenAI API setup verified!"
```

#### タスク6: FL.pyにグラフプロンプト追加

Agentless FL.py:121-133の`obtain_relevant_code_graph_prompt`を移植：

```python
# patchpilot/fl/FL.py に追加

class LLMFL:
    # 既存のプロンプト...

    obtain_relevant_code_graph_prompt = """
Please review the following GitHub problem description and relevant files, and provide a set of locations that need to be edited to fix the issue.
You will also be given a list of function/class dependencies to help you understand how functions/classes in relevant files fit into the rest of the codebase.
The locations can be specified as class names, function or method names, or exact line numbers that require modification.

### GitHub Problem Description ###
{problem_statement}

### Related Files ###
{file_contents}

### Function/Class Dependencies ###
{code_graph}

###

Please provide the class name, function or method name, or the exact line numbers that need to be edited.
### Examples:
```
full_path1/file1.py
line: 10
class: MyClass1
line: 51

full_path2/file2.py
function: MyClass2.my_method
line: 12

full_path3/file3.py
function: my_function
line: 24
line: 156
```

Return just the location(s)
"""

    def localize_line_from_files(self, pred_files, num_samples=4):
        # 既存の実装...

        # グラフコンテキストが設定されている場合は拡張プロンプトを使用
        if hasattr(self, 'graph_context') and self.graph_context:
            prompt = self.obtain_relevant_code_graph_prompt.format(
                problem_statement=self.problem_statement,
                file_contents=file_contents,
                code_graph=self.graph_context
            )
        else:
            # 既存のプロンプトを使用
            prompt = self.obtain_relevant_code_combine_top_n_prompt.format(
                problem_statement=self.problem_statement,
                file_contents=file_contents
            )

        # 既存の処理続行...
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

# Step 0: グラフ構築
for instance_id in django__django-11001 django__django-11019 django__django-11039 django__django-11049 django__django-11099; do
    echo "Building graph for $instance_id"
    python patchpilot/repograph/construct_graph.py /path/to/repo/$instance_id
    mv graph.pkl cache/code_graphs/$instance_id.pkl
    mv tags.json cache/code_graphs/tags_$instance_id.json
done

# Step 1: ベースライン（Repographなし） - README通りのコマンド
python patchpilot/fl/localize.py \
    --file_level --direct_line_level \
    --output_folder results/baseline \
    --top_n 5 --compress \
    --context_window=20 \
    --num_samples 4 --num_threads 16

# Step 2: Repograph統合版
python patchpilot/fl/localize.py \
    --file_level --direct_line_level \
    --repo_graph \
    --code_graph_dir cache/code_graphs \
    --output_folder results/with_repograph \
    --top_n 5 --compress \
    --context_window=20 \
    --num_samples 4 --num_threads 16

# Step 3: 結果比較
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
- ✅ OpenAI API (gpt-4o-mini) での推論が動作
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
| APIレート制限 | 検証に時間がかかる | バッチサイズ調整、待機時間追加 |
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
  - [ ] 依存関係インストール (requirements_repograph.txt)
  - [ ] Repographモジュール移植 (RepoGraph/repograph/ → patchpilot/repograph/)
  - [ ] import修正とテスト実行
  - [ ] グラフ構築コマンド動作確認

- [ ] Week 2
  - [ ] repograph_utils.py実装（Agentlessパターン移植）
  - [ ] FL.py拡張（グラフプロンプト追加）
  - [ ] localize.py統合（--repo_graphオプション追加）
  - [ ] 統合テスト（基本的なグラフ読み込み確認）

- [ ] Week 3
  - [ ] テストインスタンスでのグラフ構築
  - [ ] ベースラインvs統合版比較実行
  - [ ] 精度評価とメトリクス分析
  - [ ] レポート作成とPhase 2準備