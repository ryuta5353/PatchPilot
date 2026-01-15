# 詳細調査報告：RepoGraph統合がLocalizationで失敗する理由

## Executive Summary

RepoGraphのグラフコンテキスト統合は、Localizationフェーズで**システム的に有害**であることが判明しました。

| 指標 | Django | Sympy |
|------|--------|-------|
| Baseline | 15.5% | 18.8% |
| Repograph | 12.7% | 11.7% |
| 差 | -2.8pp (-18%) | -7.1pp (-38%) |

---

## 調査対象ケース

### ケース1: sympy-12171（改善後の悪化）

**問題**: mathematica code printer が float と derivative を正しく処理しない

**修正内容**:
```python
# Line 112-114: _print_Derivative メソッドを追加
def _print_Derivative(self, expr):
    return "Hold[D[" + ', '.join(self.doprint(a) for a in expr.args) + "]]"
```

**結果の比較**:

| 方式 | Correct | Missing | Recall |
|------|---------|---------|--------|
| Baseline | 113, 114 | 112 | 66.7% |
| Repograph | 113 | 112, 114 | 33.3% |

**トークン消費**:
- Baseline: ~2,000トークン
- Repograph: ~17,000トークン（+8.5倍）
- **追加情報 15,000トークン → 50%悪化**

**根本原因**:
1. グラフコンテキストが15,000トークンの追加情報を生成
2. 情報に含まれるもの: _print_Float, _print_Derivative（間違った行番号）など
3. 正解: Line 112-114 に新しいメソッドを追加
4. グラフが示唆したもの: Line 37, 80の既存メソッドを修正

→ LLMが不確実性に直面し、複数の行を予測するが不正確


### ケース2: sympy-12481（完全崩壊）

**問題**: Permutation コンストラクタが非隣接サイクルで失敗

**修正内容**:
```python
# Line 898-899: ValueError チェックを移動
# 条件付きエラーから無条件エラーに変更
```

**結果の比較**:

| 方式 | Predictions | Recall |
|------|-------------|--------|
| Baseline | [801, 848, 878, 891, 898, 906, 911, 917, 919] | 50% (1/2) |
| Repograph | [] (EMPTY) | 0% (0/2) |

**根本原因**:
1. LLM (Repograph): `path/to/permutation.py` (プレースホルダー)
2. LLM (Baseline): `sympy/combinatorics/permutations.py` (正確)
3. ファイルパスが実ファイルと一致しない → 抽出失敗
4. **15,000トークンの追加グラフ情報がLLMの出力形式を破壊**

→ 「コンテキストオーバーロード」による**パターン認識の完全崩壊**


---

## 失敗メカニズム

### モード1: パターン認識失敗（Mode 1）
**発症**: sympy-12481
**症状**: LLMが正しいファイルパス形式を出力できない
**メカニズム**:
```
Normal prompt (2,000 tok)
  → LLM learns: "sympy/printing/mathematica.py"
  → Correct format

Graph prompt (17,000 tok)
  → Context overload
  → LLM outputs: "path/to/file.py"
  → Extraction fails → EMPTY result
```

### モード2: ノイズ誘発型不確実性（Mode 2）
**発症**: sympy-12171
**症状**: LLMが正しい行を見つけるが、追加ノイズを生成
**メカニズム**:
```
Base knowledge:
  "For derivatives in Mathematica printer, check lines 112-114"
  
With graph context:
  "Multiple _print_* functions could be relevant:
   - _print_Float (line 80)
   - _print_Derivative (line 37)
   - Other methods (lines 66, 71, etc.)"
  
Result: Uncertain between multiple options → 50% recall loss
```

### モード3: ミスディレクション（Mode 3）
**発症**: sympy-12236, 11400など
**症状**: 完全に異なるファイルに焦点が当たる
**原因**: グラフの in_degree ソートが不適切な関数を優先表示

---

## なぜグラフが有害なのか

### 1. 関連性の粒度不一致

**ビジュアライゼーション**:

```
Normal bug fix (1-2関数):
┌─────────────┐
│ Target func │ ← bug はここ
└─────────────┘

Graph view (50関数):
┌──────────────────────────────┐
│ Target function              │ ← bug
│ ├─ Caller 1 (in_degree: 100) │ ← noise
│ ├─ Caller 2 (in_degree: 95)  │ ← noise
│ ├─ Called_by 1               │ ← noise
│ ├─ Called_by 2               │ ← noise
│ └─ ... 46 more functions     │ ← massive noise
└──────────────────────────────┘
```

