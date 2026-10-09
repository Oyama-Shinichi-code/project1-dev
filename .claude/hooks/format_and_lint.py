#!/usr/bin/env python3
"""
PostToolUse (matcher: Edit|Write) フック。
編集/作成されたファイルが .py の場合のみ black -> ruff --fix -> mypy を順に実行する。
PostToolUseはツール実行後に呼ばれるため、ここでの判定結果でツール呼び出し自体をブロックすることはできない
(stdout出力はadditionalContext等の付加情報用。失敗してもClaudeの処理は止めない設計とする)。
ツールが未インストールの場合は何もしない(プロジェクトのスタックがまだPython確定ではないため)。
"""
import json
import subprocess
import sys

TIMEOUT_SEC = 30


def main() -> int:
    # stdinからJSONを受け取る。形式: {"tool_input": {"file_path": "..."}, ...}
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # 入力が壊れていてもフックの失敗でClaude Codeを止めない
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    commands = [
        ["black", "--quiet", file_path],
        ["ruff", "check", "--fix", "--quiet", file_path],
        ["mypy", file_path],
    ]

    for cmd in commands:
        try:
            subprocess.run(cmd, timeout=TIMEOUT_SEC, capture_output=True)
        except FileNotFoundError:
            # black/ruff/mypyが未インストール -> 何もせず正常終了(エラーにしない)
            return 0
        except subprocess.TimeoutExpired:
            # タイムアウトしても後続処理をブロックしない
            return 0
        # 各ツールの戻り値(lintエラー等)はここでは無視し、常に正常終了させる

    return 0


if __name__ == "__main__":
    sys.exit(main())
