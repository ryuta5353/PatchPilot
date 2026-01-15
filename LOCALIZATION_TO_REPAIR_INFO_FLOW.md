# Localization → Repair フェーズ間の情報フロー分析

**重要な発見**: あなたの直感は正しい。呼び出し情報（グラフ）の価値は限定的です。

---

## データフロー

### Step 1: Localization の出力

```
found_edit_locs = [
    "file.py\nfunction: foo\nline: 42\nline: 45\n",
    ...
]
```

つまり「どのファイルの、どの行（または関数）」を修正すべきか

### Step 2: transfer_arb_locs_to_locs の処理

**コード** (`patchpilot/util/preprocess_data.py:339-348`):

```python
elif loc.startswith("line: "):
    loc = loc[len("line: "):].strip().split()[0]
    try:
        line_loc.append((int(loc), int(loc)))  # 単一行を区間として記録
    except:
        continue
```

**処理内容**：
- 行番号を受け取る（例：行42、行45）
- 区間として記録：`(42, 42)`, `(45, 45)`

### Step 3: Context Window の適用

**コード** (`patchpilot/util/preprocess_data.py:386-391`):

```python
if loc_interval:
    contextual_line_loc = []
    for loc in line_loc:
        max_line = min(loc[1] + context_window, len(content))    # 行番号 + 10
        min_line = max(loc[0] - context_window, 0)               # 行番号 - 10
        contextual_line_loc.append((min_line, max_line))
```

**処理内容**：
- デフォルト `context_window=10` 行
- 行42なら → `(32, 52)` つまり行32〜52を抽出
- **「指定行だけ」ではなく「指定行 ± 10行のコンテキスト」を抽出**

### Step 4: line_wrap_content で実際のコード片を抽出

**コード** (`patchpilot/repair/utils.py:84-90`):

```python
lines = content.split("\n")

for interval in context_intervals:
    min_line, max_line = interval
    # interval の範囲のコードを抽出して表示
```

---

## 関数指定 vs 行指定

### ケース1: 関数が指定された場合

**入力**:
```
function: foo
```

**処理** (`patchpilot/util/preprocess_data.py:273-338`):

```python
relevant_function = [
    function
    for function in functions
    if function["file"] == pred_file and function["name"] == loc
]
if len(relevant_function) > 0:
    line_loc.append((
        relevant_function[0]["start_line"],  # 関数の開始行
        relevant_function[0]["end_line"]     # 関数の終了行
    ))
```

**結果**: **関数全体** (start_line ～ end_line) が Repair に渡される

### ケース2: 行が指定された場合

**入力**:
```
line: 42
```

**処理**:
```python
line_loc.append((42, 42))
```

**その後 Context Window 適用**:
```python
min_line = max(42 - 10, 0) = 32
max_line = min(42 + 10, len(content)) = 52
```

**結果**: **行 32〜52** (指定行 ± 10行) が Repair に渡される

---

## 実際のプロンプト例

### Repair プロンプトに含まれるコード

**`patchpilot/repair/repair.py:1024-1029`**:

```python
message_get_plan = planning_prompt_random_file.format(
    problem_statement=problem_statement,
    content=topn_content.rstrip(),  # ← ここが抽出されたコード片
    example=example,
    files=' '.join(file_loc_intervals.keys())
).strip()
```

`topn_content` には、context_intervals で指定された行範囲のコードだけが含まれます。

**例**:
```
### path/to/file.py
32| def foo():
33|     x = 1
34|     y = 2
35|     z = 3
42|     return x + y + z
45|     print(result)
52| def bar():
```

---

## 重要な発見：呼び出し情報（グラフ）の価値

### 質問1: 「行だけか関数全体か」

**答え**:
- **関数が指定** → 関数全体
- **行が指定** → 行 ± 10行のコンテキスト
- **どちらもコンテキストを含める** → 修復に必要なコードはほぼ含まれている

### 質問2: 「呼び出し情報は意味あるか」

**答え**: **限定的** です。理由は以下の通り：

#### Phase 1: Localization

```
目標：「どのファイルのどの行を修正すべきか」を特定する
使用される情報：
  - 問題説明（GitHub Issue）
  - リポジトリの構造
  - グラフの呼び出し関係（RepoGraph）← ここで使える！

グラフの価値：
  - ✓ 「このファイルを修正すると、どの他のファイルが影響を受けるか」を理解
  - ✓ 「この関数を修正すると、誰が呼び出しているか」を理解
  - ✓ 修復対象の関連コードを特定できる
```

#### Phase 2: Repair

```
目標：「特定された行をどう修復するか」のコード生成
使用される情報：
  - 問題説明
  - 修復対象行 ± 10行のコンテキスト
  - グラフの呼び出し関係？← ここではあまり要らない！

なぜ？
  修復対象はすでに特定されている！
  例：ファイル X の行 42-52 を修正する

  この時点で必要な情報：
  1. 対象行のコード（あり）
  2. コンテキスト（± 10行で十分）
  3. 関連する他のコード？

質問：呼び出し関係があると役立つか？
  例：関数 foo を修正する
     foo は関数 bar と baz によって呼び出されている

  LLM の視点：
    - 「foo を修正すると、bar と baz はどう影響を受けるか」を考慮できる
    - これは「修復が他の関数を壊さない」ためには役立つ

  しかし実装上の課題：
    - グラフのコンテキスト量が多い（113,292文字）
    - トークン予算が限られている
    - 関数の実装詳細（body）よりも、呼び出しパターンの方が重要
    - グラフの関連度スコアが不正確だと、無関連な情報が混在される
```

