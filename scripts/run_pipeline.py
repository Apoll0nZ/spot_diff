#!/usr/bin/env python3
import argparse
import os
import subprocess
from pathlib import Path


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def parse_args():
    p = argparse.ArgumentParser(description="Render + optional YouTube upload pipeline")
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/spot_diff.mp4"))
    p.add_argument("--upload", action="store_true")
    p.add_argument("--title", default="脳トレ間違い探し")
    p.add_argument("--description", default="")
    p.add_argument("--tags", nargs="*", default=["間違い探し", "脳トレ", "SpotTheDifference"])
    return p.parse_args()


def main():
    args = parse_args()

    run(
        [
            "python3",
            "scripts/render_spot_diff_video.py",
            "--job",
            str(args.job),
            "--assets",
            str(args.assets),
            "--output",
            str(args.output),
        ]
    )

    if args.upload:
        token_json = os.environ.get("YOUTUBE_TOKEN_JSON", "")
        client_json = os.environ.get("YOUTUBE_CLIENT_SECRETS_JSON", "")
        if not token_json or not client_json:
            raise RuntimeError("YOUTUBE_TOKEN_JSON and YOUTUBE_CLIENT_SECRETS_JSON are required for upload")

        run(
            [
                "python3",
                "scripts/upload_to_youtube.py",
                "--video",
                str(args.output),
                "--title",
                args.title,
                "--description",
                args.description,
                "--privacy",
                "private",
                "--token-json",
                token_json,
                "--client-secrets-json",
                client_json,
                "--tags",
                *args.tags,
            ]
        )


if __name__ == "__main__":
    main()