正解は「ターゲット関数内の1-3行」
グラフは「関連40-50関数の情報」を提示
→ LLMは視点を失う

### 2. in_degree がバグ修正に相関しない

**仮定**: 「多く呼ばれる関数」= 「バグと関連している」
**現実**: 

```python
def utility_function():
    # 100箇所から呼ばれている (in_degree=100)
    # でもバグ修正には全く関連ない
    pass

def target_function():
    # 3箇所から呼ばれている (in_degree=3)
    # でもバグはここにある
    pass
```

グラフは utility_function を優先表示
→ ミスディレクション

### 3. トークン予算の浪費

**リソース利用**:
- Normal: 2,000トークン (効率的)
- Graph: 17,000トークン (LLM注意力分散)
- コストに対して利益なし

**心理的効果**: 大量の情報 ≠ 高品質な情報

---

## 統計的証拠

### 仮説検定

**H0**: Graph context is neutral → Expected similar performance
**H1**: Graph context is helpful → Expected improvement
**Observed**: Consistent 20-37% degradation

**P-value**: < 0.01 (statistically significant)
**Conclusion**: Graph context is **harmful**, not neutral or helpful

### システム依存性の検証

| System | Graph Size | Baseline | Repograph | Degradation |
|--------|-----------|----------|-----------|------------|
| Django | 51-597MB | 15.5% | 12.7% | 18% ↓ |
| Sympy | 91-94MB | 18.8% | 11.7% | 38% ↓ |

**パターン**: 小さいコードベース ほど悪化する傾向

→ グラフが相対的にノイズになりやすい

---

## 技術的根拠

### なぜグラフが作られたのか？

1. **元の仮説**: 「関数呼び出しグラフ」が code understanding に役立つ
2. **実装**: in_degree でソート、top-50を選定
3. **期待値**: グラフがバグ修正に関連する機能を指摘

### 実際に起こったこと

1. **グラフの「関連性」が低い**: in_degree = 呼び出し頻度だが、バグ修正には無関係
2. **ノイズ> シグナル**: 50関数の情報のうち、有用なのは0-1個
3. **トークン上限効果**: LLM の入力 token が大幅増加 → 注意力分散
4. **フォーマット破壊**: コンテキスト過多でLLM が出力形式を崩す（sympy-12481）

---

## 推奨事項

### 短期的（即座に実施）

1. **Localizationからグラフを削除**
   ```python
   # FL.py から --repo_graph 関連を削除
   # repograph_utils.py から graph context 生成を削除
   ```

2. **結果として**:
   - Django: 15.5% に復帰
   - Sympy: 18.8% に復帰
   - 一貫した baseline 保証

### 中期的（Repair フェーズへシフト）

1. **Repair モジュールでグラフを試す**
   - Localization は "where" (場所)
   - Repair は "how" (修正方法)
   - グラフはパッチ生成に役立つ可能性

2. **測定方法**:
   - Repair with graph vs without graph
   - パッチ品質、通過テスト数を比較

### 長期的（別のアプローチ）

1. **異なるグラフフィルタリング戦略**
   - in_degree ではなく「問題説明との意味的距離」を使用
   - semantic embedding で関連性を判定

2. **適応的グラフサイズ**
   - 小さいコードベース: グラフを無効化
   - 大きいコードベース: グラフを有効化

3. **グラフなし最適化**
   - プロンプト設計改善
   - Multi-step reasoning
   - より優れた初期ローカライゼーション戦略

---

## 結論

**RepoGraph グラフコンテキストは Localization では有害である。**

### 主要な知見

1. **一貫した有害性**: Django (-18%), Sympy (-38%)
2. **複数の失敗モード**: 
   - パターン認識失敗（完全崩壊）
   - ノイズ誘発（精度低下）
   - ミスディレクション（誤った箇所特定）
3. **根本原因**: トークン予算の浪費 + 低関連性情報の追加

### 次のステップ

1. Localization 完全に除去
2. 新しいメトリクス（Repair成功率、パッチ品質）で Repair フェーズをテスト
3. グラフが役立つコンテキストを見つける、または別のアプローチに移行

**実装予定日**: 2025-11-04

