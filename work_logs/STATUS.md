# project1 現在の状況

> このファイルは常に最新状態で上書きする。`/clear` 直後や新しいセッション開始時は、まずこのファイルを読めば現状復帰できる。
> 更新タイミング: ユーザーから明示的に指示があったときのみ（毎プロンプトでは更新しない）。
> 最終更新: 2026-10-20

## プロジェクトの現状
- プロジェクト種別は**デスクトップペット育成シミュレーション**（`desktop_pet/`で開発中）。要件定義は`requirements_drafts/desktop_pet_simulation.md`。
- MVP一式に加え、アニメーション演出・折りたたみUI・ウィンドウリサイズ・exe化・**Gemini APIによる会話評価機能**まで実装済み。要件定義書との差分は`work_logs/archive/2026-10-15_07_requirements_vs_implementation.md`参照（イベント履歴・進化システム・ミニゲーム等は未着手）。
- 直近セッションの詳細は`work_logs/archive/2026-10-20_09_exe-build-and-ai-chat.md`参照（UIモダナイズ、exe化、AI会話機能の紆余曲折をまとめた）。

## ⚠️ 直近の状態（2026-10-20時点）
- `/push-dev`済み、作業ツリーはクリーン（STATUS.md/archive更新分を除く）。
- **会話機能・名前設定機能の実機最終確認がまだ**。次回はここから動作確認を再開してよい。

## Git構成
- `origin`: https://github.com/Oyama-Shinichi-code/project1.git （本番リポジトリ）
- `dev`: https://github.com/Oyama-Shinichi-code/project1-dev.git （検証用リポジトリ、Public）
- `main` ブランチのデフォルト upstream は `dev`。引数なしの `git push`/`git pull` は検証用リポジトリに向く。
- 本番(`origin`)へは、ユーザーからの明示的な指示があったときのみ反映する。
- push操作は `/push-dev`（devのみ）、`/push-all`（dev+origin）のカスタムSkillで行う。

## デスクトップペットアプリ（desktop_pet/）
- 起動: `.venv/Scripts/python.exe -m desktop_pet.main`
- exe実行: `dist_prototype/DesktopPet/DesktopPet.exe`（フォルダごと使う。再ビルド手順はREADME.md参照）
- 構成:
  - `pet_state.py` — ステータス管理・永続化。`PetState.name`（空文字列=未設定）、`chat_history`、`toggle_button_order`等
  - `controller.py` — アクション処理一元化。`submit_chat_message`（会話送信）、`set_pet_name`（名前設定）を含む
  - `pet_window.py` — 常駐ウィンドウ・UI・モーション・リサイズ・会話パネル（最大のファイル、2000行超）
  - `tray.py` — システムトレイ
  - `effects.py` — パーティクルエフェクト
  - `main.py` — エントリーポイント（起動時にGemini APIキー未設定ならダイアログ表示）
  - `ai_chat.py`（新規） — Gemini API通信、`EvaluationWorker(QThread)`
  - `mood_rules.py`（新規） — 評価→mood変化量の変換ロジック（差し替え前提の設計）
  - `api_key_store.py`（新規） — `.env`でのAPIキー管理

### UI構成（2026-10-20時点）
- ペット画像の右下に縦積みの**6つ**のトグルボタン（下から順）: ❌終了 / ☰メニュー / 📊ステータス / 👁→拡大縮小アイコン / 📌最前面固定 / 💬会話。**ドラッグ&ドロップで並び替え可能**（`PetState.toggle_button_order`に永続化）
- `button_bar`（アクションメニュー）・`status_panel`・`chat_panel`（会話パネル）はいずれも折りたたみ式。`chat_panel`は`status_panel`より上（ウィンドウ最上部）に配置し、重なりを構造的に回避
- ウィンドウリサイズは`top_left`/`top_right`角のみ対応、アスペクト比維持、スケール範囲0.5〜2.0
- 📌最前面/最背面はWin32 API（`SetWindowPos`）で制御。最背面固定中は500ms毎に`HWND_BOTTOM`を送り直す

