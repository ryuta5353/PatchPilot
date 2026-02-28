# Phase 2-6 Investigation: Complete Summary

**実装機能**: Greedy Dynamic Token Allocation (動的トークン配分)
**実装状況**: コード実装されているが、デバッグ出力が不適切 + トークン予算超過
**結果**: ファイルレベル改善 (+5.3pp) vs ラインレベル悪化 (-8.5pp)

---

## Critical Finding: Graph Context Quality vs Size Trade-off

### The Core Issue
**ラインレベルが悪化した根本原因**: グラフコンテキストが大きすぎて、LLMを混乱させている。

**証拠**:
| Category | Graph Size | Locations | Line Recall Change |
|----------|-----------|-----------|-------------------|
| **IMPROVED** | 12K chars | 8 locations | **+8.7pp ✓** |
| **DEGRADED AVG** | 72K chars | 55 locations | **-8.5pp ✗** |
| **Ratio** | **6.0x larger** | **6.8x more** | **Inverse correlation** |

### Specific Instances
**最悪の例** (sphinx-doc__sphinx-8595):
- Graph: 17 sections, 84 locations, 122K chars, 51K tokens
- Line recall: 100% → 0% (完全に悪化)

**最良の例** (django__django-13401):
- Graph: 4 sections, 8 locations, 12K chars, 30K tokens
- Line recall: 9% → 17% (+8.7pp改善)

---

## Implementation Issues Found

### Issue #1: Debug Output Not Logged (致命的)
**問題**: Phase 2-6コード内で `print()` を使用
**影響**: デバッグ情報がログに記録されず、Greedy allocationが実装されているか検証できない

```python
# repograph_utils.py lines 326, 391, 396
print(f"[INFO construct_code_graph_context] Token budget exhausted...")  # ❌ ログに出ない
```

**修正案**: `logger.info()` を使用

### Issue #2: Token Budget Exceeded (8.4% over)
**結果データ**:
- 平均トークン使用: 33,313 tokens
- 予算: 30,740 tokens
- 超過: 2,573 tokens (8.4% over)

**原因分析**:
1. トークン推定が不正確 (`len(section) // 4`)
2. Greedy allocationの`max_tokens_this_section`が大きすぎる
3. 実際のプロンプト内でのオーバーヘッド (フォーマット、システムメッセージ等) を考慮していない

### Issue #3: def_tags Not Token-Limited
```python
# repograph_utils.py line 105
def_tags_limited = def_tags[:1]  # ❌ トークン予算チェックなし
```
定義タグは無条件に含める → 大きなグラフになりやすい

### Issue #4: Fallback Masking Results
**pydata__xarray-4094の場合**:
- グラフコンテキスト: 146K tokens (128K limit超過)
- **FALLBACK TRIGGERED** → グラフコンテキスト使用されず
- ファイルレベル改善: 0% → 100% (グラフのおかげではない)

真のグラフ改善は 1インスタンスのみ (pytest-dev__pytest-7490)

---

## Why Graph Helps Files But Hurts Lines

### ファイルレベルが改善する理由 ✓
1. グラフコンテキストが複数ファイルの依存関係を示す
2. LLMが「このファイルが関連ファイルA,Bと呼び合っている」を認識
3. ファイル選択の根拠が増える → ファイルランキング改善

**実装の正しい部分**:
- Composite score (file locality: 1000/100/1) がファイル選択に機能
- 関連ファイルの同定が正確

### ラインレベルが悪化する理由 ✗
1. 84個のロケーション = 84個以上の関数定義
2. 各関数: パラメータ、本体コード、戻り値 = 100-300トークン
3. 84個 × 200トークン = 16K+ トークンの関数コード
4. **LLMが84個の関数を全部読んで、どの行が重要か判断できない**
5. 結果: ラインレベルの精度が低下

**類推**:
- ファイルレベル: 「ここに関連するファイルがあります」→ Good ✓
- ラインレベル: 「ここに84個の関数があります。どの行を修正するか探してください」→ Bad ✗

---

## Greedy Allocation Implementation Status

### 実装されている機能 ✓
```python
# construct_code_graph_context() lines 314-330
for section_idx, item in enumerate(found_related_locs):
    sections_remaining = total_sections - section_idx
    remaining_budget = total_token_budget - tokens_used_global
    max_tokens_this_section = remaining_budget / sections_remaining  # Greedy allocation formula

# retrieve_graph() lines 209-229
if max_tokens_for_section is not None:
    for tag in ref_tags_sorted:
        tag_tokens = len(str(tag.get('text', []))) // 4
        if tokens_used + tag_tokens > max_tokens_for_section:
            break  # Token limiting
```

### 実装されていない/不正確な部分 ✗
1. **デバッグ出力がログされない** → 実行状況が見えない
2. **トークン推定が粗い** (`// 4` では不正確)
3. **def_tagsがトークン制限されない** → 必ず含まれる
4. **セクション単位ではなく、全体的なオーバーヘッド考慮なし**

---

## Root Cause of Line-level Degradation

