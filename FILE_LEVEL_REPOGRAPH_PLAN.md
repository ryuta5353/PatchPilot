# File-Level Localization における RepoGraph 活用計画書

## 1. 目的 (Objective)

PatchPilot の `File-level Localization` フェーズにおいて、既存のキーワード検索（Search Tools）では発見できない「真の原因ファイル」を、RepoGraph（構造情報）と PoC Coverage（実行情報）を用いて特定・追加する。

---

## 2. 背景調査結果

### 2.1 Coverage 可用性

| 指標 | 値 | 備考 |
|------|-----|------|
| Coverage が存在するインスタンス | 7/23 (30.4%) | |
| Coverage が存在しないインスタンス | 16/23 (69.6%) | |
| Coverage 存在時の Gold ファイル含有率 | 6/7 (85.7%) | Coverage があれば高確率で Gold を含む |

**Coverage 不在の根本原因**: `reproduce.py` で `exec_match_wrong_behavior=True` の場合のみ Coverage を収集するため。

### 2.2 Search vs Coverage: Gold ファイル発見率比較

**ファイルレベル（23インスタンス、23 Gold files）**

| Gold の発見場所 | ファイル数 | 割合 |
|----------------|----------|------|
| Search ONLY | 6 | 26.1% |
| Coverage ONLY | 3 | 13.0% |
| BOTH (Search + Coverage) | 3 | 13.0% |
| **NEITHER（どちらにもない）** | **11** | **47.8%** |

**インスタンスレベル（少なくとも1つの Gold が発見されたか）**

| 指標 | インスタンス数 | 割合 |
|------|--------------|------|
| Search で発見（BOTH含む） | 9/23 | 39.1% |
| Coverage で発見（BOTH含む） | 6/23 | 26.1% |
| Search OR Coverage | 12/23 | 52.2% |
| **NEITHER（全 Gold 未発見）** | **11/23** | **47.8%** |

**重要な発見**:
- Search の方が Coverage より Gold 発見率が高い（39.1% vs 26.1%）
- しかし、約半数（47.8%）は Search でも Coverage でも発見できない
- **RepoGraph による候補拡張が必要な理由**: Search + Coverage を組み合わせても 47.8% は発見できない

**詳細内訳**:

| Instance ID | Coverage | Search結果数 | Gold発見場所 | Baseline正解 |
|-------------|----------|-------------|-------------|--------------|
| astropy__astropy-12907 | なし | 2 | SEARCH | YES |
| astropy__astropy-14182 | なし | 2 | SEARCH | YES |
| django__django-10914 | あり | 0 | NEITHER | YES |
| django__django-11999 | あり | 0 | COVERAGE | **NO** |
| django__django-13401 | あり | 0 | COVERAGE | YES |
| django__django-13933 | あり | 1 | BOTH | YES |
| django__django-14534 | あり | 1 | BOTH | YES |
| django__django-15695 | なし | 0 | NEITHER | N/A |
| matplotlib__matplotlib-23314 | なし | 0 | NEITHER | **NO** |
| matplotlib__matplotlib-23476 | なし | 0 | NEITHER | YES |
| matplotlib__matplotlib-24970 | なし | 1 | NEITHER | YES |
| psf__requests-2317 | なし | 0 | NEITHER | YES |
| pydata__xarray-4094 | あり | 2 | BOTH | YES |
| pylint-dev__pylint-7080 | なし | 0 | NEITHER | **NO** |
| pytest-dev__pytest-7432 | なし | 4 | SEARCH | YES |
| pytest-dev__pytest-7490 | なし | 0 | NEITHER | YES |
| scikit-learn__scikit-learn-10297 | なし | 1 | SEARCH | YES |
| scikit-learn__scikit-learn-13496 | なし | 3 | SEARCH | YES |
| scikit-learn__scikit-learn-14983 | なし | 1 | SEARCH | YES |
| sphinx-doc__sphinx-11445 | なし | 0 | NEITHER | YES |
| sphinx-doc__sphinx-8595 | なし | 0 | NEITHER | YES |
| sympy__sympy-13031 | なし | 0 | NEITHER | **NO** |
| sympy__sympy-20590 | あり | 3 | COVERAGE | YES |

**Baseline File-Level 精度**: 18/22 (81.8%) ※ 1件(django-15695)は評価対象外

