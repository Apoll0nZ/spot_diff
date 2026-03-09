#!/usr/bin/env python3
import argparse
import os
from pathlib import Path

import boto3


def parse_args():
    p = argparse.ArgumentParser(description="Download rendering assets from S3")
    p.add_argument("--bucket", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--dest", type=Path, default=Path("assets/input"))
    return p.parse_args()


def main():
    args = parse_args()
    s3 = boto3.client("s3")
    args.dest.mkdir(parents=True, exist_ok=True)
    total = 0

    # 1. 動画素材を assets/ からダウンロード
    assets_prefix = os.environ.get("S3_ASSETS_PREFIX", "assets/")
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=args.bucket, Prefix=assets_prefix
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            rel = key[len(assets_prefix):].lstrip("/")
            local = args.dest / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(args.bucket, key, str(local))
            print(f"downloaded: {key} -> {local}")
            total += 1

    # 2. 画像を youtube-spot-diff/<run_id>/ からダウンロード
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=args.bucket, Prefix=args.prefix
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            rel = key[len(args.prefix):].lstrip("/")
            local = args.dest / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(args.bucket, key, str(local))
            print(f"downloaded: {key} -> {local}")
            total += 1

    # 3. video_render.json をダウンロード
    try:
        video_render_key = f"{args.prefix}video_render.json"
        s3.download_file(args.bucket, video_render_key, str(args.dest / "video_render.json"))
        print(f"downloaded: video_render.json")
        total += 1
    except Exception as e:
        print(f"video_render.json not found: {e}")

    # 4. q1/base.png → Q1_Left.png にリネーム
    for qnum in range(1, 10):
        for src_name, dst_name in [("base.png", f"Q{qnum}_Left.png"), ("diff.png", f"Q{qnum}_Right.png")]:
            src = args.dest / f"q{qnum}" / src_name
            dst = args.dest / dst_name
            if src.exists():
                src.rename(dst)
                print(f"renamed: q{qnum}/{src_name} -> {dst_name}")

    print(f"done. downloaded files: {total}")


if __name__ == "__main__":
    main()
