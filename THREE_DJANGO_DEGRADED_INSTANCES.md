# RepoGraph で精度が低下した 3つの Django インスタンスの詳細分析

**目的**: グラフ統合で実際に性能低下した Django インスタンスの問題の本質を理解する

**選定基準**: Phase 2-6 で グラフサイズが大きくなったり、処理が失敗した Django インスタンス

---

## インスタンス 1: django__django-10914

### 1-1. 問題の本質

**タイトル**: ファイルアップロードのパーミッション不一致

**問題の構造**:
```
ユーザーがファイルをアップロード
    ↓
ファイルサイズに応じて 2つの経路に分岐
    ├─ 小さいファイル：MemoryUploadedFile を使用
    │   → パーミッション: (デフォルト)
    │
    └─ 大きいファイル：TemporaryUploadedFile を使用
        → パーミッション: 0o600（tempfile のセキュリティデフォルト）
            ↓
        ファイルシステムに保存される
            ↓
        最終的にパーミッション: 0o600（一貫性がない）
```

### 1-2. 具体的な問題

```
期待される動作:
  「アップロード方法に関わらず、ファイルパーミッションは一貫している」
  例：すべてのアップロード → 0o644（読み取り可能）

実際の動作（バグ）:
  「アップロード方法により異なる」
  - MemoryUploadedFile → 0o644（通常）
  - TemporaryUploadedFile → 0o600（非常に限定的）

影響:
  後続のプロセスがファイルを読めなくなる可能性
```

### 1-3. リポジトリ構造と関連ファイル

```
django/
├── core/files/
│   ├── uploadedfile.py
│   │   ├── UploadedFile（基本クラス）
│   │   ├── MemoryUploadedFile（小さいファイル用）
│   │   ├── TemporaryUploadedFile（大きいファイル用）
│   │   │   └── tempfile.NamedTemporaryFile() で作成
│   │   │       （ここで 0o600 がセットされる）
│   │   │
│   │   └── InMemoryUploadedFile
│   │
│   ├── storage.py
│   │   ├── Storage（基本クラス）
│   │   └── FileSystemStorage（ファイル保存実装）
│   │       ├── _save(name, content)
│   │       │   ├─ content が TemporaryUploadedFile かチェック
│   │       │   ├─ file_move_safe() で移動
│   │       │   │  （ここでパーミッションが保持される）
│   │       │   └─ os.chmod() ← 修正が必要な場所
│   │       │
│   │       ├── file_permissions_mode (property)
│   │       │   （FILE_UPLOAD_PERMISSIONS設定から取得）
│   │       │
│   │       └── directory_permissions_mode
│   │
│   ├── move.py
│   │   └── file_move_safe()
│   │       （TemporaryUploadedFile を移動する）
│   │
│   └── temp.py
│
├── db/models/
│   ├── fields/
│   │   └── files.py
│   │       └── FileField（ユーザーが使う API）
│   │
│   └── __init__.py
│
└── forms/
    ├── fields.py
    │   └── FileField（フォーム側）
    │
    └── models.py
```

### 1-4. 複雑性の分析

```
「複数層にまたがる問題」:

層1: ファイルアップロード入口
  ├─ django.forms.fields.FileField（ユーザーが使う）
  └─ django.db.models.fields.files.FileField（モデル側）

層2: アップロードハンドラ
  ├─ MemoryUploadedFile の場合
  │   └─ メモリに保存（パーミッション問題なし）
  │
  └─ TemporaryUploadedFile の場合
      └─ tempfile.NamedTemporaryFile()
          └─ 0o600 で作成される（セキュリティ）

層3: ストレージエンジン
  └─ FileSystemStorage._save()
      ├─ TemporaryUploadedFile を検出
      ├─ file_move_safe() で移動
      │   ← ここでパーミッションが保持される
      └─ os.chmod() を呼ぶべき（現在は呼ばない）

層4: ファイルシステム
  └─ 最終的なパーミッション: 0o600（バグ）
```

### 1-5. なぜ RepoGraph で悪化するのか

