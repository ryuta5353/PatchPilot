# グラフコンテキスト機能の詳細調査レポート
## ラインレベル精度低下の根本原因分析

作成日: 2025-11-10

---

## 1. 調査対象

### 対比ケース
- **改善ケース**: django__django-13933 (+60.0pp, 0% → 60%)
- **悪化ケース**: scikit-learn__scikit-learn-10297 (-20.0pp, 25% → 5%)

### 目的
グラフコンテキスト機能が改善と悪化の両方をもたらす理由を特定する

---

## 2. 発見事項

### 2.1 グラフコンテキスト生成の状況

#### 改善ケース (django__django-13933)
```
グラフ検索呼び出し: 219回
グラフコンテキストセクション: 10個
最終グラフトークン: 29トークン
関連位置数: 1個

プロンプトサイズ変化:
  Baseline: 20,131 chars
  Repograph: 133,305 chars (+562.2%)
```

#### 悪化ケース (scikit-learn__scikit-learn-10297)
```
グラフ検索呼び出し: 255回
グラフコンテキストセクション: 7個
最終グラフトークン: 479トークン
関連位置数: 5個

プロンプトサイズ変化:
  Baseline: 41,082 chars
  Repograph: 38,511 chars (-6.3%)
```

**奇妙な点**: 改善ケースはプロンプト562%増加なのに改善し、悪化ケースはプロンプト削減なのに悪化している

---

### 2.2 関連位置（found_related_locs）の問題

#### 改善ケース (django__django-13933)
```
found_related_locs: 1個のリスト
  [0]: class: ModelChoiceField
       function: ModelChoiceField.clean
       function: ModelChoiceField.to_python
       ...
```

#### 悪化ケース (scikit-learn__scikit-learn-10297)
```
found_related_locs: 5個のリスト
  [0]: class: RidgeClassifierCV
       function: RidgeClassifierCV.__init__
       ...
  [1]: ['']  ← 空!
  [2]: ['']  ← 空!
  [3]: ['']  ← 空!
  [4]: ['']  ← 空!
```

**問題**: LLMが関連位置を複数返したが、4つは空。これらはグラフ生成時に処理されている

---

### 2.3 重大なテンプレート処理バグ

#### テンプレート変数の置換失敗

プロンプトに以下のテンプレート説明文が**そのまま含まれている**:

```markdown
### Dependencies for <function_name>"
- This lists the functions that are most relevant to understanding <function_name>
- Functions with higher in_degree (called more frequently) appear first

**Critical guidance for using this graph**:
1. **Primary edit location**: Find the function/line with the core bug logic...
2. **Secondary locations**: Check functions that CALL the target function...
3. **Coordination points**: Check functions CALLED BY the target function...
4. **Pattern matching**: If multiple related functions appear...

**Important**: This graph is focused (limited to most critical relationships).
Use it to guide your search but trust the problem description as the primary source of truth.
```

その後に正しく置換された内容が続く:

```markdown
### Dependencies for ModelChoiceField

location: django/forms/models.py lines 822 - 863
name: add_fields
contents:
...
```

**問題点**:
1. **二重包含**: テンプレート説明文 + 実際のグラフコンテキスト
2. **無駄なプロンプト領域**: 説明文が200行以上（推定1000トークン以上）
3. **LLM注意散漫**: 実際のコード情報より説明文の方が多くなる可能性
4. **エラーハンドリング欠如**: fallback時の処理が不適切

---

### 2.4 found_related_locs 抽出の問題

#### extract_locs_for_files() の問題 (postprocess_data.py:390-406)

```python
def extract_locs_for_files(locs, file_names):
    results = {fn: [] for fn in file_names}
    current_file_name = None
    for loc in locs:
        for line in loc.splitlines():
            if line.strip().endswith(".py"):
                current_file_name = line.strip()  # テンプレート値も処理
            elif line.strip() and any(
                line.startswith(w)
                for w in ["line:", "function:", "class:", "variable:"]
            ):
                if current_file_name in results:
                    results[current_file_name].append(line)
                else:
                    pass
    return [["\n".join(results[fn])] for fn in file_names]
```

**問題**:
1. `path/to/file.py` (テンプレート値) が `.endswith(".py")` に一致
2. テンプレート値が `current_file_name` として設定される
3. その後の関数名が、存在しないキーに追加される
4. `results` に対応するキーがないため、行が捨てられる

**結果**: 実ファイルが識別されず、グラフコンテキスト生成でスキップ

---

### 2.5 グラフコンテキスト生成フロー (repograph_utils.py:338-442)

#### 問題の流れ

```python
# Line 421: テンプレート置換
section = graph_item_format.format(func=loc, dependencies=code_graph_context)
# テンプレート:
# ### Dependencies for {func}
# {dependencies}

# しかし、ループの最初の反復で `loc` がない場合、
# または description text がそのまま含まれる場合、
# テンプレート説明文がプロンプトに含まれたままになる
```

