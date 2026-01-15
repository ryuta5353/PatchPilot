# RepoGraph 使用方法：簡潔サマリー

---

## 一覧表：各 Localization レベルでの RepoGraph 使用状況

| レベル | 段階 | 目的 | グラフ使用 | メソッド | 出力 |
|--------|------|------|---------|---------|------|
| **File Level** | 1 | どのファイルを修正するか | ✗ なし | `LLMFL.localize()` | 修正対象ファイル |
| **Related Level** | 2 | ファイル内のどの関数・クラスか | ✗ なし | `LLMFL.localize_function_from_compressed_files()` | 関連関数・クラス |
| **Fine-Grain Level** | 3 | 関数・クラス内のどの行か | ✓ あり ★ | `LLMFL.localize_line_from_coarse_function_locs()` | 修正対象の行番号 |

---

## グラフ生成タイミング

```
[事前処理] RepoGraph 生成
  ├─ generate_graphs.py を実行
  ├─ construct_graph.py でグラフ構築
  └─ cache/code_graphs/ に保存

         ↓

[localize 実行時] グラフ読み込み
  ├─ pickle.load(f"{instance_id}.pkl")
  ├─ json.load(f"tags_{instance_id}.json")
  └─ Fine-Grain Level で使用
```

**重要**: グラフは **localize.py 実行前に生成済み** である必要があります。

---

## Fine-Grain Level での処理詳細

```
入力: found_related_locs（関連関数・クラスのリスト）

┌─────────────────────────────────────────────────────────┐
│ construct_code_graph_context()                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ FOR EACH 関連関数・クラス:                               │
│  ├─ [1] Greedy Token Allocation                        │
│  │   max_tokens = remaining_budget / remaining_sections │
│  │                                                       │
│  ├─ [2] retrieve_graph()                               │
│  │   └─ 1-hop 依存関係を検索                             │
│  │      - 同ファイルの関数                               │
│  │      - 呼び出し関数                                   │
│  │      - 被呼び出し関数                                 │
│  │                                                       │
│  └─ [3] タグをフォーマット                              │
│      └─ "### Dependencies for FUNC_NAME" セクション   │
│         location: file.py lines X - Y                   │
│         name: function_name                             │
│         contents: [コード片]                             │
│                                                          │
└─────────────────────────────────────────────────────────┘

出力: graph_context（文字列）
```

---

## プロンプト統合ポイント

### グラフなし（デフォルト）

```
### GitHub Problem Description ###
{problem_statement}

### Related Files ###
{file_contents}

### Code Relationship Graph ###
[なし]
```

### グラフあり（--repo_graph 指定時）

```
### GitHub Problem Description ###
{problem_statement}

### Related Files ###
{file_contents}        ← ここが削減される可能性がある

### Code Relationship Graph ###
### Dependencies for Function1
location: file.py lines 10-20
contents: [code snippet]

### Dependencies for Function2
...

{code_graph}           ← グラフがここに挿入される
```

**トークン圧迫メカニズム**:
```
グラフなし: file_contents = 88,509 トークン
グラフあり:
  ├─ file_contents = 38,310 トークン（-50,199）
  └─ code_graph    = 28,323 トークン
  合計: 66,633 トークン（削減）

→ ファイル内容が大幅に削減される
→ 修復情報が不足
→ 性能低下（-5.6pp）
```

---

## グラフサイズと内容

### Django__Django-10914 の実測値

```
全タグ: 23,040 個
├─ 定義(def): 7,682 個
└─ 参照(ref): 15,358 個

疑わしいタグ: 847 個
├─ _ (アンダースコア): 493
├─ . (ドット): 107
└─ 単一文字 A-Z

グラフコンテキストサイズ: 113,272 文字 (28,323 トークン)
```

### 論文（Agentless）の期待値

```
1-hop: 11.6 ノード （PatchPilot の 113+ ノードと比較）
グラフサイズ: 2,311 トークン （28,323 の 12 分の 1）
```

**サイズの差: 12 倍**

---

## グラフ検索戦略の比較

### 論文（成功: +5.6pp）

```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':  # ref ONLY
            tags.append(tag)
        if len(tags) >= max_tags:  # max_tags=100
            break
    return tags
```

**特徴**:
- ref タグのみ（シンプル）
- ソートなし（高速）
- max_tags=100（寛容）

### PatchPilot Phase 2-6（失敗: -5.6pp）

