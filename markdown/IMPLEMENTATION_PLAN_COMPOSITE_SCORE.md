# Localization グラフ優先度改善計画：in_degree → 複合スコア

## 現状分析

### 関連ファイル構成

```
patchpilot/fl/localize.py (263行, 412行)
    ↓ 呼び出し
patchpilot/fl/repograph_utils.py
    ├── construct_code_graph_context() (line 115)
    │   ├─ retrieve_graph() を複数回呼び出し (151, 162, 173行)
    │   └─ found_related_locs を処理
    │
    └── retrieve_graph() (line 12) ← 優先度決定ロジック
        ├── def_tags を処理 (44-50行)
        ├── ref_tags を取得 (46-47行)
        ├── **in_degree でソート (75-79行) ← ここを改善**
        └── one_hop_tags を構築 (90-112行)
```

### 現在の retrieve_graph() フロー

```python
# Line 75-79: 現在の実装
ref_tags_sorted = sorted(ref_tags, key=get_in_degree, reverse=True)
ref_tags_limited = ref_tags_sorted[:max_tags]
```

**問題**: in_degree （呼び出し頻度）がバグ修正と無関係

---

## 実装計画

### フェーズ1: 準備（検証のみ、編集なし）

#### 1-1. 必要な情報を確認
- [ ] `retrieve_graph()` に渡される `structure` パラメータの内容確認
  - ファイルパス情報は含まれているか？
  - 確認方法: ログ出力を追加して debug
  
- [ ] `code_graph` の構造確認
  - NetworkX グラフ: nodes と edges の情報
  - has_edge(), predecessors(), successors() が使用可能か確認

- [ ] `search_term` と `structure` の対応確認
  - search_term から対象ファイルを特定できるか
  - 確認方法: `retrieve_graph()` の debug ログで確認

#### 1-2. 複合スコアの設計仕様書作成
- [ ] ファイルローカル性スコア: どのファイルを基準にするか
- [ ] 直接呼び出し関係の定義: has_edge() で判定
- [ ] スコア重み付け: 各要素の相対的重要度

---

### フェーズ2: コード追加（非破壊）

#### 2-1. 新しいヘルパー関数を追加（repograph_utils.py）

追加場所: `retrieve_graph()` 内の `get_in_degree()` と `get_out_degree()` の後（line 68）

```python
# 新規追加関数 (line 69-90)
def get_file_locality_score(tag, target_file):
    """
    ファイルローカル性スコアを計算
    - 同じファイル: 1000点
    - 同じディレクトリ: 100点
    - 別ファイル: 1点
    """
    if tag['rel_fname'] == target_file:
        return 1000
    elif tag['rel_fname'].split('/')[0] == target_file.split('/')[0]:
        return 100
    else:
        return 1

def is_direct_neighbor(tag, search_term, code_graph):
    """
    search_term と直接呼び出し関係があるか確認
    - search_term が tag を呼ぶ: True
    - tag が search_term を呼ぶ: True
    - その他: False
    """
    try:
        return (code_graph.has_edge(tag['name'], search_term) or
                code_graph.has_edge(search_term, tag['name']))
    except:
        return False

def calculate_composite_score(tag, search_term, code_graph, target_file):
    """
    複合スコアを計算：ファイル + 直接呼び出し + in_degree（補助）
    """
    locality_score = get_file_locality_score(tag, target_file)
    neighbor_bonus = 50 if is_direct_neighbor(tag, search_term, code_graph) else 0
    in_degree_score = min(code_graph.in_degree(tag['name']) / 10, 10)  # max 10点
    
    return locality_score + neighbor_bonus + in_degree_score
```

#### 2-2. ソート処理を新関数に置き換え（repograph_utils.py）

**変更場所**: line 75-79

**変更前**:
```python
# Sort by in_degree (importance as caller context)
ref_tags_sorted = sorted(ref_tags, key=get_in_degree, reverse=True)

# Take top N ref tags
ref_tags_limited = ref_tags_sorted[:max_tags]
```

**変更後**:
```python
# MODIFICATION (段階3): Replace in_degree with composite score
# Composite score = file locality + direct neighbor + in_degree (auxiliary)
def score_function(tag):
    return calculate_composite_score(tag, search_term, code_graph, ???)

ref_tags_sorted = sorted(ref_tags, key=score_function, reverse=True)
ref_tags_limited = ref_tags_sorted[:max_tags]

print(f"[INFO retrieve_graph] Sorted by composite score (file locality + direct neighbor)")
print(f"[INFO retrieve_graph] Filtered ref tags: {len(ref_tags)} → {len(ref_tags_limited)}")
```

**問題点**: target_file を `retrieve_graph()` に渡す必要がある

#### 2-3. シグネチャ変更（必須）

**変更場所**: line 12（関数定義）

**変更前**:
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=50):
```

**変更後**:
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=50, target_file=None):
```

#### 2-4. 呼び出し元を更新（repograph_utils.py）

**変更場所**: line 151, 162, 173（construct_code_graph_context内）

各呼び出しに target_file を追加する必要がある

---

### フェーズ3: テスト・検証

#### 3-1. ローカルテスト
```bash
python patchpilot/fl/localize.py \
    --file_level --related_level --fine_grain_line_level \
    --task_list_file test_instances_sympy_10.txt \
    --output_folder results/localization_composite_score_test_20251104 \
    --repo_graph --code_graph_dir cache/code_graphs \
    --top_n 3 \
    --compress \
    --context_window 20 \
    --num_samples 4 \
    --num_threads 4 \
    --model gpt-4o-mini \
    --temperature 0.7
```

#### 3-2. 結果評価
```bash
python extract_gold_answers.py test_instances_sympy_10.txt gold_answers_sympy_10_cs.json
python evaluate_localization.py results/localization_composite_score_test_20251104/loc_outputs.jsonl gold_answers_sympy_10.json
```

#### 3-3. 比較表作成
- Baseline (current): 18.8%
- Composite Score (new): ???%
- Django での結果も確認（test_instances_10_new.txt で再実行）

---

## 課題・検討事項

### 課題1: target_file をどう特定するか

`construct_code_graph_context()` では複数の関数・クラスをループ処理している。
各ループで異なる search_term が処理されるが、対応するファイルを特定する必要がある。

**解決案**:
- option A: `found_related_locs` から ファイル情報を抽出
- option B: search_term の形式から推測（例: `ClassName.method` から ClassName のファイルを検索）
- option C: graph_tags から search_term のファイルを検索

**推奨**: option C（最も確実）
```python
def find_target_file(search_term, graph_tags):
    """search_term が定義されているファイルを返す"""
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'def':
            return tag['rel_fname']
    return None
```

### 課題2: in_degree 情報は今後も必要か

現在、get_in_degree() と get_out_degree() が定義されている。
複合スコアで in_degree を補助的に使用する場合、削除は不要。
ただし debug ログは更新が必要。

### 課題3: パフォーマンス

composite_score の計算は複数の graph 操作（has_edge() など）を含む。
ref_tags の数が多い場合、パフォーマンス影響あるか。

**対策**: max_tags=50 で既に制限されているため、問題なし。

---

## 実装チェックリスト

- [ ] Phase 1: 必要な情報確認完了
- [ ] Phase 2-1: 新ヘルパー関数追加
- [ ] Phase 2-2: ソート処理を新関数に置き換え
- [ ] Phase 2-3: シグネチャ変更（target_file 追加）
- [ ] Phase 2-4: 呼び出し元を更新
- [ ] Phase 3-1: ローカルテスト実行
- [ ] Phase 3-2: 評価スクリプト実行
- [ ] Phase 3-3: 結果分析・報告

