# 計画書: Related Level キーワードベース Graph Context 追加

## 1. 概要

### 1.1 目的
Related Level の精度向上（65.1% → 70%以上）を、既存の成功インスタンスを壊さずに実現する。

### 1.2 アプローチ
問題記述からキーワードを抽出し、`graph_tags` に存在するもののみをフィルタリングして、Related Level プロンプトに補助情報として追加する。

### 1.3 設計方針

| 方針 | 説明 |
|------|------|
| Skeleton が主役 | 現状の成功パターンを維持 |
| Graph Context は補助 | 「Supplementary Reference」として明示 |
| トークン制限なし（初期） | まず動作確認、問題発生時に制限追加 |
| found_files に限定 | File Level で特定したファイル内のタグのみ対象 |
| LLM呼び出しなし | 正規表現 + タグフィルタリングでコスト回避 |

---

## 2. 処理フロー

```
┌─────────────────────────────────────────────────────────────┐
│ 入力                                                         │
│  - problem_statement (問題記述)                              │
│  - found_files (File Level の結果, top_n件)                  │
│  - graph_tags (tags_*.json)                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: キーワード抽出 (extract_keywords_from_problem)       │
│  - 正規表現で snake_case / CamelCase を抽出                  │
│  - graph_tags の name と照合してフィルタリング               │
│  - found_files 内のタグのみ対象                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: タグ検索 (search_tags_by_keywords)                   │
│  - 抽出キーワードにマッチする def/ref タグを取得             │
│  - ファイル・行番号情報を保持                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Graph Context 構築 (build_keyword_graph_context)     │
│  - マッチしたタグをコンパクトにフォーマット                  │
│  - Supplementary Reference セクションとして構造化            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: Related Level 実行                                   │
│  - 既存 Skeleton プロンプト + Graph Context                  │
│  - additional_info パラメータ経由で渡す                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 実装詳細

### 3.1 新規関数（repograph_utils.py に追加）

#### 3.1.1 extract_keywords_from_problem

```python
def extract_keywords_from_problem(problem_statement: str,
                                   graph_tags: list,
                                   found_files: list) -> dict:
    """
    問題記述からキーワードを抽出し、タグに存在するもののみ返す

    Args:
        problem_statement: GitHub Issue の問題記述
        graph_tags: tags_*.json のデータ
        found_files: File Level で特定したファイルリスト

    Returns:
        {
            'functions': ['serialize', 'handle', ...],  # 関数+メソッド
            'classes': ['TypeSerializer', ...]          # クラス
        }
    """
```

**実装ロジック:**
1. 正規表現で snake_case パターン抽出: `r'\b([a-z_][a-z0-9_]{2,})\b'`
2. 正規表現で CamelCase パターン抽出: `r'\b([A-Z][a-zA-Z0-9]+)\b'`
3. found_files 内のタグ名を収集
4. 集合演算でフィルタリング（タグに存在するもののみ）

#### 3.1.2 search_tags_by_keywords

```python
def search_tags_by_keywords(graph_tags: list,
                            keywords: dict,
                            found_files: list) -> dict:
    """
    キーワードにマッチするタグを検索（部分一致対応）

    Args:
        graph_tags: tags_*.json のデータ
        keywords: extract_keywords_from_problem の結果
        found_files: File Level で特定したファイルリスト

    Returns:
        {
            'def': [tag1, tag2, ...],  # 定義タグ
            'ref': [tag3, tag4, ...]   # 参照タグ
        }
    """
```

**実装ロジック:**
1. keywords から全キーワードを収集
2. graph_tags をループ
3. found_files 内のタグのみ対象
4. **マッチング判定**: 最小キーワード長による切り替え
   - 3文字未満: 完全一致のみ（`id` → `valid` を防ぐ）
   - 3文字以上: 部分一致（キーワードがタグ名に含まれるか）
5. マッチしたタグを def/ref に分類

**マッチング関数:**
```python
def keyword_matches_tag(keyword, tag_name):
    keyword_lower = keyword.lower()
    tag_name_lower = tag_name.lower()

    # 短いキーワード（3文字未満）は完全一致のみ
    if len(keyword) < 3:
        return keyword_lower == tag_name_lower

    # 3文字以上は部分一致（キーワードがタグ名に含まれる）
    return keyword_lower in tag_name_lower
