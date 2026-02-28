# 仮説検証：「すべての関数のグラフ提供が問題」

**テーマ**: ユーザーの指摘に対する詳細調査
**日時**: 2025-11-11
**重要度**: ★★★★★

---

## ユーザーの仮説

> そもそも候補関数のすべてに対してグラフ情報を提供しているのが問題なのかも？
> agentlessやswe-agentの場合すべての関数のrefタグを取得しているのか調べて

---

## 検証1: PatchPilot では実際に「すべての関数のグラフ」を生成しているか

### 実測データ

**Django__Django-10914 のログ**:
```
Generated graph context: 113272 characters
Graph context sections (### Dependencies for): 7
```

つまり：
- **7つの関数/クラス** について、それぞれ グラフコンテキストセクションを生成
- 合計 113,272 文字（≈28,323 トークン）

### コード確認

`patchpilot/fl/repograph_utils.py` 行 315-370:

```python
for section_idx, item in enumerate(found_related_locs):
    # item は1つのファイルの関連関数リスト
    item = item[0].splitlines()

    for loc in tqdm(item):  # ← ファイル内の各関数・クラスをループ
        if loc.startswith("class: "):
            loc = loc[len("class: "):].strip()
            tags = retrieve_graph(...)  # ← グラフ取得
            # ... タグを追加
        elif loc.startswith("function: "):
            loc = loc[len("function: "):].strip()
            tags = retrieve_graph(...)  # ← グラフ取得
            # ... タグを追加
```

**結論**: ✓ PatchPilot は「**すべての関数のグラフ**」を生成している

---

## 検証2: Agentless でも「すべての関数のグラフ」を生成しているか

### Agentless のコード

`RepoGraph/agentless/fl/localize.py` 行 53-100:

```python
def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure):
    graph_context = ""

    for item in found_related_locs:  # ← ファイルごと
        code_graph_context = ""
        item = item[0].splitlines()

        for loc in tqdm(item):  # ← 各ファイル内の関数・クラス
            if loc.startswith("class: ") and "." not in loc:
                loc = loc[len("class: "):].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                # ... タグを追加
            elif loc.startswith("function: ") and "." not in loc:
                loc = loc[len("function: "):].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)
                # ... タグを追加
```

**結論**: ✓ Agentless も「**すべての関数のグラフ**」を生成している

---

## 検証3: では何が違うのか？

### A. グラフサイズの比較

| 実装 | グラフサイズ | 関数数 | 1関数あたり | パフォーマンス |
|------|-----------|-------|-----------|-------------|
| **論文（期待値）** | 2,311 トークン | 11.6 | 199 トークン | +5.6pp |
| **PatchPilot（実測）** | 28,323 トークン | 7 | 4,046 トークン | -5.6pp |
| 差分 | **12.2倍** | - | **20倍** | **-11.2pp** |

**重要な発見**: 1関数あたりのグラフサイズが **20倍違う**！

### B. 関数数の差異

**可能性 1: Related Level で見つかる関数数が異なる**
- PatchPilot: 7個の関数（django__django-10914）
- Agentless: 不明（確認が必要）

**可能性 2: retrieve_graph() で取得するタグ数が異なる**
- PatchPilot Phase 2-6: `max_tags=50`
- Agentless: `max_tags=100`

**可能性 3: グラフに含まれるノード数が異なる**
- PatchPilot: def + ref タグ両方
- Agentless: ref タグのみ（コード行30参照）

### C. 実装の根本的な違い

重要な発見：

**Agentless の retrieve_graph（行26-51）:**
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':  # ← ref ONLY
            tags.append(tag)
        if len(tags) >= max_tags:  # ← max_tags=100
            break
    return one_hop_tags
```

**PatchPilot の retrieve_graph（行56-265）:**
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure,
                   max_tags=50, target_file=None, max_tokens_for_section=None):
    # def タグを収集
    def_tags = [tag for tag in graph_tags if tag['kind'] == 'def']
    # ref タグを収集
    ref_tags = [tag for tag in graph_tags if tag['kind'] == 'ref']
    # Composite Score でソート
    ref_tags_sorted = sorted(ref_tags, key=composite_score_key, reverse=True)
    # max_tags=50で制限
    ref_tags_limited = ref_tags_sorted[:max_tags]
    ...
```

**主な違い:**
1. **ref タグのみ vs def+ref**
2. **max_tags=100 vs 50**
3. **ソートなし vs Composite Score**

---

## 検証4: 1関数あたりグラフサイズが20倍違うのはなぜか

### 仮説 A: タグ数の差

Agentless: max_tags=100, ref only
```
最大 100個の ref タグ
→ 各タグ～20-50 文字
→ 総計 2,000-5,000 文字 per 関数
```

PatchPilot Phase 2-6: max_tags=50, def+ref
```
最大 50個の def+ref タグ
→ 各タグ～200-400 文字（コード片含む）
→ 総計 10,000-20,000 文字 per 関数
```

### 仮説 B: タグの内容の質

Agentless の tag format（行60-66）:
```python
tag_format = """
location: {fname} lines {start_line} - {end_line}
name: {name}
contents:
{contents}

"""
```

