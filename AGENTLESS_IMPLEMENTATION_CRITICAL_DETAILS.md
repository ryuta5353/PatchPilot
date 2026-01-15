# 論文の Agentless 実装 vs 我々の実装：致命的な相違の詳細分析

**作成日**: 2025-11-10
**重要性**: ⭐⭐⭐⭐⭐ 最も重要な発見

---

## 核心的な違い：retrieve_graph の実装

### 論文の Agentless 実装（成功例）

**ファイル**: `/RepoGraph/agentless/fl/localize.py` 行26-51

```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        # 重要：'ref' タグのみ！（呼び出し元のみ）
        if tag['name'] == search_term and tag['kind'] == 'ref':
            tags.append(tag)
        if len(tags) >= max_tags:  # max_tags = 100
            break

    for i, tag in enumerate(tags):
        # find corresponding calling function/class
        path = tag['rel_fname'].split('/')
        s = deepcopy(structure)
        for p in path:
            s = s[p]

        # 関数を探す
        for txt in s['functions']:
            if tag['line'] >= txt['start_line'] and tag['line'] <= txt['end_line']:
                one_hop_tags.append((txt, tag['rel_fname']))

        # クラスメソッドを探す
        for txt in s['classes']:
            for func in txt['methods']:
                if tag['line'] >= func['start_line'] and tag['line'] <= func['end_line']:
                    func['text'].insert(0, txt['text'][0])
                    one_hop_tags.append((func, tag['rel_fname']))

    return one_hop_tags
```

**特徴**：
1. **'ref' タグのみ取得**
   - 呼び出し元（caller）の情報のみ
   - 定義（definition）は不要
2. **max_tags = 100**
   - 最大100個のタグ
   - 超過時は最初の100個で打ち切り
3. **シンプルなループ**
   - for ループで順序に取得
   - 複雑なスコアリングなし
4. **関連度判定なし**
   - 単に tag['name'] == search_term で判定

---

### 我々の実装（失敗例）

**ファイル**: `patchpilot/fl/repograph_utils.py` 行56-265

```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=50,
                   target_file=None, max_tokens_for_section=None):
    # 'def' タグも取得
    def_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'def']
    ref_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'ref']

    # def を 1 個に制限
    def_tags_limited = def_tags[:1]

    # ref を Composite Score で並び替え
    def composite_score_key(tag):
        return calculate_composite_score(tag, search_term, code_graph, target_file)

    ref_tags_sorted = sorted(ref_tags, key=composite_score_key, reverse=True)

    # トークン数制御
    if max_tokens_for_section is not None:
        ref_tags_limited = []
        tokens_used = 0
        for tag in ref_tags_sorted:
            tag_tokens = len(str(tag.get('text', []))) // 4
            if tokens_used + tag_tokens > max_tokens_for_section:
                break
            ref_tags_limited.append(tag)
            tokens_used += tag_tokens
            if len(ref_tags_limited) >= max_tags:
                break
    else:
        ref_tags_limited = ref_tags_sorted[:max_tags]

    tags = def_tags_limited + ref_tags_limited
    # ... (続きの処理)
```

**特徴**：
1. **'def' と 'ref' タグの両方取得**
   - 定義と呼び出し元の両方
   - 複雑さ増加
2. **max_tags = 50**
   - 論文の 100 より少ない
   - ただし Composite Score で重みづけされた上位50個
3. **複雑な Composite Score**
   - ファイル近接性: 1000/100/1
   - 直接隣人ボーナス: +50
   - In-degree: 0-10
4. **トークン数制限**
   - max_tokens_for_section パラメータ
   - Greedy allocation

---

## Composite Score の計算が問題

### 論文のアプローチ：スコアなし

```python
for tag in graph_tags:
    if tag['name'] == search_term and tag['kind'] == 'ref':
        tags.append(tag)  # スコア計算なし！単純にリスト化
```

**メリット**：
- シンプル
- 予測可能
- バグが少ない
- グラフの本質的な情報を保持

### 我々のアプローチ：複合スコア

```python
def calculate_composite_score(tag, search_term, code_graph, target_file):
    locality_score = get_file_locality_score(tag, target_file)
    neighbor_bonus = 50 if is_direct_neighbor(tag, search_term, code_graph) else 0
    in_degree = code_graph.in_degree(tag['name']) if tag['name'] in code_graph else 0
    in_degree_score = min(in_degree / 10, 10)

    return locality_score + neighbor_bonus + in_degree_score
```

**問題点**：
1. **スコアの重みが恣意的**
   - 本当に locality_score が 1000 の価値がある？
   - in_degree スコアの max=10 は適切か？
2. **target_file に依存**
   - target_file が None の場合、スコアが狂う
   - 複数の定義がある場合の選択が不安定
3. **グラフ構造の情報が失われる**
   - 単なる in_degree に削減
   - 複雑な依存関係が無視される

**結果**：
- スコアが不正確 → 無関連な関数を高く評価 → ノイズ化

---

