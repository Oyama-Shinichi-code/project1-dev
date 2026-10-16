# project1 — デスクトップペット育成シミュレーション

常駐の透過ウィンドウでデスクトップ上にペット（猫）を表示し、餌やり・なでるなどの
お世話をしながらステータス（満腹度/機嫌/体力）を管理する、個人開発のデスクトップアプリです。

## 必要環境

- Windows
- Python 3.x系（最新安定版推奨）
- Git

## セットアップ

```powershell
git clone https://github.com/Oyama-Shinichi-code/project1-dev.git
cd project1

python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

venvはプロジェクトルートの `.venv/` に作成してください（`.gitignore`で除外済み）。
以降、Pythonの実行・パッケージ追加はすべて `.venv/Scripts/python.exe` 経由で行います。

## 起動方法

```powershell
.venv\Scripts\python.exe -m desktop_pet.main
```

起動するとデスクトップ上にペット画像の常駐ウィンドウが表示され、同時にシステムトレイにもアイコンが追加されます。
ウィンドウを閉じてもアプリは終了しません（トレイアイコンの右クリックメニュー、またはウィンドウ上の終了ボタンから終了してください）。

## 操作方法（ウィンドウUI）

ペット画像の右下に、縦に並んだ3つの小さい丸ボタンがあります（下から順）。

| ボタン | 機能 |
| --- | --- |
| ☰ | アクションメニュー（🍖餌やり / 👋なでる / ⏰時間操作 / ❌終了）の開閉 |
| 📊 | ステータスパネル（満腹度/機嫌/体力ゲージ）の開閉 |
| 👁 | リサイズハンドルの見た目（角のL字マーク）の表示/非表示切り替え |

### アクションメニュー（☰を開くと表示）

- **🍖 餌やり**: 満腹度を回復させる。満腹時に与えると「あげすぎ」判定になり、機嫌が下がる演出が出る
- **👋 なでる**: ペット画像をクリックしても同じ「なでる」が発動する
- **⏰ 時間操作**: クリックするとサブメニューが開き、`+10分` / `+1時間` / `+1日` / `-1時間` / `-1日` を選べる（テストプレイ用。時間を戻してもイベント自体は戻らず、内部の時間ステータスのみ巻き戻る）
- **❌ 終了**: アプリを終了する（ステータスは自動保存される）

### ウィンドウ操作

- **ドラッグ移動**: ペット画像をクリック＆ドラッグしてウィンドウ位置を移動
- **リサイズ**: ウィンドウの左上・右上の角にカーソルを合わせてドラッグするとサイズ変更できる（アスペクト比は常に維持、0.5倍〜2.0倍の範囲）

### システムトレイメニュー（右クリック）

ウィンドウ上のボタンと同じ操作（餌やり/なでる/時間操作/終了）をトレイアイコンの右クリックメニューからも行えます。

## データの保存

ステータス（満腹度/機嫌/体力、ウィンドウ位置など）は `desktop_pet/data/pet_state.json` に自動保存されます（`.gitignore`で除外済み。ユーザーごとのプレイ状況のため）。

## exe化（Windows用配布ファイルのビルド）

Python環境が無い人でも実行できるよう、PyInstallerで単体のWindowsアプリ（exe + 同梱DLL一式）としてビルドできます。

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m PyInstaller --name DesktopPet --onedir --windowed --noconfirm `
  --distpath dist_prototype --workpath dist_prototype/_build --specpath dist_prototype/_build `
  --add-data "desktop_pet\assets;desktop_pet/assets" -p . desktop_pet\main.py
```

ビルドが成功すると `dist_prototype/DesktopPet/` 配下に `DesktopPet.exe` と `_internal/`（依存DLL・アセット一式）が生成されます。**このフォルダごと**配布してください（exeファイル単体では動きません）。`dist_prototype/_build/` は中間ファイル（`.spec`・`.toc`等）で、こちらに実行可能なexeは生成されません。**実行・配布には必ず `dist_prototype/DesktopPet/DesktopPet.exe` を使ってください。**

- `dist_prototype/` は丸ごとビルド成果物・中間ファイル（数百MB規模のバイナリ）のため `.gitignore` で除外しています。配布する場合は `dist_prototype/DesktopPet/` フォルダをZIP圧縮するかGitHub Releases等、リポジトリ外の手段を使ってください。
- セーブデータ（`pet_state.json`）はexeと同じ `_internal/desktop_pet/data/` 配下に作成されます。配布先の環境で管理者権限が必要な場所（`C:\Program Files\` 等）に置くと保存に失敗する可能性があるため、デスクトップなど書き込み可能な場所への配置を推奨します。

## 画像生成ツール（開発者向け）

ペット用画像などを生成する場合は `tools/image_gen/generate_image.py`（Pollinations.ai利用、APIキー不要・無料）を使用します。生成された画像は `tools/generated_images/`（git管理外）に保存され、確定版は `desktop_pet/assets/pet/` 等へ手動で移動して使用します。

## プロジェクト構成

```
desktop_pet/        デスクトップペットアプリ本体
  pet_state.py       ステータス管理・永続化
  controller.py       アクション処理の一元化（ウィンドウ/トレイ共通）
  pet_window.py        常駐ウィンドウ・UI・アニメーション・リサイズ
  tray.py              システムトレイメニュー
  effects.py           パーティクルエフェクト
  main.py              エントリーポイント
  assets/pet/           ペット画像
  data/                 セーブデータ（git管理外）
tools/image_gen/     画像生成ツール
requirements.txt     Python依存パッケージ
dist_prototype/      exe化ビルド成果物・中間ファイル（git管理外。DesktopPet/が配布用、_build/が中間ファイル）
```

## 開発ルール

プロジェクトのコーディング規約・Git運用・各種開発ルールは [CLAUDE.md](CLAUDE.md) を参照してください。