**失敗ケースの分析**:
- **django__django-11999**: Coverage に Gold があるが、LLM が選択しなかった
- **matplotlib__matplotlib-23314**: Search も Coverage もなく、Repository Structure からの推測が失敗
- **pylint-dev__pylint-7080**: Search も Coverage もなく、推測が失敗
- **sympy__sympy-13031**: Search も Coverage もなく、推測が失敗

### 2.4 Baseline 評価結果の詳細分析

#### 2.4.1 File Level vs Line Level 精度

| レベル | 正解数/総数 | 精度 |
|--------|------------|------|
| **File Level** | 18/22 | 81.8% |
| **Line Level** | 9/22 | 40.9% |

**重要な発見**: File Level から Line Level への精度低下が約41ポイントと大きい。

#### 2.4.2 Gold ファイルのランク分布（Top-N 分析）

| ランク | インスタンス数 | 割合 |
|--------|--------------|------|
| **Top-1** | 13 | 59.1% |
| Top-2 | 4 | 18.2% |
| Top-3 | 1 | 4.5% |
| **NOT FOUND** | 4 | 18.2% |

**累積精度**:
- Top-1: 59.1%
- Top-3: 81.8%

**重要な発見**: Top-1 と Top-3 の間に約23ポイントの差がある。これは、Gold ファイルは候補に含まれているが、ランキングが低いケースが多いことを示す。

#### 2.4.3 Step 1.5 の価値に関する考察

**候補拡張 vs ランキング改善**:

現状の分析から、Step 1.5 には2つの価値がある：

1. **候補拡張**: Search + Coverage で発見できない 47.8% のファイルを RepoGraph で発見
2. **ランキング改善**: Top-1 を 59.1% から向上させることで、後続の Line Level 精度を改善

特に、File Level → Line Level で精度が半減している問題に対して、Top-1 精度の改善は有効な対策となる可能性がある。Gold ファイルが Top-1 にランクされれば、LLM は関連する行をより正確に特定できる。

#### 2.4.4 インスタンス別評価結果

| Instance ID | File Level | Line Level | Gold Rank |
|-------------|------------|------------|-----------|
| astropy__astropy-12907 | YES | YES | 1 |
| astropy__astropy-14182 | YES | NO | 2 |
| django__django-10914 | YES | YES | 1 |
| django__django-11999 | **NO** | NO | NOT FOUND |
| django__django-13401 | YES | NO | 2 |
| django__django-13933 | YES | NO | 1 |
| django__django-14534 | YES | NO | 2 |
| matplotlib__matplotlib-23314 | **NO** | NO | NOT FOUND |
| matplotlib__matplotlib-23476 | YES | NO | 3 |
| matplotlib__matplotlib-24970 | YES | YES | 1 |
| psf__requests-2317 | YES | NO | 1 |
| pydata__xarray-4094 | YES | YES | 1 |
| pylint-dev__pylint-7080 | **NO** | NO | NOT FOUND |
| pytest-dev__pytest-7432 | YES | YES | 1 |
| pytest-dev__pytest-7490 | YES | NO | 1 |
| scikit-learn__scikit-learn-10297 | YES | YES | 1 |
| scikit-learn__scikit-learn-13496 | YES | YES | 1 |
| scikit-learn__scikit-learn-14983 | YES | NO | 2 |
| sphinx-doc__sphinx-11445 | YES | NO | 1 |
| sphinx-doc__sphinx-8595 | YES | YES | 1 |
| sympy__sympy-13031 | **NO** | NO | NOT FOUND |
| sympy__sympy-20590 | YES | YES | 1 |

**パターン分析**:
- File Level 成功 + Line Level 成功: 9 インスタンス（ほぼ全て Gold Rank = 1）
- File Level 成功 + Line Level 失敗: 9 インスタンス（Gold Rank が 2-3 のケースが多い）
- File Level 失敗: 4 インスタンス（全て NEITHER カテゴリ）

### 2.5 Localization 処理フローの詳細

PatchPilot の Localization は3段階で構成される：

```
File Level (Top-N files)
    ↓
Related Level (各ファイル内の関連クラス/関数を特定)
    ↓
Fine-grain Level (具体的な行番号を特定)
```

#### 2.5.1 File Level

**メソッド**: `LLMFL.localize()` (`FL.py:516-611`)