### 会話機能（💬ボタン）
- ユーザーの発言をGemini API（`gemini-3.5-flash-lite`、`thinkingConfig`なし）に送信し、「動物としての反応」をナレーション文＋5段階評価(`very_bad`〜`very_good`)で返させる
- 評価→mood変化量は`mood_rules.compute_mood_delta`（現状は段階ごとの乱数幅。将来「繰り返し発言の減点」等に差し替え予定）
- 不適切入力（暴言・プロンプトインジェクション等）はAIが`is_inappropriate`フラグで検出 → ナレーションは表示せず固定の注意文（赤字）を表示、mood変化なし
- **ペット名が未設定（空文字列）の間は会話不可**。会話パネル内の名前入力欄（設定ボタンなし、`textChanged`でリアルタイム反映、絵文字禁止・15文字まで）に入力すると使えるようになる
- APIキーは`.env`の`GEMINI_API_KEY`。未設定なら起動時に`QInputDialog`で取得（キャンセルしても他機能は通常通り使える）

### モーション・アニメーション仕様
- `normal`/`angry`/`hungry`いずれも2〜3フレームの往復アニメーション（`EXPRESSION_ANIM_FRAMES`辞書で一元管理）
- 怒り時: 💢エフェクトが顔の左下(小)→右上(中、300ms後追加)→休止のサイクルでループ
- 餌やり/なでる: 既存のハート・シェイク演出（詳細はコード内コメント参照）

## 画像生成の運用方針
- 通常は `tools/image_gen/generate_image.py`（Pollinations.ai、認証不要・無料）を使う。
- 高品質な画像が必要な場合は、Microsoft Copilotを**ユーザーが手動で**使い、人力で取り込む運用。
- 画像の保存先は `tools/generated_images/`（git管理外）。確定版は`desktop_pet/assets/pet/`等へ移動。

## ディレクトリ構成
- `CLAUDE.md` — プロジェクトスコープのルール
- `README.md` — セットアップ手順・UI説明・exe化手順
- `prompt_logs/PROMPT_LOG.md` — ユーザーが送信した生のプロンプトを逐一記録
- `work_logs/STATUS.md`（本ファイル） — 現在の状況のスナップショット
- `work_logs/archive/` — セッション区切りの作業要約（直近: `2026-10-20_09_exe-build-and-ai-chat.md`）
- `desktop_pet/` — デスクトップペットアプリ本体（構成は上記参照）
- `dist_prototype/` — exe化ビルド成果物・中間ファイル（git管理外。`DesktopPet/`が配布用、`_build/`が中間ファイル）
- `.env` / `.env.example` — Gemini APIキー（`.env`はgit管理外）
- `tools/image_gen/` — 画像生成ツール（Pollinations.ai版）
- `tools/generated_images/` — 生成画像の保存先（git管理外）
- `.claude/skills/` — `push-dev`, `push-all`, `_template/`
- `.claude/agents/` — 汎用サブエージェント6種, `_template.md`
- `.claude/hooks/` — Hookスクリプト5種, `_template.sh`
- `.venv/` — Python仮想環境（git管理外）。依存: PySide6, requests, python-dotenv, pyinstaller

## 検討済みで見送った事項
- `/clear` 実行時のarchive自動化（技術的制約により見送り）
- 画像生成のHugging Face・Google Gemini API採用（無料枠なしのため見送り、画像生成はPollinations.aiに統一）
- exe化で`--onefile`形式（`__file__`が不安定になるため`--onedir`を採用）

## 運用上の注意（サブエージェントに毎回明記している内容）
- サブエージェントは`prompt_logs/PROMPT_LOG.md`に追記しない
- 指示されていない限り、ファイル名・フォルダ名のリネーム等スコープ外の変更をしない

## 次にやること（未決事項）
1. 会話機能・名前設定機能の実機最終確認（直近の変更が未確認の可能性あり、まずユーザーに確認）
2. 要件定義書との差分のうち、次に着手するもの（イベント履歴、進化システム、ミニゲーム等）を検討
3. 評価ロジック（`mood_rules.py`）の高度化（同一発言の繰り返し減点、拒否反応連呼の指数関数的減点等）はユーザーから将来実装の意向あり、着手時はここに追記