---

## 3. ラインレベル精度低下の根本原因

### 3.1 改善ケース: なぜ+60.0ppになったのか?

**仮説**:
1. グラフコンテキストが少ない (29トークン)
2. テンプレート説明文のオーバーヘッドが小さい
3. 実際の関連関数 (ModelChoiceField など) が正確に特定されている
4. LLMが問題文に集中できる余裕がある

**結果**: グラフの質 > テンプレート説明文のノイズ → 改善

---

### 3.2 悪化ケース: なぜ-20.0ppになったのか?

**問題チェーン**:

```
1. LLMが関連位置を5個返す
   ↓
2. その内4個が空 ['']
   ↓
3. extract_locs_for_files() でテンプレート値 "path/to/file.py" が処理される
   ↓
4. 実ファイルが識別されず、グラフ生成がスキップ
   または部分的
   ↓
5. テンプレート説明文がプロンプトに残される
   ↓
6. プロンプトが肥大化（テンプレート説明文）
   ↓
7. LLMが実コードより説明文に注意を払う
   ↓
8. 抽出行数が大幅削減 (35 → 16, -54%)
```

---

## 4. プロンプト品質分析

### 4.1 改善ケースのプロンプト構造

```
問題説明: 150行
ファイルスケルトン: 300行
テンプレート説明文: 200行 ← 無駄
実グラフコンテキスト: 600行 ← 質が良い
合計: 1,250行
```

→ グラフコンテキストが支配的 → 改善

### 4.2 悪化ケースのプロンプト構造

```
問題説明: 250行
ファイルスケルトン: 800行 ← 大規模
テンプレート説明文: 200行 ← 無駄
実グラフコンテキスト: 300行 ← 少ない
合計: 1,550行
```

→ ファイルスケルトンが支配的、グラフが補助的 → 悪化

---

## 5. 結論

### 5.1 グラフコンテキスト機能の問題

| 問題 | 影響 | 重大度 |
|-----|------|--------|
| テンプレート説明文がプロンプトに残される | プロンプト肥大化、LLM注意散漫 | **高** |
| 空の関連位置が複数返される | グラフ生成スキップ | **高** |
| extract_locs_for_files が `path/to/file.py` を処理 | ファイル識別失敗 | **中** |
| テンプレート変数 `<function_name>` が置換されない | テンプレート説明文が残される | **高** |
| 関連位置検索の精度が低い | 5個中4個が空 | **中** |

### 5.2 な なぜ改善と悪化が両立するのか

**グラフの効果は2つの競合する要因による**:

1. **効果的な要因** (+効果)
   - 関連関数の正確な特定
   - ファイルレベルでの補助情報

2. **逆効果な要因** (-効果)
   - テンプレート説明文のプロンプト肥大化
   - 関連位置検索の失敗による空リスト
   - LLMの注意散漫

**結果**:
- グラフが小さく質が良い場合 → 効果的 (+)
- グラフが大きく説明文が多い場合 → 逆効果 (-)
- **総合**: ラインレベルで -5.0pp の劣化

---

## 6. 推奨される修正

### 6.1 即座に実施すべき修正

1. **テンプレート説明文の削除**
   ```python
   # repograph_utils.py の graph_item_format から削除
   # または、適切な条件下でのみ含める
   ```

2. **extract_locs_for_files の改善**
   - `path/to/file.py` などのテンプレート値を除外
   - ファイル検証を追加

3. **empty found_related_locs の処理**
   - 空の位置をスキップ
   - グラフ生成前に検証

### 6.2 中期的な改善

1. グラフ検索精度の向上
2. 関連位置検索の品質管理
3. プロンプト構造の最適化

---

## 7. 付記

### テンプレート説明文の具体例

実際にプロンプトに含まれているテンプレート説明文（約1000トークン):

```markdown
### Dependencies for <function_name>"
- This lists the functions that are most relevant to understanding <function_name>
- Functions with higher in_degree (called more frequently) appear first

**Critical guidance for using this graph**:
1. **Primary edit location**: Find the function/line with the core bug logic (mentioned in problem description)
2. **Secondary locations**: Check functions that CALL the target function - they may:
   - Need updates if the target function's behavior changes
   - Have related bugs that stem from the same root cause
   - Require coordinated error handling changes
3. **Coordination points**: Check functions CALLED BY the target function:
   - If you modify how the target function calls them, update the calls
   - If those functions have expectations about error handling, align with your changes
4. **Pattern matching**: If multiple related functions appear, they likely interact - fix them together

**Important**: This graph is focused (limited to most critical relationships).
Use it to guide your search but trust the problem description as the primary source of truth.
```

このテキストがプロンプトに複数回含まれる可能性があり、**実コンテキストの価値を薄める**ことになっています。
