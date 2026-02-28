#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def parse_args():
    p = argparse.ArgumentParser(description="Upload rendered video to YouTube")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--tags", nargs="*", default=[])
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--token-json", required=True, help="YOUTUBE_TOKEN_JSON")
    p.add_argument("--client-secrets-json", required=True, help="YOUTUBE_CLIENT_SECRETS_JSON")
    return p.parse_args()


def build_client(token_json: str, client_secrets_json: str):
    token_data = json.loads(token_json)
    client = json.loads(client_secrets_json)["installed"]

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=client["token_uri"],
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)


def main():
    args = parse_args()
    youtube = build_client(args.token_json, args.client_secrets_json)

    body = {
        "snippet": {
            "title": args.title,
            "description": args.description,
            "tags": args.tags,
            "categoryId": "24",
        },
        "status": {"privacyStatus": args.privacy},
    }

    media = MediaFileUpload(str(args.video), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = req.next_chunk()
        if response and "id" in response:
            print(response["id"])
            return


if __name__ == "__main__":
    main()
