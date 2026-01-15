# Django-10914 深堀分析：ファイルパーミッション問題

## 1. 問題の基本情報

### Issue ID
- **django__django-10914**

### 問題の要約
Django の `FileSystemStorage` でファイルを保存する際、一時ファイル（TemporaryUploadedFile）のパーミッションが **0o600** に固定されてしまい、意図しない制限が発生する。

### バグの症状
```
期待値: ファイルパーミッション = 0o644 or 0o664 （読み取り可能）
実際:   ファイルパーミッション = 0o600    （所有者のみ読み取り可能）
```

---

## 2. PoC コードから見える問題

```python
import os
import tempfile

# Create a temporary file using NamedTemporaryFile
with tempfile.NamedTemporaryFile(delete=False) as temp_file:
    temp_file_name = temp_file.name

# Check the permissions of the created file
file_permissions = oct(os.stat(temp_file_name).st_mode & 0o777)
print(f"Permissions of the temporary file: {file_permissions}")

# Clean up the temporary file
os.remove(temp_file_name)

# 実行結果:
# Permissions of the temporary file: 0o600
```

### 問題点
```
tempfile.NamedTemporaryFile() で作成されたファイル:
  → セキュリティ上の理由で、デフォルトで 0o600 の厳しいパーミッション
  → これを Django FileSystemStorage が保持し続ける
  → ファイルアップロード後も 0o600 のままで、他のプロセスが読み込み不可に
```

---

## 3. 関連する Django コンポーネント

### 関連ファイル（推測される）

```
django/core/files/
  ├── storage.py (FileSystemStorage クラス)
  ├── uploadedfile.py (TemporaryUploadedFile クラス)
  └── base.py

django/db/models/fields/
  ├── files.py (FileField, ImageField)

django/forms/
  └── fields.py (FileField)

django/views/
  └── decorators/http.py
```

### キーの関数・クラス

| コンポーネント | 役割 | パーミッション関連 |
|-----------|------|-----------------|
| **FileSystemStorage** | ファイル保存ロジック | ✓ 0o600 の問題ここで発生 |
| **TemporaryUploadedFile** | 一時ファイル処理 | ✓ 0o600 で作成 |
| **save()** メソッド | ファイル最終保存 | ✓ パーミッション設定の機会 |
| **chmod()** | パーミッション変更 | ✓ 明示的な修正位置 |

---

## 4. 根本原因の推測

### Python の tempfile モジュールの仕様

```python
import tempfile

# tempfile.NamedTemporaryFile のデフォルト動作
with tempfile.NamedTemporaryFile(delete=False) as f:
    f.write(b"data")
    # ファイルモード: 0o600 で作成（セキュリティ）
    # 理由: 一時ファイルは秘密情報を含む可能性
```

### Django での処理フロー（推測）

```
1. ユーザーがファイルをアップロード
   ↓
2. Django が TemporaryUploadedFile を作成
   ├─ 内部で tempfile.NamedTemporaryFile 使用
   ├─ パーミッション: 0o600 で自動設定

3. FileSystemStorage.save() で永続ファイルに保存
   ├─ os.rename(temp_file, final_location) で移動
   ├─ ← ここで 0o600 がそのまま保持される

4. 問題：
   ├─ Webサーバー (nginx, apache) が読み込み不可
   ├─ 他のプロセスがアクセス不可
   ├─ MEDIA_ROOT の設定と矛盾
```

---

## 5. 予想される修正箇所

### 修正案1: save() メソッドで chmod を明示的に実行

```python
# django/core/files/storage.py の FileSystemStorage.save()

def save(self, name, content, max_length=None):
    """Save file to disk and fix permissions"""

    # ... existing code ...

    full_path = self.path(name)

    # Write file
    with open(full_path, 'wb') as f:
        f.write(content.read())

    # ← FIX: 明示的にパーミッションを設定
    try:
        # Get the desired file permissions from settings
        # Default: 0o644 (owner read/write, others read)
        file_mode = getattr(settings, 'FILE_UPLOAD_PERMISSIONS', 0o644)
        os.chmod(full_path, file_mode)
    except (OSError, AttributeError):
        pass

    return name
```

### 修正案2: TemporaryUploadedFile でパーミッション指定

```python
# django/core/files/uploadedfile.py

class TemporaryUploadedFile:
    def __init__(self, ...):
        # ... existing code ...

        # Create temp file with explicit permissions
        # Instead of relying on tempfile's 0o600 default
        self.tmp_file = tempfile.NamedTemporaryFile(
            delete=False,
            dir=FILE_UPLOAD_TEMP_DIR,
            # Note: mode parameter won't help for file permissions
        )
```

---

## 6. Django リポジトリ構造（django__django-10914 時点）

