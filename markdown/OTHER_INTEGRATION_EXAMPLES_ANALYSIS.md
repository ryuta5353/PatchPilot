# RepoGraph 複数フレームワーク統合の詳細比較分析

**作成日**: 2025-11-10
**重要性**: ⭐⭐⭐⭐⭐ 統合戦略の決定的な違いを解明

---

## 統合されたフレームワーク一覧と成果

### 論文での評価対象（Table 3）

| フレームワーク | タイプ | Baseline | +RepoGraph | 改善 | 相対改善 |
|-------------|--------|---------|-----------|------|---------|
| **RAG** | Procedural | 2.67% | 5.33% | +2.66pp | +99.6% |
| **Agentless** | Procedural | 27.33% | 29.67% | +2.34pp | +8.6% |
| **AutoCodeRover** | Agent | 19.00% | 21.33% | +2.33pp | +12.3% |
| **SWE-agent** | Agent | 18.33% | 20.33% | +2.00pp | +11.0% |

**ユーザーの実装（PatchPilot Phase 2-6）**:
```
Baseline (Agentlessに準じた): 77.8%
+ RepoGraph: 72.2%
悪化: -5.6pp
```

---

## 1. Agentless (Procedural Framework) - 最も成功

### 実装アプローチ

**決定論的フロー**:
```
入力：GitHub Issue
  ↓
[Step 1] ファイルレベルのLocalization
  - 機能的に全体像を把握
  ↓
[Step 2] 関数/クラスレベルのLocalization
  - 修復対象を絞り込む
  ↓
[Step 3] 行レベルの編集位置特定
  - 正確な修復行を特定
  ↓
出力：修復パッチ
```

### RepoGraph の統合方法

**位置**：各ステップの「Function/Class Dependencies」セクション

```
### GitHub Issue Description ###
[issue text]

### Repository Context ###
[file structure]

### Function/Class Dependencies ###
[RepoGraph ego-graph context]  ← ここに k=1 の親構造を挿入

### Instructions ###
[task instructions]
```

**グラフコンテキストのサイズ**：
- k=1 direct flattening: 2,311 トークン
- 形式：「関数Xは関数Yから呼び出される」という依存関係を明示的に記載

**成果**：
```
27.33% → 29.67% (+2.34pp)
決定論的フローのおかげで、グラフコンテキストが効果的に機能
```

---

## 2. SWE-agent (Agent Framework) - 中程度の改善

### 実装アプローチ

**試行錯誤フロー（Agent-based）**:
```
State: [Current Code Understanding]
  ↓
Action Space:
  - search() : リポジトリ検索
  - edit() : コード編集
  - search_repograph() : グラフ検索 ← RepoGraph追加アクション
  ↓
Agent が以下を決定：
  1. 次に何をするか
  2. search_repograph() を呼び出すか
  3. 検索キーワードは何か
  ↓
State: [Updated Understanding]
```

### search_repograph() アクション

**署名**:
```python
def search_repograph(search_term: str) -> dict:
    """
    Agentが指定したsearch_termについて、
    k-hop ego-graphを取得して返す
    """
    # 返り値: 関連関数の定義と参照情報
    return {
        'definitions': [...],
        'references': [...],
        'call_graph': [...]
    }
```

**Agentの意思決定**：
```
Agent の思考：「CheckError関数が何をしているかわからない。
                グラフで呼び出し元を調べてみよう」
  ↓
Action: search_repograph("CheckError")
  ↓
Response: CheckError の1-hopグラフ情報
  ↓
Agent が次の行動を決定
```

### 呼び出しパターン

**頻度**：
- 最初の15ラウンドでほとんどの呼び出し
- ピークの後は減少

**コスト**：
```
1回の search_repograph() 呼び出し: 2,311トークン程度
1タスクあたりの平均トークン: +$0.13-0.18（追加コスト）
トークン爆発の危険性あり
```

**成果**：
```
18.33% → 20.33% (+2.00pp)
手数がかかるが、グラフ情報が役立つ局面あり
```

---

## 3. AutoCodeRover (Agent Framework) - SWE-agent より高い改善

### 実装アプローチ

**SWE-agent に類似しているが、より構造化**：
```
AutoCodeRover の特徴：
  - リポジトリ構造を事前に解析
  - Project structure aware
  - Agentがより効率的に検索可能

RepoGraph 統合：
  - search_repo() アクションを追加
  - インデックス化されたグラフから効率的に取得
```

### 実装の最適化

```python
# AutoCodeRover での実装の推測
class AutoCodeRoverAgent:
    def __init__(self):
        self.repo_structure = parse_structure()  # 事前解析
        self.code_graph = build_graph()  # グラフ事前構築

    async def search_repo(self, term: str):
        """最適化されたグラフ検索"""
        # インデックスを使用した高速検索
        return self.code_graph.get_k_hop_neighbors(term, k=1)
```

**成果**：
```
19.00% → 21.33% (+2.33pp)
SWE-agent より若干高い改善
理由：リポジトリ構造の事前理解が、グラフ活用を最適化
```

