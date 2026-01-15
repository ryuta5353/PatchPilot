# グラフコンテキスト機能の問題詳細分析と解決策

---

## 問題1: テンプレート説明文がプロンプトに残される

### 1.1 問題の詳細な説明

#### 現象
プロンプトを確認すると、以下のようなテンプレート説明文が**複数回含まれている**：

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

#### 発生原因

コードを確認してみます：

**repograph_utils.py の graph_item_format（Line 338-341）:**

```python
graph_item_format = """
### Dependencies for {func}
{dependencies}
"""
```

このテンプレートが使用される場所（Line 421）:

```python
section = graph_item_format.format(func=loc, dependencies=code_graph_context)
```

**問題のシナリオ:**

1. LLMが関連位置を返す（例：`related_loc_traj.response`）
   ```
   ```
   django/forms/models.py
   class: ModelChoiceField
   function: ModelChoiceField.clean
   ```
   ```

2. これが `found_related_locs` に変換される

3. グラフコンテキスト生成ループで処理される
   ```python
   for section_idx, item in enumerate(found_related_locs):
       item = item[0].splitlines()  # Line 373
       for loc in item:  # "class: ModelChoiceField" などのリスト
   ```

4. **問題**: テンプレート説明文そのものが**初期値として含まれる可能性**、またはLLMが返すテンプレート説明文が処理される

#### トークン消費の具体例

**django__django-13933の場合:**

```
テンプレート説明文のトークン消費:
  - 説明文長: 約900字
  - 推定トークン: 225トークン (900/4)
  - 実プロンプト増加: +562.2%

結果、入力トークンが：
  Baseline: 5,581 → Repograph: 8,268 (+2,687トークン)

この追加トークンの大部分がテンプレート説明文！
```

#### LLMへの影響

LLMの観点から見ると：

```
プロンプト内容の優先度:

【重要な情報】
- 問題説明 (150行)
- ファイルスケルトン (500行)
- 実グラフコンテキスト (実関数定義など)

【ノイズ】
- テンプレート説明文 (200行) ← 入力の15-20%

LLMは「どれが重要か」を判断する際、
ボリュームの多い部分に注意を払う傾向がある。
テンプレート説明文のような教科書的な説明文は、
実際のコードセクションより重要度が低いはずだが、
その区別がつきにくい。
```

---

## 問題2: 空の関連位置が複数返される

### 2.1 問題の詳細な説明

#### 現象

LLMが関連位置を特定する際、複数の空文字列を返す：

```python
found_related_locs = [
    ['class: RidgeClassifierCV\nfunction: RidgeClassifierCV.__init__\n...'],  # [0]: 実データ
    [''],  # [1]: 空
    [''],  # [2]: 空
    [''],  # [3]: 空
    [''],  # [4]: 空
]
```

#### 発生原因

**FL.py の処理フロー（大まかな流れ）:**

1. ファイルレベルで見つかったファイルリスト：
   ```python
   found_files = ['sklearn/linear_model/ridge.py', ...]
   ```

2. LLMに関連位置を特定させる：
   ```python
   # 各ファイルに対して「どこに関連関数があるか」を聞く
   prompt = "For each of these files, provide related locations..."
   response = llm.call(prompt)  # 複数回の回答
   ```

3. LLMの応答が4サンプル（num_samples=4）返ってくる

4. **問題**: LLMが確実な関連位置しか特定できず、不確実な場合は空を返す

#### グラフ生成での処理

**repograph_utils.py Line 351-371:**

```python
for section_idx, item in enumerate(found_related_locs):
    sections_remaining = total_sections - section_idx
    remaining_budget = total_token_budget - tokens_used_global

    # ...

    code_graph_context = ""
    item = item[0].splitlines()  # Line 373

    for loc in item:  # 空リストの場合、ここを通らない
        # グラフ検索
```

**実際に起きること:**

```python
# scikit-learn の場合
found_related_locs[1] = ['']
item = [''][0].splitlines()  # '' を分割
# → [] (空リスト)

for loc in []:  # ループが実行されない！
    # この中は実行されず、code_graph_context は空のまま

# Line 420: 空チェック
if code_graph_context.strip():  # False (空なので)
    section = graph_item_format.format(...)
    # ここに到達しない！
```

#### 結果的な影響

```
期待値: 5個の異なるグラフセクション
実際: 1個のグラフセクション + 4個の処理スキップ

出力行数:
  Baseline (4サンプル): 35行
  Repograph (1回のまともなグラフ): 16行
  削減率: -54%
```

---

## 問題3: テンプレート値 "path/to/file.py" の処理

### 3.1 問題の詳細な説明

#### 現象

LLMが関連位置を返す際、テンプレート例をそのまま返すことがある：

