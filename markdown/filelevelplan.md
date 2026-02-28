1. 概要
File-Level Localization プロセスにおいて、キーワード検索だけでは発見できない「真の原因ファイル（上位のCaller）」を特定するロジックを追加する。 グラフデータ（.pkl）は使用せず、JSONタグデータのみを使用して論理的に推論を行う。

2. 統合フロー (Integration Flow)
既存のパイプラインにおける 「キーワード検索処理」と「LLMによるファイル選定処理」の間 に、以下の拡張ロジックを挿入する。

graph TD
    A[Start] --> B[Reproduction: PoC作成 & Coverage取得]
    B --> C[Step 1: キーワード検索 (既存処理)]
    C -->|Seed Files & Keywords| D[★ Step 1.5: 構造的拡張 (新規ロジック)]
    D -->|Expanded Candidates| E[Step 2: LLMによるファイル選定 (既存処理)]

3. 機能詳細ロジック (Step 1.5 Logic)
Phase A: 起点の特定 (Seed Identification)
検索結果（文字列）を、タグデータ上の正確な「関数/クラス名」にマッピングする。

ロジック (Scope-Aware Mapping):

1.検索ヒットしたファイル（Seed File）内の def タグを全て抽出する。

2.条件: tag['kind'] == 'def' AND tag['rel_fname'] == seed_file

3.抽出した各 def タグの info（ソースコード情報）内に、検索キーワード が含まれているか確認する。

含まれている場合、その def タグの name（関数名/クラス名）を**「起点（Seed Name）」**としてリスト化する。


Phase B: 逆探知とフィルタリング (Expansion & Filtering)
特定した関数名を呼び出している「親ファイル（Caller）」を探す。ここでユニーク判定によるフィルタリングを行う。

フィルタリング（Unique Def Check）:

その Seed Name を持つ def タグが、全タグデータ内で 「1つだけ（Unique）」 か確認する。

2つ以上ある場合: 名前衝突のリスクがあるため、その名前での検索はスキップする。

1つだけの場合: 安全と判断し、逆探知を実行する。

逆探知（Caller Identification）:

安全と判定された名前についてのみ、ref タグ（参照）を検索し、呼び出し元のファイルリスト（Caller Files）を取得する。

検索ロジック:

1.全タグデータを走査する。

2.tag['kind'] == 'ref' かつ tag['name'] == Seed Name であるタグを探す。

3.見つかったタグの tag['rel_fname'] を取得し、候補リストに追加する。


Phase C: スコアリングと選抜 (Scoring & Ranking)
取得したCallerファイル（候補者）に対し、以下のルールで重要度を計算し、上位10件を選抜する。

評価項目,条件,加点,意図
基本点,Seedファイルを呼んでいる,+1 pt,依存関係の基本
Hub Bonus,2つ以上の異なるSeedに関連している,+30 pt,最重要。複数の検索結果を束ねる「交差点」を浮上させる。
Coverage Bonus,PoC Coverageに含まれている,+50 pt,実行パス上にある確実な証拠。
Locality Bonus,Seedと同じディレクトリにある,+5 pt,遠くの他人の空似を除外するための補助。


4. プロンプトへの注入形式
LLMに渡す追加情報は、断定を避け、「構造的なつながりがあるため、調査を推奨する」 というスタンスで記述するテキストを生成する。
例.
### Structural Analysis (RepoGraph Suggestions) ###
The following files are identified as structurally relevant based on dependency analysis. They call the functions/classes found in your keyword search. Please consider checking them.

1. {ファイルパス}
   - **Role**: Structural Hub / Caller
   - **Status**: {Coverageにあれば "Executed in PoC"}
   - **Reason**: This file invokes multiple search results (`{関数A}`, `{関数B}`). It acts as a bridge between them.

2. {ファイルパス}
   ...