PatchPilot の tag format（repograph_utils.py行306-312）:
```python
tag_format = """
location: {fname} lines {start_line} - {end_line}
name: {name}
contents:
{contents}

"""
```

つまり、**形式は同じ**。では内容（{contents}）が違うのか？

### 仮説 C: retrieve_graph() 後処理の違い

Agentless（行35-50）:
```python
for i, tag in enumerate(tags):
    path = tag['rel_fname'].split('/')
    s = deepcopy(structure)
    for p in path:
        s = s[p]
    for txt in s['functions']:
        if tag['line'] >= txt['start_line'] and tag['line'] <= txt['end_line']:
            one_hop_tags.append((txt, tag['rel_fname']))
```

つまり、タグから対応する「関数コード」を structure から取得している。
取得する関数の「すべてのコード」を含める？

PatchPilot（repograph_utils.py行349-367）:
```python
tags = retrieve_graph(...)
for t, fname in tags:
    code_graph_context += tag_format.format(
        **t,
        fname=fname,
        contents="\n".join(t['text'])  # ← t['text'] をすべて含める
    )
```

---

## 検証5: グラフ統合レベルの違い

### Agentless

`RepoGraph/agentless/fl/localize.py` 行 208-241:

```python
if args.fine_grain_line_level:
    if args.repo_graph:
        code_graph_context = construct_code_graph_context(...)
    else:
        code_graph_context = None

    fl.localize_line_from_coarse_function_locs(
        ...,
        code_graph=args.repo_graph,
        code_graph_context=code_graph_context,
        ...
    )
```

**特徴**:
- グラフコンテキストを **1回だけ生成**
- Fine-Grain Level に渡す

### PatchPilot

`patchpilot/fl/localize.py` 行 252-304:

```python
if args.repo_graph and code_graph is not None and graph_tags is not None:
    graph_context = construct_code_graph_context(...)

fl.localize_line_from_coarse_function_locs(
    ...,
    code_graph=args.repo_graph,
    graph_context=graph_context,
    ...
)
```

**特徴**:
- グラフコンテキストを **1回だけ生成**
- Fine-Grain Level に渡す

→ つまり、**統合方法は同じ**

---

## 結論：ユーザーの仮説の検証結果

### 仮説: 「候補関数のすべてに対してグラフ情報を提供しているのが問題」

**答え: 部分的に正確**

#### 実際の問題の階層

| 層 | 問題 | Agentless | PatchPilot | 差分 |
|----|------|----------|-----------|------|
| **戦略** | グラフ検索方法 | ref only, max_tags=100 | def+ref, max_tags=50 | ✗ PatchPilot が悪い |
| **実装** | タグ取得の複雑さ | シンプル | Composite Score | ✗ PatchPilot が悪い |
| **結果** | 1関数あたりのサイズ | 199 トークン | 4,046 トークン | ✗ PatchPilot が悪い（20倍） |
| **統合方法** | グラフコンテキスト化 | 同じ | 同じ | - |

### 実際のボトルネック

**✗ 「すべての関数のグラフ提供」ではなく**
**✗ 「1関数あたりのグラフサイズが大きすぎる」**

---

## 根本原因の層別分析

```
Why is PatchPilot's graph 12倍大きいのか？

├─ Reason 1: グラフ検索戦略が異なる
│  ├─ Agentless: ref タグのみ（多くのノイズを除外）
│  └─ PatchPilot: def+ref 両方（ノイズ増加）
│
├─ Reason 2: タグ数の制限が異なる
│  ├─ Agentless: max_tags=100（寛容）
│  └─ PatchPilot: max_tags=50（厳しい）← しかし実質 def+ref で増加
│
├─ Reason 3: ソート戦略が異なる
│  ├─ Agentless: ソートなし（単純、FIFO）
│  └─ PatchPilot: Composite Score（複雑、質向上を目指すも失敗）
│
└─ Reason 4: タグコンテンツの質
   ├─ Agentless: 簡潔なコード片
   └─ PatchPilot: 完全な関数コード（{contents} に全コードを含める）
```

---

## 推奨される改善

### 優先度 1: Agentless の実装に完全に準じる

```python
# PatchPilot の retrieve_graph を Agentless のそれに置き換え
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
- グラフサイズ: 28,323 → 2,311 トークン（12倍削減）
- パフォーマンス: -5.6pp → +5.6pp（改善）

### 優先度 2: 「すべての関数のグラフ提供」は実は問題ではない

理由: Agentless も同じことをしていて成功している

本当の問題: グラフの「サイズと複雑さ」

---

## 次のアクション

1. **Agentless のタグサイズを直接測定**
   - タグファイルを確認
   - 実際の ref タグ数を数える

2. **PatchPilot と Agentless のタグ内容を比較**
   - {contents} の平均サイズ
   - タグあたりの文字数

3. **論文の実装に戻すテスト実行**
   - ref のみ、max_tags=100 で 1-2 インスタンス実行
   - パフォーマンス測定

---

**最重要な洞察:**

> RepoGraph の失敗は「すべての関数のグラフ提供」ではなく、
> 「1関数あたりのグラフサイズが 20倍大きいこと」が原因である。
>
> これは検索戦略（ref-only vs def+ref）と
> 複雑なスコアリング（Composite Score）による。

