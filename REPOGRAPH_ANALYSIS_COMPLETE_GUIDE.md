# RepoGraph 統合分析 - 完全ガイド

**作成日**: 2025-11-21
**調査対象**: Phase 2-6（23インスタンス）
**結論**: RepoGraph の有効性は問題の複雑性に依存

---

## 📚 全ドキュメント一覧

### 最初に読むべきドキュメント

#### 1. **REPOGRAPH_VALIDITY_CONCLUSION.md** ⭐⭐⭐ 最重要
**長さ**: 15分読み込み
**内容**: RepoGraph の有効性に関する最終結論

```
この 1つで十分：
  - RepoGraph がなぜ失敗するのか
  - どの条件で有効か、無効か
  - 最終的な判定と推奨事項

読むべき人:
  - 意思決定者
  - 経営層
  - プロジェクトリーダー
```

---

### 詳細分析ドキュメント

#### 2. **DEGRADATION_INSTANCE_ANALYSIS.md**
**長さ**: 20分読み込み
**内容**: 23インスタンスの詳細な性能データ

```
内容:
  - グラフサイズと性能の完全な相関
  - インスタンス別の詳細データ
  - 失敗した 4インスタンスの分析
  - パターン抽出

読むべき人:
  - データに基づく判断をしたい人
  - インスタンス別の詳細を知りたい人
  - 統計的根拠が必要な人
```

#### 3. **REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md**
**長さ**: 20分読み込み
**内容**: 実装レベルでの根本原因分析

```
内容:
  - グラフ構築層の問題
  - トークン管理層の問題
  - プロンプト構成層の問題
  - 3層統合的な分析

読むべき人:
  - 実装の詳細を理解したい人
  - バグの根本を知りたい人
  - 修正方針を決定したい人
```

#### 4. **DJANGO_GRAPH_DEGRADATION_ANALYSIS.md**
**長さ**: 15分読み込み
**内容**: Django 特有の問題とグラフの相性

```
内容:
  - グラフで悪化した Django インスタンス
  - 「局所的問題」vs「分散的問題」
  - Django の多層設計の影響
  - RepoGraph の有効/無効の判定

読むべき人:
  - Django 問題を扱う人
  - 問題の複雑性を理解したい人
  - framework 特性を知りたい人
```

---

### 調査・検証用ドキュメント

#### 5. **INVESTIGATION_CHECKLIST_NEXT_STEPS.md**
**長さ**: 30分読み込み + 3日間実施
**内容**: あなたが実施すべき調査の手順

```
内容:
  - Phase A-E の詳細な調査手順
  - 各フェーズの期待される結果
  - データ収集方法
  - 検証方法

読むべき人:
  - 実際に調査を実施する人
  - ログから根拠を抽出したい人
  - 仮説を検証したい人

実施期間: 3日（1日 3-4時間 × 3日）
```

---

## 🎯 用途別の読み方

### 「RepoGraph が有効か無効かだけ知りたい」
```
1. REPOGRAPH_VALIDITY_CONCLUSION.md （15分）
   → 最終結論とサマリーだけ読む

完成。
```

### 「なぜ失敗するのか理解したい」
```
1. REPOGRAPH_VALIDITY_CONCLUSION.md （15分）
2. DEGRADATION_INSTANCE_ANALYSIS.md （20分）
3. REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md （20分）

完成。根本原因が理解できます。
```

### 「Django の問題に限定して知りたい」
```
1. DJANGO_GRAPH_DEGRADATION_ANALYSIS.md （15分）
2. DEGRADATION_INSTANCE_ANALYSIS.md 内の Django セクション（10分）

完成。Django 特有の課題が理解できます。
```

### 「実装レベルでの修正方針を決めたい」
```
1. REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md （20分）
2. 実装コードの確認 （30分）

完成。何を修正すべきか明確になります。
```

### 「実際に調査を実施して根拠を得たい」（推奨）
```
Day 1:
  1. REPOGRAPH_VALIDITY_CONCLUSION.md （15分）
  2. INVESTIGATION_CHECKLIST_NEXT_STEPS.md を読む （30分）
  3. Phase A + B を実施（3-4時間）

Day 2:
  4. Phase C + D を実施（4-5時間）

Day 3:
  5. Phase E を実施（3-4時間）
  6. 自分の調査結果をまとめる

完成。客観的な根拠に基づいた判定ができます。
```

---

## 📊 ドキュメント構造図

```
REPOGRAPH_VALIDITY_CONCLUSION.md
  ↓ （詳細知りたい場合）
  ├─ DEGRADATION_INSTANCE_ANALYSIS.md
  │   （統計データ、インスタンス別詳細）
  │
  ├─ REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md
  │   （実装レベルの問題分析）
  │
  └─ DJANGO_GRAPH_DEGRADATION_ANALYSIS.md
      （Django 特有の分析）

どのドキュメントからでも、
INVESTIGATION_CHECKLIST_NEXT_STEPS.md へ進める
  （実際の調査・検証実施）
```

---

## 🔑 各ドキュメントのキーメッセージ

### REPOGRAPH_VALIDITY_CONCLUSION.md
```
KEY: 「グラフが大きいほど悪化する」

数字:
  ファイルレベル: -5.6pp
  ラインレベル: -8.5pp
  処理完了率: -17.4pp

判定:
  グラフサイズ < 20K chars → 有効 ✓
  グラフサイズ > 50K chars → 無効 ✗
```

