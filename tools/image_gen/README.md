# 画像生成ツール (gpt-image-1)

このツールはOpenAIの画像生成API（`gpt-image-1`）を使用して、テキストプロンプトから画像を生成します。

## 概要

- **用途**: テキストプロンプトからPNG形式の画像を生成
- **利用API**: OpenAI `gpt-image-1`
- **使用方法**: Python関数として呼び出すか、CLIから直接実行可能

## 前提条件

### OpenAI APIキー

このツールを使用するにはOpenAIのAPIキーが必要です。

- **取得方法**: https://platform.openai.com で管理画面にアクセスし、APIキーを発行してください
- **注意**: APIキーは秘密情報として扱い、コードやGitに含めないでください

## セットアップ手順

### 1. 仮想環境の準備

プロジェクトルートで仮想環境 `.venv` がまだなければ作成します：

```powershell
python -m venv .venv
```

### 2. 依存パッケージのインストール

プロジェクトルート（`.venv` と同じディレクトリ）から以下を実行：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 3. APIキーの設定

プロジェクトルートに `.env` ファイルを作成します。`.env.example` をテンプレートに使用：

```bash
# .env.example をコピー
copy .env.example .env

# または手動作成：
# .env の内容:
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
```

`.env` ファイルは `.gitignore` に含まれており、Gitで管理されません。各自で設定が必要です。

## 使い方

### CLIから実行

```powershell
.venv/Scripts/python.exe tools/image_gen/generate_image.py "プロンプト文" -o output.png --size 1024x1024
```

#### CLIオプション

| オプション | 説明 | デフォルト |
|-----------|------|----------|
| `prompt`（位置引数） | 画像生成用のプロンプト文（必須） | - |
| `-o, --output` | 出力先ファイルパス | `output.png` |
| `--size` | 画像サイズ | `1024x1024` |

#### 使用例

```powershell
# デフォルト設定で生成
.venv/Scripts/python.exe tools/image_gen/generate_image.py "青空と白い雲"

# 出力先を指定
.venv/Scripts/python.exe tools/image_gen/generate_image.py "猫がコーヒーを飲んでいる" -o cat.png

# サイズを変更（縦長）
.venv/Scripts/python.exe tools/image_gen/generate_image.py "夜景" --size 1024x1536
```

### Pythonコードから使用

```python
from tools.image_gen.generate_image import generate_image

# 画像を生成
output_path = generate_image(
    prompt="青い海と夕日",
    output_path="sunset.png",
    size="1024x1024"
)
print(f"保存しました: {output_path}")
```

#### 関数シグネチャ

```python
def generate_image(
    prompt: str,
    output_path: str | Path,
    size: str = "1024x1024"
) -> Path
```

- **prompt**: 画像生成用のテキストプロンプト
- **output_path**: 画像の保存先パス（ファイルが存在しない場合は自動作成）
- **size**: 画像サイズ（省略時は `1024x1024`）
- **戻り値**: 保存した画像ファイルのPathオブジェクト

## サポートしているサイズ

gpt-image-1がサポートするサイズは以下の4種類です：

- `1024x1024` （正方形）
- `1024x1536` （縦長）
- `1536x1024` （横長）
- `auto` （モデルが最適なサイズを自動選択）

## トラブルシューティング

### `OPENAI_API_KEY が設定されていません` エラー

**原因**: `.env` ファイルが作成されていない、または `OPENAI_API_KEY` が設定されていない

**解決方法**:
1. プロジェクトルートに `.env` ファイルが存在することを確認
2. `.env` ファイルに `OPENAI_API_KEY=sk-...` の形式でAPIキーが記載されているか確認
3. ファイル保存後、再度実行してみてください

### APIキーが無効なエラー

**原因**: APIキーが正しくない、または有効期限切れ

**解決方法**:
1. https://platform.openai.com で現在のAPIキーを確認
2. 必要に応じて新しいAPIキーを発行し、`.env` を更新
3. `.env` ファイルには余分なスペースが入らないようご注意ください

### `未サポートのsizeです` エラー

**原因**: 指定したサイズが上記サポート値に含まれていない

**解決方法**: 上記の「サポートしているサイズ」から選択してください

## 参考

- [OpenAI API ドキュメント](https://platform.openai.com/docs/guides/images)
- プロジェクト内の依存パッケージ: `requirements.txt`
