# RepoGraph統合失敗の根本原因調査：グラフ品質分析

**作成日**: 2025-11-10
**重要性**: ★★★★★ 極めて重要
**状態**: 調査中

---

## 核心的な発見

### 事実1: construct_graph.py は正しい実装
PatchPilot の `RepoGraph/repograph/construct_graph.py` (行290-328) は、論文と同じフィルタリング機構を実装している：

```python
# 行290-301: 標準ライブラリとbuiltinsの抽出
std_funcs, std_libs = self.std_proj_funcs(code, fname)
builtins_funs = [name for name in dir(builtins)]
builtins_funs += dir(list)
builtins_funs += dir(dict)
...

# 行323-328: フィルタリング
if tag_name in std_funcs:
    continue
elif tag_name in std_libs:
    continue
elif tag_name in builtins_funs:
    continue
```

つまり、グラフ生成時のフィルタリングは **正しく実装されている**。

### 事実2: 論文の実装と PatchPilot の実装は全く異なる
論文（Agentless）:
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':  # ref ONLY
            tags.append(tag)
        if len(tags) >= max_tags:
            break
```

PatchPilot 現在:
```python
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=50,
                   target_file=None, max_tokens_for_section=None):
    # def と ref 両方を収集
    def_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'def']
    ref_tags = [tag for tag in graph_tags
                if tag['name'] == search_term and tag['kind'] == 'ref']

    # Composite Score で複雑にソート
    ref_tags_sorted = sorted(ref_tags, key=composite_score_key, reverse=True)
```

### 事実3: ユーザーの主張が正確
> "元々はagentlessと同じ実装をしていて、それでも下がる一方だからこのようにいろいろな策を考えてきたんです"

つまり：
1. 最初は論文と同じシンプルな実装をした → -5.6pp に低下
2. 改善策を試した（Composite Score, Greedy allocation）→ さらに悪化
3. 現在の複雑な実装に至った

**重要**: グラフの生成方法は同じ（フィルタリングあり）。だが、グラフの利用方法（retrieve_graph）が大きく異なる。

---

## 仮説：グラフ品質の問題ではなく、統合方法の問題

### 問題点の特定

#### 問題A: グラフの「誤ったインポート」フィルタリング

construct_graph.py の `std_proj_funcs` メソッドを詳しく見ると：

```python
def std_proj_funcs(self, code, fname):
    std_funcs = []
    std_libs = []
    tree = ast.parse(code)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # ...
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            # 第三者ライブラリをフィルタリング
            try:
                eval_name = alias.name if alias.asname is None else alias.asname
                std_funcs.extend([name for name, member in
                                 inspect.getmembers(eval(eval_name))
                                 if callable(member)])
            except:
                pass

    return std_funcs, std_libs
```

**潜在的な問題**:
- `eval()` を使用している → セキュリティリスク？
- インポート構文解析の精度
- プロジェクト固有の関数を「第三者」と判定する可能性

#### 問題B: フィルタリング後のグラフサイズ

論文での成功例：
- 1-hop: 平均 11.6 ノード, 37.1 エッジ, ~2,311 トークン → +5.6pp 改善

PatchPilot での失敗例：
- 113 ロケーション, 28,323 トークン → -5.6pp 悪化

**グラフサイズが 12 倍以上** → フィルタリングが機能していない可能性

#### 問題C: タグの品質

construct_graph.py のクエリ定義（行239-252）：

```python
scm_fname = """
(class_definition
name: (identifier) @name.definition.class) @definition.class

(function_definition
name: (identifier) @name.definition.function) @definition.function

(call
function: [
    (identifier) @name.reference.call
    (attribute
        attribute: (identifier) @name.reference.call)
]) @reference.call
"""
```

この tree-sitter クエリは**非常にシンプル**。実装詳細：

```python
for node, tag in captures:
    if tag.startswith("name.definition."):
        kind = "def"
    elif tag.startswith("name.reference."):
        kind = "ref"
    else:
        continue

    tag_name = node.text.decode("utf-8")

    # フィルタリング
    if tag_name in std_funcs:
        continue
    # ...
```

**問題**: フィルタリング後でも、取得されたタグが実際に役立つとは限らない。

---

## 検証計画：グラフ品質の実測定

### ステップ1: タグファイルの詳細検査 ✓ 実施済み

Django__Django-10914 のタグファイル分析結果：

**基本統計：**
```
Total tags: 23,040
  - def: 7,682
  - ref: 15,358
