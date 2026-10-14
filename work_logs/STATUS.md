# project1 現在の状況

> このファイルは常に最新状態で上書きする。`/clear` 直後や新しいセッション開始時は、まずこのファイルを読めば現状復帰できる。
> 更新タイミング: ユーザーから明示的に指示があったときのみ（毎プロンプトでは更新しない）。
> 最終更新: 2026-10-14

## プロジェクトの現状
- プロジェクト種別は**デスクトップペット育成シミュレーション**に確定（実質）。`desktop_pet/`で開発中。要件定義は`requirements_drafts/desktop_pet_simulation.md`。
- MVP一式（常駐ウィンドウ、ステータス管理、餌やり/なでるモーション、時間操作、永続化）に加え、アニメーション・各種演出も実装済み。

## Git構成
- `origin`: https://github.com/Oyama-Shinichi-code/project1.git （本番リポジトリ）
- `dev`: https://github.com/Oyama-Shinichi-code/project1-dev.git （検証用リポジトリ、Public）
- `main` ブランチのデフォルト upstream は `dev`。引数なしの `git push`/`git pull` は検証用リポジトリに向く。
- 本番(`origin`)へは、ユーザーからの明示的な指示があったときのみ反映する。
- push操作は `/push-dev`（devのみ）、`/push-all`（dev+origin）のカスタムSkillで行う。

## デスクトップペットアプリ（desktop_pet/）
- 起動: `.venv/Scripts/python.exe -m desktop_pet.main`
- 構成: `pet_state.py`（ステータス管理・永続化）、`controller.py`（アクション処理一元化）、`pet_window.py`（常駐ウィンドウ・UI・モーション）、`tray.py`（システムトレイ）、`effects.py`（パーティクルエフェクト）、`main.py`（エントリーポイント）
- 画像: `desktop_pet/assets/pet/`。通常状態は`normal/`配下の3フレーム往復アニメーション、hungry/angryは静止画（`hungry.png`, `angry.png`）
- 操作: 🍖餌やり / 👋なでる / ⏰時間操作（±10分/±1時間/±1日のサブメニュー）/ ❌終了（ウィンドウのボタン列＋システムトレイメニュー両方から可能）
- モーション仕様:
  - 餌やり（満腹でない時）: 食べかす演出→ハート（180ms加速、2600ms持続）→通常速度(400ms)復帰
  - 餌やり（満腹時=あげすぎ）: 食べかす演出を出さず直接シェイク→通常速度復帰。mood-5のペナルティのみ（hungerは変化しない）
  - なでる: バウンド+キラキラ→ハート（餌やりと共通、180ms加速）→通常速度復帰
  - いずれもモーション中はボタン無効化、モーション完全終了（ハート消滅/シェイク終了）まで再有効化しない
- アニメーション速度調整スライダーは実装済みだが非表示（確認済みのため）。ロジックは生きている。
- **重要なバグ修正**: `PetState.feed()`/`pet()`から`apply_time_decay()`呼び出しを削除済み。時間経過による自然減少は定期タイマー（main.py）のみの責務。各アクションでは対象ステータスの加算のみ行う。

## 画像生成の運用方針
- 通常は `tools/image_gen/generate_image.py`（Pollinations.ai、認証不要・無料）を使う。
- これまでOpenAI・Hugging Face・Google Gemini APIを試したが、いずれも無料枠が実質ゼロ/課金必須と判明し不採用（Pollinations.aiのみ動作確認済みの無料サービス）。
- 高品質な画像が必要な場合は、Microsoft Copilotを**ユーザーが手動で**使い、生成した画像を人力でプロジェクトに取り込む運用（自動化は規約リスクのため行わない）。Claude側からも必要に応じてプロンプト案等を提案する。
- 画像の保存先は `tools/generated_images/`（git管理外）。確定版はアプリ内の`desktop_pet/assets/pet/`等へ移動して使う。

## ディレクトリ構成
- `CLAUDE.md` — プロジェクトスコープのルール
- `prompt_logs/PROMPT_LOG.md` — ユーザーが送信した生のプロンプトを逐一記録（サブエージェントはこのファイルを変更しない）
- `work_logs/STATUS.md`（本ファイル） — 現在の状況のスナップショット
- `work_logs/archive/` — セッション区切りの作業要約（直近: `2026-10-14_06_desktop-pet-motions.md`）
- `requirements_drafts/` — アプリ案4候補の要件定義ドラフト（実質`desktop_pet_simulation.md`が採用）
- `desktop_pet/` — デスクトップペットアプリ本体
- `tools/image_gen/` — 画像生成ツール（Pollinations.ai版）
- `tools/generated_images/` — 生成画像の保存先（git管理外）
- `.claude/skills/` — `push-dev`, `push-all`（カスタムコマンド）, `_template/`（ひな型）
- `.claude/agents/` — 汎用サブエージェント6種, `_template.md`（ひな型）
- `.claude/hooks/` — Hookスクリプト5種, `_template.sh`（ひな型）
- `.venv/` — Python仮想環境（git管理外）、`requirements.txt`で依存管理（PySide6等）

## 検討済みで見送った事項
- `/clear` 実行時のarchive自動化、`/clear`自体のフックブロック（技術的制約により見送り）
- 画像生成のHugging Face・Google Gemini API採用（無料枠なしのため見送り）
- 画像生成・Copilotの自動操作（規約リスクのため見送り、手動運用に統一）

## 運用上の注意（サブエージェントに毎回明記している内容）
- サブエージェントは`prompt_logs/PROMPT_LOG.md`に追記しない（過去に複数回、親からの指示文をユーザー発言と誤記録する事故あり）
- 指示されていない限り、ファイル名・フォルダ名のリネーム等スコープ外の変更をしない（過去に無断リネーム事故あり）

## 次にやること（未決事項）
- 追加モーション・機能（ミニゲーム、会話機能等、要件定義書の拡張ロードマップ参照）
- CLAUDE.mdの「プロジェクト概要」はPython/Webアプリ未確定のままの記述が残っているので、実態（デスクトップペット確定）に合わせて更新を検討してもよい