---

## 実装上の意味

### 現在の実装（Baseline）

```
Localization:
  found_files = [file_a, file_b, file_c]
  found_edit_locs = [
    "line: 42\nline: 45",  # file_a の行42, 45
    "function: foo",        # file_b の関数 foo 全体
    "line: 100"            # file_c の行100
  ]

Repair:
  context_intervals = [
    (32, 52),       # file_a: 行42 ± 10行
    (80, 120),      # file_b: foo 関数全体
    (90, 110)       # file_c: 行100 ± 10行
  ]

  topn_content = 「これらの行範囲のコード片」

  LLM プロンプト：
  「以下のコードを修正してください：[topn_content]」
```

### RepoGraph の実装

```
Localization:
  ↓ (グラフコンテキスト追加)
  graph_context = 「関連関数の呼び出しグラフ」（113,292文字）

Repair:
  topn_content = 「行範囲のコード片」
  graph_context = 「呼び出しグラフ」

  LLM プロンプト：
  「以下のコードを修正してください：
   [topn_content]

   関連する呼び出しグラフ：
   [graph_context]
  」
```

**問題点**:
- グラフを追加することで、プロンプトがサイズ制限に引っかかる
- グラフを削減すると、修復対象のコンテキストまで削減される
- グラフなしでも、すでにコンテキストは十分含まれている

---

## 結論

### 呼び出し情報の価値の違い

| フェーズ | 呼び出し情報の価値 | 理由 |
|---------|------------------|------|
| **Localization** | ⭐⭐⭐⭐⭐ | 「どこを修正すべきか」の判断に直接役立つ |
| **Repair** | ⭐⭐☆☆☆ | 「どう修復すべきか」にはコンテキストで十分 |

### あなたの直感が正しい理由

1. **Localization での利点**
   - グラフで「関連ファイル」を発見できる
   - 複数の修復対象候補から最適なものを選べる
   - RepoGraph が有効に機能する場所

2. **Repair での制限**
   - すでに修復行が特定されている
   - 周囲 10 行のコンテキストがあれば十分
   - 呼び出しグラフは「追加情報」に過ぎない
   - しかし追加情報のため、他の情報（修復対象の詳細）が削減される

3. **グラフが無効になる理由**
   ```
   修復対象：関数 foo の行42を修正

   グラフなし：
     - foo の実装（行32-52）：完全に表示可能 ✓
     - 修復コンテキスト：明確

   グラフあり：
     - foo の実装（行32-52）：部分的に削減される
     - 呼び出しグラフ：表示される
     - 結果：修復対象の詳細が少なくなる ✗
   ```

---

## 推奨

### Repair フェーズでグラフを有効利用するには

1. **戦略A: グラフを別フェーズで使う**
   - Localization のみ でグラフを使用
   - Repair では使用しない
   - トークンの無駄がない

2. **戦略B: グラフを選別して使う**
   - すべての呼び出し関係ではなく、「重要な呼び出し」のみを含める
   - 例：修復対象関数を呼び出す関数のみ（直接の caller）
   - サイズを 113,292 文字 から数千文字に削減

3. **戦略C: グラフを補助情報に**
   - 通常のコンテキスト（± 10行）を優先
   - グラフは「オプション情報」として後に付与
   - 優先度を明示（"Reference information" セクション）

### 現在の実装の問題

```
グラフ追加による情報損失：

修復対象のコード詳細の削減量  > グラフから得られる新しい情報
      ≈ 50,182 トークン             ≈ 28,323 トークン

結果：修復に必要な情報が減少 → ファイルリコール低下 (-5.6pp)
```

---

## 技術的詳細：Context Window の実装

### デフォルト設定

**`patchpilot/repair/repair.py`**:
```python
parser.add_argument('--context_window', type=int, default=20)
```

つまり **前後20行** が デフォルト。

### 計算例

```
修復行が行 100 の場合：

Baseline:
  context_intervals = (80, 120)
  コード表示 = 行80～120（40行）+ 問題説明 + テンプレート

RepoGraph:
  context_intervals = (80, 120)
  graph_context = 113,292 文字

  ↓ トークン数超過時

  context_intervals = (85, 115)  ← 削減される
  graph_context = 113,292 文字 ← 保持される

  結果：修復対象コンテキストが減少
```

---

## あなたの質問への直接的な答え

### 「行のコードだけを渡すのか、関数全体を渡すのか」

**答え**:
- **関数が指定** → 関数全体（start_line ～ end_line）を渡す
- **行が指定** → その行 ± 20 行（デフォルト）を渡す
- つまり **常にコンテキスト付き**

### 「関数全体を渡すなら、呼び出し情報は意味あるのか」

**答え**: **Repair フェーズでは限定的**

理由：
1. 関数全体と周囲コンテキストで、修復に必要な情報はほぼ揃う
2. 呼び出し関係は「Localization で役立つ」が「Repair では追加情報」
3. グラフコンテキストを追加すると、他の情報が削減される
4. グラフの関連度スコアが不正確だと、ノイズになる

**結論**: RepoGraph の価値は **Localization フェーズに集中** している。
Repair フェーズでは使用しない方が効果的である可能性が高い。