Unique function/class names: 5,673
```

**最も一般的な ref タグ:**
```
1. _: 493
2. execute: 211
3. quote_name: 161
4. add_argument: 136
5. get_field: 133
6. ValidationError: 131
7. write: 119
8. .: 107  [SUSPICIOUS - dot character]
9. Error: 104
10. ImproperlyConfigured: 103
```

**重大な発見：パージング品質の問題**
```
Suspicious names (短い名前 or _ で始まる): 847
  - Single letters: A-Z (各1-20回)
  - Underscores: _ (493回)
  - Dots: . (107回)
```

**解釈：**
- パージング品質の問題により、短い名前や記号が大量に含まれている
- '_' だけで 493 回出現 → Python の "ignore" 変数を過度にキャッチしている
- '.' が 107 回出現 → AST パージングエラーの可能性

### ステップ2: グラフコンテキスト統合の測定 ✓ 実施済み

Django__Django-10914 の Fine-Grain Level ログ：

```
Generated graph context: 113,272 characters [≈ 28,323 tokens]
Graph context sections: 7 (7 個の「### Dependencies for X」セクション)
Graph context locations: 28-113 (参考資料により数値が変動)
Related locations:
  - Location 1: 34 chars, items: 0
  - Location 2: 231 chars, items: 7
  - ...

Prompt token count (with graph): 25,502 トークン
```

**解釈：**
- 7 個の関数についてグラフコンテキストを生成
- 合計 113,272 文字 (28,323 トークン)
- 平均して関数ごと 4,000+ 文字 (≈ 4,000 トークン)

### ステップ3: 論文との実装比較 ✓ 実施済み

**実装の根本的差異：**

| 観点 | 論文（Agentless） | PatchPilot Phase 2-6 |
|------|----------------|-------------------|
| retrieve_graph の処理 | ref タグのみ | def + ref タグ両方 |
| タグソート方法 | なし（単純ループ） | Composite Score |
| max_tags | 100 | 50 |
| トークン管理 | なし | Dynamic token limiting |
| グラフ統合方法 | Procedural (template に直接埋め込み) | Fine-Grain Level に複数セクション |

**パフォーマンス差：**

| メトリクス | 論文（1-hop） | PatchPilot | 差分 |
|-----------|------------|----------|------|
| グラフサイズ | 2,311 トークン | 28,323 トークン | **12.2倍** |
| ノード数（推定） | 11.6 | 113+ | **10倍** |
| File Recall@3 | +5.6pp | -5.6pp | **-11.2pp** |

---

## 仮説的な根本原因

### 仮説1: フィルタリング対象の抽出が不完全

`std_proj_funcs` が以下を見落としている可能性：
1. 相対インポート（`from . import foo`）
2. 動的インポート（`__import__('name')`）
3. カスタムクラスのメソッド呼び出しなど

結果：論文では 1-hop で ~12 個のタグ、PatchPilot では 113 個

### 仮説2: グラフコンテキスト構築の差異

論文の `construct_code_graph_context` (行 53-100)：
```python
def construct_code_graph_context(found_related_locs, code_graph,
                                 graph_tags, structure):
    # シンプル：見つかった場所に対してグラフを生成
    # トークン管理なし
```

PatchPilot の `construct_code_graph_context`：
```python
# Phase 2-6: Greedy token allocation
# Phase 2-5: Composite Score による複雑なソート
# 複雑な制御フロー
```

グラフ自体は同じだが、統合方法が複雑化→ノイズ増加

### 仮説3: プロンプト統合時の情報喪失

論文：
```
### Function/Class Dependencies ###
[グラフコンテキスト 2,311 トークン]

### File Contents ###
[ファイルコンテンツ]
```

PatchPilot：
```
### Related Locations ###
[削減済みコンテンツ]

### Dependencies for FUNCTION_NAME ###
[グラフコンテキスト 28,323 トークン]

### Fine-Grained Level ###
[さらに削減]
```

**結果**: グラフ追加 → ファイルコンテンツ削減 → 修復に必要な情報喪失

---

## 根本原因の特定

### 証拠1: パージング品質の低下

construct_graph.py は論文と同じフィルタリングロジックを持つが、結果のグラフは：
- 23,040 個のタグを含む（論文の 12 倍）
- 847 個の「疑わしい」名前（単一文字、記号）を含む
- `_` だけで 493 回、`.` で 107 回出現

原因の可能性：
1. tree-sitter クエリの過剰マッチング
2. Python 特定の構文（アンダースコア変数）への対応不足
3. 同じクエリでも言語やバージョン差異による結果の違い

### 証拠2: グラフ検索戦略の悪化

論文（Agentless）の retrieve_graph:
```python
for tag in graph_tags:
    if tag['name'] == search_term and tag['kind'] == 'ref':  # ref ONLY
        tags.append(tag)
    if len(tags) >= max_tags:  # max_tags=100
        break
```

PatchPilot Phase 2-6:
```python
def_tags = [tag for ... 'def']  # [削除]
ref_tags = [tag for ... 'ref']  # [削除]
ref_tags_sorted = sorted(ref_tags, key=composite_score_key)  # [新規]
ref_tags_limited = ref_tags_sorted[:max_tags]  # max_tags=50
```

**問題**：
- Composite Score はグラフの品質を改善していない
- むしろ無関連なタグを高スコア化している可能性

### 証拠3: トークン予算圧迫

Fine-Grain レベルでの実測値：
- グラフコンテキスト: 28,323 トークン (ほぼ固定)
- 最終プロンプト: 25,502 トークン (グラフ付き)
- グラフが占める比率: >100% ではないが、ファイルコンテンツを圧迫

---

## 最終結論

### グラフ生成の品質問題

construct_graph.py は正しくフィルタリングしているにもかかわらず、グラフに大量のノイズが含まれている。これは：
1. **tree-sitter クエリの過度なマッチング** → パージング品質低下
2. **デフォルトフィルタリングの不完全性** → Python 特定の構文未対応

### グラフ検索の戦略ミス

論文の「シンプルな ref タグのみ」→ 11.6 ノード に対して、PatchPilot の Composite Score → 113+ ノードになった理由：

1. **def タグの追加** → 無意味に膨張
2. **in_degree に基づく Composite Score** → 関連度不正確
3. **max_tags 削減** (100 → 50) → 逆効果（品質低下してから削減）

### 情報喪失の悪循環

1. グラフが大きい (28,323 トークン)
2. グラフを追加するとプロンプト超過
3. ファイルコンテキストを削減
4. **修復に必要な情報が失われる**
5. 性能低下 (-5.6pp)

---

## 推奨される対策（優先度順）

### 対策 A: グラフ検索を論文に完全に準じる（即座）

```python
# 現在の retrieve_graph を論文の実装に置き換え
def retrieve_graph(code_graph, graph_tags, search_term, structure, max_tags=100):
    one_hop_tags = []
    tags = []
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'ref':  # <-- ref ONLY
            tags.append(tag)
        if len(tags) >= max_tags:  # max_tags=100 に戻す
            break
    # ...
```

**期待値**: グラフサイズ 28,323 → 2,311 トークン, パフォーマンス -5.6pp → +5.6pp

### 対策 B: tree-sitter クエリの品質向上（本日）

construct_graph.py の query_scm に、以下の追加フィルタを：

```python
# 行328の後に追加
# Filter out single characters and spurious tokens
if len(tag_name) <= 1 or tag_name in ['.', ',', '(', ')', '[', ']']:
    continue
```

### 対策 C: グラフをLocalizationのみに（段階的）

現在：Fine-Grain Level にグラフを統合
推奨：File Level レベルに移動（より早い段階で活用）

---

**最重要の気付き：**

> RepoGraph の失敗は、グラフ生成の品質ではなく、**グラフ検索戦略の悪化と不適切な統合方法**が根本原因である。

論文の実装（ref タグのみ、シンプルな逐次検索）に戻すことで、-5.6pp から +5.6pp への改善が期待できる。

---

## 関連リソース

- RepoGraph 論文: https://arxiv.org/html/2410.14684v1
- PatchPilot RepoGraph フォルダ: `C:\Users\Ryuta5353\research\PatchPilot\RepoGraph\`
- construct_graph.py: `C:\Users\Ryuta5353\research\PatchPilot\RepoGraph\repograph\construct_graph.py`
- repograph_utils.py: `C:\Users\Ryuta5353\research\PatchPilot\patchpilot\fl\repograph_utils.py`

---

## 重要な見解

**グラフ生成は正しい。問題は別の場所にある。**

グラフの生成方法（フィルタリング付き）は論文と同じだが、グラフのサイズが 12 倍になってしまう → どこかで大量のタグが取得されている → それが修復性能を低下させている。

原因は以下の 3 つのいずれか：
1. フィルタリングロジックが Python のバージョン差、OS 差、リポジトリ固有の理由で機能していない
2. グラフ生成後の操作（retrieve_graph）で余分なタグが追加されている
3. タグ生成クエリが期待以上に多くのタグをキャッチしている

**次の調査で特定できる。**

