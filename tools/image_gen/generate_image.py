"""
OpenAI の画像生成API (gpt-image-1) を使った汎用画像生成モジュール。

どのプロジェクトからも
`from tools.image_gen.generate_image import generate_image` でインポートして使える独立モジュール。

CLIとしても実行可能:
    python generate_image.py "プロンプト文" -o output.png --size 1024x1024
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Windows環境でのcp932/UTF-8不一致によるコンソール出力の文字化けを避ける
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# gpt-image-1 がサポートするサイズ値（公式ドキュメント確認済み: 正方形 or 縦長/横長の3種 + auto）。
SUPPORTED_SIZES = ("1024x1024", "1024x1536", "1536x1024", "auto")
DEFAULT_SIZE = "1024x1024"

# プロジェクトルートの .env を読み込む（このファイルから2階層上がルート: tools/image_gen/ -> project1/）。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")


def generate_image(prompt: str, output_path: str | Path, size: str = DEFAULT_SIZE) -> Path:
    """gpt-image-1 で画像を生成し、output_path にPNG等として保存してPathを返す。

    Args:
        prompt: 画像生成のプロンプト文。
        output_path: 保存先ファイルパス。
        size: "1024x1024" / "1024x1536" / "1536x1024" / "auto" のいずれか。

    Returns:
        保存した画像ファイルのPath。

    Raises:
        ValueError: size が未サポートの値、または OPENAI_API_KEY が未設定の場合。
    """
    if size not in SUPPORTED_SIZES:
        raise ValueError(
            f"未サポートのsizeです: {size!r} (サポート値: {', '.join(SUPPORTED_SIZES)})"
        )

    # APIキーが無い状態でクライアントを作ると分かりにくいエラーになるため、先に明示チェックする。
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError(
            "OPENAI_API_KEY が設定されていません。"
            "プロジェクトルートの .env に OPENAI_API_KEY=sk-... の形式で設定してください"
            "（.env.example を参考にしてください）。"
        )

    client = OpenAI()

    # gpt-image-1 は response_format パラメータを受け付けず、常に b64_json 形式でのみ画像データを返す
    # （dall-e-2/3 はresponse_format="url"等が選べたが、gpt-image-1では廃止されている）。
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size,
        n=1,
    )

    b64_data = response.data[0].b64_json
    image_bytes = base64.b64decode(b64_data)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)

    return output_path


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenAI gpt-image-1 を使った画像生成CLI")
    parser.add_argument("prompt", help="画像生成用のプロンプト文")
    parser.add_argument(
        "-o", "--output", default="output.png", help="出力先ファイルパス（デフォルト: output.png）"
    )
    parser.add_argument(
        "--size",
        default=DEFAULT_SIZE,
        choices=SUPPORTED_SIZES,
        help=f"画像サイズ（デフォルト: {DEFAULT_SIZE}）",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    saved_path = generate_image(args.prompt, args.output, size=args.size)
    print(f"画像を保存しました: {saved_path}")