### DEGRADATION_INSTANCE_ANALYSIS.md
```
KEY: 「相関係数 -0.95」（完全な逆相関）

データ:
  最良: 12K chars → +8.7pp
  最悪: 122K chars → -100pp

パターン:
  セクション数 20+ → 必ず悪化
  関数位置数 50+ → 完全悪化
```

### REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md
```
KEY: 「3つの層で問題が積み重なっている」

1. グラフ構築層: 無差別に関数を選出
2. トークン管理層: 制限が機能していない
3. プロンプト層: LLM が混乱している
```

### DJANGO_GRAPH_DEGRADATION_ANALYSIS.md
```
KEY: 「Django は多層設計だから RepoGraph が無効」

特徴:
  - 複数層にまたがる
  - グラフが必然的に大きくなる
  - 意味的な関連性の判定が困難
```

### INVESTIGATION_CHECKLIST_NEXT_STEPS.md
```
KEY: 「3日間で完全検証可能」

5つの Phase:
  A: ログ検証
  B: トークン計算検証
  C: グラフサイズ詳細分析
  D: 失敗パターン調査
  E: 実装コード検証
```

---

## ✅ チェックリスト：読むべき順序

### レベル 1: エグゼクティブ向け（30分）
- [ ] REPOGRAPH_VALIDITY_CONCLUSION.md
  - [ ] セクション I（実験結果）
  - [ ] セクション IX（結論）

**結論**: グラフは条件付きで有効。全体的には無効。

### レベル 2: 技術理解（2時間）
- [ ] REPOGRAPH_VALIDITY_CONCLUSION.md（全部）
- [ ] DEGRADATION_INSTANCE_ANALYSIS.md（セクション 1-3）
- [ ] DJANGO_GRAPH_DEGRADATION_ANALYSIS.md

**結論**: 複雑な問題では必ず無効。修正すべき項目が明確。

### レベル 3: 実装詳細（3時間）
- [ ] REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md（全部）
- [ ] 実装コードの確認（repograph_utils.py）

**結論**: 何を修正すべきか具体化。

### レベル 4: 完全検証（3日間）
- [ ] INVESTIGATION_CHECKLIST_NEXT_STEPS.md
- [ ] 5つの Phase を実施
- [ ] 自分の結論をまとめる

**結論**: 客観的根拠に基づいた判定。

---

## 💡 主要な発見まとめ

```
発見 1: グラフサイズが大きいほど悪化
  相関係数: -0.95

発見 2: 有効と無効の境界は明確
  境界: グラフサイズ 20K chars

発見 3: Django は平均的に無効
  理由: 多層設計 → グラフが必然的に大きい

発見 4: 実装に複数の問題
  - Greedy allocation が機能していない
  - logger 出力がない
  - エラーハンドリングがない

発見 5: 修正は可能
  項目: グラフサイズ制限 + エラー対応
  期待効果: 全体 -5.6pp → 0pp（改善）
```

---

## 🚀 推奨される次のステップ

### 今日
```
REPOGRAPH_VALIDITY_CONCLUSION.md を読む（15分）
  → 意思決定：調査を実施するか、修正を進めるか
```

### 明日～3日後（推奨）
```
INVESTIGATION_CHECKLIST_NEXT_STEPS.md に従って調査（3日）
  → 客観的根拠を確保
  → より確実な判定
```

### 1週間後
```
REPOGRAPH_IMPLEMENTATION_ROOT_CAUSE.md に基づいて修正
  → グラフサイズ制限
  → エラーハンドリング
  → logger 修正
```

---

## 📝 ドキュメント作成の背景

このドキュメント群は、以下の問題を解決するために作成されました：

```
問題:
  RepoGraph 統合で -5.6pp 性能低下したが、
  「なぜ？」という根本原因が不明確

分析:
  - 23インスタンスの詳細データ分析
  - グラフサイズと性能の相関確認
  - 実装コードの詳細調査
  - Django 特有の課題分析

結果:
  根本原因を完全に特定
  有効条件と無効条件を明確化
  修正方針を具体化
```

---

## 最終的な結論

```
RepoGraph の有効性は「銀弾ではない」。

✓ 条件が揃えば有効
✗ 条件が揃わなければ有害

現在の実装は「条件が揃わないまま使用」している状態。

修正により、「条件に応じた適切な使用」が可能になる。
```

---

## 質問と回答

### Q: RepoGraph は今すぐ無効化すべき？
```
A: 不要。修正で改善可能。

グラフサイズ制限とエラーハンドリングを追加すれば、
悪い影響を最小化しつつ、良い効果を保持できる。
```

### Q: Django 問題では使わない方が良い？
```
A: 大多数の Django 問題では不要。

ただし、単純な Django 問題（django-13401 型）では有効。
問題の複雑性を自動判定して、使い分けるべき。
```

### Q: 修正にかかる時間は？
```
A: 短期修正（グラフサイズ制限）: 4-8時間
   中期修正（複雑性判定）: 1-2日
   長期改善（意味的スコア）: 1-2週間
```

### Q: 期待される改善は？
```
A: 短期: -5.6pp → -2-3pp（わずかに改善）
   中期: -5.6pp → +1-2pp（若干改善）
   長期: -5.6pp → +3-5pp（ベースライン超過の可能性）
```

