# Reproduce から Localization への情報フロー：詳細分析

**作成日**: 2025-11-11
**重要度**: ★★★★★
**テーマ**: RepoGraph 統合の改善機会

---

## ユーザーの指摘

> reproduce ってlocalizationにありますよね。そこからlocalizationに渡される情報が知りたい。
> そこで候補ファイルなどがあるなら、そこにrepographを使えばいいと思った。

---

## 1. Reproduce の出力

### ファイル位置
```
results/reproduce/{instance_id}/issue_parsing_report_0.json
```

### 出力構造（実測例）
```json
{
  "instance_id": "astropy__astropy-12907",
  "result": {
    "poc": {
      "is_complete": true,
      "poc_code": {
        "poc_code.py": "[証拠コード]"
      }
    },
    "oracle": {
      "oracle_description": "...",
      "expected_behavior": "...",
      "wrong_behavior": "...",
      "execution_output": {
        "stdout": "...",
        "stderr": "..."
      },
      "exec_match_wrong_behavior": true|false,
      "if_match_reasoning": "..."
    },
    "coverage": "Name  Stmts Miss Cover Missing\n...",
    "commit_info": {
      "changed_files": ["file1.py", "file2.py", ...],
      "bug_fixed": true|false,
      ...
    }
  }
}
```

### 詳細な内容

| フィールド | 内容 | 用途 |
|----------|------|------|
| `poc.poc_code` | 証拠コード（Python） | バグ再現のテストコード |
| `oracle.execution_output` | stdout, stderr | 実行結果、エラーメッセージ |
| `oracle.exec_match_wrong_behavior` | ブール値 | バグが再現できたかどうか |
| `coverage` | カバレッジレポート（テキスト） | PoC が実行したコード範囲 |
| `commit_info.changed_files` | 修正で変更されたファイル | **← ここが重要** |
| `commit_info.bug_fixed` | ブール値 | 修正がバグを解決できたか |

---

## 2. Localization への渡され方

### ファイル位置
`patchpilot/fl/localize.py` 行 75-113

### コード流れ
```python
# Step 1: Reproduce 出力から情報抽出
coverage_info = {}
reproduce_info = ""
if args.reproduce_folder:
    reproduce_output_file = os.path.join(args.reproduce_folder, instance_id, "issue_parsing_report_0.json")

    reproduce_info_dict = json.load(open(reproduce_output_file))
    repro_result_dict = reproduce_info_dict.get('result', {})
    oracle_dict = repro_result_dict.get('oracle', {})

    # PoC コードと実行出力を抽出
    poc_code = repro_result_dict.get('poc', {}).get('poc_code', {}).values()
    std_out = oracle_dict.get('execution_output', {}).get('stdout', {})
    std_err = oracle_dict.get('execution_output', {}).get('stderr', {})

    # カバレッジ情報を抽出
    coverage_raw = repro_result_dict.get('coverage', "")
    coverage_dict = coverage_to_dict(coverage_raw)  # テキストをパース

    # Commit 情報を抽出
    commit_info = repro_result_dict.get('commit_info', {})

    # PoC 情報をテンプレート化
    reproduce_info = poc_info_prompt.format(
        poc_code=poc_code,
        stdout=std_out,
        stderr=std_err
    )

    # Coverage 情報が十分ならば使用
    coverage_info = {
        "coverage_dict": coverage_dict,    # カバレッジデータ
        "commit_info": commit_info,        # 変更ファイル情報
    }

# Step 2: Localization に渡す
found_files = fl.localize(
    ...
    search_res_files=search_str_with_file,  # 問題説明から検索した結果
    coverage_info=coverage_info              # Reproduce から抽出した情報
)
```

---

## 3. File Level での使用

### ファイル位置
`patchpilot/fl/FL.py` 行 516-611（localize メソッド）

### 使用方法

#### Case A: Coverage情報がある場合（≥3ファイル）

```python
if coverage_info and coverage_info.get("coverage_dict") and len(coverage_dict) > 2:
    # Coverage ファイルのみを使用
    message = self.obtain_coverage_file_prompt.format(
        problem_statement=problem_statement,
        coverage_files=[list of coverage files],
        search_str_with_file_prompt=search_str_with_file_prompt,
    )
```

**プロンプト**:
```
Please look through the following GitHub problem description and a list of coverage files...

### GitHub Problem Description ###
{problem_statement}

### Coverage files ###
[カバレッジで実行されたファイルのリスト]

{search_str_with_file_prompt}

Please only provide the full path and return at most 5 files...
```

**→ ここで RepoGraph を使うチャンス！**

#### Case B: Coverage情報がない場合

```python
else:
    # プロジェクト全体の構造を使用
    message = self.obtain_relevant_files_prompt.format(
        problem_statement=problem_statement,
        structure=show_project_structure(self.structure),  # 全リポジトリ構造
        search_str_with_file_prompt=search_str_with_file_prompt,
    )
```

