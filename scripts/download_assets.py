#!/usr/bin/env python3
import argparse
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

    paginator = s3.get_paginator("list_objects_v2")
    total = 0
    for page in paginator.paginate(Bucket=args.bucket, Prefix=args.prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            rel = key[len(args.prefix) :].lstrip("/")
            local = args.dest / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(args.bucket, key, str(local))
            total += 1
            print(f"downloaded: s3://{args.bucket}/{key} -> {local}")

    print(f"done. downloaded files: {total}")


if __name__ == "__main__":
    main()