```

**マッチング例:**
| 検索ワード | 長さ | タグ名 | マッチ | 理由 |
|-----------|------|--------|--------|------|
| `valid` | 5 | `validate` | ○ | 部分一致 |
| `valid` | 5 | `invalid` | ○ | 部分一致 |
| `id` | 2 | `valid` | × | 完全一致のみ |
| `ordering` | 8 | `find_ordering_name` | ○ | 部分一致 |
| `wrapper` | 7 | `_wrapper` | ○ | 部分一致 |
| `subclass` | 8 | `__subclasscheck__` | ○ | 部分一致 |

#### 3.1.3 build_keyword_graph_context

```python
def build_keyword_graph_context(matched_tags: dict,
                                 keywords: dict) -> str:
    """
    マッチしたタグから Graph Context 文字列を構築

    Args:
        matched_tags: search_tags_by_keywords の結果
        keywords: extract_keywords_from_problem の結果

    Returns:
        フォーマット済みの Graph Context 文字列
    """
```

**実装ロジック:**
1. ヘッダー追加（Supplementary Reference）
2. Keywords セクション構築
3. Definitions セクション構築（def タグから）
4. References セクション構築（ref タグから）

### 3.2 出力フォーマット

```
### Supplementary Reference ###
Note: Use this only if the skeleton above is insufficient.

Keywords found in codebase:
- functions: serialize, _registry
- classes: TypeSerializer, Serializer

Definitions:
- serialize (function) @ django/db/migrations/serializer.py:26
- serialize (function) @ django/db/migrations/serializer.py:34
- TypeSerializer (class) @ django/db/migrations/serializer.py:200

References (call sites):
- serialize @ django/db/migrations/writer.py:23
- TypeSerializer @ django/db/migrations/serializer.py:320
```

### 3.3 localize.py の変更

#### 3.3.1 新規引数追加

```python
parser.add_argument("--keyword_graph_context", action="store_true",
                    help="Add keyword-based graph context to Related Level")
```

#### 3.3.2 Related Level 呼び出し修正（L260-270付近）

```python
# キーワードベース Graph Context を生成
keyword_graph_context = ""
if args.keyword_graph_context and graph_tags is not None:
    keywords = extract_keywords_from_problem(problem_statement, graph_tags, pred_files)
    matched_tags = search_tags_by_keywords(graph_tags, keywords, pred_files)
    keyword_graph_context = build_keyword_graph_context(matched_tags, keywords)
    logger.info(f"Keywords extracted: {keywords}")
    logger.info(f"Matched tags: def={len(matched_tags['def'])}, ref={len(matched_tags['ref'])}")

# Related Level 実行
(found_related_locs, ...) = fl.localize_function_from_compressed_files(
    pred_files,
    mock=args.mock,
    num_samples=args.num_samples,
    coverage_info=coverage_info,
    additional_info=keyword_graph_context  # 追加
)
```

---

## 4. ファイル変更一覧

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `patchpilot/fl/repograph_utils.py` | **追加** | 3つの新関数 |
| `patchpilot/fl/localize.py` | **修正** | 引数追加、Related Level 呼び出し修正 |

---

## 5. テスト計画

### 5.1 テストコマンド

```bash
python patchpilot/fl/localize.py \
    --file_level \
    --related_level \
    --fine_grain_line_level \
    --output_folder results/localization_keyword_graph_test \
    --top_n 5 \
    --compress \
    --context_window 20 \
    --num_samples 4 \
    --num_threads 1 \
    --task_list_file instances/test_instances_django_43.txt \
    --benchmark verified \
    --keyword_graph_context \
    --code_graph_dir RepoGraph_cache
