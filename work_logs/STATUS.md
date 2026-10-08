# project1 現在の状況

> このファイルは常に最新状態で上書きする。`/clear` 直後や新しいセッション開始時は、まずこのファイルを読めば現状復帰できる。
> 更新タイミング: ユーザーから明示的に指示があったときのみ（毎プロンプトでは更新しない）。
> 最終更新: 2026-10-08

## プロジェクトの現状
- プロジェクト種別は Python か Webアプリかまだ未確定（詳細は [CLAUDE.md](../CLAUDE.md) の「プロジェクト概要」参照）。
- 実コードはまだ存在しない。現時点はリポジトリ・運用ルール・Claude Code拡張の雛形整備が完了した段階。

## Git構成
- `origin`: https://github.com/Oyama-Shinichi-code/project1.git （本番リポジトリ）
- `dev`: https://github.com/Oyama-Shinichi-code/project1-dev.git （検証用リポジトリ、Public）
- `main` ブランチのデフォルト upstream は `dev`。引数なしの `git push`/`git pull` は検証用リポジトリに向く。
- **本番(`origin`)へは、ユーザーからの明示的な指示があったときのみ `git push origin main` のように明示指定して反映する。**

## ディレクトリ構成
- `CLAUDE.md` — プロジェクトスコープのルール（随時更新・最新状態を保つ）
- `prompt_logs/PROMPT_LOG.md` — ユーザーが送信した生のプロンプトを逐一記録（指定がない限り全件記録）
- `work_logs/STATUS.md`（本ファイル） — 現在の状況のスナップショット。ユーザーの指示があったときのみ更新
- `work_logs/archive/` — セッション区切りの作業要約を保管
- `.claude/skills/_template/` — カスタムスキルのひな型（`SKILL.md`）
- `.claude/agents/_template.md` — サブエージェント定義のひな型
- `.claude/hooks/_template.sh` — Hookスクリプトのひな型
- `.claude/settings.json.example` — Hookを登録する際の設定例（実際のhooksはまだ未登録、`.claude/settings.json`自体は未作成）

## 検討済みで見送った事項
- `/clear` 実行時にアーカイブ作成を自動化すること → 技術的制約（SessionEndフックの1.5秒タイムアウト、/clear自体がUserPromptSubmitフックを経由するか不確定）により見送り。archiveの更新は常にユーザーの明示的な指示があったときのみ手動で行う。

## 次にやること（未決事項）
- プロジェクト種別（Python / Webアプリ）の確定。候補出しを行い、詳細は `work_logs/archive/2026-10-08_03_project-idea-candidates.md` 参照。
  - ユーザーは「ゲームがよさそう」と反応。最有力候補は **AIゲームマスター付きテキストアドベンチャー/TRPGアプリ**（Python GUI、agent=NPC応答・ストーリー生成、skill=シナリオテンプレート、hook=セーブ処理）。
  - まだ確定ではなく検討中。
- 種別確定後、CLAUDE.md の「言語・基本方針」セクションを具体化する
- 必要になったタイミングで `.claude/skills/`・`.claude/agents/`・`.claude/hooks/` に実際のスキル・エージェント・Hookを追加する