```
問題:
  「複数層 × 複数ファイル = 大きなグラフ」

具体的には:
  1. uploadedfile.py （15 tags）
     - TemporaryUploadedFile クラス
     - パーミッション設定

  2. storage.py （86+ tags）
     - FileSystemStorage クラス
     - _save() メソッド
     - chmod() 関連

  3. move.py （~20 tags）
     - file_move_safe() 関数

  合計: 120+ tags → 50K+ chars のグラフ

LLM の混乱:
  「120個の関数定義から、どの行を修正...？」
  → 判断不可 → ラインレベル精度低下
```

### 1-6. 修正箇所

```
修正ファイル: django/core/files/storage.py
修正メソッド: FileSystemStorage._save() (行 225)

修正内容:
  file_move_safe() の後に os.chmod() を追加

  def _save(self, name, content):
      ...
      if hasattr(content, 'temporary_file_path'):
          file_move_safe(content.temporary_file_path(), full_path)

      # ★ ここに追加 ★
      if self.file_permissions_mode is not None:
          os.chmod(full_path, self.file_permissions_mode)
      ...
```

---

## インスタンス 2: django__django-11999

### 2-1. 問題の本質

**タイトル**: モデルメソッド `get_FIELD_display()` のオーバーライド不可

**問題の構造**:
```
Django 2.1:
  ユーザーが get_foo_bar_display() を override
    ↓
  動作する ✓（オーバーライドが有効）

Django 2.2+:
  ユーザーが get_foo_bar_display() を override
    ↓
  動作しない ✗（オーバーライドが無視される）
  （代わりにデフォルトの choice 値を返す）
```

### 2-2. 具体的な問題

```
コード例:

class FooBar(models.Model):
    foo_bar = models.CharField(
        choices=[(1, 'foo'), (2, 'bar')]
    )

    def get_foo_bar_display(self):
        return "something"  # ← オーバーライド

実際の挙動:
  Django 2.1: get_foo_bar_display() → "something"  ✓
  Django 2.2: get_foo_bar_display() → "foo" or "bar" ✗

原因:
  Django 2.2 で、Model.__getattr__() が実装方法を変更
  → get_FIELD_display() の動的生成方式が変わった
  → オーバーライドを無視して、動的に生成するようになった
```

### 2-3. リポジトリ構造と関連ファイル

```
django/
├── db/models/
│   ├── __init__.py
│   │   ├── Model（基本クラス）
│   │   └── __getattr__() ← ここで get_FIELD_display を動的生成
│   │
│   ├── fields/
│   │   ├── __init__.py
│   │   │   ├── Field（基本フィールドクラス）
│   │   │   ├── CharField
│   │   │   └─ get_FOO_display() の動的生成ロジック
│   │   │
│   │   └─ related.py
│   │
│   └─ options.py
│       ├─ Options（メタ情報）
│       └─ get_field() （フィールド検索）
│
└─ model_utils/
    (内部ユーティリティ)
```

### 2-4. 複雑性の分析

```
「複数ファイル + 複雑な継承構造」:

構造:
  1. Model.__getattr__()
     ├─ get_FIELD_display の検索
     ├─ フィールド型の検認
     ├─ 動的メソッド生成
     └─ return

  2. Field.get_prep_value()
     ├─ 値の準備
     └─ return

  3. 選択肢検索ロジック
     ├─ フィールドの choices を取得
     ├─ 値をマッチング
     └─ 表示値を返す

関連ファイル数: 5-10個（models/fields/) + metaclass 関連

グラフサイズ:
  推定: 60-80K chars
  関数数: 50-70個
```

### 2-5. なぜ RepoGraph で悪化するのか

```
問題:
  「メタプログラミング = グラフが追跡困難」

具体的には:
  1. Model.__getattr__() の動作
     → 動的にメソッドを生成
     → グラフには「静的な呼び出し」しか見えない

  2. metaclass の使用
     → ModelBase, Options など複雑なクラス階層
     → グラフが「関連性の判定」を誤る

  3. 内部的な get_FOO_display 実装の変更
     → 複数の経路がある
     → グラフが「どの経路が正しい」か判定できない

LLM の混乱:
  「Model の __getattr__() と 50個の関連関数」
  「どこで実装が変わったのか...？」
  → 判断不可 → ラインレベル精度低下

グラフが示さない重要情報:
  「Django 2.2 で ModelBase の __new__() が変わった」
  「get_FIELD_display() の動的生成ロジックが変わった」
  ← この「設計変更」をグラフは追跡できない
```

