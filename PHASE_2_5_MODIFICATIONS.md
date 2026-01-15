# Phase 2-5 修正: 複数関数定義の曖昧性解決

**実施日時:** 2025-11-07
**目的:** グラフコンテキスト生成時に、同じ関数名が複数ファイルに存在する場合にファイルレベルで選定されたファイルの定義を優先する

## 修正概要

### 問題
- `find_target_file()` が複数のdef tagを見つけた場合、最初のものだけを返していた
- ファイルレベル localization で選定されたファイルの情報が失われていた
- 結果として、異なるファイルの関数定義がLLMに渡されて混乱が生じていた

### 解決方法
- `find_target_file()` に `preferred_files` パラメータを追加
- `construct_code_graph_context()` に `preferred_files` パラメータを追加
- ファイルレベル localization の結果 `pred_files` をグラフ構築フェーズに渡す

---

## 修正ファイルと変更内容

### File 1: patchpilot/fl/repograph_utils.py

#### 修正1: find_target_file() 関数定義（行12-53）

**変更前:**
```python
def find_target_file(search_term, graph_tags):
    """
    Find the file path where search_term is defined.
    Module-level function for use in both retrieve_graph() and construct_code_graph_context().

    Args:
        search_term: Function/class name to search for
        graph_tags: List of tag dictionaries

    Returns:
        str or None: rel_fname of the file where search_term is defined
    """
    for tag in graph_tags:
        if tag['name'] == search_term and tag['kind'] == 'def':
            return tag['rel_fname']
    return None
```

**変更後:**
```python
def find_target_file(search_term, graph_tags, preferred_files=None):
    """
    Find the file path where search_term is defined.
    Module-level function for use in both retrieve_graph() and construct_code_graph_context().

    MODIFICATION (段階Composite Score Phase 2-5): Accept preferred_files to disambiguate multiple definitions.
    When multiple definitions exist, prefer definitions from the predicted/selected files.

    Args:
        search_term: Function/class name to search for
        graph_tags: List of tag dictionaries
        preferred_files: (Optional) List of file paths where the search term should be preferred.
                        If multiple definitions exist, return the one from preferred_files first.

    Returns:
        str or None: rel_fname of the file where search_term is defined
    """
    # Collect all definitions
    all_defs = [tag for tag in graph_tags if tag['name'] == search_term and tag['kind'] == 'def']

    if not all_defs:
        return None

    # If only one definition exists, return it
    if len(all_defs) == 1:
        return all_defs[0]['rel_fname']

    # If multiple definitions exist and preferred_files is provided, prefer those
    if preferred_files:
        for def_tag in all_defs:
            if def_tag['rel_fname'] in preferred_files:
                print(f"[INFO find_target_file] {search_term} has {len(all_defs)} definitions, selected from preferred_files: {def_tag['rel_fname']}")
                return def_tag['rel_fname']
        # Log warning if no definition in preferred files
        print(f"[WARNING find_target_file] {search_term} has {len(all_defs)} definitions, none in preferred_files")
        print(f"  Definitions found in: {[tag['rel_fname'] for tag in all_defs]}")
        print(f"  Preferred files: {preferred_files}")

    # Default: return first definition (original behavior)
    if len(all_defs) > 1:
        print(f"[INFO find_target_file] {search_term} has {len(all_defs)} definitions, using first: {all_defs[0]['rel_fname']}")
    return all_defs[0]['rel_fname']
```

#### 修正2: construct_code_graph_context() 関数定義（行238-254）

**変更前:**
```python
def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure):
    """
    Construct code graph context from found related locations.

    Args:
        found_related_locs: List of related code locations
        code_graph: NetworkX graph object
        graph_tags: List of tag dictionaries
        structure: Repository structure dictionary

    Returns:
        String containing formatted graph context
    """
```

**変更後:**
```python
def construct_code_graph_context(found_related_locs, code_graph, graph_tags, structure, preferred_files=None):
    """
    Construct code graph context from found related locations.

    MODIFICATION (段階Composite Score Phase 2-5): Accept preferred_files to disambiguate multiple definitions.
    Pass preferred_files to find_target_file() to ensure definitions from selected files are prioritized.

    Args:
        found_related_locs: List of related code locations
        code_graph: NetworkX graph object
        graph_tags: List of tag dictionaries
        structure: Repository structure dictionary
        preferred_files: (Optional) List of file paths to prefer when multiple definitions exist

    Returns:
        String containing formatted graph context
    """
```

#### 修正3: クラス参照処理（行279）

**変更前:**
```python
target_file = find_target_file(loc, graph_tags)
```

**変更後:**
```python
target_file = find_target_file(loc, graph_tags, preferred_files=preferred_files)
```

#### 修正4: 関数参照処理（行292）

**変更前:**
```python
target_file = find_target_file(loc, graph_tags)
```

**変更後:**
```python
target_file = find_target_file(loc, graph_tags, preferred_files=preferred_files)
```

#### 修正5: 修飾名処理（行305）

**変更前:**
```python
target_file = find_target_file(loc, graph_tags)
```

**変更後:**
```python
target_file = find_target_file(loc, graph_tags, preferred_files=preferred_files)
```

---

### File 2: patchpilot/fl/localize.py

#### 修正6: fine_grain_line_level でのグラフコンテキスト生成（行264-269）

**変更前:**
```python
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure
)
```

**変更後:**
```python
# MODIFICATION (段階Composite Score Phase 2-5): Pass preferred_files to disambiguate multiple definitions
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure,
    preferred_files=pred_files
)
```

#### 修正7: review_level でのグラフコンテキスト生成（行415-420）

**変更前:**
```python
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure
)
```

**変更後:**
```python
# MODIFICATION (段階Composite Score Phase 2-5): Pass preferred_files to disambiguate multiple definitions
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure,
    preferred_files=pred_files
)
```

---

## ロールバック方法

このドキュメントの「変更前」コードに戻すことでロールバック可能です。

**クイックロールバックコマンド:**
```bash
# Git を使用している場合
git diff patchpilot/fl/repograph_utils.py
git diff patchpilot/fl/localize.py
git checkout patchpilot/fl/repograph_utils.py
git checkout patchpilot/fl/localize.py
```

---

## 効果検証

### 期待される動作

**複数定義環境:**
```
Django django/shortcuts.py と django/views.py に get_object_or_404() が定義

ログ出力:
[INFO find_target_file] get_object_or_404 has 2 definitions, selected from preferred_files: django/shortcuts.py
```

**単一定義環境:**
- ログ出力なし（元の処理と同じ）

**ワーニングケース:**
```
Preferred files に定義が見つからない場合:
[WARNING find_target_file] func_name has N definitions, none in preferred_files
  Definitions found in: [...]
  Preferred files: [...]
```

---

## テストチェックリスト

- [ ] 複数def環境インスタンスで INFO ログが出力される
- [ ] 単一def環境インスタンスで余分なログが出ない
- [ ] グラフコンテキストのサイズが適切（token数の大幅な増減なし）
- [ ] LLM出力品質が向上したか検証

---

**作成日:** 2025-11-07
**修正者:** Claude Code
**ステータス:** 完了