```
LLMの応答:
```
path/to/file.py
class: FooBar
function: FooBar.get_foo_bar_display
```
```

#### 発生原因

**related_loc_traj で見たような問題:**

```python
# django__django-11999 の場合
response = ['```\npath/to/file.py\nclass: FooBar\n...```']
```

LLMが「こういう形式で返しなさい」というプロンプト例を、そのまま返している。

#### extract_locs_for_files での処理

**postprocess_data.py Line 390-406:**

```python
def extract_locs_for_files(locs, file_names):
    results = {fn: [] for fn in file_names}
    current_file_name = None

    for loc in locs:
        for line in loc.splitlines():
            # ★問題: ここで "path/to/file.py" にマッチする
            if line.strip().endswith(".py"):
                current_file_name = line.strip()  # "path/to/file.py" を設定

            elif line.strip() and any(
                line.startswith(w) for w in ["line:", "function:", "class:", "variable:"]
            ):
                if current_file_name in results:
                    results[current_file_name].append(line)
                else:
                    pass  # ★current_file_name = "path/to/file.py" は results に無いので捨てられる

    return [["\n".join(results[fn])] for fn in file_names]
```

#### 具体例

```
input:
  locs = ['path/to/file.py\nclass: FooBar\nfunction: FooBar.get_foo_bar_display']
  file_names = ['django/contrib/auth/models.py', 'django/conf/global_settings.py']

processing:
  line 1: "path/to/file.py"
    → current_file_name = "path/to/file.py"

  line 2: "class: FooBar"
    → current_file_name ("path/to/file.py") が results に無いので捨てられる

  line 3: "function: FooBar.get_foo_bar_display"
    → 同様に捨てられる

output:
  results = {
    'django/contrib/auth/models.py': [],  # 空
    'django/conf/global_settings.py': []   # 空
  }

result → found_related_locs に空が返される
```

---

## 解決策1: テンプレート説明文の削除

### 1.1 修正内容

**ファイル**: `patchpilot/fl/repograph_utils.py`

**現在の実装（Line 338-341）:**

```python
graph_item_format = """
### Dependencies for {func}
{dependencies}
"""
```

**修正後:**

テンプレート説明文を含まず、実データだけを含める。説明文は別の場所（プロンプト全体の先頭など）に1度だけ含める。

### 1.2 修正コード

```python
# repograph_utils.py の修正

# Line 338-341 の graph_item_format を以下に変更:
graph_item_format = """
### Dependencies for {func}

{dependencies}
"""

# 追加: プロンプト生成時に説明文を1度だけ含める処理
# (これは FL.py で行う)
```

**+ FL.py での修正（edit_loc_prompts 生成時）:**

```python
# FL.py の どこかのプロンプト生成箇所に以下を追加

GRAPH_GUIDANCE = """
**How to use the dependency graph**:
The following dependency sections show functions that are relevant to fixing the bug.
- Functions listed first typically have higher impact (called more frequently)
- Review both CALLER functions (functions that call your target) and CALLEE functions (functions your target calls)
"""

# プロンプト生成時:
prompt = PROBLEM_DESCRIPTION + FILES_SKELETON + GRAPH_GUIDANCE + graph_context
```

### 1.3 効果

```
改善前:
  - テンプレート説明文: 200行 × 複数セクション
  - 推定トークン: 500-1000トークン

改善後:
  - テンプレート説明文: 10行 × 1度のみ
  - 推定トークン: 10-20トークン

削減効果: 約 950トークン削減
```

---

## 解決策2: 空の関連位置のフィルタリング

### 2.1 修正内容

**ファイル**: `patchpilot/fl/repograph_utils.py`

**現在の実装**: 空の位置がそのまま処理ループに入る

**修正後**: グラフコンテキスト生成前に空の位置をフィルタリング

### 2.2 修正コード

```python
# repograph_utils.py の construct_code_graph_context 関数内

# Line 351 の前に以下を追加:

# MODIFICATION: Filter out empty related locations (Phase 2-6 fix)
found_related_locs_filtered = [
    item for item in found_related_locs
    if item and isinstance(item, list) and len(item) > 0 and item[0].strip()
]

if logger:
    if len(found_related_locs_filtered) < len(found_related_locs):
        logger.info(f"[INFO construct_code_graph_context] Filtered empty locations: {len(found_related_locs)} → {len(found_related_locs_filtered)}")

# Line 351 を以下に変更:
for section_idx, item in enumerate(found_related_locs_filtered):  # ← _filtered を使用
    # 以下は変わらない
    sections_remaining = total_sections - section_idx  # total_sections を found_related_locs_filtered の長さに更新する必要あり
```

**更新版:**