```

### 5.2 評価指標

| 指標 | 現状 | 目標 |
|------|------|------|
| Related Level 精度 | 65.1% (28/43) | **70%以上 (30/43)** |
| 既存成功の維持 | 28件 | **28件以上** |
| コンテキスト超過エラー | - | **0件** |

### 5.3 評価スクリプト

既存の `create_related_level_evaluation_v2.py` を使用

---

## 6. 実装チェックリスト

### Phase 1: 関数実装

- [ ] `extract_keywords_from_problem()` 実装
  - [ ] snake_case 正規表現パターン
  - [ ] CamelCase 正規表現パターン
  - [ ] graph_tags との照合フィルタリング
  - [ ] found_files への限定

- [ ] `search_tags_by_keywords()` 実装
  - [ ] def タグの検索
  - [ ] ref タグの検索
  - [ ] found_files 内への限定

- [ ] `build_keyword_graph_context()` 実装
  - [ ] Keywords セクション
  - [ ] Definitions セクション
  - [ ] References セクション
  - [ ] Supplementary Reference ヘッダー

### Phase 2: 統合

- [ ] `localize.py` に `--keyword_graph_context` 引数追加
- [ ] Related Level 呼び出し部分の修正
- [ ] ログ出力の追加（デバッグ用）

### Phase 3: テスト

- [ ] 単体テスト（1インスタンスで動作確認）
- [ ] 43インスタンスでの全体テスト
- [ ] 結果評価
  - [ ] Related Level 精度確認
  - [ ] 回帰確認（既存成功28件）
  - [ ] コンテキスト超過確認

### Phase 4: 調整（必要に応じて）

- [ ] トークン制限の追加（超過発生時）
- [ ] キーワード抽出パターンの調整
- [ ] フォーマットの調整

---

## 7. リスクと対策

| リスク | 確率 | 対策 |
|--------|------|------|
| コンテキスト超過 | 中 | Phase 4 でトークン制限追加 |
| 既存成功の回帰 | 低 | Supplementary として明示、主役は Skeleton |
| キーワード抽出の誤り | 低 | タグフィルタリングでノイズ除去済み |
| 処理時間増加 | 低 | タグ検索は軽量（O(n)） |

---

## 8. 背景情報

### 8.1 調査済み失敗インスタンス（6件）

| Instance | Gold | 失敗カテゴリ | 詳細 |
|----------|------|-------------|------|
| django__django-13028 | `check_filterable` | パス形式の不一致 | 正しい関数名を特定したが path/to/file.py 形式で出力 |
| django__django-13033 | `find_ordering_name` | 呼び出しチェーンが深い | サンプルコード(OneModel等)に注目、実際の関数に到達できず |
| django__django-15814 | `deferred_to_data` | スタックトレース優先 | ユーザーが提示した行745より、スタックトレースの関数を優先 |
| django__django-14238 | `__subclasscheck__` | クラスのみ特定 | AutoFieldMetaクラスは特定したがメソッドまで絞れず |
| django__django-14580 | `TypeSerializer.serialize` | クラスの混同 | Serializer(レジストリ)とTypeSerializer(実際のバグ箇所)を混同 |
| django__django-14787 | `_wrapper` | ネスト関数未特定 | 親関数`_multi_decorate`は特定したが内部関数`_wrapper`に到達できず |

### 8.2 本実装で改善可能性のある4インスタンス

部分一致による改善予測:

| Instance | Gold | 抽出キーワード | 部分一致タグ | 改善可能性 |
|----------|------|---------------|-------------|-----------|
| django__django-13033 | `find_ordering_name` | `ordering` | `find_ordering_name`, `clear_ordering` | **○** |
| django__django-14580 | `TypeSerializer.serialize` | `serialize` | `serialize`, `TypeSerializer` | **○** |
| django__django-14787 | `_wrapper` | `wrapper` | `_wrapper`, `wrapper` | **○** |
| django__django-14238 | `__subclasscheck__` | `subclass` | `__subclasscheck__`, `_subclasses` | **○** |

### 8.3 RepoGraph タグ構造

```python
{
    "fname": "絶対パス",
    "rel_fname": "相対パス",
    "line": 行番号,
    "name": "関数/クラス名",
    "kind": "def" or "ref",
    "category": "function" or "class",
    "info": "ソースコード or タブ区切りメソッド名"
}
```

- `function` カテゴリ: スタンドアロン関数 + クラスメソッド
- `class` カテゴリ: クラス定義のみ

### 8.4 現状の Related Level パイプライン

```
File Level 結果 (found_files)
         │
         ▼
get_skeleton() で圧縮
         │
         ▼
LLM に問い合わせ
         │
         ▼
found_related_locs (関数/クラス/変数リスト)
```

---

## 9. 参考資料

- `analysis/RELATED_LEVEL_LOCALIZATION_FLOW.md`: Related Level の入出力フロー詳細
- `create_related_level_evaluation_v2.py`: 評価スクリプト
- `patchpilot/fl/repograph_utils.py`: 既存の RepoGraph ユーティリティ