**処理**:
1. Coverage の有無で分岐
   - Coverage あり → `obtain_coverage_file_prompt`（Coverage ファイルリストから選択）
   - Coverage なし → `obtain_relevant_files_prompt`（Repository Structure 全体を提供）
2. LLM が Top-5 ファイルを選択

**出力**: `found_files` = ["file1.py", "file2.py", "file3.py"]

#### 2.5.2 Related Level

**メソッド**: `LLMFL.localize_function_from_compressed_files()` (`FL.py:613-729`)

**処理**:
1. 各 Top-N ファイルを「スケルトン」に圧縮（`get_skeleton()` 使用）
   - クラス定義、関数シグネチャ、docstring のみを残す
   - 関数本体のコードは省略
2. LLM に圧縮コードを提示
3. LLM が関連するクラス/関数/変数を特定

**出力**: `found_related_locs` = 各ファイルに対する関連クラス/関数のリスト

#### 2.5.3 Fine-grain Level

**メソッド**: `LLMFL.localize_line_from_coarse_function_locs()` (`FL.py:822-958`)

**処理**:
1. Related Level で特定した関数/クラスの**実際のコード**を抽出
2. `context_window` 行分の前後コンテキストを含める
3. 行番号付きでフォーマット
4. LLM が具体的な行番号を特定

**出力**: `found_edit_locs` = 各ファイルの具体的な行番号

### 2.6 Line Level 失敗インスタンスの詳細分析

File Level は成功したが Line Level で失敗した9インスタンスを詳細に分析した。

#### 2.6.1 失敗パターン分類

| パターン | 件数 | 説明 |
|----------|------|------|
| **Close Miss（惜しい）** | 3件 | Gold Line から 2〜9 行の距離 |
| **Wrong Location（別の場所）** | 3件 | 同じファイル内で全く別の関数/クラス |
| **Far Before（大幅に前）** | 2件 | Gold より数百〜千行前を参照 |
| **No Output（出力なし）** | 1件 | Fine-grain Level が行番号を出力しない |

#### 2.6.2 Close Miss（惜しい）- 3件

| Instance | Gold Lines | Found Lines | 距離 | 原因 |
|----------|-----------|-------------|------|------|
| pydata__xarray-4094 | 1964 | 1901, 1955 | **9行** | `to_unstacked_dataset` 関数内だが、修正箇所ではなく関数の入り口付近を指定 |
| matplotlib__matplotlib-24970 | 718-728 | 730-732 | **2行** | `Colormap.__call__` を指定したが、実際は直前の別の場所が正解 |
| scikit-learn__scikit-learn-13496 | 123-195 | 167-339 | **2行** | `IsolationForest` クラス内だが、`__init__` の引数定義部分ではなく別の場所 |

**特徴**: 正しい関数/クラスを特定しているが、**関数内の具体的な修正箇所**を外している

#### 2.6.3 Wrong Location（別の場所）- 3件

| Instance | Gold Lines | Found Lines | 距離 | 原因 |
|----------|-----------|-------------|------|------|
| astropy__astropy-12907 | 245 | 27-311 (245除く) | 45行 | `_cstack` 関数（line 245）ではなく `separability_matrix`, `_separable` を指定 |
| matplotlib__matplotlib-23476 | 3026-3028 | 2911, 3499 | 115行 | `FigureBase.__setstate__`（line 2911）を指定したが、正解は `Figure.__setstate__`（line 3026） |
| sphinx-doc__sphinx-8595 | 1077 | 634-1110 | 23行 | `Documenter` クラスの広範囲を指定、正解の `ModuleDocumenter.get_object_members` 内の特定行を外す |

**特徴**: **Related Level で間違った関数を主要候補として選択**している

**astropy-12907 の詳細**:
- 問題文に「separability_matrix」が明示されているため、その関数を重視
- しかし実際の修正箇所は `_cstack` 関数内（`separability_matrix` から呼ばれる）
- **RepoGraph の Callee 情報**があれば、`separability_matrix` → `_cstack` の呼び出し関係を把握できた可能性

**matplotlib-23476 の詳細**:
- `FigureBase.__setstate__` と `Figure.__setstate__` が両方存在
- Related Level が親クラス `FigureBase` を選択したが、正解は子クラス `Figure`
- **継承関係の情報**があれば改善できた可能性