### 定量的証拠
| Metric | Improved Instance | Degraded Instances | Ratio |
|--------|-------------------|-------------------|-------|
| Graph Size | 12K chars | 72K chars avg | 6.0x |
| Locations | 8 | 55 avg | 6.8x |
| Line Recall Change | +8.7pp | -8.5pp avg | Inverse |

### メカニズム
1. **Composite score** は「ファイル関連性」を最適化
   - File locality (1000/100/1): 同じファイル・同じディレクトリの関数を優先
   - Result: 関連ファイルの全関数が含まれる → グラフが巨大化

2. **グラフサイズ増加** → ノイズ増加
   - 84個の関数 = 複雑な依存グラフ
   - LLMが「どの関数の中のどの行?」の絞り込みに失敗

3. **トークン数制限が機能していない**
   - 平均 33.3K tokens で予算 30.7K を超過
   - 実装では制限されているはずだが、実際は超過

---

## Recommendations for Fix

### 短期的 (Phase 2-6 デバッグ)

1. **ロギング修正**
   ```python
   # 変更前
   print(f"[DEBUG construct_code_graph_context] Global graph tokens: {tokens_used_global:,}")

   # 変更後
   logger.info(f"[DEBUG construct_code_graph_context] Global graph tokens: {tokens_used_global:,}")
   ```

2. **トークン計数の検証**
   - Actual tokenizer使用 (char/4 推定ではなく)
   - セクション単位のトークン数をログに出力
   - Greedy allocationが実際に機能しているか確認

3. **単一インスタンステスト**
   - 1つのインスタンス(e.g., django__django-13401)で詳細ログを取得
   - 各セクションの `max_tokens_this_section` 値を確認
   - 実際のタグスキップが発生しているか確認

### 中期的 (ラインレベル改善)

1. **グラフコンテキストサイズを制限**
   - Option A: ロケーション数を 50-100 から 10-20 に削減
   - Option B: 1ロケーションあたりのタグ数を 3-5 に制限
   - Option C: 関数本体を削除、シグネチャのみ提示

2. **ファイルレベルとラインレベルで別のコンテキスト使用**
   - **File-level phase**: 完全なグラフコンテキスト (ファイル選択用)
   - **Line-level phase**: 最小限のグラフコンテキスト (呼び出し関係のみ)

3. **Composite scoreを段階的に調整**
   - ラインレベル: in_degree のみを使用 (file locality無し)
   - または: 同一ファイル内の依存関係のみを優先

### 長期的 (グラフコンテキスト戦略全体の再設計)

1. **2層コンテキストアーキテクチャ**
   ```
   Phase 1 (File Localization):
   - 完全なグラフ構造 + 簡潔なコード

   Phase 2 (Line Localization):
   - 最小限のグラフ (選定ファイル内のみ)
   - 関数シグネチャのみ + インラインコメント
   ```

2. **関連性重み付け**
   - バグ説明からキーワード抽出
   - 各関数の"bug relevance score"を計算
   - 最も関連の高い関数のみを含める

3. **適応的トークン割り当て**
   - Simple bug (依存関係少): 完全なコンテキスト使用
   - Complex bug (依存関係多): フィルター済みコンテキスト使用

---

## Key Numbers to Remember

### Success Metrics
- File-level: +5.3pp improvement (68.4% → 73.7%)
- Line-level: -8.5pp degradation (24.1% → 15.6%)
- Graph context generation: 91.3% coverage (21/23 instances)

### Size Comparisons
- Improved instance: 12K chars, 8 locations
- Degraded instances: 72K chars avg, 55 locations avg
- **6.0x larger = worse line-level performance**

### Token Usage
- Budget: 30,740 tokens
- Average usage: 33,313 tokens (+8.4% over)
- Max usage: 146,536 tokens (pydata__xarray-4094, triggered fallback)

### Instances
- Total evaluated: 23
- Fallback triggered: 1 (pydata__xarray-4094)
- Line improved: 1 (django__django-13401)
- Line degraded: 4 (sphinx-doc__sphinx-8595, sphinx-doc__sphinx-11445, pytest-dev__pytest-7432, astropy__astropy-14182)

---

## Conclusion

Phase 2-6 の Greedy Dynamic Token Allocation は**実装されている**が、以下の問題がある:

1. **デバッグ出力がログされていない** → 実装状況が見えない
2. **トークン予算が超過している** → Greedy allocationが完全に機能していない
3. **根本的な問題**: グラフコンテキストは**ファイル選択には良い**が**ラインレベルの精度には悪い**

ラインレベル悪化の原因は、Greedy allocation の失敗というより、むしろ**グラフコンテキストが大きすぎてLLMを混乱させている**ことにある。

### 最優先事項
1. デバッグログを修正して、Greedy allocationが実際に動作しているか確認
2. グラフサイズを 12K chars(Good) と 72K chars(Bad) の間に調整
3. ファイル選択とラインレベルで別のコンテキストを使用することを検討

---

**Generated Analysis Scripts**:
- `analyze_phase2_6_detailed_investigation.py` - Detailed metrics extraction
- `compare_improved_vs_degraded.py` - Comparison of improved vs degraded instances
- `PHASE2_6_INVESTIGATION_REPORT.md` - Full technical report
