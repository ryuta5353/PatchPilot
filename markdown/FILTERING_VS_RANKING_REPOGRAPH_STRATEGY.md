# RepoGraph 統合戦略：「絞る」 vs 「不要ファイル削除」

## 1. 2つのアプローチの本質的な違い

### アプローチA: ランキング＆Tier（絞る）
```
入力: 152+ ファイル候補
      ↓
RepoGraph で「関連度スコア」付け
      ↓
出力: Tier 1-3 のみ提示（5-10 ファイル）

特徴:
  - 候補を削減
  - 優先度情報を付与
  - 「最も関連しそう」を前面に
```

### アプローチB: フィルタリング（削除）
```
入力: 152+ ファイル候補
      ↓
RepoGraph で「関連なし」を特定
      ↓
出力: 関連なしを除外（50-100 ファイル）

特徴:
  - 完全にノイズを削除
  - LLM に「すべて関連ある」と伝える
  - 候補は減るが完全削除ではない
```

---

## 2. 詳細比較

### 2-1. 実装の複雑さ

**アプローチA（ランキング）:**
```python
# 1. グラフから関連ファイル抽出
for keyword in keywords:
    related_files = retrieve_graph(keyword)
    # → keyword に関連するファイル集合

# 2. ファイル別に「関連キーワード数」をカウント
for file in all_files:
    score = count_related_keywords(file)

# 3. Tier 分け
for file in sorted_by_score:
    if score >= 3:
        tier = 1
    elif score >= 2:
        tier = 2
    else:
        tier = 3

# 4. Tier 1-2 のみプロンプトに含める
prompt += format_tier_files(tier_files[1] + tier_files[2])
```

**アプローチB（フィルタリング）:**
```python
# 1. グラフから関連ファイル取得
related_files_union = set()
for keyword in keywords:
    related = retrieve_graph(keyword)
    related_files_union.update(related)

# 2. グラフで「関連なし」のファイルを特定
all_candidate_files = set(search_res_files.values())
unrelated_files = all_candidate_files - related_files_union

# 3. 「関連なし」を削除
filtered_candidates = all_candidate_files - unrelated_files

# 4. 全 candidate をプロンプトに含める
prompt += format_candidates(filtered_candidates)
```

**判定: B の方が実装が簡潔**
```
A は: score 計算 + Tier 分け + 条件分岐 = 複雑
B は: Union 集合演算 + 差分演算 = シンプル
```

---

### 2-2. LLM への情報伝達

**アプローチA（ランキング）:**
```
### File Candidates (Ranked) ###

Tier 1 (Connected to 3 keywords):
  - django/db/models.py (execute, save, permission)

Tier 2 (Connected to 2 keywords):
  - django/core/base.py (execute, save)

Tier 3 (Connected to 1 keyword):
  - django/test/utils.py (execute only)

LLM への暗黙的メッセージ:
  「Tier 1 が最も重要」
  「Tier 3 は参考程度」
  → LLM は Tier を意識して選択
```

**アプローチB（フィルタリング）:**
```
### File Candidates (Verified by RepoGraph) ###

The following files are connected to the keywords
via code dependencies:
  - django/db/models.py (related to: execute, save, permission)
  - django/core/base.py (related to: execute, save)
  - django/test/utils.py (related to: execute)

All unrelated files have been filtered out.

LLM への暗黙的メッセージ:
  「すべてこのグラフに関連」
  「順序は特別な意味なし」
  → LLM は「すべて等しく関連」と認識
```

**判定: A の方が情報が豊富**
```
A: 優先度 (Tier) を明示
B: 「すべて関連」という単一メッセージ
```

---

### 2-3. 失敗時の動作

**アプローチA（ランキング）:**
```
Tier 1 で失敗（修正箇所がない）
    ↓
Tier 2 を試す → 成功
    ↓
または
    ↓
Tier 2 も失敗
    ↓
Tier 3 を試す

特徴: フォールバック戦略が組み込まれている
    優先度順に試していける
```

**アプローチB（フィルタリング）:**
```
候補 A で失敗（修正箇所がない）
    ↓
候補 B を試す → 成功
    ↓
または
    ↓
すべての候補を試す → 失敗

特徴: 選択順序が不明確
    「どれから試すべき」という判断基準なし
    ランダムに試すことになる可能性
```

**判定: A の方が失敗時に有利**

---

### 2-4. トークン消費