```python
def retrieve_graph(code_graph, graph_tags, search_term, structure,
                   max_tags=50, target_file=None, max_tokens_for_section=None):
    def_tags = [tag for ... 'def']
    ref_tags = [tag for ... 'ref']
    ref_tags_sorted = sorted(ref_tags, key=composite_score_key, reverse=True)
    ref_tags_limited = ref_tags_sorted[:max_tags]
    ...
```

**特徴**:
- def + ref タグ（膨張）
- Composite Score でソート（複雑）
- max_tags=50（厳しい）
- トークン管理あり

---

## Fallback メカニズム

```python
# Fine-Grain Level での処理
if num_tokens_from_messages(message, "gpt-4o-2024-05-13") > 128000:
    # Fallback: グラフなしテンプレートに切り替え
    template = obtain_relevant_code_combine_top_n_prompt
    graph_context = ""  # グラフは削除
```

**観測**:
- 現在の実装では Fallback 率が常に **47.8%** となっている
- つまり、ほぼすべてのインスタンスで Fallback が発動
- グラフが追加されることで、プロンプトが必ず超過する

---

## グラフ生成と読み込みのコード位置

| 処理 | ファイル | 行番号 | 説明 |
|------|---------|--------|------|
| グラフ生成 | `RepoGraph/repograph/construct_graph.py` | 全体 | tree-sitter でグラフ構築 |
| グラフ読み込み | `patchpilot/fl/localize.py` | 67-73 | pickle/json で読み込み |
| グラフ検索 | `patchpilot/fl/repograph_utils.py` | 56-265 | retrieve_graph() |
| コンテキスト構築 | `patchpilot/fl/repograph_utils.py` | 268-400+ | construct_code_graph_context() |
| プロンプト統合 | `patchpilot/fl/FL.py` | 859-863 | obtain_relevant_code_graph_prompt に統合 |
| Fallback判定 | `patchpilot/fl/FL.py` | 873-879 | トークン超過で Fallback |

---

## 重要なパラメータ

### グラフ関連

```bash
--repo_graph                          # グラフ有効化フラグ
--code_graph_dir cache/code_graphs/   # グラフファイル位置
```

### localize.py 内部定数

```python
# repograph_utils.py:268
total_token_budget = 30740  # グラフコンテキスト予算

# repograph_utils.py:56
max_tags = 50  # 各関数の最大タグ数

# FL.py:859-873
max_tokens = 128000  # プロンプト上限
```

---

## デバッグ・検証方法

### グラフが実際に使われているか確認

```bash
# ログから確認
grep -i "graph context enabled: True" results/localization_*/localization_logs/*.log

# グラフサイズ確認
grep "Generated graph context:" results/localization_*/localization_logs/*.log
```

### Fallback 発動状況確認

```bash
# Fallback が発動したインスタンス数
grep -c "FALLBACK TRIGGERED" results/localization_*/localization_logs/*.log | grep -v ":0" | wc -l

# Fallback 率計算
echo "Fallback 率 = (Fallback 発動数) / (全インスタンス数)"
```

### グラフコンテキストのトークン数

```bash
grep "Prompt total tokens (with graph):" results/localization_*/localization_logs/*.log | \
  awk -F': ' '{print $NF}' | \
  awk '{sum+=$1; count++} END {print "Average:", sum/count, "Max:", max}'
```

---

## 現在のパフォーマンス

| 設定 | File Recall@3 | Line Recall | Fallback率 |
|------|--------------|------------|-----------|
| Baseline（グラフなし） | 77.8% | 27.1% | - |
| Phase 2-6（グラフあり） | 72.2% | 26.5% | 47.8% |
| 変化 | **-5.6pp** | **-0.6pp** | **+47.8pp** |

---

## 推奨される改善

### 優先度 1: グラフ検索を論文に準じる

```python
# 現在の retrieve_graph を論文の実装に置き換え
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':  # ref のみ
            tags.append(tag)
        if len(tags) >= max_tags:  # max_tags=100
            break
    return one_hop_tags
```

**期待値**:
- グラフサイズ: 28,323 → 2,311 トークン
- パフォーマンス: -5.6pp → +5.6pp（可能性）

### 優先度 2: tree-sitter フィルタリング強化

```python
# construct_graph.py:328 の後に追加
if len(tag_name) <= 1 or tag_name in ['.', ',', '(', ')', '[', ']']:
    continue
```

**期待値**:
- グラフノイズ 3.1% 削減

---

**結論: PatchPilot の RepoGraph 使用方法は明確。問題は実装戦略にある。**

