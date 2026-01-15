# ファイルレベルの詳細説明：Reproduce からの情報フロー

## 1. プロジェクト構造とは何か

### 1-1. 「プロジェクト全体の構造」＝ リポジトリ全体の Python ファイル・クラス・関数の一覧

```
structure = {
    "django/": {
        "db/": {
            "models.py": {
                "functions": [
                    {"name": "save", "start_line": 10, "end_line": 50, "text": [...]}
                ],
                "classes": [
                    {"name": "Model", "methods": [...], "start_line": 5, "end_line": 200}
                ],
                "text": ["# Django models"],
                "imports": [...],
                "import_interval": [0, 5]
            }
        },
        "core/": { ... },
        ...
    },
    "tests/": { ... }
}
```

**つまり:**
- `structure` = リポジトリの完全なファイル・フォルダ・クラス・関数の階層構造
- `show_project_structure()` がこれをテキスト形式に変換（ツリー表示）
- ファイルレベルでは「どのファイルが修正対象か」を判定するため、この全体構造が必要

---

## 2. Reproduce フェーズからの出力と情報フロー

### 2-1. Reproduce が出力する内容（issue_parsing_report_0.json）

```json
{
  "instance_id": "django__django-10914",
  "result": {
    "poc": {
      "poc_code": {
        "poc_code.py": "import os\nimport tempfile\n..."
      }
    },
    "oracle": {
      "execution_output": {
        "stdout": "Permissions of the temporary file: 0o600\n",
        "stderr": ""
      }
    },
    "coverage": "Name Stmts Miss Cover Missing\n...",
    "commit_info": {
      "bug_fixed": false,
      "changed_files": ["django/db/models.py", "django/core/base.py"]
    }
  }
}
```

**含まれる情報:**
- `poc_code`: バグを再現するテストコード
- `stdout`: テスト実行の成功時出力
- `stderr`: エラーメッセージ
- `coverage`: Coverage.py による実行トレース（どのファイルが実行されたか）
- `commit_info`: 修正コミットで変更されたファイルリスト

### 2-2. Localize.py が抽出するもの（行 80-110）

```python
if os.path.exists(reproduce_output_file):
    # 3種類の情報を抽出
    poc_code = result.get('poc', {}).get('poc_code', {}).values()
    std_out = result.get('oracle', {}).get('execution_output', {}).get('stdout')
    std_err = result.get('oracle', {}).get('execution_output', {}).get('stderr')
    coverage_dict = coverage_to_dict(coverage_raw)  # Coverage をパース
    commit_info = result.get('commit_info')          # コミット情報

    # reproduce_info = poc_code + stdout + stderr のテンプレート化
    reproduce_info = poc_info_prompt.format(
        poc_code=poc_code,
        stdout=std_out,
        stderr=std_err
    )
```

---

## 3. Step 0: LLM に検索キーワードを提案させる（行 147）

### 3-1. プロセス

```
入力:
  - 問題文（GitHub Issue）
  - PoC コード（バグ再現コード）
  - 実行結果（stdout + stderr）

LLM への質問:
  「問題を解決するために、どの関数・クラス・文字列を検索すべきですか？」

LLM の回答:
  Tool Call:
    - search_string("0o600")
    - search_string("NamedTemporaryFile")
    - search_func_def("save")
    - search_class_def("Model")

検索実行:
  search_string("NamedTemporaryFile")
    → grep でリポジトリ全体を検索
    → 見つかったファイル: ["python/tempfile.py", "django/db/models.py"]
    → "NamedTemporaryFile is found in: python/tempfile.py, django/db/models.py"

  search_func_def("save")
    → 関数定義を検索
    → "save function is defined in: django/db/models.py"

出力:
  search_str_with_file = {
      "NamedTemporaryFile": "python/tempfile.py, django/db/models.py",
      "save": "django/db/models.py"
  }
```

**つまり:**
- LLM が「何を検索すべき」かを自動判断
- その検索結果がファイルレベル探索へのヒント

---

## 4. Step 1: ファイルレベル探索（3つのパターン）

### 4-1. パターンA: Coverage データが十分ある場合（行 533-542）

```python
if coverage_dict and len(coverage_dict) > 2:
    # Coverage から実際に実行されたファイルを取得
    coverage_files = list(coverage_dict.keys())
    # 例: ["django/db/models.py", "django/core/base.py"]

    message = obtain_coverage_file_prompt.format(
        problem_statement=problem_statement,
        coverage_files=coverage_files,
        search_str_with_file_prompt=search_str_with_file,
    )
```

