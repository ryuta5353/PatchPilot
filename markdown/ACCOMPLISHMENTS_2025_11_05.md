# RepoGraph 統合研究 - 成果物・調査結果まとめ
**日付:** 2025-11-05  
**対象:** PatchPilot への RepoGraph (Composite Score) 統合

---

## 📊 実施した実験・調査一覧

### 1. **Composite Score 実装完了**
**目的:** in_degree のみの優先度付けを改善

**実装内容:**
```python
# patchpilot/fl/repograph_utils.py

Composite Score = ファイル距離（1000/100/1）
                + 直接グラフ接続（+50）
                + in_degree 補助（0-10）
```

**変更点:**
- `retrieve_graph()` の max_tags: 100 → 50 に削減
- Composite Score でのソートに変更
- 定義タグ（def_tags）の制限: 複数 → 1個に統一
- Debug ログの追加

**ファイル:** `patchpilot/fl/repograph_utils.py`

---

### 2. **Sympy/Django/Matplotlib での Localization 実験**
**目的:** Composite Score の効果をプロジェクト別に測定

**実験結果:**
```
Sympy:        +9.5pp  改善 ✓
Django:       -6.4pp  悪化 ✗
Matplotlib:   -7.5pp  悪化 ✗
```

**分析:**
- Sympy: ファイル構造が明確で Composite Score が効果的
- Django/Matplotlib: モジュール間依存が複雑、ファイル距離の有効性低い

**判断:** LLM モデルの違い（gpt-4o-mini vs Claude 3.5 Sonnet）の影響を考慮

---

### 3. **ベンチマークデータセット検証**
**目的:** PatchPilot と RepoGraph の基盤データセットの相違を解明

**重要発見:**
```
PatchPilot の想定: SWE-bench Verified
RepoGraph の基盤: SWE-bench Lite

PatchPilot の testbed 状況:
  - 全体: 790個のインスタンス（verified_setup_map.json）
  - 実際: 約500個がテストベッド化

共通インスタンス（両方に存在）: 78個
  ├─ Django: 43個
  ├─ Sympy: 22個
  └─ Matplotlib: 7個
```

**制約:** PatchPilot の完全なパイプライン評価には、この 78個のみが使用可能

**ファイル:** `setup_result/verified_setup_map.json`, `RepoGraph_cache/tags_*.json`

---

### 4. **グラフサイズ分析と実験的閾値発見**
**目的:** グラフサイズと localization 精度の関係を特定

**発見:**
```
グラフサイズ別の精度:
  91KB-28MB:     良好（33-100% recall）
  100MB-:        不可（0% recall）

Lite データセット内の分布:
  Django:       35-47MB   全て適切 ✓
  Matplotlib:   53-56MB   全て適切 ✓
  Sympy:        91MB-1.9GB 大部分不適切 ✗
                  ├─ 小（91-94MB）: 11個
                  └─ 大（548M-1.9GB）: 64個
```

**結論:** グラフサイズ最適化の重要性が確認された

---

### 5. **グラフの物理的構造の詳細分析**
**目的:** グラフコンテキストメカニズムの完全な理解

**発見:**

#### tags.json ファイル構造
```
- 形式: JSON 配列（JSON Lines ではなく）
- 総タグ数: 58,382個（Sympy の場合）
  - def タグ: 12,803個（関数定義）
  - ref タグ: 45,579個（関数参照/呼び出し）

各タグの構成:
  {
    "name": "関数名",
    "kind": "def" or "ref",
    "rel_fname": "相対パス",
    "line": 行番号,
    "category": "function" or "class",
    "info": "コード片"
  }
```

#### retrieve_graph() の処理フロー
```
入力: search_term = "parse_input"

Step 1: タグ抽出
  - def_tags: 1個（関数定義）
  - ref_tags: 500個（呼び出し箇所）

Step 2: Composite Score でランク付け（500個）

Step 3: max_tags で制限（上位50個）

Step 4: 各ref_tagが含まれる関数全体を抽出
  → 各関数 30-50行

Step 5: プロンプト形式で返却（計1-51個の関数）
```

#### コンテキスト超過の原因
```
グラフサイズが大きい ≠ コンテキスト超過の直接原因

実際の原因:
  found_related_locs の関数数 × max_tags(50) × 関数コード行数
  = 10関数 × 50tags × 30行 = 15,000行以上

グラフサイズの役割:
  - メモリ消費: 500MB グラフのロード時間
  - 検索速度: 45,579個のref_tagsから該当を探す時間
  - プロンプトサイズへの影響: 間接的（大きなグラフ = 複雑なリポジトリ = ref_tags多い）
```

**ファイル:** `phase1_repograph_integration.md` セクション 7-9

---

### 6. **テストインスタンスの選定と作成**
**目的:** 適切なグラフサイズを持つテストセットを構築

**作成ファイル:**
```
test_instances_django_43.txt
  - 内容: Django 共通インスタンス全43個
  - グラフサイズ: 全て 35-47MB（適切）
  - 用途: Phase 1 実験のメイン対象

test_instances_sympy_10_verified_lite_common.txt
  - 内容: Sympy 共通インスタンス10個（当初案）
  - グラフサイズ: 549MB-597MB（全て不適切）
  - 判定: 使用不可

test_instances_verified_lite_filtered.txt
  - 内容: 複数プロジェクト混在10個（当初案）
  - 内訳: Sympy 3個 + Django 4個 + Matplotlib 3個
  - グラフサイズ: Sympy は大きい（使用保留）
  - 判定: 部分的に使用可能
```

