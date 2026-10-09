#!/usr/bin/env python3
"""
PreToolUse (matcher: Bash) フック。
危険なコマンドパターンにマッチしたBash実行をブロックする。

出力仕様について:
  公式ドキュメント(https://code.claude.com/docs/en/hooks.md)のPreToolUseセクションを確認した結果、
  現行仕様ではトップレベルの {"decision": "block", "reason": "..."} ではなく、
  hookSpecificOutput.permissionDecision (値: "allow" | "deny" | "ask" | "defer") を使う形式が
  正とされている。ブロック時は permissionDecision="deny" + permissionDecisionReason を返す。
  (旧仕様のdecision/reasonトップレベル形式は非推奨とみなし、本実装では使用しない。
   ドキュメントの更新頻度次第で変わる可能性があるため、将来仕様が変わっていないか要確認。)
マッチしない場合は何も出力せず(stdoutを空のまま)正常終了する -> 通常の許可フローに委ねられる。
"""
import json
import re
import sys

# 危険とみなすコマンドパターン(正規表現)。大文字小文字は区別しない想定はせず、シェル上の慣習に合わせる。
DANGEROUS_PATTERNS = [
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\b", "rm -rf 相当の再帰強制削除コマンド"),
    (r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r\b", "rm -fr 相当の再帰強制削除コマンド"),
    (r"\bgit\s+push\s+.*(--force|-f)\b", "git push --force / -f (強制push)"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard (作業内容の破棄)"),
    (r"\bgit\s+clean\s+.*-f", "git clean -f (未追跡ファイルの強制削除)"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "フォークボム"),
    (r"\bmkfs\b", "mkfs (ファイルシステム作成/初期化)"),
    (r">\s*/dev/sd[a-z]\b", "ディスクデバイスへの直接書き込み"),
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = data.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    for pattern, label in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"危険なコマンドパターン「{label}」を検出したためブロックしました: {command}",
                }
            }
            # Windows環境でのcp932/UTF-8不一致による文字化けを避けるため\uXXXXエスケープで出力する
            print(json.dumps(output, ensure_ascii=True))
            return 0

    # マッチしない場合は何も出力しない
    return 0


if __name__ == "__main__":
    sys.exit(main())