**プロンプト**:
```
Please look through the following GitHub problem description and Repository structure...

### GitHub Problem Description ###
{problem_statement}

### Repository Structure ###
[全リポジトリの構造（数千行以上）]

{search_str_with_file_prompt}

Please only provide the full path and return at most 5 files...
```

#### Case C: Commit情報を追加

```python
if coverage_info and coverage_info.get("commit_info"):
    change_files = coverage_info["commit_info"].get('changed_files', {})
    bug_fixed = coverage_info["commit_info"].get('bug_fixed', False)

    if change_files and bug_fixed:
        # プロンプトに「これらファイルに注意してください」というヒント追加
        change_files_prompt = (
            "\nPlease pay attention here: We have found the commit that may be "
            "related to this issue, and found the change files at that time.\n"
            "These files may have caused this issue, so please pay more attention "
            "to these files:\n" + str(change_files)
        )
        message = message + change_files_prompt
```

---

## 4. 現在の実装の問題点

### 問題1: Coverage 情報の活用が限定的

```
Coverage files = [カバレッジで実行されたファイル]

現在: LLM にカバレッジファイル名リストを渡すだけ
問題: LLM が実際にどのファイルを選ぶべきか判断できない
       ファイル名だけでは不十分
```

### 問題2: RepoGraph が活用されていない

```
利用可能な情報:
  1. Coverage files: カバレッジで実行されたファイル
  2. Commit changed files: 修正で変更されたファイル

現在: これらを「ファイル名のリスト」としてのみ渡す

改善機会:
  → RepoGraph を使って、カバレッジ/変更ファイルの
    「依存関係」を LLM に提供できる
```

### 問題3: 2つの異なる戦略

```
Coverage あり: カバレッジファイル（狭い範囲）を提供
Coverage なし: 全リポジトリ構造（広い範囲）を提供

問題: 情報の質と量が大きく異なる
      Coverage あり: 直接的だが限定的
      Coverage なし: 包括的だがノイズ多い
```

---

## 5. ユーザーの提案の妥当性

### 提案内容
> 候補ファイル（Coverage/Changed files）がるなら、そこに RepoGraph を使えばいい

### 検証

| 提案 | 妥当性 | 理由 |
|-----|--------|------|
| **Coverage files に RepoGraph 使用** | ✓ 高 | ファイル数少ない → グラフサイズ管理可能 |
| **Changed files に RepoGraph 使用** | ✓ 高 | 修正ファイルの依存関係は重要 |
| **全リポジトリには使わない** | ✓ 高 | グラフサイズが爆発的に大きくなる |

---

## 6. 改善案：File Level での RepoGraph 統合

### 案 A: Coverage ファイルの依存関係を提供

```python
if coverage_info and coverage_dict and len(coverage_dict) > 2:
    coverage_files = list(coverage_dict.keys())

    # ★新規: RepoGraph で依存関係を追加
    if args.repo_graph and code_graph and graph_tags:
        # Coverage ファイルと、それらのカラーを呼び出す関数
        related_files = retrieve_related_files_via_graph(
            coverage_files,
            code_graph,
            graph_tags,
            max_depth=1,  # 1-hop のみ
            max_related_files=5
        )

        graph_context_file_level = construct_file_level_graph_context(
            coverage_files,
            related_files,
            code_graph,
            graph_tags
        )

        message = message + "\n\n### Related Files via Dependencies ###\n" + graph_context_file_level
```

**期待値**:
- Coverage ファイルだけでなく、それらを呼び出す/呼ばれるファイルも候補に含める
- File Level でより正確な修復ファイル特定
- グラフサイズは小さい（Coverage ファイル数 × 1-hop）

### 案 B: Changed files を参考に

```python
if commit_info and commit_info.get('changed_files'):
    changed_files = commit_info['changed_files']

    # ★新規: RepoGraph で Changed files の依存関係を提供
    if args.repo_graph and code_graph and graph_tags:
        graph_context_changed = construct_file_level_graph_for_changed_files(
            changed_files,
            code_graph,
            graph_tags,
            max_depth=1
        )

        message = message + "\n\n### Historical Changes Context ###\n" + graph_context_changed
```

---

## 7. 現在のグラフ統合との違い

### 現在（Fine-Grain Level）
```
グラフ統合ポイント: Fine-Grain Level
グラフ対象: Related Level で見つかった 7-10 個の関数
グラフサイズ: 28,323 トークン
パフォーマンス: -5.6pp
理由: グラフが大きすぎてファイルコンテンツ圧迫
```

### 提案（File Level）
```
グラフ統合ポイント: File Level
グラフ対象: Coverage/Changed files（通常 3-10 ファイル）とそれらの 1-hop 依存
グラフサイズ: 推定 1,000-5,000 トークン（現在の 1/5 以下）
パフォーマンス: +5-10pp の可能性
理由: グラフが小さく、File Level でより重要な情報を提供
```

