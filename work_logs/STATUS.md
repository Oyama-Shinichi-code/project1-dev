# project1 現在の状況

> このファイルは常に最新状態で上書きする。`/clear` 直後や新しいセッション開始時は、まずこのファイルを読めば現状復帰できる。
> 更新タイミング: ユーザーから明示的に指示があったときのみ（毎プロンプトでは更新しない）。
> 最終更新: 2026-10-13

## プロジェクトの現状
- プロジェクト種別は Python か Webアプリかまだ未確定。`requirements_drafts/` に4候補の要件定義ドラフトを作成済み（詳細は後述）。
- 画像生成ツール（`tools/image_gen/`）は実装済み・コミット済み。Pollinations.ai（認証不要・無料）を使用。
- それ以外の実コードはまだ存在しない。

## Git構成
- `origin`: https://github.com/Oyama-Shinichi-code/project1.git （本番リポジトリ）
- `dev`: https://github.com/Oyama-Shinichi-code/project1-dev.git （検証用リポジトリ、Public）
- `main` ブランチのデフォルト upstream は `dev`。引数なしの `git push`/`git pull` は検証用リポジトリに向く。
- 本番(`origin`)へは、ユーザーからの明示的な指示があったときのみ反映する。
- push操作は `/push-dev`（devのみ）、`/push-all`（dev+origin）のカスタムSkillで行う。
- 直近コミット: `991dac8`（画像生成をPollinations.aiに移行）。未コミットの変更なし。

## 画像生成ツール（tools/image_gen/）
- **使用API**: Pollinations.ai（`https://image.pollinations.ai/prompt/{prompt}`）。認証・APIキー・サインアップ一切不要、完全無料。
- **これまでの試行**: OpenAI(`gpt-image-1`、有料のため削除) → Hugging Face FLUX.1-schnell(トークン取得後402 Payment Required、クレジット必須のため削除) → Pollinations.ai(動作確認済み、採用)。
- **教訓**: 画像生成APIは実装前に実際にAPIを叩いて無料で使えることを確認すること（過去2回、調査段階の情報だけで実装し手戻りが発生した）。
- **制約**: 匿名利用は15秒に1回のレート制限、ウォーターマークが入る可能性あり（`nologo=true`で軽減）。
- **画像の保存先**: 今後生成する画像は `tools/generated_images/` に保存する方針（`.gitignore`で画像バイナリ自体は除外、`.gitkeep`でフォルダ構成のみ保持）。
- `tools/image_gen/README.md`は無し（ユーザーの判断により削除。認証不要になり他者への説明が不要と判断）。
- 使い方: `from tools.image_gen.generate_image import generate_image` または `.venv/Scripts/python.exe tools/image_gen/generate_image.py "プロンプト" [--width] [--height] [--model] [--seed] [-o 出力先]`。

## ディレクトリ構成
- `CLAUDE.md` — プロジェクトスコープのルール
- `prompt_logs/PROMPT_LOG.md` — ユーザーが送信した生のプロンプトを逐一記録
- `work_logs/STATUS.md`（本ファイル） — 現在の状況のスナップショット
- `work_logs/archive/` — セッション区切りの作業要約（直近: `2026-10-13_05_image-gen-pollinations.md`）
- `requirements_drafts/` — アプリ案4候補の要件定義ドラフト（`trpg_ai_gamemaster.md`, `desktop_pet_simulation.md`, `local_rag_chat.md`, `paint_tool.md`）
- `tools/image_gen/` — 画像生成ツール（Pollinations.ai版）
- `tools/generated_images/` — 生成画像の保存先（git管理外）
- `.claude/skills/` — `push-dev`, `push-all`（カスタムコマンド）, `_template/`（ひな型）
- `.claude/agents/` — 汎用サブエージェント6種（`code-reviewer`, `test-writer`, `debugger`, `security-reviewer`, `doc-writer`, `changelog-writer`）, `_template.md`（ひな型）
- `.claude/hooks/` — Hookスクリプト5種（フォーマット/危険コマンドブロック/秘密情報保護/状況読込/git状態注入）, `_template.sh`（ひな型）
- `.venv/` — Python仮想環境（git管理外）、`requirements.txt`で依存管理

## 検討済みで見送った事項
- `/clear` 実行時のarchive自動化（技術的制約により見送り、手動運用に統一）
- `/clear` 自体をフックでブロックして確認を挟む案（確実な実現方法が見つからず見送り、ユーザーが手動で慎重に実行する運用）

## 次にやること（未決事項）
- プロジェクト種別（Python / Webアプリ）の確定。`requirements_drafts/`の4候補（TRPGアプリが現時点の最有力）を比較検討中
- 種別確定後、CLAUDE.md の「言語・基本方針」セクションを具体化する
- プロジェクト固有のサブエージェント・Skill・Hookは種別確定後に追加