**プロンプト例:**
```
### GitHub Problem Description ###
Django の NamedTemporaryFile で作成されたファイルのパーミッションが
0o600 ではなく別の値が設定されている

### Coverage Files (実際に実行されたファイル) ###
django/db/models.py
django/core/base.py
django/__init__.py

### Search Results ###
NamedTemporaryFile is found in: python/tempfile.py, django/db/models.py

このファイルリストから、修正が必要なファイルを選択してください（最大5個）
```

**特徴:**
- 候補ファイルが限定される（実行ファイルのみ）
- トークン消費が少ない（全体構造不要）
- 精度が高い（実行トレースは客観的）

---

### 4-2. パターンB: Coverage がない or 不十分な場合（行 543-557）

```python
else:
    # リポジトリ全体の構造をテキスト化して提供
    message = obtain_relevant_files_prompt.format(
        problem_statement=problem_statement,
        structure=show_project_structure(structure),  # リポジトリ全体構造
        search_str_with_file_prompt=search_str_with_file,
    )

    # Commit 情報があれば、ヒントとして追加
    if coverage_info.get("commit_info"):
        change_files = coverage_info["commit_info"].get('changed_files', {})
        change_files_prompt = (
            "\nHint: We found the following files were changed in a related fix:\n" +
            str(change_files)
        )
        message = message + change_files_prompt
```

**プロンプト例:**
```
### GitHub Problem Description ###
Django の NamedTemporaryFile で作成されたファイルのパーミッションが
0o600 ではなく別の値が設定されている

### Repository Structure ###
django/
  db/
    models.py
    backend.py
  core/
    permissions.py
    base.py
  ...
  (全ファイル一覧、場合によっては数千行)

### Search Results ###
NamedTemporaryFile is found in: python/tempfile.py, django/db/models.py

### Hint from Commit ###
These files were changed in a related fix:
['django/db/models.py', 'django/core/base.py']

このリストから、修正が必要なファイルを選択してください（最大5個）
```

**特徴:**
- リポジトリ全体の構造を提供 = LLM が全体像を理解できる
- Coverage がなくても動作
- Commit 情報があれば強力なヒント
- **デメリット**: リポジトリが大きい場合、トークン爆発のリスク（数千～数万トークン）

---

## 5. Coverage とは何か

### 5-1. Coverage データの形式

```
Coverage Report:
Name              Stmts   Miss  Cover   Missing
-----------------------------------------------
django/db/models.py       250   40   84%   10-15, 25, 30-35
django/core/base.py       300   75   75%   10-20, 40-50
django/__init__.py         50    0  100%
-----------------------------------------------
TOTAL                     600  115   81%
```

**意味:**
- **Stmts**: ファイル内の実行可能ステートメント数
- **Miss**: 実行されなかったステートメント数
- **Cover**: カバレッジ率（%）
- **Missing**: 実行されなかった行番号

### 5-2. Coverage の利用方法

```python
# localize.py で Coverage をパース
coverage_dict = coverage_to_dict(coverage_raw)

# 結果:
coverage_dict = {
    "django/db/models.py": [10, 11, 12, 15, 25, 30, 31, 32, 33, 34, 35],  # Missing lines
    "django/core/base.py": [...],
    ...
}

# ファイルレベルでは「実行されたファイルリスト」として使用
coverage_files = list(coverage_dict.keys())
# → ["django/db/models.py", "django/core/base.py", ...]
```

**メリット:**
- 「実際にテスト実行時に読まれたファイル」が特定できる
- ノイズが少ない（テストに関係ないファイルは除外される）
- トークン効率が良い

---

## 6. 完全な情報フロー図