---

## 4. 我々の実装（PatchPilot Phase 2-6）- 失敗

### 実装アプローチ

```
Localization の Fine-Grain Level で：

  ├─ グラフコンテキスト生成 (construct_code_graph_context)
  │  ├─ found_related_locs から全ロケーションを取得
  │  ├─ Composite Score で関連度判定
  │  │  ├─ ファイル近接性: 1000/100/1
  │  │  ├─ 直接隣人ボーナス: +50
  │  │  └─ In-degree: 0-10
  │  ├─ Greedy allocation で トークン配分
  │  │  └─ max_tokens_this_section = remaining_budget / sections_remaining
  │  └─ 113 ロケーション, 28,323トークン
  │
  └─ プロンプト構築 (FL.py)
     ├─ ファイルコンテキスト + グラフコンテキスト
     ├─ トークン数チェック
     └─ 超過時はフォールバック（他の内容削減）
```

### 問題点の詳細

**1. グラフサイズの過度な膨張**
```
論文（最適）: 2,311トークン
論文（避けるべき）: 10,505トークン
我々: 28,323トークン（最適の 12倍！）
```

**2. 複雑なComposite Score**
```
論文: 構造的距離（k-hop）のみ
我々: ファイル近接性 + 隣人ボーナス + In-degree

結果: スコアの精度が落ち、無関連な関数が混在
```

**3. Greedy Allocation の失敗**

```
論文での仮定: グラフが小さい（2,311トークン）
              → 他の内容削減不要

我々での現実: グラフが大きい（28,323トークン）
             → ファイルコンテキスト削減必須（-50,182トークン）

結果: 修復対象のコンテキストが不足
```

**4. 決定論的でない統合**
```
論文（Agentless）:
  - Step 1 → Step 2 → Step 3 → 完了
  - 各ステップで グラフ情報が有効

我々:
  - Fine-Grain Level のみでグラフ使用
  - 関連度判定が複雑
  - 統合点が限定的
```

**成果**：
```
77.8% → 72.2% (-5.6pp) ✗ 逆効果
```

---

## フレームワーク別の統合パターン

### Procedural Framework（Agentless）の特徴

**メリット**:
```
✓ 決定論的フロー
✓ グラフコンテキストの位置が明確
✓ 各ステップで一貫した情報量
✓ トークン管理が容易
✓ エラー蓄積がない
```

**グラフ統合の最適性**:
```
フロー全体で グラフ情報を活用
  ↓
各ステップで意思決定が改善される
  ↓
結果：最大の改善（+2.34pp）
```

**実装の単純さ**:
```
1. プロンプトテンプレートに セクション追加
2. グラフ検索 1回
3. フラッテン & 挿入
完了
```

---

### Agent Framework（SWE-agent, AutoCodeRover）の特徴

**メリット**:
```
✓ 柔軟な意思決定
✓ 複雑な問題に対応
✓ グラフ活用を動的に選択可能
```

**デメリット**:
```
✗ エラー蓄積（小さなミス → 大きな失敗）
✗ グラフ呼び出し爆発の危険性
✗ トークン管理が複雑
✗ 不確定な動作（最適でない選択の可能性）
```

**グラフ統合の課題**:
```
Agent が「いつ」「何を」検索するか を決定
  ↓
不適切な検索 → 無関連な情報取得
  ↓
Agent の判断が狂う（エラー蓄積）
  ↓
結果：改善は限定的（+2.00-2.33pp）
```

**実装の複雑さ**:
```
1. search_repograph() アクション追加
2. Agent の推論で何を検索するか決定
3. 呼び出し制御（過度な呼び出し防止）
4. レスポンス処理
複雑！
```

---

## 比較分析：なぜ我々の実装は失敗したのか

### 失敗要因の対照表

| 要因 | 論文（成功） | 我々の実装（失敗） | 理由 |
|------|-----------|-----------------|------|
| **グラフサイズ** | 2,311トークン | 28,323トークン | Composite Scoreが大量の不要な関数を含める |
| **ホップ距離** | k=1（固定） | k=∞（無制限） | 論文では避けると明記された 2-hop 以上を採用 |
| **スコアリング** | 構造的距離のみ | 複合スコア | 複雑さが関連度精度を低下 |
| **トークン管理** | 充分 | 不足 | Greedy allocation が実装と現実の乖離 |
| **フロー** | 決定論的（Procedural） | 非決定論的（Fine-Grain のみ） | 統合ポイントが限定的 |
| **結果** | +2.34pp ✓ | -5.6pp ✗ | グラフが有害化 |

---

## 論文での明確な警告を見落とした点

### 警告 1: k≥3 は探索しない

> "We limit our exploration to k values up to 2 due to the extensive context
> required for integration and the potential introduction of noise or irrelevant nodes."

**我々**: 113 ロケーション（k=∞相当）を収集

### 警告 2: 2-hop でパフォーマンス悪化