#### 2.6.4 Far Before（大幅に前）- 2件

| Instance | Gold Lines | Found Lines | 距離 | 原因 |
|----------|-----------|-------------|------|------|
| django__django-13933 | 1287-1291 | 287-809 | **478行** | `ModelChoiceField` クラスの定義部分（287）を指定、実際の修正箇所（1287）はクラス内メソッド |
| scikit-learn__scikit-learn-14983 | 1166-2165 | 105-269 | **897行** | `RepeatedKFold`, `RepeatedStratifiedKFold` のクラス定義を指定、実際は `__repr__` メソッド内 |

**特徴**: **クラス定義行**のみを出力し、**クラス内の特定メソッド/行**が正解の場合に失敗

**django-13933 の詳細**:
```
Related Level 出力:
  class: ModelChoiceField
  function: ModelChoiceField.clean
  function: ModelChoiceField.to_python
  function: ModelChoiceField.validate

Fine-grain Level 出力:
  class: ModelChoiceField
  line: 287  ← クラス定義行のみ

Gold:
  lines 1287-1291  ← クラス内の default_error_messages 定義
```

#### 2.6.5 No Output（出力なし）- 1件

| Instance | Gold Lines | Found Lines | 原因 |
|----------|-----------|-------------|------|
| sympy__sympy-20590 | 20-24 | (空) | Related Level で `class: Printable` を特定しているが、Fine-grain Level で行番号を出力していない |

**特徴**: Gold File が Rank 2 で、**Top-1 ではないファイルに対する行特定が不安定**

#### 2.6.6 失敗の根本原因まとめ

| 根本原因 | 件数 | 改善策 |
|----------|------|--------|
| **Related Level で間違った関数を選択** | 4件 | RepoGraph で依存関係を提供し、正しい関数を特定支援 |
| **正しい関数だが行番号がずれ** | 3件 | より詳細なコンテキスト提供、複数候補の出力 |
| **Gold File が Top-1 でない** | 1件 | File Level のランキング改善 |
| **クラス定義行のみ出力** | 2件 | Fine-grain Level のプロンプト改善（メソッド内の具体的な行を要求） |

### 2.7 File Level 失敗インスタンスの詳細分析

File Level で失敗した4インスタンスを詳細に分析した。

#### 2.7.1 失敗インスタンス一覧

| Instance | Gold File | Found Files | Gold 発見場所 | 失敗原因 |
|----------|-----------|-------------|--------------|---------|
| django__django-11999 | `django/db/models/fields/__init__.py` | `django/db/models/base.py` | COVERAGE | Coverage にあるが LLM が選択せず |
| matplotlib__matplotlib-23314 | `lib/mpl_toolkits/mplot3d/axes3d.py` | 2D axes 関連ファイル | NEITHER | 別パッケージのファイル |
| pylint-dev__pylint-7080 | `pylint/lint/expand_modules.py` | 設定パース系ファイル | NEITHER | 呼び出し先のファイル |
| sympy__sympy-13031 | `sympy/matrices/sparse.py` | `sympy/matrices/matrices.py`, `dense.py` | NEITHER | 同じモジュール内の別ファイル |

#### 2.7.2 詳細分析

**django__django-11999**:
```
Problem: Cannot override get_FOO_display() in Django 2.2+

Gold File: django/db/models/fields/__init__.py
Found Files: django/db/models/base.py

原因:
- Coverage に Gold File が含まれていた
- しかし LLM が Model 基底クラス (base.py) を選択
- Field クラスの contribute_to_class メソッドが実際の修正箇所

RepoGraph 改善可能性:
- base.py → fields/__init__.py への依存関係（Field を import）を辿れば発見可能
```

**matplotlib__matplotlib-23314**:
```
Problem: 3D projection の subplot で set_visible(False) が効かない

Gold File: lib/mpl_toolkits/mplot3d/axes3d.py
Found Files: lib/matplotlib/axes/_axes.py, artist.py, figure.py

原因:
- 3D 関連コードは別パッケージ (mpl_toolkits) にある
- キーワード検索では 2D 関連ファイルがヒット
- Repository Structure からの推測も失敗

RepoGraph 改善可能性:
- Axes3D は Axes を継承しているため、継承関係を辿れば発見可能
- ただし別パッケージにあるため、RepoGraph のカバー範囲による
```

