# project1 現在の状況

> このファイルは常に最新状態で上書きする。`/clear` 直後や新しいセッション開始時は、まずこのファイルを読めば現状復帰できる。
> 更新タイミング: ユーザーから明示的に指示があったときのみ（毎プロンプトでは更新しない）。
> 最終更新: 2026-10-09

## プロジェクトの現状
- プロジェクト種別は Python か Webアプリかまだ未確定。`requirements_drafts/` に4候補の要件定義ドラフトを作成済み（詳細は後述）。
- 実コードはまだ存在しない。現時点はリポジトリ・運用ルール・Claude Code拡張（Skills/Agents/Hooks）の整備が中心。

## Git構成
- `origin`: https://github.com/Oyama-Shinichi-code/project1.git （本番リポジトリ）
- `dev`: https://github.com/Oyama-Shinichi-code/project1-dev.git （検証用リポジトリ、Public）
- `main` ブランチのデフォルト upstream は `dev`。引数なしの `git push`/`git pull` は検証用リポジトリに向く。
- 本番(`origin`)へは、ユーザーからの明示的な指示があったときのみ反映する。
- push操作は `/push-dev`（devのみ）、`/push-all`（dev+origin）のカスタムSkillで行う。

## ⚠️ 未コミットの変更あり（2026-10-09時点）
以下がまだコミット・push前の状態（ユーザーの指示でコミット前にログ記録を実施）:
- `.claude/agents/`: `code-reviewer`, `test-writer`, `debugger`, `security-reviewer`, `doc-writer`, `changelog-writer`（汎用サブエージェント6種、新規）
- `.claude/hooks/`: `format_and_lint.py`, `block_dangerous_commands.py`, `protect_secrets.py`, `load_status.py`, `inject_git_context.py`（新規、動作確認済み）
- `.claude/settings.json`（新規、上記5 Hooksを登録済み）
- `.gitignore`（新規）
- `CLAUDE.md`, `prompt_logs/PROMPT_LOG.md`（更新）
- 次にやるべきこと: ユーザーの指示があれば `/push-dev` 等でコミット・push する。

## ディレクトリ構成
- `CLAUDE.md` — プロジェクトスコープのルール
- `prompt_logs/PROMPT_LOG.md` — ユーザーが送信した生のプロンプトを逐一記録
- `work_logs/STATUS.md`（本ファイル） — 現在の状況のスナップショット
- `work_logs/archive/` — セッション区切りの作業要約（直近: `2026-10-09_04_agents-and-hooks.md`）
- `requirements_drafts/` — アプリ案4候補の要件定義ドラフト（`trpg_ai_gamemaster.md`, `desktop_pet_simulation.md`, `local_rag_chat.md`, `paint_tool.md`）
- `.claude/skills/` — `push-dev`, `push-all`（カスタムコマンド）, `_template/`（ひな型）
- `.claude/agents/` — 汎用サブエージェント6種, `_template.md`（ひな型）
- `.claude/hooks/` — Hookスクリプト5種, `_template.sh`（ひな型）

## 検討済みで見送った事項
- `/clear` 実行時のarchive自動化（技術的制約により見送り、手動運用に統一）
- `/clear` 自体をフックでブロックして確認を挟む案（確実な実現方法が見つからず見送り、ユーザーが手動で慎重に実行する運用）

## 次にやること（未決事項）
- 未コミットの変更をコミット・push（ユーザーの指示待ち）
- プロジェクト種別（Python / Webアプリ）の確定。`requirements_drafts/`の4候補（TRPGアプリが現時点の最有力）を比較検討中
- 種別確定後、CLAUDE.md の「言語・基本方針」セクションを具体化する
- プロジェクト固有のサブエージェント・Skill・Hookは種別確定後に追加