> "2-hop variants performed worse when simply flattened"

**1-hop direct**: 29.67% （最高）
**2-hop direct**: 26.00% （低下）

**我々**: 28,323トークン（2-hop より大）→ 72.2%（低下）

### 警告 3: LLM サマリゼーションの落とし穴

> "For 1-hop, direct flattening achieved 29.67%;
> summarization degraded to 28.33%"

**教訓**: 情報圧縮は1-hopでは不要（かえって悪い）

**我々**: Complex Score という「圧縮」を導入 → 情報喪失

---

## 推奨される統合パターン

### パターン1: Agentless-style（推奨）

```
利点: 論文で最も成功している実装

実装:
1. Localization の各ステップで グラフ情報を挿入
2. k=1, direct flattening のみ（2,311トークン）
3. "Function/Class Dependencies" セクションに明確に配置
4. Composite Score は使わない

期待結果: +2.34pp の改善
```

### パターン2: SWE-agent-style

```
利点: 複雑な問題に対応可能

実装:
1. search_repograph() アクション追加
2. Agent が動的に検索タイミングを決定
3. k=1 ego-graph のみ取得
4. 呼び出し回数制御（10回程度/タスク）

期待結果: +2.00pp の改善
コスト: +$0.13-0.18/タスク
```

### パターン3: 我々の改善版（Phase 2-7）

```
現状から最小変更で改善：

1. グラフサイズ削減
   max_hops = 1  # k=1に制限
   → 28,323 → 2,311トークン

2. Composite Score 削除
   # シンプルな構造的距離のみ

3. トークン予算現実化
   total_token_budget = 2,311  # 硬コード

期待結果: -5.6pp → +5.6pp への転換
リスク: 低（論文の実装をコピー）
```

---

## 実装の複雑性による失敗

### 論文の哲学

```
設計原則: Simplicity is Strength

グラフ統合の本質:
  - k=1 ego-graph で十分
  - 構造的距離の情報だけで効果的
  - 複雑なスコアリングは不要

実装の単純さ:
  - Agentless: わずか数行の変更
  - SWE-agent: アクション1つ追加
  - AutoCodeRover: インデックス活用
```

### 我々の複雑化

```
設計選択: More is Better（間違い）

導入した複雑さ:
  ✗ Composite Score（4つの要素）
  ✗ Greedy Allocation（段階的配分）
  ✗ def/ref タグ分別
  ✗ 113 ロケーション収集
  ✗ 複数セクション分割

結果:
  複雑さ ∝ バグの可能性
  複雑さ ∝ トークン消費
  複雑さ ∝ パフォーマンス低下
```

---

## 最終的な改善シナリオ

### 短期修正（本日～1週間）

**Phase 2-7a: グラフサイズ制限**

```python
# 変更1: construct_code_graph_context への k=1 制限
graph_context = construct_code_graph_context(
    found_related_locs,
    code_graph,
    graph_tags,
    structure,
    max_hops=1,  # ← 追加
    total_token_budget=2311,  # ← 変更
    preferred_files=pred_files,
    logger=logger
)

# 変更2: Composite Score 削除
def calculate_composite_score(tag, ...):
    # 複雑さ削除
    return code_graph.in_degree(tag['name'])  # シンプルなみ
```

**期待**: -5.6pp → -2.0pp 程度に改善

### 中期改善（1-2週間）

**Phase 2-7b: 論文の実装に準じる**

```
1. Agentless の統合アプローチを完全採用
2. all localization steps で graph context を使用
3. プロンプトテンプレートを再設計

期待: -5.6pp → +2.0-2.5pp の改善
```

### 長期戦略（2-3週間）

**Phase 2-8: Agent Framework の採用検討**

```
Agentless-style が +2.34pp なら、
SWE-agent-style で +2.00pp
AutoCodeRover-style で +2.33pp

複数実装を試し、最適なパターンを選択
```

---

## 結論：なぜグラフベース統合は複雑なのか

### グラフ統合の本質的課題

```
グラフは便利だが、危険
  ↓
情報量が多い → トークン圧迫
  ↓
圧迫を解決するため複雑化 → バグ増加
  ↓
複雑さ → パフォーマンス低下
```

### 論文での解決策

```
シンプルに保つ
  ↓
k=1 ego-graph（2,311トークン）で十分
  ↓
構造的距離のみで関連度判定
  ↓
プロンプトテンプレートへの明確な挿入
  ↓
結果：最小限の複雑さで最大の効果（+5.6pp）
```

### 我々が取るべき行動

```
複雑さを削減する
  ↓
論文の実装をコピーする
  ↓
シンプルな実装で再評価
  ↓
改善を実測
  ↓
成功 → 論文の実装が正しかったことを証明
```

---

**参考資料**:
- RepoGraph 論文: https://arxiv.org/html/2410.14684v1
- Table 3: フレームワーク別結果
- Figure 4: Agentless prompt structure
- Figure 8: Agent framework call frequency