**pylint-dev__pylint-7080**:
```
Problem: --recursive=y オプション使用時に ignore-paths 設定が無視される

Gold File: pylint/lint/expand_modules.py
Found Files: config_file_parser.py, pylinter.py, base_options.py

原因:
- 問題はファイル展開時の ignore パターンチェック漏れ
- キーワード "recursive", "ignore-paths" では設定パース系がヒット

RepoGraph 改善可能性:
- pylinter.py → expand_modules.py への呼び出し関係を辿れば発見可能
- _discover_files 関数から expand_modules が呼ばれる
```

**sympy__sympy-13031**:
```
Problem: Matrix hstack/vstack の問題

Gold File: sympy/matrices/sparse.py
Found Files: matrices.py, dense.py, densearith.py

原因:
- sparse.py と dense.py は同じモジュール内
- LLM が dense.py を選択（より一般的なファイル名）

RepoGraph 改善可能性:
- matrices.py から sparse.py への参照を辿れば発見可能
```

#### 2.7.3 File Level 失敗の根本原因まとめ

| 根本原因 | 件数 | 改善策 |
|----------|------|--------|
| **Coverage にあるが LLM が別ファイルを選択** | 1件 | Coverage ファイルの優先度を上げる |
| **別パッケージにある** | 1件 | 継承関係の情報を活用 |
| **呼び出し先のファイル** | 1件 | RepoGraph の Callee 情報を活用 |
| **同モジュール内の別ファイル** | 1件 | モジュール内の参照関係を活用 |

### 2.3 Django インスタンスの依存関係統計

| 指標 | 値 |
|------|-----|
| Avg refs per def name | 2.62 |
| Avg callees per file | 15.2 |
| Avg callers per file | 17.4 |
| 典型的な 3 seed files からの 1-hop 展開 | 72 候補 |
| Hub 候補（2+ seeds を呼び出す） | 3-41 files |

---

## 3. 処理フロー (Process Flow)

この処理は、`search_in_problem_statement`（検索実行）の後、`localize`（LLM によるファイル選択）の前に実行される **"Step 1.5: Candidate Expansion"** である。

```
【現在のフロー】
Step 0: LLM が検索キーワード提案
Step 1: 検索実行 → seed_files 取得
Step 2: LLM がファイル選択

【提案するフロー】
Step 0: LLM が検索キーワード提案
Step 1: 検索実行 → seed_files 取得
Step 1.5: Candidate Expansion（RepoGraph + Coverage）← NEW
Step 2: LLM がファイル選択（拡張された候補から）
```

---

## 4. 入力データ

### 4.1 search_str_with_file（検索結果）

```python
# Step 0-1 の検索結果
search_str_with_file = {
    "NamedTemporaryFile": "django/core/files/uploadedfile.py django/core/files/storage.py",
    "0o600": "django/core/files/uploadedfile.py",
    "file_permissions_mode": "django/core/files/storage.py"
}
```

### 4.2 graph_tags（RepoGraph タグ情報）

```python
# tags.json からロード
graph_tags = [
    {"rel_fname": "django/core/files/uploadedfile.py", "name": "TemporaryUploadedFile", "kind": "def", "line": 10},
    {"rel_fname": "django/core/files/uploadedfile.py", "name": "save", "kind": "ref", "line": 25},
    ...
]
```

### 4.3 coverage_dict（PoC Coverage）

```python
# reproduce の結果から取得（存在しない場合は None）
coverage_dict = {
    "django/core/files/uploadedfile.py": [10, 15, 20, ...],  # 実行された行
    "django/core/files/storage.py": [5, 10, 15, ...],
    ...
}
```

---

## 5. アルゴリズム設計

### 5.1 Phase 1: キーワード限定のタグ情報取得

#### 5.1.1 目的

seed_files 内の**すべての関数/クラス**ではなく、**検索キーワードを含む関数/クラスのみ**を対象にする。

#### 5.1.2 判定基準

関数/クラスが対象となる条件：
- **関数名/クラス名**に検索キーワードが含まれる
- **関数本体のコード**に検索キーワードが含まれる

#### 5.1.3 実装方法: 後処理でマッチング（方法A）

検索結果（`search_str_with_file`）を受け取った後、各ファイル内でキーワードを含む関数/クラスを特定する。

