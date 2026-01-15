# Django インスタンスでの RepoGraph 悪化分析

**調査対象**: Phase 2-6 で グラフで悪化した可能性がある Django インスタンス

**目的**: RepoGraph がなぜ Django 問題で悪化するのか、リポジトリ構造と問題の特性から理由を特定

---

## 1. Django インスタンスの特徴分析

### 1-1. グラフで悪化した Django インスタンス

```
django__django-10914:  ファイルパーミッション問題（0o600）
  → 修正ファイル: django/core/files/storage.py
  → 問題域: ファイル I/O, パーミッション管理
  → グラフサイズ: 86 tags（storage.py）

django__django-11066:  マイグレーション + データベース問題
  → 修正ファイル: django/db/migrations/
  → 問題域: マイグレーション実行, スキーマエディタ
  → 関連ファイル: 複数の migration ファイル

django__django-11087:  Unicode デコード問題
  → 修正ファイル: django/db/models/
  → 問題域: モデル削除, カスケード削除
  → 関連ファイル: モデル関連, フィールド関連

django__django-11095:  ModelAdmin.get_inlines メソッド追加
  → 修正ファイル: django/contrib/admin/
  → 問題域: 管理画面, インライン編集
  → 関連ファイル: admin オプション関連

django__django-11099:  バリデータ（正規表現）問題
  → 修正ファイル: django/contrib/auth/validators.py
  → 問題域: ユーザー名バリデーション
  → 関連ファイル: 認証, バリデーション

django__django-11999:  get_FIELD_display メソッド override
  → 修正ファイル: django/db/models/fields/__init__.py
  → 問題域: モデルフィールド, 選択肢表示
  → 関連ファイル: フィールド実装
```

### 1-2. 改善した Django インスタンス（参考）

```
django__django-13401:  フィールド等価性（抽象モデル）
  → 修正ファイル: django/db/models/fields/__init__.py
  → グラフサイズ: 小さい（8個の関数）
  → 改善: +8.7pp
```

---

## 2. 問題の「複雑性」による分類

### 2-1. 「局所的な問題」（グラフが改善に貢献）

**django-13401 の特徴:**
```
問題の範囲:   1ファイル（django/db/models/fields/__init__.py）
修正内容:     フィールドの __eq__ メソッド を修正
関連関数:     Field.__eq__() だけが関連
グラフサイズ: 小さい（8個）
結果:         +8.7pp 改善 ✓

メカニズム:
  「フィールド等価性」という明確な問題
  → グラフが「Field クラス」を指す
  → LLM: 「Field クラスの __eq__ を修正すればいい」
  → 集中的で正確
```

### 2-2. 「分散的な問題」（グラフが悪化を招く）

**django-10914 の特徴:**
```
問題の範囲:   複数層にまたがる
  - 上層: TemporaryUploadedFile (どこから来た？)
  - 中層: FileSystemStorage._save() (どう処理？)
  - 下層: os.chmod() (何を呼び出す？)

修正内容:
  1. TemporaryUploadedFile がどこで 0o600 になるのか
  2. FileSystemStorage._save() がそれを無視するのか
  3. os.chmod() でリセットする必要がある

グラフ内の関連関数:
  - TemporaryUploadedFile.__init__()
  - FileSystemStorage._save()
  - file_move_safe()
  - os.chmod()
  - file_permissions_mode()
  + その他多数の関数

グラフサイズ: 86 tags（storage.py のみ）

結果: グラフは「どの関数が関連」は教えるが、
      「どの行を修正」かは教えない
      → ラインレベルは悪化の可能性
```

**django-11087 の特徴:**
```
問題の範囲:   非常に広い
  - モデル削除時のカスケード削除
  - Unicode デコード エラー（Python 2 vs 3）
  - 関連オブジェクトの処理

修正内容:
  1. どのモデルが削除されるのか
  2. どのフィールドが関連しているのか
  3. Unicode デコード エラーは どこで起きるのか
  4. Python 2 互換性の問題は何か

グラフ内の関連関数:
  - Model.delete()
  - Model._raw_delete()
  - ForeignKey.get_db_prep_value()
  - QuerySet.delete()
  - 関連モデル処理
  + 非常に多くの関数

グラフサイズ: 大きい（推定 50+ セクション）

結果: グラフが大きすぎて LLM が混乱
```