```
django/
├── core/
│   ├── files/
│   │   ├── __init__.py
│   │   ├── base.py           ← File 基本クラス
│   │   ├── storage.py        ← FileSystemStorage (修正対象)
│   │   └── uploadedfile.py   ← TemporaryUploadedFile (修正対象)
│   │
│   ├── management/
│   ├── mail/
│   └── ...
│
├── db/
│   ├── models/
│   │   ├── fields/
│   │   │   └── files.py      ← FileField
│   │   └── ...
│   └── ...
│
├── forms/
│   └── fields.py             ← FormFileField
│
├── views/
├── http/
├── ...
```

---

## 7. Grep キーワード（修正するなら検索すべき）

```
検索すべきキーワード:

1. "FILE_UPLOAD_PERMISSIONS"
   └─ ファイルアップロード時のパーミッション設定

2. "0o600"
   └─ 厳しいパーミッション (0o600 = rw-------)

3. "os.chmod"
   └─ ファイルパーミッション変更

4. "TemporaryUploadedFile"
   └─ 一時ファイル処理

5. "FileSystemStorage.save()"
   └─ ファイル永続化処理

6. "tempfile.NamedTemporaryFile"
   └─ Python のテンポラリファイル作成
```

---

## 8. 影響範囲

### 影響を受けるユースケース

```
1. ファイルアップロード機能
   - ユーザー画像アップロード
   - ドキュメント保存
   - メディアファイル管理

2. マルチプロセス環境
   - Celery ワーカーが保存ファイルにアクセスできない
   - 別プロセスが画像処理できない
   - キャッシュシステムがアクセス不可

3. 開発環境での影響
   - デバッグ時にファイルが読めない
   - テストが失敗する可能性
```

### 深刻度

```
中程度 ~ 高
  - セキュリティ上のリスク低（0o600 は実は安全）
  - 機能的な問題高（他のプロセスが使えない）
  - ワーカー環境での実際的な問題
```

---

## 9. 修正の検証方法

```python
# テストコード例

def test_file_upload_permissions():
    """Verify uploaded file has correct permissions"""

    # Upload file
    file = SimpleUploadedFile("test.txt", b"content")
    storage = FileSystemStorage()
    name = storage.save("test.txt", file)

    # Check permissions
    full_path = storage.path(name)
    file_stat = os.stat(full_path)
    file_mode = file_stat.st_mode & 0o777

    # Should NOT be 0o600
    assert file_mode != 0o600, f"File has too restrictive permissions: {oct(file_mode)}"

    # Should be readable by others
    assert file_mode & 0o044 != 0, f"File not readable: {oct(file_mode)}"

    # Cleanup
    os.remove(full_path)
```

---

## 10. 実装分析：Django 10914 の実際の修正コード

### 10-1. FileSystemStorage._save() メソッド（行 225-280）

**実装の核心部分:**

```python
def _save(self, name, content):
    full_path = self.path(name)

    # ディレクトリを作成
    directory = os.path.dirname(full_path)
    try:
        if self.directory_permissions_mode is not None:
            old_umask = os.umask(0)
            try:
                os.makedirs(directory, self.directory_permissions_mode, exist_ok=True)
            finally:
                os.umask(old_umask)
        else:
            os.makedirs(directory, exist_ok=True)
    except FileExistsError:
        raise FileExistsError('%s exists and is not a directory.' % directory)

    # ファイルを保存（重要な2つのパターン）
    while True:
        try:
            # パターン1: TemporaryUploadedFile の場合
            #   temporary_file_path() を持っているファイルの場合
            if hasattr(content, 'temporary_file_path'):
                file_move_safe(content.temporary_file_path(), full_path)
                # ← ここでファイルを移動（os.rename）
                # ← 問題: 0o600 パーミッションがそのまま保持される

            # パターン2: MemoryUploadedFile の場合
            #   ストリーミング書き込み
            else:
                fd = os.open(full_path, self.OS_OPEN_FLAGS, 0o666)
                # ← ここで明示的に 0o666 を指定
                # ← umask によって実際の権限は決まる
        except FileExistsError:
            name = self.get_available_name(name)
            full_path = self.path(name)
        else:
            break

    # ★ 重要な修正ポイント ★
    # ファイル保存後、パーミッションを明示的に設定
    if self.file_permissions_mode is not None:
        os.chmod(full_path, self.file_permissions_mode)  # ← 修正！

    return name.replace('\\', '/')
```

**問題と修正:**

| 項目 | 詳細 |
|------|------|
| **問題が発生するのは** | TemporaryUploadedFile の場合 |
| **原因** | file_move_safe() で移動しても、元のファイルの 0o600 パーミッションが保持される |
| **修正** | _save() の最後で os.chmod(full_path, self.file_permissions_mode) を呼び出す |
| **現在の実装** | ✓ 修正済み（os.chmod を実装） |

### 10-2. file_permissions_mode と directory_permissions_mode（行 215-219）

```python
@cached_property
def file_permissions_mode(self):
    """
    FILE_UPLOAD_PERMISSIONS 設定から権限を取得
    デフォルトは None（Django が明示的に権限を設定しない）
    ユーザーが設定すれば、それを使用
    """
    return self._value_or_setting(
        self._file_permissions_mode,
        settings.FILE_UPLOAD_PERMISSIONS
    )

@cached_property
def directory_permissions_mode(self):
    """
    FILE_UPLOAD_DIRECTORY_PERMISSIONS 設定から権限を取得
    """
    return self._value_or_setting(
        self._directory_permissions_mode,
        settings.FILE_UPLOAD_DIRECTORY_PERMISSIONS
    )
```