```python
def get_matching_defs_in_file(
    file_path: str,
    keywords: list[str],
    structure
) -> list[str]:
    """
    ファイル内で、キーワードを含む関数/クラス名を返す

    Args:
        file_path: 対象ファイルパス
        keywords: 検索キーワードのリスト
        structure: リポジトリ構造

    Returns:
        マッチした関数/クラス名のリスト
    """
    matching_defs = []
    files, classes, functions = get_full_file_paths_and_classes_and_functions(structure)

    # 該当ファイルの関数を取得
    for func in functions:
        if func["file"] == file_path:
            func_name = func["name"]
            func_code = func.get("text", [])  # 関数本体のコード

            for keyword in keywords:
                keyword_lower = keyword.lower()
                # 関数名にキーワードが含まれるか
                if keyword_lower in func_name.lower():
                    matching_defs.append(func_name)
                    break
                # 関数本体にキーワードが含まれるか
                if any(keyword_lower in line.lower() for line in func_code):
                    matching_defs.append(func_name)
                    break

    # 該当ファイルのクラスを取得
    for cls in classes:
        if cls["file"] == file_path:
            cls_name = cls["name"]
            cls_code = cls.get("text", [])  # クラス本体のコード

            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in cls_name.lower():
                    matching_defs.append(cls_name)
                    break
                if any(keyword_lower in line.lower() for line in cls_code):
                    matching_defs.append(cls_name)
                    break

    return matching_defs
```

#### 5.1.4 方法Aを選択した理由

| 方法 | 説明 | メリット | デメリット |
|------|------|----------|------------|
| **方法A: 後処理でマッチング** | 検索後にファイル内の関数を走査 | 既存コード変更なし、実装が簡単 | 二重走査のオーバーヘッド |
| 方法B: search_tool.py 拡張 | 検索時に関数情報も返す | 効率的 | 既存APIの変更が必要 |

**結論**: 方法A（後処理でマッチング）を採用

### 5.2 Phase 2: タグ情報からの依存関係取得

（次回以降に詳細化）

### 5.3 Phase 3: スコアリング

（次回以降に詳細化）

---

## 6. 実装場所

### 6.1 新規ファイル/関数

| ファイル | 関数 | 説明 |
|---------|------|------|
| `patchpilot/fl/repograph_utils.py` | `get_matching_defs_in_file()` | キーワード限定の関数/クラス取得 |
| `patchpilot/fl/repograph_utils.py` | `expand_candidates_with_repograph()` | Step 1.5 メイン処理 |

### 6.2 修正ファイル

| ファイル | 修正内容 |
|---------|---------|
| `patchpilot/fl/localize.py` | Step 1.5 の呼び出しを追加（行 147-150 付近） |

---

## 7. 検討事項・未決定事項

### 7.1 キーワードマッチングの詳細

- [ ] 大文字小文字の扱い（現在: case-insensitive）
- [ ] 部分一致 vs 完全一致（現在: 部分一致）
- [ ] 複合キーワードの扱い（例: "NamedTemporaryFile" で "Temporary" もマッチさせるか）

### 7.2 structure からの情報取得

- [ ] `func["text"]` が利用可能か確認する必要あり
- [ ] クラスのメソッドはどう扱われているか確認

### 7.3 Phase 2-3 の設計

- [ ] Caller vs Callee の両方向探索の詳細
- [ ] Hub Bonus / Coverage Bonus の具体的な値
- [ ] 候補数の上限

---

## 8. 変更履歴

| 日付 | 内容 |
|------|------|
| 2025-11-27 | 初版作成。背景調査結果、Phase 1 の設計を記載 |
| 2025-11-28 | Section 2.4 追加。Baseline 評価結果の詳細分析（File Level 81.8%, Line Level 40.9%）、Top-N ランク分布、インスタンス別評価結果表を追加 |
| 2025-11-28 | Section 2.5 追加。Localization 処理フローの詳細（File/Related/Fine-grain Level の3段階処理）を記載 |
| 2025-11-28 | Section 2.6 追加。Line Level 失敗9インスタンスの詳細分析（Close Miss 3件、Wrong Location 3件、Far Before 2件、No Output 1件）を記載 |
| 2025-11-28 | Section 2.7 追加。File Level 失敗4インスタンスの詳細分析と RepoGraph による改善可能性を記載 |