## construct_code_graph_context の相違

### 論文の実装

**ファイル**: `/RepoGraph/agentless/fl/localize.py` 行53-100

```python
def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure):
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

    # retrieve the code graph for dependent functions and classes
    for item in found_related_locs:
        code_graph_context = ""
        item = item[0].splitlines()
        for loc in tqdm(item):
            if loc.startswith("class: ") and "." not in loc:
                loc = loc[len("class: "):].strip()
                tags = retrieve_graph(code_graph, graph_tags, loc, structure)  # ← simple call
                # ... (tag_format で出力)

    return graph_context
```

**特徴**：
1. **retrieve_graph への引数が最小限**
   - code_graph
   - graph_tags
   - search_term (loc)
   - structure
   - デフォルト max_tags=100 を使用
2. **パラメータなし**
   - target_file の明示的な指定なし
   - max_tokens_for_section なし
   - シンプルさ重視

### 我々の実装

**ファイル**: `patchpilot/fl/localize.py` 行264-271

```python
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure,
    preferred_files=pred_files,  # ← 追加
    logger=logger                 # ← 追加
    # NOTE: total_token_budget パラメータ NOT passed - uses default of 30,740
)
```

**問題点**：
1. **total_token_budget が渡されていない**
   - ハードコードされた 30,740 を使用
   - 実際の予算と乖離
2. **preferred_files を渡している**
   - より複雑な logic が必要
   - デバッグが難しい

---

## グラフコンテキストのプロンプト統合

### 論文の実装

**ファイル**: `/RepoGraph/agentless/fl/FL.py` 行121-156

```python
obtain_relevant_code_graph_prompt = """
Please review the following GitHub problem description and relevant files,
and provide a set of locations that need to be edited to fix the issue.
You will also be given a list of function/class dependencies to help you
understand how functions/classes in relevant files fit into the rest of the codebase.

### GitHub Problem Description ###
{problem_statement}

### Related Files ###
{file_contents}

### Function/Class Dependencies ###
{code_graph}

###

Please provide the class name, function or method name, or the exact line numbers
that need to be edited.
"""
```

**特徴**：
1. **明確なセクション分け**
   - GitHub Problem Description
   - Related Files
   - Function/Class Dependencies ← グラフはここ
2. **セクションの説明が明確**
   - "list of function/class dependencies"
   - "help you understand how ... fit into the rest of the codebase"
3. **シンプルなフォーマット**
   - セクションは3つのみ

### 我々の実装

**ファイル**: `patchpilot/fl/FL.py` 行237-290

```python
obtain_relevant_code_graph_prompt = """
Please review the following GitHub problem description and relevant files,
and provide a set of locations that need to be edited to fix the issue.
You will also be given a focused list of function/class dependencies to help
you understand the immediate context of required changes.

### GitHub Problem Description ###
{problem_statement}

### Related Files ###
Below are the files that contain the code mentioned in the problem description.
Each file section is marked with ### File: followed by the file path and contents
with line numbers. Only consider the files explicitly listed below.
{file_contents}

### Code Relationship Graph ###

Format:
- Each "### Dependencies for X" section lists functions directly connected to X
- Entries are ordered by relevance to the bug
- Graph includes only immediate relationships (1-hop neighbors)

For bug fixing:
1. Identify the function with the core bug from the problem description
2. Check callers (functions that call the target): ...
3. Check callees (functions called by target): ...
4. Primary source is the problem description; use this graph to identify related code locations

{code_graph}

###
```

**問題点**：
1. **説明が過度に詳細**
   - Format セクション（4行）
   - bug fixing の手順（4項目）
   - LLM に過剰な指示
2. **セクション構成が複雑**
   - "Related Files" に詳細説明
   - "Code Relationship Graph" に Format と指示
3. **"immediate context" の強調**
   - 1-hop neighbor との指定
   - しかし実装は 1-hop に限定していない（113 ロケーション）

---

## フォールバック処理の相違

### 論文の実装

**ファイル**: `/RepoGraph/agentless/fl/FL.py` 行515-524

```python
elif code_graph:
    template = self.obtain_relevant_code_graph_prompt
    message = template.format(
        problem_statement=self.problem_statement,
        file_contents=topn_content,
        code_graph=code_graph_context
    )
    if num_tokens_from_messages(message, "gpt-4o-2024-05-13") > 128000:
        template = self.obtain_relevant_code_combine_top_n_prompt
        message = template.format(
            problem_statement=self.problem_statement,
            file_contents=topn_content  # ← グラフなし
        )
else:
    template = self.obtain_relevant_code_combine_top_n_prompt
    message = template.format(
        problem_statement=self.problem_statement,
        file_contents=topn_content
    )
```

**特徴**：
1. **グラフをまず追加**
   - obtain_relevant_code_graph_prompt を使用
2. **トークン数超過時のみフォールバック**
   - 128000 超過チェック
3. **フォールバック時はグラフを削除**
   - obtain_relevant_code_combine_top_n_prompt に切り替え
   - topn_content は変わらない

