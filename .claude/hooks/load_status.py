#!/usr/bin/env python3
"""
SessionStart フック。
work_logs/STATUS.md が存在すれば読み込み、additionalContextとして返す。
新しいセッション開始時にClaudeがプロジェクトの現状をすぐ把握できるようにする目的。
存在しない場合は何も出力せず正常終了する。
"""
import json
import sys
from pathlib import Path


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    # SessionStart入力のcwdをプロジェクトルートとみなす(通常は起動時のカレントディレクトリ)
    cwd = data.get("cwd")
    if cwd:
        base = Path(cwd)
    else:
        # cwdが取得できない場合は、このスクリプトの位置(.claude/hooks/)から2階層上をルートとみなす
        base = Path(__file__).resolve().parents[2]

    status_file = base / "work_logs" / "STATUS.md"
    if not status_file.is_file():
        return 0

    try:
        content = status_file.read_text(encoding="utf-8")
    except OSError:
        return 0

    if not content.strip():
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"[work_logs/STATUS.md の内容]\n{content}",
        }
    }
    # Windows環境でのcp932/UTF-8不一致による文字化けを避けるため\uXXXXエスケープで出力する
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
