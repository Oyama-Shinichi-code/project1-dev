#!/usr/bin/env python3
"""
PreToolUse (matcher: Edit|Write) フック。
秘密情報を含みやすいファイルパスへの編集/書き込みをブロックする。
出力仕様はblock_dangerous_commands.pyと同じ(hookSpecificOutput.permissionDecision="deny")。
"""
import json
import re
import sys

# 明らかにテンプレート/サンプルと分かるファイル名は許可する(秘密情報パターンより先に判定)
ALLOW_PATTERNS = [
    r"\.env\.example$",
    r"\.env\.sample$",
    r"\.env\.template$",
    r"example",
    r"sample",
    r"template",
]

# 秘密情報を含みやすいパターン
SECRET_PATTERNS = [
    r"(^|[/\\])\.env(\.[^/\\]*)?$",  # .env, .env.local など
    r"secret",
    r"credentials?",
    r"(^|[/\\])id_rsa$",
    r"(^|[/\\])id_dsa$",
    r"(^|[/\\])id_ecdsa$",
    r"(^|[/\\])id_ed25519$",
    r"\.pem$",
    r"\.pfx$",
    r"\.p12$",
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    lower_path = file_path.lower()

    # テンプレートと分かるものは明示的に許可(先に判定して秘密パターンより優先)
    for pattern in ALLOW_PATTERNS:
        if re.search(pattern, lower_path, re.IGNORECASE):
            return 0

    for pattern in SECRET_PATTERNS:
        if re.search(pattern, lower_path, re.IGNORECASE):
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"秘密情報を含む可能性のあるファイルパスのため編集をブロックしました: {file_path}"
                    ),
                }
            }
            # Windows環境でのcp932/UTF-8不一致による文字化けを避けるため\uXXXXエスケープで出力する
            print(json.dumps(output, ensure_ascii=True))
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