**動作:**
- `FILE_UPLOAD_PERMISSIONS` が設定されていれば、その値を使用
- 設定されていなければ、None を返す
- None の場合、os.chmod() は呼ばれない

### 10-3. 実装の流れ（レポジトリ内での実行トレース）

**86個の tag が取得されたファイル: django/core/files/storage.py**

主要な関数とクラス:
- `Storage` (class, 行 24): 基本クラス
- `FileSystemStorage` (class, 行 169): ファイルシステム実装
- `save()` (function, 行 37): 基本 save インターフェース
- `_save()` (function, 行 225): 実装の詳細
- `file_permissions_mode()` (property, 行 215): パーミッション取得
- `directory_permissions_mode()` (property, 行 219): ディレクトリ権限取得

---

## 11. RepoGraph による問題追跡

### 11-1. ファイルレベルでの検索キーワード

PoC と問題記述から LLM が提案するべき検索キーワード:
```
1. "0o600"
   → find: django/core/files/storage.py
   → function: _save() が 0o600 に関連

2. "FILE_UPLOAD_PERMISSIONS"
   → find: django/core/files/storage.py (file_permissions_mode)
   → Django 設定としてパーミッション管理

3. "TemporaryUploadedFile"
   → find: django/core/files/uploadedfile.py
   → 一時ファイルの実装

4. "os.chmod"
   → find: django/core/files/storage.py (行 ~272)
   → パーミッション修正の場所

5. "file_move_safe"
   → find: django/core/files/move.py
   → 一時ファイル移動時にパーミッション保持
```

### 11-2. RepoGraph ego graph を使った関連関数の探索

**1-hop 関連関数（file_move_safe を中心に）:**

```
[呼び出し元]
  _save()
    → file_move_safe()
        ↓
  [呼び出し先]
    os.rename()
    (パーミッション保持)
```

**流れ:**
1. FileSystemStorage._save() が TemporaryUploadedFile を検出
2. file_move_safe(temp_path, final_path) を呼び出し
3. file_move_safe は内部で os.rename() を使用（パーミッション保持）
4. 結果として 0o600 が最終ファイルに設定される

**修正には必要:**
- os.chmod() を _save() 内で呼び出す
- TemporaryUploadedFile → FileSystemStorage._save() のフロー理解

### 11-3. リポジトリ構造での位置付け

```
django/
├── core/
│   ├── files/
│   │   ├── storage.py          ← ★ 修正ファイル (FileSystemStorage._save)
│   │   ├── uploadedfile.py     ← 一時ファイル定義
│   │   ├── move.py             ← ファイル移動処理
│   │   ├── base.py
│   │   ├── temp.py
│   │   └── utils.py
│   ├── exceptions.py
│   └── ...
│
├── db/
│   ├── models/
│   │   ├── fields/
│   │   │   └── files.py        ← FileField でアップロード受け取り
│   │   └── ...
│   └── ...
│
└── forms/
    ├── fields.py               ← フォーム側のファイルフィールド
    └── ...
```

---

## 12. 次のステップ：RepoGraph の活用

### 12-1. ファイルレベル最適化での改善方法

**現在の問題:**
- LLM が search_string("0o600"), search_func_def("save") などで 152+ のファイルを候補に上げる
- うち実際に修正が必要なのは django/core/files/storage.py のみ
- 他のファイルはノイズ

**RepoGraph による改善:**
```
1. キーワード: ["0o600", "FILE_UPLOAD_PERMISSIONS", "file_move_safe"]

2. 各キーワードの定義ファイル/関連ファイルを取得:
   - 0o600: django/core/files/storage.py
   - FILE_UPLOAD_PERMISSIONS: django/core/files/storage.py
   - file_move_safe: django/core/files/move.py (と呼び出し元)

3. 共通ファイル（Intersection）:
   - django/core/files/storage.py (3/3 キーワード)
   - django/core/files/move.py (1/3 キーワード)
   - django/core/files/uploadedfile.py (part of flow)

4. Tier 分類:
   - Tier 1 (Rank 3): django/core/files/storage.py
   - Tier 2 (Rank 2): django/core/files/move.py
   - Tier 3 (Rank 1): django/core/files/uploadedfile.py, ...

5. LLM への提供:
   - Tier 1-2 のみを候補に提供
   - 精度向上: 152+ → 3 に削減
```

### 12-2. 実装への示唆

この問題は RepoGraph が役に立つケースを示している:
- 複数の検索キーワードがある
- キーワード同士の関連性が重要
- 呼び出し関係（file_move_safe → os.rename）が有効

**推奨アクション:**
1. キーワード交差スコアリング (Intersection Scoring)
2. 定義ファイルベースのフィルタリング
3. 1-hop caller/callee の追加

