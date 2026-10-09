# セッション要約: 汎用サブエージェント・Hooks整備、要件定義ドラフト (2026-10-09)

## やったこと
1. `push-dev`/`push-all` カスタムSkillを作成（`.claude/skills/`）。コミット+pushの手順を毎回文章で指示する手間を解消。
2. 4候補のアプリ要件定義をサブエージェント（並列4体）で作成し `requirements_drafts/` に保存。
   - `trpg_ai_gamemaster.md`、`desktop_pet_simulation.md`、`local_rag_chat.md`、`paint_tool.md`
   - 複数の独立タスクはサブエージェント並列実行がコンテキスト汚染防止・時間短縮の両面で有利という判断。
3. 汎用サブエージェント6種を `.claude/agents/` に作成: `code-reviewer`, `test-writer`, `debugger`, `security-reviewer`（いずれも`model: sonnet`、正確性重視）, `doc-writer`, `changelog-writer`（いずれも`model: haiku`、誤りのコストが低い文章生成系）。
4. 汎用Hooksを5本実装（サブエージェントに実装委任、`.claude/hooks/`）。
   - `format_and_lint.py`（PostToolUse, Edit|Write）: `.py`ファイルにblack→ruff→mypyを実行。未インストールでもエラーにしない。
   - `block_dangerous_commands.py`（PreToolUse, Bash）: `rm -rf`、`git push --force`、`git reset --hard`等をブロック。
   - `protect_secrets.py`（PreToolUse, Edit|Write）: `.env`等の秘密情報ファイルへの書き込みをブロック（`.env.example`等テンプレートは許可）。
   - `load_status.py`（SessionStart）: `work_logs/STATUS.md`を自動で読み込み、セッション開始時にClaudeへ注入。
   - `inject_git_context.py`（UserPromptSubmit）: 現在のgitブランチ・未コミット変更の有無を毎回軽量に注入。
   - `.claude/settings.json` を新規作成しこれらを登録。
5. 実装後に2つの不具合を発見・修正。
   - **文字化け**: `json.dumps(..., ensure_ascii=False)` がWindowsのcp932/UTF-8不一致で文字化けする問題。全スクリプトで `ensure_ascii=True`（`\uXXXX`エスケープ）に修正。
   - **相対パス解決の脆さ**: hookの`command`を `.claude/hooks/xxx.py` という相対パスで書いていたため、Bashツールの作業ディレクトリが`.claude/hooks`配下に変わった際にパスが二重解決されて全Bash/Edit/Writeがブロックされる事態が発生。`$CLAUDE_PROJECT_DIR`（Claude Codeが実行時に動的設定する環境変数、ハードコードされた絶対パスではない）を使う形に修正し解消。他の開発者がpullしても問題なく動く。
6. `.gitignore` を新規作成（`__pycache__/`, `.venv/`, `.env`等を除外）。

## 決定事項
- サブエージェントの`model`は明示指定する方針。正確性重視はsonnet、文章生成系はhaiku。
- Hookの`command`パスは必ず `$CLAUDE_PROJECT_DIR` 基準の絶対パス形式で書く（相対パスは実行時cwd依存で壊れる）。
- 日本語を含むJSON出力は `ensure_ascii=True` で統一する（Windows環境の文字化け対策）。

## 未コミットの状態（このログを書いた時点）
- 以下が未コミット: `.claude/agents/`配下の6エージェント、`.claude/hooks/`配下の5スクリプト、`.claude/settings.json`、`.gitignore`、`CLAUDE.md`・`prompt_logs/PROMPT_LOG.md`の更新。
- `requirements_drafts/`の4ファイルと`push-dev`/`push-all`スキルは前回セッションで既にコミット・dev push済み。
- コミット・push自体はユーザーからの明示的な指示を待っている状態（実行前に中断された）。

## 未決事項
- プロジェクト種別（Python / Webアプリ）の確定。`requirements_drafts/`の4候補を比較検討中。