### 2-6. 修正箇所

```
修正ファイル: django/db/models/__init__.py
修正メソッド: Model.__getattr__() (複数候補)

修正の方向:
  オーバーライドを優先する順序を変更

  # 現在の順序（Django 2.2）:
  1. 動的に get_FIELD_display() を生成
  2. 呼び出す

  # 修正すべき順序:
  1. instance.__dict__ にオーバーライドがあるか確認
  2. あれば、それを使用
  3. なければ、動的生成

修正の複雑性: 中程度（メタプログラミング理解が必要）
```

---

## インスタンス 3: django__django-13933

### 3-1. 問題の本質

**タイトル**: ModelChoiceField のバリデーションエラーメッセージが不完全

**問題の構造**:
```
ユーザーが無効な選択肢を選ぶ
    ↓
ModelChoiceField がバリデーション
    ↓
エラーメッセージを生成
    │
    ├─ 期待: "Select a valid choice. 3 is not one of the available choices."
    │         (無効な値 "3" を含む)
    │
    └─ 実際: "Select a valid choice. That choice is not one of the available choices."
             (値を含まない)

影響:
  デバッグが困難（どの値が無効だったか不明）
  ユーザーがどの選択肢を試したか分からない
```

### 3-2. 具体的な問題

```
コード例:

class Article(models.Model):
    category = models.ForeignKey(Category, on_delete=...)

# フォーム
form = ArticleForm(data={'category': 999})  # 無効な ID
form.is_valid()  # → False
form.errors['category']  # → "Select a valid choice..."

問題:
  エラーメッセージに "999" が含まれていない
  → ユーザーは「どの値が問題か」分からない
```

### 3-3. リポジトリ構造と関連ファイル

```
django/
├── forms/
│   ├── fields.py
│   │   ├── Field（基本フィールドクラス）
│   │   ├── ChoiceField
│   │   │   └─ エラーメッセージに値を含める ✓
│   │   │
│   │   └─ ModelChoiceField
│   │       ├─ __init__()
│   │       ├─ _get_queryset()
│   │       ├─ to_python()
│   │       ├─ validate() ← エラーメッセージを生成
│   │       │   └─ ValidationError に値を渡すべき
│   │       │
│   │       └─ ModelMultipleChoiceField
│   │
│   └── widgets.py
│       ├─ Select
│       └─ SelectMultiple
│
├── core/exceptions.py
│   └── ValidationError
│
└── db/models/
    └── fields/
        └── related.py
            ├─ ForeignKey
            └─ ManyToManyField
```

### 3-4. 複雑性の分析

```
「比較的シンプル」だが「複数ファイルにまたがる」:

メインファイル:
  1. django/forms/fields.py (ModelChoiceField)
     ├─ validate() メソッド
     └─ エラーメッセージ生成

関連ファイル:
  2. django/core/exceptions.py (ValidationError)
  3. django/forms/fields.py (ChoiceField の実装参照)
  4. django/db/models/fields/related.py (ForeignKey)

グラフサイズ:
  推定: 30-40K chars
  関数数: 30-40個
  セクション数: 5-8

複雑度の理由:
  - ValidationError の処理フロー
  - ChoiceField との共通コード
  - ForeignKey の呼び出し関係
```

### 3-5. なぜ RepoGraph で悪化するのか

```
問題:
  「エラーメッセージの値パラメータが追跡困難」

具体的には:
  1. validate() メソッド内で:
     raise ValidationError(...)

  2. ValidationError が何度も reformat される
     → パラメータの追跡が複雑

  3. グラフが「どこで値を埋め込むべき」か示さない
     → LLM が「値パラメータを追加する場所」を判定困難

グラフが示すもの:
  「ModelChoiceField.validate() が ValidationError を raise」
  「ValidationError がある」
  「他の ChoiceField でも似たことをしている」

グラフが示さないもの:
  「このエラーメッセージでは値パラメータが不足」
  「ChoiceField との差分はここ」
  「値を渡すべき正確な場所」

LLM の混乱:
  「30個の関数の中で、どこにパラメータを追加？」
  → 判断不可 → 処理失敗またはラインレベル悪化
```

