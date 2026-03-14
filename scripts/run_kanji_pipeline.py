#!/usr/bin/env python3
import argparse
import os
import subprocess
from pathlib import Path


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def parse_args():
    p = argparse.ArgumentParser(description="漢字動画生成 + YouTubeアップロードパイプライン")
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("out/kanji_quiz.mp4"))
    p.add_argument("--test", action="store_true", help="テストモード: 1問のみ・10秒カウントダウン")
    p.add_argument("--upload", action="store_true", help="YouTubeにアップロード")
    p.add_argument("--title", default="漢字穴埋めクイズ", help="動画タイトル")
    p.add_argument("--description", default="", help="動画説明")
    p.add_argument("--tags", nargs="*", default=["漢字クイズ", "脳トレ", "漢字", "クイズ"], help="タグ")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"], help="プライバシー設定")
    return p.parse_args()


def main():
    args = parse_args()

    # 漢字動画生成
    render_cmd = [
        "python3",
        "lambda_local/render_kanji_video.py",
        "--job",
        str(args.job),
        "--assets",
        str(args.assets),
        "--output",
        str(args.output),
    ]
    
    if args.test:
        render_cmd.append("--test")
    
    run(render_cmd)

    # YouTubeアップロード
    if args.upload:
        token_json = os.environ.get("YOUTUBE_TOKEN_JSON", "")
        client_json = os.environ.get("YOUTUBE_CLIENT_SECRETS_JSON", "")
        if not token_json or not client_json:
            raise RuntimeError("YOUTUBE_TOKEN_JSON and YOUTUBE_CLIENT_SECRETS_JSON are required for upload")

        # チャプター情報を説明文に追加
        chapters_text = extract_chapters_from_log(str(args.output).replace('.mp4', '.log'))
        full_description = args.description
        if chapters_text:
            full_description += f"\n\n{chapters_text}"

        upload_cmd = [
            "python3",
            "scripts/upload_to_youtube.py",
            "--video",
            str(args.output),
            "--title",
            args.title,
            "--description",
            full_description,
            "--privacy",
            args.privacy,
            "--token-json",
            token_json,
            "--client-secrets-json",
            client_json,
            "--tags",
            *args.tags,
        ]
        
        run(upload_cmd)


def extract_chapters_from_log(log_file: str) -> str:
    """ログファイルからチャプター情報を抽出"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        chapters = []
        for line in lines:
            if "YouTubeチャプター" in line:
                continue
            if ":" in line and any(char in line for char in ["第", "オープニング", "エンディング"]):
                chapters.append(line.strip())
        
        if chapters:
            return "チャプター:\n" + "\n".join(chapters)
        return ""
    except FileNotFoundError:
        return ""


if __name__ == "__main__":
    main()
