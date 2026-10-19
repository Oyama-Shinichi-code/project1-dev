"""Gemini APIキーの.env読み込み・保存・初回入力ダイアログ。"""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from PySide6.QtWidgets import QInputDialog, QLineEdit

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
ENV_KEY_NAME = "GEMINI_API_KEY"


def load_api_key() -> str | None:
    """.envからGEMINI_API_KEYを読み込む。ファイルやキーが無ければNone。"""
    if not ENV_PATH.exists():
        return None
    values = dotenv_values(ENV_PATH)
    key = values.get(ENV_KEY_NAME)
    return key if key else None


def save_api_key(api_key: str) -> None:
    """.envにGEMINI_API_KEYを書き込む（既存の他キーは保持）。"""
    existing = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    existing[ENV_KEY_NAME] = api_key
    lines = [f"{k}={v}" for k, v in existing.items() if v is not None]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)


def prompt_for_api_key() -> str | None:
    """APIキー入力用のシンプルなダイアログを出す。キャンセル・空入力はNone。"""
    text, ok = QInputDialog.getText(
        None,
        "Gemini APIキーの設定",
        "会話機能を使うにはGemini APIキーが必要です。\n"
        "（Google AI StudioでAPIキーを無料取得できます。未設定でも他の機能は使えます）\n"
        "APIキー:",
        QLineEdit.Normal,
        "",
    )
    if not ok or not text.strip():
        return None
    return text.strip()