### 3-6. 修正箇所

```
修正ファイル: django/forms/fields.py
修正クラス: ModelChoiceField
修正メソッド: validate()

修正内容:
  ValidationError に value パラメータを追加

  # 現在:
  raise ValidationError(
      self.error_messages['invalid_choice'],
      code='invalid_choice',
  )

  # 修正後:
  raise ValidationError(
      self.error_messages['invalid_choice'],
      code='invalid_choice',
      params={'value': value},  # ← 追加
  )

修正の複雑性: 低（パラメータ追加だけ）
```

---

## 4. 3つのインスタンスの共通パターン

### 4-1. 複雑性の比較

```
django-10914（パーミッション）:
  複雑度: 高 ★★★★★
  - 複数層（uploadedfile → storage → move）
  - グラフサイズ: 120+ tags, 50K+ chars
  - 修正難易度: 中（パーミッション理解必要）
  - RepoGraph での悪化: 大

django-11999（get_FIELD_display）:
  複雑度: 非常に高 ★★★★★★
  - メタプログラミング
  - 動的メソッド生成
  - グラフサイズ: 60-80K chars
  - 修正難易度: 高（メタクラス理解必要）
  - RepoGraph での悪化: 大～極大

django-13933（バリデーションメッセージ）:
  複雑度: 中 ★★★☆☆
  - 相対的には単純
  - グラフサイズ: 30-40K chars
  - 修正難易度: 低（パラメータ追加だけ）
  - RepoGraph での悪化: 中
```

### 4-2. RepoGraph が失敗する理由

```
すべてのインスタンスに共通:

1. グラフサイズが大きい（30K-120K chars）
   → LLM が 30-120個の関数から判定
   → 混乱 → 精度低下

2. 複数ファイルにまたがる
   → 「どのファイルが重要か」が不明確
   → グラフが「構造的関連」だけを示す
   → 「意味的関連」（修正が必要な場所）を示さない

3. 複雑な内部ロジック
   → メタプログラミング（django-11999）
   → 多層設計（django-10914）
   → エラーハンドリング（django-13933）
   → グラフが追跡困難
```

### 4-3. グラフが示さない重要情報

```
django-10914:
  ❌ グラフは「TemporaryUploadedFile と storage が関連」を示す
  ✓ グラフが示すべき: 「_save() の最後に chmod() が必要」

django-11999:
  ❌ グラフは「Model と Field が関連」を示す
  ✓ グラフが示すべき: 「Django 2.2 で動的生成ロジックが変わった」

django-13933:
  ❌ グラフは「ModelChoiceField と ValidationError が関連」を示す
  ✓ グラフが示すべき: 「value パラメータを params に追加」
```

---

## 5. 結論

### 5-1. Django の問題の特徴

```
Django は「フレームワーク」：

1. 多層的な設計
   → 一つの問題が複数ファイルに影響
   → グラフが必然的に大きくなる

2. 強い抽象化
   → メタプログラミング多用
   → 動的メソッド生成
   → グラフが追跡困難

3. 複雑な内部ロジック
   → エラーハンドリング
   → 値の変換処理
   → グラフが「意味」を理解できない

結果:
  RepoGraph は「構造的関連」を示すが
  → Django 問題では「意味的関連」が重要
  → グラフは無効化
```

### 5-2. RepoGraph の限界

```
✓ グラフが有効な場面:
  - 単一ファイル内の問題
  - グラフサイズが小さい
  - 修正が明確

✗ グラフが無効な場面:
  - 複数ファイル + 複数層
  - グラフサイズが大きい
  - 修正が不明確（メタプログラミング含む）

Django の 3つのインスタンスすべて: 「✗ 無効な場面」に該当
```