**結果**：
- グラフが小さい（2,311トークン）なら、ほぼフォールバックしない
- グラフが大きい（28,323トークン）なら、常にフォールバック

### 我々の実装

**ファイル**: `patchpilot/fl/FL.py` 行859-878

```python
elif code_graph:
    template = self.obtain_relevant_code_graph_prompt
    message = template.format(
        problem_statement=self.problem_statement,
        file_contents=topn_content,
        code_graph=graph_context,
        last_search_results=last_search_results
    )
    # DEBUG: Log graph context information
    self.logger.info("==== GRAPH CONTEXT DEBUG ====")
    self.logger.info(f"Graph context size: {len(graph_context)} characters")
    self.logger.info(f"Prompt total tokens (with graph): {num_tokens_from_messages(message, 'gpt-4o-2024-05-13')}")

    if num_tokens_from_messages(message, "gpt-4o-2024-05-13") > 128000:
        self.logger.warning("⚠️ FALLBACK TRIGGERED: Token count exceeds 128000")
        template = self.obtain_relevant_code_combine_top_n_prompt
        message = template.format(
            problem_statement=self.problem_statement,
            file_contents=topn_content,
            last_search_results=last_search_results
        )
```

**問題点**：
1. **グラフが大きすぎる**
   - 28,323トークン vs 2,311トークン（12倍）
2. **常にフォールバック**
   - 128000 を超える確率が高い
3. **topn_content が事前に切り詰められている**
   - グラフ生成前に既に削減されている（line 843）
   - フォールバック時も削減版を使用

---

## 根本的な哲学の違い

### 論文：Less is More

```
シンプルさを重視：
  ✓ k=1 のみ（2,311トークン）
  ✓ ref タグのみ
  ✓ スコアリングなし
  ✓ max_tags = 100
  ✓ トークン効率最高
  ✓ バグが少ない
  ✓ 予測可能
  ✓ 結果：+5.6pp ✓
```

### 我々：More is Better（失敗）

```
複雑さを追加：
  ✗ k=∞（113ロケーション）
  ✗ def + ref タグ
  ✗ 複雑な Composite Score
  ✗ max_tags = 50
  ✗ Dynamic token limiting
  ✗ Greedy allocation
  ✗ token management
  ✗ トークン効率悪い
  ✗ バグが多い
  ✗ 不予測な動作
  ✗ 結果：-5.6pp ✗
```

---

## 最終的な根本原因

### なぜ論文は成功し、我々は失敗したのか

1. **グラフサイズの管理**
   - 論文：k=1 で固定、2,311トークン
   - 我々：制限なし、28,323トークン

2. **スコアリング戦略**
   - 論文：なし（単純性重視）
   - 我々：複合スコア（不正確）

3. **統合の明確さ**
   - 論文："ref タグのみ"と明確に定義
   - 我々："def と ref を分別"と複雑化

4. **トークン管理**
   - 論文：グラフが小さいので自動的に効率的
   - 我々：グラフが大きいので常にフォールバック

5. **エラー処理**
   - 論文：シンプルなので想定外のケースが少ない
   - 我々：複雑なので想定外のケースが多い

---

## 改善案

### Phase 2-7: 論文の実装に完全に準じる

**Step 1: retrieve_graph を論文の実装に変更**

```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    # 変更点：
    # 1. max_tags = 50 → 100
    # 2. 'ref' タグのみ（def 不要）
    # 3. Composite Score 削除
    # 4. target_file パラメータ削除
    # 5. max_tokens_for_section パラメータ削除

    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':  # ref のみ
            tags.append(tag)
        if len(tags) >= max_tags:
            break

    # ... (論文と同じ実装)
    return one_hop_tags
```

**Step 2: construct_code_graph_context を論文の実装に変更**

```python
def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure):
    # 変更点：
    # 1. preferred_files パラメータ削除
    # 2. total_token_budget パラメータ削除
    # 3. logger パラメータ削除
    # 4. retrieve_graph への引数を最小限に

    # ... (論文と同じ実装)
```

**期待される改善**：
- グラフサイズ：28,323 → 2,311トークン（92%削減）
- スコアリング：複雑 → シンプル
- ファイルリコール：72.2% → 77.8% 以上（+5.6pp 回復）

---

## 結論

論文の Agentless 実装を詳細に調べた結果、我々の実装は以下の点で大きく逸脱している：

1. **グラフ取得方法**：ref タグのみ vs def+ref（複雑化）
2. **タグ数制限**：max_tags=100 vs max_tags=50+スコア（削減）
3. **関連度スコア**：なし vs Composite Score（不正確）
4. **トークン管理**：自動効率化 vs Dynamic limiting（複雑）
5. **プロンプト統計**：3セクション vs 過度な詳細説明

**最も重要な発見**：
論文は「何をしないか」の方が重要である。ref タグのみで十分であり、複雑なスコアリングや def タグの取得は無用の長物。シンプルさが最大の強みである。

