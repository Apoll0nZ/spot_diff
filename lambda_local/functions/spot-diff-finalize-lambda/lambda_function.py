#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, List

import boto3

from common_spot_diff import DIFF_COUNT, GRID_COLS, GRID_ROWS, QUESTION_COUNT


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def _put_json(s3_client: Any, bucket: str, key: str, payload: Dict[str, Any]) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _get_json(s3_client: Any, bucket: str, key: str) -> Dict[str, Any]:
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body.decode("utf-8"))


def trigger_github_actions(run_id: str) -> None:
    """GitHub Actionsを起動する"""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    
    if not token or not repo:
        LOGGER.warning("GITHUB_TOKEN or GITHUB_REPO not set")
        return
    
    url = f"https://api.github.com/repos/{repo}/actions/workflows/render_and_upload.yml/dispatches"
    
    payload = json.dumps({
        "ref": "main",
        "inputs": {
            "run_id": run_id,
            "use_dummy_assets": "false",
            "upload_to_youtube": "false"
        }
    }).encode()
    
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }, method="POST")
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 204:
                LOGGER.info(f"GitHub Actions triggered successfully for run_id: {run_id}")
            else:
                LOGGER.error(f"Failed to trigger GitHub Actions: {response.status}")
    except Exception as e:
        LOGGER.error(f"Error triggering GitHub Actions: {e}")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    finalize_started = time.time()
    LOGGER.info("finalize event=%s", json.dumps(event, ensure_ascii=False))

    bucket = event["bucket"]
    prefix = event["prefix"]
    run_id = event["run_id"]
    seed = int(event["seed"])
    pipeline_started_at = float(event.get("pipeline_started_at", finalize_started))

    question_results: List[Dict[str, Any]] = event.get("question_results", [])
    question_results = sorted(question_results, key=lambda x: x.get("question_no", 999))
    if len(question_results) != QUESTION_COUNT:
        raise RuntimeError(f"question count mismatch: expected={QUESTION_COUNT} got={len(question_results)}")

    s3 = boto3.client("s3")
    manifest_questions: List[Dict[str, Any]] = []
    video_render_questions: List[Dict[str, Any]] = []
    
    for item in question_results:
        json_s3_key = item["json_s3_key"]
        diff_json = _get_json(s3, bucket, json_s3_key)
        
        # manifest用データ（Webアプリ用）
        manifest_questions.append(
            {
                "question_no": diff_json["question_no"],
                "theme": diff_json.get("theme", item.get("theme", "")),
                "base_s3_key": item["base_s3_key"],
                "diff_s3_key": item["diff_s3_key"],
                "json_s3_key": json_s3_key,
                "diff_points": diff_json.get("diff_points", []),
            }
        )
        
        # video render用データ（動画生成用）
        valid_diff_points = []
        
        # mask_targetsからdiff_pointsを生成（cx/cyを中心座標として使用）
        mask_targets = diff_json.get("mask_targets", [])
        for target in mask_targets:
            # cx/cyを左右の円の中心座標として使用
            diff_point = {
                "left_x": target["cx"],
                "left_y": target["cy"],
                "right_x": target["cx"],
                "right_y": target["cy"],
                "radius": 60  # 表示用は固定60px（マスク半径とは別）
            }
            valid_diff_points.append(diff_point)
        
        video_render_questions.append(
            {
                "question_no": diff_json["question_no"],
                "theme": diff_json.get("theme", item.get("theme", "")),
                "left_image": f"Q{diff_json['question_no']}_Left.png",
                "right_image": f"Q{diff_json['question_no']}_Right.png",
                "image_height": diff_json.get("image_size", {}).get("height", 1024),
                "image_width": diff_json.get("image_size", {}).get("width", 896),
                "diff_points": valid_diff_points,
            }
        )

    now = time.time()
    manifest = {
        "run_id": run_id,
        "grid": {"cols": GRID_COLS, "rows": GRID_ROWS},
        "diff_count": DIFF_COUNT,
        "question_count": QUESTION_COUNT,
        "seed": seed,
        "questions": sorted(manifest_questions, key=lambda x: x["question_no"]),
        "pipeline_started_at": pipeline_started_at,
        "pipeline_elapsed_seconds": round(now - pipeline_started_at, 2),
        "finalize_elapsed_seconds": round(now - finalize_started, 2),
    }
    
    # video render用JSON
    video_render = {
        "run_id": run_id,
        "seed": seed,
        "questions": sorted(video_render_questions, key=lambda x: x["question_no"]),
    }
    
    # manifest.jsonを保存（Webアプリ用）
    manifest_key = f"{prefix.rstrip('/')}/{run_id}/manifest.json"
    _put_json(s3, bucket, manifest_key, manifest)
    
    # video_render.jsonを保存（動画生成用）
    video_render_key = f"{prefix.rstrip('/')}/{run_id}/video_render.json"
    _put_json(s3, bucket, video_render_key, video_render)
    
    manifest["manifest_s3_key"] = manifest_key
    manifest["video_render_s3_key"] = video_render_key
    LOGGER.info("finalize completed run_id=%s", run_id)
    
    # GitHub Actionsを起動してvideo_render.jsonを生成
    trigger_github_actions(run_id)
    
    return manifest