**アプローチA（ランキング）:**
```
Tier 1: 3-5 ファイル → 100-200 tokens
Tier 2: 3-5 ファイル → 100-200 tokens
Tier 3: 1-3 ファイル → 50-100 tokens
────────────────────────────
プロンプトに含める: Tier 1 + Tier 2 = 200-400 tokens

残り Tier 3 は「参考」として省略可能
```

**アプローチB（フィルタリング）:**
```
グラフ関連ファイル: 50-100 ファイル → 500-1000 tokens
────────────────────────────
プロンプトに含める: すべて = 500-1000 tokens

すべて「等しく関連」なので省略不可
```

**判定: A の方がトークン効率が良い**

---

### 2-5. 「完全に関連ない」の定義の曖昧性

**問題: グラフで「関連なし」と判定されたファイルが本当に無関係?**

```
例: Django での "execute" キーワード

search_string("execute") で見つかったファイル A:
  実は "execute" という変数名が出現しているだけ
  → 関数 execute() とは無関係

RepoGraph で調査:
  A は retrieve_graph("execute") に含まれない
  → 「関連なし」と判定 ✓

しかし...

実は A は execute() を呼ぶ別ファイルが存在:
  B → C → execute()
  （2-hop の関係）

RepoGraph で「1-hop のみ」なら:
  A は見つからない → 「関連なし」と判定 ✗（誤検出）
```

**問題点:**
```
アプローチB は「1-hop で関連ない = 完全に無関係」と仮定
実際には k-hop (k>=2) で関連する可能性がある
→ 「無関係」の定義が不完全
```

**対策:**
```
定義を明確に:
  「1-hop で関連なし」 = 「直接的には無関係」
  完全な無関係ではない可能性を念頭に
```

---

## 3. 各アプローチの実装シナリオ

### シナリオ: Django のバグ修正

#### 現状（両アプローチ前）
```
search_res_files:
  execute: [file1, file2, ..., file50]  (50 ファイル)
  save: [file_a, file_b]                (2 ファイル)
  permission: [file_x, ..., file_z]     (100 ファイル)

合計候補: 152 ファイル
```

#### アプローチA実行後
```
Step 1: グラフから関連ファイル抽出
  execute → {file1, file2, file3, file10, ...}  (20 ファイル)
  save → {file1, file2, file50}                  (3 ファイル)
  permission → {file2, file3, file_x, ...}      (25 ファイル)

Step 2: スコア計算
  file1: 2 (execute, save)
  file2: 3 (execute, save, permission)
  file3: 2 (execute, permission)
  ... 他多数

Step 3: Tier 分け
  Tier 1: file2 のみ                             (1 ファイル)
  Tier 2: file1, file3, file4, ...               (8 ファイル)
  Tier 3: その他                                 (多数)

Step 4: プロンプト含める
  ✓ Tier 1 (1)
  ✓ Tier 2 (8)
  ✗ Tier 3 (省略)

最終候補: 9 ファイル
```

#### アプローチB実行後
```
Step 1: グラフから関連ファイル抽出
  execute → {file1, file2, file3, file10, ...}  (20 ファイル)
  save → {file1, file2, file50}                  (3 ファイル)
  permission → {file2, file3, file_x, ...}      (25 ファイル)

Step 2: Union を計算
  related_union = {file1, file2, file3, file10, file_a, file_b, file_x, ...}
  (重複を除いた関連ファイル)                      (合計 40 ファイル)

Step 3: グラフ関連なしを特定
  unrelated = all_candidates - related_union
            = 152 - 40 = 112 ファイル

Step 4: フィルタ後の候補
  filtered = all_candidates - unrelated = 40 ファイル

Step 5: プロンプト含める
  ✓ すべての関連ファイル (40)

最終候補: 40 ファイル
```

---

## 4. ケース別の判断

### ケース1: Search Results がすでに精度が高い場合

```
シナリオ: execute, save, permission で見つかったファイルの
         ほとんどが実は関連ある

アプローチA: 9 ファイル → LLM が簡単に選択 ✓✓✓
アプローチB: 40 ファイル → LLM が選択に迷う可能性 ✓

判定: A が優位
      B は不要な削減をしていない（逆にメリット）
```

### ケース2: Search Results が低精度（ノイズ多い）

```
シナリオ: execute は 50 ファイル（ほぼノイズ）
         permission も 100 ファイル（ほぼノイズ）
         実際に関連なのは 5-10 ファイル

グラフ関連: 40 ファイル
グラフ無関: 112 ファイル

アプローチA: 9 ファイル (Tier 1-2) → 本当に関連なものに絞れる ✓✓✓
アプローチB: 40 ファイル → まだノイズが多い ✓

判定: A が大幅に優位
      ノイズが激しいほど、ランキングの価値が上がる
```