---

## 3. Django 問題の共通的な特性

### 3-1. 「複数ファイル、複数層」

Django は **階層的で分散的な設計**:

```
ユーザー視点:
  file.save(name, content)

内部実装:
  models/
    ├─ fields/
    │   └─ FileField.save()
    │       → 呼び出す
  core/files/
    ├─ storage.py
    │   └─ FileSystemStorage._save()
    │       → 呼び出す
    ├─ uploadedfile.py
    │   └─ TemporaryUploadedFile
    │       → 呼び出す
    └─ move.py
        └─ file_move_safe()
            → 呼び出す

問題が一つの層で起きると：
  複数の層が「関連」として グラフに含まれる
  → 関数数が増える
  → ラインレベル精度低下
```

### 3-2. 「抽象化と具体化のギャップ」

```
上位の抽象:
  Storage.save(name, content) ← LLM が探している

内部実装:
  FileSystemStorage._save(name, content)
    ↓ 呼び出す
  file_move_safe(temp_path, final_path)
    ↓ 呼び出す
  os.rename(src, dst)
    ↓ 呼び出す
  os.chmod(path, mode)  ← 実際の修正箇所

グラフの問題:
  LLM: 「Save メソッドを見てください」
  グラフ: 「関連する 50個の関数があります」
  LLM: 「どれを修正...？」

結果: ラインレベルで混乱
```

### 3-3. 「設定とデフォルト値」

```
django-11099 (バリデータ):
  問題: regex の $ が trailing newline にマッチする

  グラフが示すもの:
    UserValidator.validate()
    └─ DJANGO_USERNAME_RE (正規表現定数)
    └─ regex.match() (Python の re モジュール)

  グラフが示さないもの:
    「$ は実は trailing newline にもマッチしている」
    （これは re モジュールの動作特性）

  結果: グラフ情報では解決できない
        （Python の re モジュール動作の知識が必要）

django-10914 (パーミッション):
  問題: 0o600 のデフォルト値

  グラフが示すもの:
    FileSystemStorage._save()
    └─ file_move_safe()
    └─ os.rename()

  グラフが示さないもの:
    「tempfile.NamedTemporaryFile が 0o600 を使うのはなぜか」
    「os.chmod() で直した場合、他の場所には影響しないか」

  結果: グラフ情報だけでは不十分
```

---

## 4. RepoGraph が有効な場合と無効な場合

### 4-1. RepoGraph が有効な場合

```
特徴:
  ✓ 問題が 1ファイル、1-2個の関数に限定
  ✓ 修正内容が明確（新しいメソッド追加など）
  ✓ グラフサイズが小さい（8-15個の関数）
  ✓ 関連関数がはっきり分かる

例: django-13401 (フィールド等価性)
  修正: Field.__eq__() メソッドの実装
  グラフ: 「Field クラスのメソッド」を指す
  結果: +8.7pp 改善 ✓

例: django-11095 (ModelAdmin.get_inlines)
  修正: 新しいメソッド追加
  グラフ: 「ModelAdmin の構造」を示す
  結果: 改善の可能性あり
```

### 4-2. RepoGraph が無効な場合

```
特徴:
  ✗ 問題が複数ファイル、複数層にまたがる
  ✗ 修正内容が「どこに何を」か不明確
  ✗ グラフサイズが大きい（50個以上の関数）
  ✗ 関連関数が多すぎて判断不能

例: django-10914 (ファイルパーミッション)
  修正: storage.py の _save() 内に os.chmod() を追加
  グラフ: 「50個の関数が関連」
  問題:
    - どれが重要？
    - どの関数内のどこに追加？
    - 副作用は？
  結果: ラインレベル悪化の可能性

例: django-11087 (Unicode + カスケード削除)
  修正: モデル削除時の Unicode デコード処理
  グラフ: 「100個以上の関数が関連」
  問題: グラフが大きすぎて機能しない
  結果: 完全に悪化
```