---

## 8. 実装の検討ポイント

### 利点

1. **グラフサイズが小さい**
   - Coverage/Changed files のみが対象
   - 1-hop only
   - 全リポジトリグラフより圧倒的に小さい

2. **早い段階で活用**
   - File Level で候補ファイルを絞り込める
   - Related/Fine-Grain Level での精度向上

3. **既存の情報を活用**
   - Reproduce がすでに計算している Coverage/Changed files
   - 廃棄される情報を活用

4. **現在の Fine-Grain Level グラフ を削除できる**
   - グラフで -5.6pp の損失を回復
   - トークン予算を他に使える

### 課題

1. **File Level でグラフが必要か**
   - File Level は既に LLM で判断
   - グラフを追加すると複雑化

2. **依存関係の方向**
   - Coverage ファイルが「呼び出す」ファイル？
   - Coverage ファイルを「呼び出す」ファイル？

3. **テスト必要**
   - 1-2 インスタンスで試験実行
   - パフォーマンス測定

---

## 9. ユーザーの指摘「Reproduce なしの場合」

### 質問
> Reproduce を使ってないときの Localization ってどうやってファイルレベルを特定するのだろうか。

### 答え

**Reproduce なし → Coverage なし → Case B を実行**

```python
# reproduce_folder が指定されていない
# または issue_parsing_report_0.json が存在しない

coverage_info = {
    "coverage_dict": {},
    "commit_info": {},
}

# Case B が実行される
message = self.obtain_relevant_files_prompt.format(
    problem_statement=problem_statement,
    structure=show_project_structure(self.structure),  # ← 全リポジトリ構造
    search_str_with_file_prompt=search_str_with_file_prompt,
)
```

**つまり**:
- Reproduce なし → プロジェクト構造全体をプロンプトに含める
- LLM が問題説明から全構造を見て、修復ファイルを判断

**利点**: 全体的な判断が可能
**欠点**: プロンプトが巨大（数千行以上）

---

## 10. 総合的な流れ図

```
┌─────────────────────────────────────────────────────────┐
│ Reproduce（オプション）                                 │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ 出力:                                                   │
│  - PoC code: 証拠コード                                 │
│  - execution_output: 実行結果                           │
│  - coverage_raw: カバレッジ                              │
│  - commit_info: 修正ファイル、バグ修復成功             │
│                                                          │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Localization: File Level（候補ファイル特定）            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ INPUT:                                                  │
│  - problem_statement                                   │
│  - coverage_dict (Reproduce から)        ← ここ重要   │
│  - commit_info (Reproduce から)          ← ここ重要   │
│  - structure (全リポジトリ) or not        ← 選択       │
│                                                          │
│ ★改善提案: Coverage/Commit ファイルの                  │
│            RepoGraph 依存関係を追加                    │
│                                                          │
│ OUTPUT: found_files (top_n, e.g., 5個)                 │
│                                                          │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Localization: Related Level（関連関数・クラス）        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ INPUT:                                                  │
│  - found_files (File Level の結果)                     │
│  - file_contents (圧縮版)                               │
│                                                          │
│ OUTPUT: found_related_locs                             │
│                                                          │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Localization: Fine-Grain Level（具体的な行）          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ INPUT:                                                  │
│  - found_related_locs (Related Level の結果)           │
│  - RepoGraph (現在ここで使用) ← 問題の原因            │
│                                                          │
│ OUTPUT: found_edit_locs (修復対象行)                  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## 11. 推奨される改善戦略

### Step 1: 当面の最小限の修正（即座）
- Fine-Grain Level の retrieve_graph を論文の実装に戻す
- グラフサイズ: 28,323 → 2,311 トークン
- パフォーマンス改善: -5.6pp → +5.6pp（期待値）

### Step 2: File Level での RepoGraph 統合（将来）
- Coverage/Commit ファイルの 1-hop 依存関係を提供
- グラフサイズ: 小（1,000-5,000 トークン）
- File Level での精度向上

### Step 3: Fine-Grain Level グラフを削除
- Step 2 での改善確認後
- Fine-Grain Level での RepoGraph を完全に削除

---

## 結論

ユーザーの指摘は **完全に正当**です：

> 「候補ファイル（Coverage/Changed files）があるなら、そこに RepoGraph を使えばいい」

理由：
1. ✓ 候補ファイル数が少ない（3-10個）
2. ✓ グラフサイズを管理可能（1-5K トークン）
3. ✓ File Level で早期に活用できる
4. ✓ 現在の Fine-Grain Level グラフより価値がある

**次のアクション**:
1. Fine-Grain Level での検索を論文に戻す（即座）
2. File Level での RepoGraph 統合を検討（将来）