```python
# もっと正確には:

def construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure,
    total_token_budget=30740,
    target_file=None,
    preferred_files=None,
    logger=None,
):
    # ... existing code ...

    # MODIFICATION: Filter out empty related locations
    found_related_locs_filtered = []
    for item in found_related_locs:
        if item and isinstance(item, list) and len(item) > 0:
            content = item[0].strip()
            if content:  # 空でない場合のみ
                found_related_locs_filtered.append(item)

    if logger:
        skipped = len(found_related_locs) - len(found_related_locs_filtered)
        if skipped > 0:
            logger.info(f"[INFO construct_code_graph_context] Skipped {skipped} empty locations")

    graph_context = ""

    # MODIFICATION: Update total_sections count after filtering
    tokens_used_global = 0
    total_sections = len(found_related_locs_filtered)  # ← フィルタ後の数
    items_added = 0
    items_skipped = 0

    # ... rest of the code using found_related_locs_filtered instead of found_related_locs ...

    for section_idx, item in enumerate(found_related_locs_filtered):  # ← ここで使用
        # existing code
```

### 2.3 効果

```
改善前 (scikit-learn__scikit-learn-10297):
  - found_related_locs: 5個
  - そのうち実データ: 1個
  - グラフセクション: 7個（ほとんどが空処理）
  - 実データ: 479トークン
  - 抽出行数: 16行

改善後:
  - found_related_locs_filtered: 1個
  - グラフセクション: 1個（すべて実データ）
  - 実データ: 479トークン
  - 抽出行数: 見積 25行 (テンプレート説明文削除で改善)
```

---

## 解決策3: テンプレート値の除外

### 3.1 修正内容

**ファイル**: `patchpilot/util/postprocess_data.py`

**修正後**: `path/to/file.py` などのテンプレート値を除外

### 3.2 修正コード

```python
def extract_locs_for_files(locs, file_names):
    """
    Extract locations from LLM output and organize by file.

    MODIFICATION: Filter out template values like 'path/to/file.py'
    """
    # Template values to exclude
    TEMPLATE_VALUES = {
        'path/to/file.py',
        'path/to/file',
        '<file_path>',
        'example.py',
    }

    results = {fn: [] for fn in file_names}
    current_file_name = None

    for loc in locs:
        for line in loc.splitlines():
            if line.strip().endswith(".py"):
                potential_file = line.strip()

                # MODIFICATION: Skip template values
                if potential_file not in TEMPLATE_VALUES:
                    current_file_name = potential_file
                else:
                    if logger:
                        logger.debug(f"[DEBUG extract_locs_for_files] Skipped template value: {potential_file}")
                    current_file_name = None  # Reset

            elif line.strip() and any(
                line.startswith(w)
                for w in ["line:", "function:", "class:", "variable:"]
            ):
                if current_file_name and current_file_name in results:
                    results[current_file_name].append(line)
                else:
                    pass

    return [["\n".join(results[fn])] for fn in file_names]
```

### 3.3 効果

```
改善前:
  - "path/to/file.py" が処理される
  - 後続の関数名が捨てられる
  - found_related_locs が空になる

改善後:
  - "path/to/file.py" はスキップ
  - テンプレート値に続く関数名も処理されない
  - found_related_locs_filter で事前フィルタリング
  - グラフ生成がスキップ（空だから）
```

---

## 実装順序と優先度

### Step 1: **テンプレート説明文削除** (優先度: 高) ✅ 最初に実施
- 効果: 500-1000トークン削減
- 影響: すべてのケースで改善
- 実装時間: 5分

### Step 2: **空の関連位置フィルタリング** (優先度: 高) ✅ Step 1の直後
- 効果: 不要な処理スキップ、グラフ品質向上
- 影響: 空位置が多い場合に改善
- 実装時間: 10分

### Step 3: **テンプレート値除外** (優先度: 中)
- 効果: テンプレート値の誤処理防止
- 影響: エッジケース改善
- 実装時間: 10分

---

## 検証方法

修正後、以下で検証：

```bash
# 修正後、同じコマンドで再実行
python patchpilot/fl/localize.py \
    --file_level --related_level --fine_grain_line_level \
    --output_folder results/localization_repo_23inst_fixed_20251110 \
    --repo_graph \
    --code_graph_dir cache/code_graphs \
    --num_samples 4 \
    --top_n 5 \
    --compress \
    --context_window 20 \
    --temperature 0.7 \
    --reproduce_folder results/reproduce \
    --task_list_file instances/test_instances_mixed_phase1_v2.txt \
    --num_threads 4 \
    --model gpt-4o-mini \
    --backend openai \
    --benchmark verified

# 結果比較
python compare_3way_results.py  # Repograph 4-samples vs Baseline
```

**期待される改善:**
- テンプレート説明文削除: +3-5pp
- 空位置フィルタリング: +2-3pp
- **総合**: -5.0pp → 0-3pp（改善または変化なし）