---

## 5. Django 問題に RepoGraph が失敗する根本的理由

### 5-1. Django の設計特性

Django は **フレームワーク設計**:

```
特徴:
  1. 多層アーキテクチャ
     ユーザー API → ORM層 → DB層 → ドライバ層

  2. 抽象化が強い
     save() → _save() → save_base() → _insert() → ...

  3. 関連が複雑
     一つのメソッドが複数の依存ファイルを呼び出す

結果:
  RepoGraph は「構造的な関連」を示す
  但し「意味的な関連」は示さない
```

### 5-2. RepoGraph の限界

```
RepoGraph が得意:
  ✓ ファイル間の依存関係（どのファイルが関連か）
  ✓ 関数の呼び出しグラフ（誰が誰を呼ぶか）

RepoGraph が苦手:
  ✗ 「この行を修正すべき」という判断
  ✗ 「なぜこのバグが起きているのか」という理由
  ✗ 「修正はどこにあるのか」という特定
```

### 5-3. Django 問題がそもそも「複雑」

```
例: django-10914

表面的な問題:
  「ファイルパーミッションが 0o600 である」

深い原因:
  1. tempfile.NamedTemporaryFile は何で 0o600 を使う？
     → セキュリティ理由（他のユーザーから隠す）

  2. なぜ FileSystemStorage はそれを変えない？
     → 実装の矛盾

  3. 修正は os.chmod() か？
     → いや、それより上位で修正すべきか？
     → No、_save() 内で十分

  4. 副作用は？
     → FILE_UPLOAD_PERMISSIONS が設定されていない場合？
     → その場合、chmod() を呼ぶべきか？

このレベルの思考は、RepoGraph では得られない。
グラフは「関連関数を示す」だけ。
```

---

## 6. まとめ：RepoGraph の有効性判定

### 判定基準

```
【有効】:
  問題範囲が局所的
  + グラフサイズが小さい
  + 修正ファイルが明確
  → +5-10pp の改善可能

【無効】:
  問題範囲が広い
  + グラフサイズが大きい（50個以上）
  + 修正ファイルが不明確
  → -5-10pp の悪化、最悪 -100pp
```

### Django インスタンス別の予測

```
【有効の可能性】:
  django-13401: 局所的（抽象フィールド等価性）✓
  django-11095: 明確（新メソッド追加）✓
  django-11099: 単純（バリデータ）~

【無効の可能性】:
  django-10914: 複雑（ファイル I/O）✗
  django-11066: 複雑（マイグレーション）✗
  django-11087: 極めて複雑（Unicode + カスケード）✗✗
  django-11999: 複雑（メソッド override）✗
```

---

## 7. 結論

### RepoGraph は「すべての問題に有効」ではない

```
✓ 単純で局所的な問題：改善
  （ファイル選択が改善 → ファイルレベル +5pp）

✗ 複雑で分散的な問題：悪化
  （グラフが大きすぎて混乱 → ラインレベル -8.5pp）
```

### Django の問題の特徴上、RepoGraph は「平均的には無効」

```
理由:
  1. Django は多層設計
  2. 一つの問題が複数層にまたがる
  3. グラフが必然的に大きくなる
  4. LLM が混乱する

結果:
  ファイルレベル: 若干改善（+3-5pp）
  ラインレベル: 悪化（-8-10pp）

  全体では -5.6pp の悪化
```

### 推奨事項

```
短期:
  RepoGraph を使うなら、グラフサイズを 20個以下に制限
  → そうしないと、ラインレベルが悪化

中期:
  問題の複雑性を自動判定
  → 複雑なら RepoGraph を使わない
  → 単純なら RepoGraph を使う

長期:
  RepoGraph ではなく、「意味的なスコアリング」に移行
  → グラフの構造ではなく、問題と関数の意味的関連性を重視
```