### ケース3: 単純な検索キーワード（曖昧性低い）

```
シナリオ: search_res_files が既にかなり精度高
         execute は実際に 3 ファイルのみ
         save は 2 ファイル（すべて関連）

グラフ関連: 5-8 ファイル
グラフ無関: ほぼなし

アプローチA: 8 ファイル (Tier 1-2) ✓✓
アプローチB: 8 ファイル → 無駄な削除なし ✓✓

判定: 両者ほぼ同等
      この場合は削除のメリットが低い
```

---

## 5. 推奨判断マトリックス

```
                Search Results 精度
                  低            高
          ┌─────────────────┬─────────────────┐
ノイズ 多  │    アプローチA   │ アプローチA or B │
          │   (絞る が有効) │   (どちらでも可) │
          ├─────────────────┼─────────────────┤
ノイズ 少  │  アプローチ B   │   アプローチB   │
          │ (削除 で十分)   │  (削除 で十分)  │
          └─────────────────┴─────────────────┘
```

---

## 6. PatchPilot の現状を考慮した推奨

### 現在の実装の特性

```
PatchPilot の Step 0:
  - LLM が自動的に検索キーワードを決定
  - search_string("error message") のようなアドホックなキーワード
  - 精度が不明 (問題によって大きく異なる)

Step 1 の重要性:
  - File Recall@3 が 55.6% = Step 0 のノイズが相当
  - 現在すでに「全候補をプロンプトに含める」実装
    → ノイズが大量に含まれている可能性が高い
```

### 推奨：アプローチA（絞る）

**理由:**

```
1. 現在のノイズが多い実装に対して
   アプローチA は「優先度情報」を追加
   → LLM の判断精度が向上（最大の効果）

2. Step 0 の精度が不確定
   → 100 ファイルが本当に関連かグラフで検証する価値が高い

3. トークン効率
   → Tier 1-2 のみ含めることで削減可能

4. 失敗時のフォールバック
   → Tier 1 で失敗 → Tier 2 を試す戦略が利用可能

5. プロンプト設計
   → 「重要度」を明示することで LLM の判断が格段に向上
```

**具体的な効果:**
```
現在: File Recall@3 = 55.6%
    ├─ 152 ファイル候補
    └─ LLM: 「どれを選べば?」

改善案A: File Recall@3 = 70-75% (推定 +15pp)
    ├─ Tier 1-2: 9 ファイル（優先度明示）
    └─ LLM: 「Tier 1 を優先」→ 判断が容易

改善案B: File Recall@3 = 60-65% (推定 +5pp)
    ├─ 40 ファイル（無関連削除）
    └─ LLM: 「すべて関連」でも候補が多い
```

---

## 7. 最終判定

### **結論：アプローチA（絞る＆優先度付け）の方が優位**

```
理由の優先順位:

1️⃣ 【効果の大きさ】
   ノイズが多い環境では優先度情報が最大のメリット
   単なる「削除」より「優先度付け」の方がはるかに有効

2️⃣ 【失敗時の対応】
   Tier ごとの試行戦略が利用可能
   ランダムに試すより系統的

3️⃣ 【トークン効率】
   Tier 1-2 のみでプロンプト構築可能
   Tier 3 は省略可

4️⃣ 【実装の価値】
   削除は「不要」を特定するだけ
   優先度は「本当に重要」を特定する ← より高度

5️⃣ 【LLM との親和性】
   「Tier を意識して選択」の方が自然
   「すべて等しく関連」は LLM を活かし切れない
```

### ただし・・・

```
アプローチB（削除）が有効な場合:
  - ノイズが極めて多い（削除するだけで大幅改善）
  - 実装をシンプルに保ちたい
  - トークン削減が最優先
```

---

## 8. ハイブリッド案

```
最強の組み合わせ：

Step 1: グラフで「無関連」を削除（アプローチB）
  152 ファイル → 40 ファイル

Step 2: 残った 40 ファイルを優先度付け（アプローチA）
  40 ファイル → Tier 1-3 に分類

Step 3: プロンプトに含める
  ✓ Tier 1 (1-3 ファイル)
  ✓ Tier 2 (5-10 ファイル)
  ✗ Tier 3 (省略または参考）

結果: 削除 + 優先度 のダブル効果
     - ノイズの徹底削除
     - LLM の判断がさらに容易
     - トークン最小化
```

