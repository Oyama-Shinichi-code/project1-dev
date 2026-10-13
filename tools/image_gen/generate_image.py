"""Pollinations.ai を使った画像生成ツール。

認証不要・APIキー不要で画像生成APIを呼び出せる(2026年時点で確認済み)。
以前のHugging Face版(課金必須と判明)から移行した。
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Windows環境でのコンソール出力の文字化け対策
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_URL = "https://image.pollinations.ai/prompt/{}"
# プロジェクトルート基準のデフォルト保存先 (tools/image_gen/generate_image.py から2階層上)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "tools" / "generated_images"
TIMEOUT_SECONDS = 60


class ImageGenerationError(RuntimeError):
    """画像生成リクエストが失敗したことを示す例外。"""


def _build_default_output_path(prompt: str) -> Path:
    """プロンプトとタイムスタンプから分かりやすいファイル名を自動生成する。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # ファイル名に使えない文字を除去し、長すぎる場合は切り詰める
    safe_prompt = "".join(c if c.isalnum() or c in (" ", "_", "-") else "" for c in prompt)
    safe_prompt = safe_prompt.strip().replace(" ", "_")[:40] or "image"
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OUTPUT_DIR / f"{timestamp}_{safe_prompt}.png"


def generate_image(
    prompt: str,
    output_path: str | Path | None = None,
    width: int = 1024,
    height: int = 1024,
    model: str = "flux",
    seed: int | None = None,
) -> Path:
    """Pollinations.ai APIで画像を生成し、ファイルに保存する。

    Args:
        prompt: 画像生成用のテキストプロンプト。
        output_path: 保存先パス。省略時は tools/generated_images/ 配下に自動命名で保存。
        width: 画像の幅(px)。
        height: 画像の高さ(px)。
        model: 使用モデル("flux", "turbo", "stable-diffusion"等)。
        seed: 再現性のためのシード値。省略時は毎回ランダムな画像になる。

    Returns:
        保存した画像ファイルのPath。

    Raises:
        ImageGenerationError: タイムアウトやHTTPエラー等でリクエストが失敗した場合。
    """
    encoded_prompt = urllib.parse.quote(prompt)
    params = {"width": str(width), "height": str(height), "model": model, "nologo": "true"}
    if seed is not None:
        params["seed"] = str(seed)
    url = BASE_URL.format(encoded_prompt) + "?" + urllib.parse.urlencode(params)

    if output_path is None:
        resolved_output_path = _build_default_output_path(prompt)
    else:
        resolved_output_path = Path(output_path)
        resolved_output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise ImageGenerationError(
                    f"画像生成に失敗しました(HTTPステータス: {response.status})"
                )
            image_data = response.read()
    except urllib.error.HTTPError as e:
        raise ImageGenerationError(
            f"画像生成APIがエラーを返しました(HTTPステータス: {e.code})"
        ) from e
    except urllib.error.URLError as e:
        # タイムアウトやDNS解決失敗等、ネットワーク関連のエラーをまとめて扱う
        raise ImageGenerationError(f"画像生成APIへの接続に失敗しました: {e.reason}") from e

    resolved_output_path.write_bytes(image_data)
    return resolved_output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pollinations.aiで画像を生成する")
    parser.add_argument("prompt", help="画像生成用のプロンプト文")
    parser.add_argument("-o", "--output", help="出力先ファイルパス(省略時は自動命名)")
    parser.add_argument("--width", type=int, default=1024, help="画像の幅(px)")
    parser.add_argument("--height", type=int, default=1024, help="画像の高さ(px)")
    parser.add_argument(
        "--model", default="flux", help="使用モデル(flux, turbo, stable-diffusion等)"
    )
    parser.add_argument("--seed", type=int, default=None, help="再現性のためのシード値")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        saved_path = generate_image(
            prompt=args.prompt,
            output_path=args.output,
            width=args.width,
            height=args.height,
            model=args.model,
            seed=args.seed,
        )
    except ImageGenerationError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"画像を保存しました: {saved_path}")


if __name__ == "__main__":
    main()
