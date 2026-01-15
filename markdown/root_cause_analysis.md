# Repographグラフコンテキスト生成の問題 - 根本原因分析

## 調査結果

### 1. 全ての実験でグラフコンテキストが生成されていない

| 実験名 | インスタンス数 | グラフ生成済み | グラフ空 |
|--------|----------------|----------------|----------|
| localization_repograph | 2 | 0 | 2 (32文字) |
| localization_repograph_10inst | 9 | 0 | 5 (32文字) |
| localization_repograph_fixed | 2 | 0 | N/A |
| localization_repograph_max10 | 2 | 0 | 1 (32文字) |
| localization_repograph_max5 | 7 | 0 | 5 (32文字) |
| localization_repograph_new | 10 | 0 | 10 (32文字) |

**結論**: グラフコンテキストは**すべての実験で**ほぼ生成されていない。

### 2. なぜ生成されていないのか

実装を追跡すると（django__django-11815の例）：

```
Sample 0: 空
  → item[0].splitlines() = []
  → forループが実行されない
  → retrieve_graphが呼ばれない
  → graph_contextに何も追加されない ✗

Sample 1: 非空（8行）
  → item[0].splitlines() = 8行
  → forループが実行される
  → retrieve_graphが呼ばれる（はず）
  → でもグラフコンテキストは空 ???
  → graph_contextに何も追加されない ✗

Sample 2: 非空（13行）
  → item[0].splitlines() = 13行
  → forループが実行される
  → retrieve_graphが呼ばれる（はず）
  → でもグラフコンテキストは空 ???
  → graph_contextに何も追加されない ✗
```

**謎**: Sample 1と2ではforループが実行されるはずだが、タグが見つかっていない

### 3. 考えられる原因

#### 原因A: tag['kind'] == 'ref'のみで'def'が除外

```python
# repograph_utils.py:30-34
for tag in graph_tags:
    if tag['name'] == search_term and tag['kind'] == 'ref':  # ← 'ref'のみ
        tags.append(tag)
```

タグファイルの構造によっては、関数定義が'def'として格納されており、'ref'のみでは見つからない可能性。

#### 原因B: tag['name']のフォーマット不一致

例えば：
- 検索語: `"CreateModel"` または `"CreateModel.__init__"`
- タグのname: 別の形式（例: モジュール修飾名など）

#### 原因C: max_tags=5で制限されている

実装では`max_tags=5`に設定されているため、見つかるタグが制限されている。

#### 原因D: グラフファイル（tags.json）に十分な情報がない

生成されたタグファイルに、検索対象となるタグが含まれていない可能性。

### 4. ユーザーの質問の真の答え

**質問**: 「以前別のdjango問題10個でやったときは確かにグラフをretriveしていました。なぜ今回はなくなてしまったのだろうか。」

**答え**:

1. **実は前回もグラフコンテキストは生成されていませんでした**
   - localization_repograph_10instの全5インスタンスが32文字のみ

2. **全ての実験で同じ状況**
   - どの実験でも、グラフコンテキストは生成されていない

3. **ユーザーが見た「グラフのretrieve」は何だったのか？**
   - ログに「Retrieving graph for...」というメッセージがない
   - ループが実行された形跡がない
   - もしくは、construct_code_graph_contextが呼ばれ始めた時点で、「グラフを使う」という設計が導入されたが、実装に問題があった

4. **根本的な問題は**:
   - 実装内の`retrieve_graph`関数がタグを見つけられていない
   - 理由はタグ検索ロジック（'ref'のみ、またはname不一致など）の可能性が高い

## 推定される実装の歴史

```
Phase 1（最初）:
  - Repograph統合の計画策定
  - repograph_utils.py作成
  - construct_code_graph_context実装

Phase 2（実験開始）:
  - localization_repograph実行 → グラフコンテキスト空
  - localization_repograph_10inst実行 → グラフコンテキスト空
  - max_tagsを10から5に削減 → グラフコンテキスト依然空

Phase 3（現在）:
  - localization_repograph_new実行 → グラフコンテキスト空
  - ユーザーが「グラフが使われていない」と指摘
```

## 実装上の疑問点

### 疑問1: ログに「Retrieving graph for」がないのはなぜ？

`repograph_utils.py:38`の`print(f"Retrieving graph for {i}/{len(tags)}")`が実行されていない
→ `retrieve_graph`関数が呼ばれていない可能性

### 疑問2: なぜmax_tags削減が効果なし？

max_tags=10→5に削減しても、グラフコンテキストは32文字のまま
→ そもそもタグを見つけられていない可能性

### 疑問3: タグファイルは正常か？

生成された`tags_*.json`ファイルに、検索対象のタグが含まれているか確認必要

## 次の調査ステップ

1. タグファイル（tags.json）の内容確認
   - 実際に'CreateModel'というタグが含まれているか？
   - tag['kind']は何か？（'ref'か'def'か？）
   - tag['name']のフォーマットは？

2. retrieve_graph関数のデバッグ
   - 実際に呼ばれているか（ログ追加）
   - 見つかるタグ数は（戻り値確認）

3. construct_code_graph_contextのデバッグ
   - ループが実行されているか
   - code_graph_contextが実際に生成されているか
