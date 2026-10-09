#!/usr/bin/env python3
"""
UserPromptSubmit フック。
現在のgitブランチ名と未コミット変更の有無を1行程度の軽量なテキストとして
additionalContextに注入する。トークン消費を抑えるため簡潔にする。
gitリポジトリでない等でgitコマンドが失敗した場合は何もしない。
"""
import json
import subprocess
import sys

TIMEOUT_SEC = 5


def run_git(args: list) -> str | None:
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def main() -> int:
    # stdinは読み捨てる(プロンプト内容自体は今回使わない)
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    branch = run_git(["branch", "--show-current"])
    if branch is None:
        # gitリポジトリでない、またはgit未導入 -> 何もしない
        return 0

    status = run_git(["status", "--short"])
    dirty = bool(status)

    context = f"[git: {branch or '(detached)'}, {'未コミットの変更あり' if dirty else '変更なし'}]"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }
    # Windows環境でのcp932/UTF-8不一致による文字化けを避けるため\uXXXXエスケープで出力する
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