```
┌──────────────────────────────────────────────────────┐
│ REPRODUCE PHASE                                      │
│ (issue_parsing_report_0.json)                        │
├──────────────────────────────────────────────────────┤
│ PoC Code:         バグを再現するテストコード          │
│ Stdout:           テスト実行結果                      │
│ Stderr:           エラーメッセージ                   │
│ Coverage:         実行トレース（どのファイル実行）    │
│ Commit Info:      修正コミットで変更されたファイル   │
└────────────────┬─────────────────────────────────────┘
                 │
                 ↓ (localize.py 行 100, 147)
                 │
     ┌───────────────────────────────────┐
     │ reproduce_info テンプレート化:     │
     │ PoC + stdout + stderr を          │
     │ 構造化テンプレートに              │
     └───────────────────┬───────────────┘
                         │
                         ↓ (FL.search_in_problem_statement)
                         │
    ┌────────────────────────────────────────┐
    │ STEP 0: LLM が検索キーワード提案      │
    ├────────────────────────────────────────┤
    │ 入力:                                  │
    │  - 問題文                              │
    │  - PoC + stdout + stderr               │
    │                                        │
    │ LLM: 「何を検索すべき?」               │
    │                                        │
    │ Tool Calls:                            │
    │  - search_string("NamedTemporaryFile") │
    │  - search_func_def("save")             │
    │                                        │
    │ 出力:                                  │
    │  search_str_with_file = {              │
    │    "NamedTemporaryFile": [file paths]  │
    │    "save": [file paths]                │
    │  }                                     │
    └────────────────┬─────────────────────┘
                     │
                     ↓ (FL.localize, 行 533-557)
                     │
        ┌────────────────────────────────┐
        │ STEP 1: ファイルレベル探索    │
        ├────────────────────────────────┤
        │                                │
        │ Coverage 十分 ?               │
        │    ├─ YES ─→ obtain_coverage_file_prompt
        │    │           (Coverage ファイルリスト提供)
        │    │           (トークン少量)
        │    │
        │    └─ NO  ─→ obtain_relevant_files_prompt
        │                (リポジトリ全体構造提供)
        │                (Commit info があれば追加)
        │                (トークン大量)
        │
        │ どちらでも:
        │  + Problem Statement
        │  + Search Results (Step 0 の結果)
        │
        │ LLM: 修正ファイル候補を選択
        │
        │ 出力:
        │  ["django/db/models.py",
        │   "django/core/base.py"]
        │
        └────────────┬─────────────────┘
                     │
                     ↓ (FL._parse_model_return_lines)
                     │
        ┌────────────────────────────────┐
        │ LLM 出力パース＆投票           │
        ├────────────────────────────────┤
        │ Counter(model_found_files_raw) │
        │ → 最頻値ファイルを選択         │
        └────────────┬─────────────────┘
                     │
                     ↓ (correct_file_paths)
                     │
        ┌────────────────────────────────┐
        │ ファイルパス正規化             │
        ├────────────────────────────────┤
        │ リポジトリ実ファイル一覧と照合│
        │ 完全一致 or 部分一致を確認    │
        │                                │
        │ found_files = [実ファイルパス] │
        └────────────┬─────────────────┘
                     │
                     ↓ (localize.py 行 184+)
                     │
    ┌────────────────────────────────────┐
    │ STEP 2+: Related/Line Level        │
    │ (found_files を使用して詳細探索)   │
    └────────────────────────────────────┘
```

---

## 7. トークン消費の差異

### Coverage がある場合（効率的）
```
obtain_coverage_file_prompt:
  - Problem Statement:    ~500 tokens
  - Coverage Files:       ~100 tokens (実行ファイルのみ)
  - Search Results:       ~200 tokens
  ────────────────────────────────
  合計: ~800 tokens (小規模)
```

### Coverage がない場合（非効率）
```
obtain_relevant_files_prompt:
  - Problem Statement:    ~500 tokens
  - Repository Structure: ~5,000-50,000 tokens (リポジトリサイズに依存)
  - Search Results:       ~200 tokens
  - Commit Info:          ~100 tokens
  ────────────────────────────────
  合計: ~5,800-50,800 tokens (大規模!)
```

**つまり:**
- Coverage あり = 実行ファイルのみ = トークン効率良好
- Coverage なし = 全体構造必須 = トークン爆発リスク

---

## 8. まとめ

| 項目 | 説明 |
|------|------|
| **プロジェクト構造** | リポジトリの Python ファイル・クラス・関数の完全な階層構造 |
| **Reproduce 出力** | PoC + 実行結果 + 実行トレース + コミット情報 |
| **Step 0** | LLM が「どのキーワード・クラス・関数を検索すべき」かを決定 |
| **Step 1 (A)** | Coverage ファイルリスト + 検索結果 → LLM が修正ファイル選択 |
| **Step 1 (B)** | リポジトリ全体構造 + 検索結果 → LLM が修正ファイル選択 |
| **Coverage** | 実行時にトレースされたファイル一覧（トークン削減の鍵） |
| **Coverage なし** | 全体構造が必須 → トークン爆発のリスク |

**ファイルレベル探索の本質:**
1. Reproduce の出力（PoC + 実行結果）を与える
2. LLM が自動的に「何を検索すべき」かを決定する
3. その検索結果 + （Coverage or 全体構造）から修正ファイルを推定
4. パス正規化して確定

**RepoGraph との関係:**
- ファイルレベル: RepoGraph 未使用（構造情報のみ）
- Fine-Grain レベル: RepoGraph 統合（でもトークン超過で削減される矛盾）