**推奨:**
```
Phase 1 実験用: test_instances_django_43.txt
  - 43個の適切なサイズのインスタンス
  - 統計的に有意な結果が期待できる
  - すぐに実施可能
```

---

### 7. **グラフ生成スクリプト作成**
**ファイル:** `generate_graphs.py`

**用途:** Verified testbed から新規グラフを生成する場合に使用

**使用方法:**
```bash
python generate_graphs.py \
  test_instances_django_43.txt \
  cache/code_graphs
```

**機能:**
- 複数インスタンスの一括グラフ生成
- graph.pkl と tags_*.json の自動生成・保存
- エラーハンドリングとログ出力

---

## 📁 成果物一覧

### 計画書・ドキュメント
| ファイル | 内容 |
|---------|------|
| `phase1_repograph_integration.md` | 完全な統合計画書（セクション 1-9） |
| `ACCOMPLISHMENTS_2025_11_05.md` | 本ファイル（成果物まとめ） |

### 実装ファイル
| ファイル | 変更内容 |
|---------|--------|
| `patchpilot/fl/repograph_utils.py` | Composite Score 実装完了 |
| `patchpilot/fl/localize.py` | グラフコンテキスト統合（機能確認済み） |
| `patchpilot/fl/FL.py` | グラフコンテキスト使用コード確認済み |

### テストデータ
| ファイル | 内容 | インスタンス数 |
|---------|------|------------|
| `test_instances_django_43.txt` | Django 共通インスタンス | 43個 |
| `test_instances_verified_lite_filtered.txt` | 複数プロジェクト混在 | 10個 |
| `test_instances_sympy_10_verified_lite_common.txt` | Sympy 共通（不適切） | 10個 |

### ユーティリティ
| ファイル | 用途 |
|---------|-----|
| `generate_graphs.py` | グラフ生成スクリプト |

---

## 📈 数値サマリー

### データセット規模
```
ベンチマーク別:
  Verified（PatchPilot 対象）: 790インスタンス
  Lite（RepoGraph 基盤）:      300インスタンス
  共通:                       78インスタンス

プロジェクト別共通インスタンス:
  Django:    43個 ✓ 実験可能
  Sympy:     22個 ✗ グラフサイズ問題
  Matplotlib: 7個 ✓ グラフサイズ適切
```

### グラフサイズ分析
```
Django（35-47MB）:
  - メモリ効率: 優良
  - プロンプト超過リスク: 低

Sympy（91MB-1.9GB）:
  - メモリ効率: 低（大部分が大きい）
  - プロンプト超過リスク: 高
  - 利用可能: 91-94MB の 11個のみ

Matplotlib（53-56MB）:
  - メモリ効率: 良好
  - プロンプト超過リスク: 低
```

### 実験結果
```
Composite Score 効果:
  Sympy:        +9.5pp
  Django:       -6.4pp
  Matplotlib:   -7.5pp

平均:           -1.5pp（悪化傾向）
※ LLM モデル差（gpt-4o-mini）の可能性を考慮
```

---

## 🎯 次のステップ（推奨）

### Phase 1: Django 43個での Composite Score 効果測定（推奨）
```
1. reproduce フェーズ
   コマンド: python patchpilot/reproduce/reproduce.py \
     --reproduce_folder results/reproduce_django_43_20251105 \
     --num_threads 4 \
     --setup_map setup_result/verified_setup_map.json \
     --tasks_map setup_result/verified_tasks_map.json \
     --task_list_file test_instances_django_43.txt

2. localization フェーズ（baseline と repograph の両方）
   - baseline: --repo_graph フラグなし
   - repograph: --repo_graph フラグあり

3. repair フェーズで結果比較

4. 統計分析
```

**メリット:**
- 43個で統計的に有意な結果が期待できる
- グラフサイズが全て最適範囲内
- すぐに実施可能

### Phase 2: Sympy グラフの最適化（オプション）
```
- グラフサイズ削減の方法検討
- max_tags のさらなる削減（50 → 20 or 10）
- 新規グラフ生成オプションの検討
```

### Phase 3: 複数プロジェクト比較
```
- Django（ファイル距離が有効）
- Matplotlib（グラフサイズが適切）
- Sympy（グラフが複雑）
での効果を比較
```

---

## 🔍 主要な発見と学習

### 誤解が解けたこと
1. **グラフ全体がプロンプトに入る**
   - ❌ 誤解
   - ✅ 実際: 特定関数に関連する 50個のタグのみ抽出

2. **グラフサイズ = コンテキスト超過の直接原因**
   - ❌ 簡単な因果関係ではない
   - ✅ 実際: found_related_locs の関数数に依存

3. **graph.pkl が必須**
   - ❌ tags.json のみで十分
   - ✅ code_graph は定義されているが、実装ではtags.jsonから直接タグを抽出

### 新しく理解したこと
1. **1-hop neighbors の正体**
   - 「その関数を呼び出している関数」「その関数が呼び出している関数」の両方

2. **Composite Score の有効性**
   - プロジェクト依存（Sympy では +9.5pp）
   - ファイル構造とグラフ構造の相性が重要

3. **ベンチマーク間のズレ**
   - PatchPilot: Verified 想定
   - RepoGraph: Lite 基盤
   - 完全なパイプライン評価には共通インスタンスのみが使用可能

---

## 📝 参考資料

- **計画書全文:** `phase1_repograph_integration.md`
- **実装コード:** `patchpilot/fl/repograph_utils.py`
- **README:** `RepoGraph/README.md`
- **Docker 設定:** `docker-compose.yml`

---

**作成日:** 2025-11-05  
**作者:** Claude Code  
**ステータス:** 調査完了、Phase 1 実験準備完了
