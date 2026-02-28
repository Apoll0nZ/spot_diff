#!/usr/bin/env python3
import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from moviepy.audio.AudioClip import AudioClip
from moviepy.video.fx.MaskColor import MaskColor
import numpy as np
from PIL import Image, ImageDraw

VIDEO_W = 1920
VIDEO_H = 1080
FPS = 30


@dataclass
class DiffPoint:
    left_x: int
    left_y: int
    right_x: int
    right_y: int
    radius: int = 36


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_video(path: Path, duration: float = 2.0, color=(20, 20, 20)):
    if path.exists():
        return VideoFileClip(str(path))
    return ColorClip(size=(VIDEO_W, VIDEO_H), color=color, duration=duration)


def safe_audio(path: Path, duration: float = 1.0, volume: float = 1.0):
    if path.exists():
        return AudioFileClip(str(path)).with_volume_scaled(volume)

    def make_frame(_t: float):
        return 0.0

    return AudioClip(make_frame, duration=duration, fps=44100)


def loop_background(bg_clip: VideoFileClip, duration: float):
    base = bg_clip.resized((VIDEO_W, VIDEO_H)).without_audio()
    if base.duration >= duration:
        return base.subclipped(0, duration)
    loops = int(duration // base.duration) + 1
    return concatenate_videoclips([base] * loops, method="compose").subclipped(0, duration)


def loop_audio(audio_clip: AudioClip, duration: float):
    if audio_clip.duration >= duration:
        return audio_clip.subclipped(0, duration)
    loops = int(duration // audio_clip.duration) + 1
    return concatenate_audioclips([audio_clip] * loops).subclipped(0, duration)


def apply_chroma_key(
    clip: VideoFileClip, key_color: Tuple[int, int, int], threshold: float = 90, stiffness: float = 6
):
    return clip.with_effects(
        [MaskColor(color=key_color, threshold=threshold, stiffness=stiffness)]
    )


def make_countdown_clip(duration: float, start_seconds: int = 90):
    # PILでフレーム生成してImageMagick依存を回避
    def make_frame(t: float):
        remaining = max(0, start_seconds - int(t))
        img = Image.new("RGBA", (260, 120), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((0, 0, 260, 120), radius=20, fill=(0, 0, 0, 150))
        txt = f"{remaining:02d}" if remaining < 100 else str(remaining)
        draw.text((85, 28), txt, fill=(255, 255, 255, 255))
        return np.array(img)

    clip = VideoClip(
        frame_function=lambda t: make_frame(t), duration=duration
    ).with_fps(FPS)
    return clip.with_position((VIDEO_W // 2 - 130, 24))


def slide_in_image(path: Path, target_x: int, target_y: int, start_t: float, side: str):
    img = ImageClip(str(path)).resized((930, 780))
    in_duration = 0.8
    off_x = -929 if side == "left" else VIDEO_W - 1

    def pos(t: float):
        local_t = t
        if local_t <= 0:
            return off_x, target_y
        if local_t >= in_duration:
            return target_x, target_y
        p = local_t / in_duration
        eased = 1 - (1 - p) * (1 - p)
        x = off_x + (target_x - off_x) * eased
        return x, target_y

    return img.with_start(start_t).with_position(pos)


def circle_overlay(
    duration: float,
    points: List[Tuple[int, int]],
    radius: int,
    rgba: Tuple[int, int, int, int],
):
    def make_frame(_t: float):
        img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=rgba, width=8)
        return np.array(img)

    return VideoClip(
        frame_function=lambda t: make_frame(t), is_mask=False, duration=duration
    ).with_fps(FPS)


def q_diff_points(q_data: dict) -> List[DiffPoint]:
    out = []
    for p in q_data.get("diff_points", []):
        out.append(
            DiffPoint(
                left_x=int(p["left_x"]),
                left_y=int(p["left_y"]),
                right_x=int(p["right_x"]),
                right_y=int(p["right_y"]),
                radius=int(p.get("radius", 36)),
            )
        )
    return out


def build_question_scene(
    q_idx: int,
    q_data: dict,
    assets: Path,
    used_backgrounds: set,
    timing: dict,
):
    question_clip = safe_video(assets / f"question{q_idx}.mp4", duration=3.0)

    all_bgs = sorted(assets.glob("S*.mp4"))
    candidates = [p for p in all_bgs if p.name not in used_backgrounds] or all_bgs
    if not candidates:
        candidates = []

    if candidates:
        bg_path = random.choice(candidates)
        used_backgrounds.add(bg_path.name)
        bg_base = safe_video(bg_path, duration=8.0)
    else:
        bg_base = ColorClip(size=(VIDEO_W, VIDEO_H), color=(30, 30, 30), duration=8.0)

    description_audio = safe_audio(assets / "description.mp3", duration=3.0)
    cue60_audio = safe_audio(assets / "60s.mp3", duration=1.0)
    cue30_audio = safe_audio(assets / "30s.mp3", duration=1.0)
    answer_audio = safe_audio(assets / "answer.mp3", duration=2.0)
    answer1_audio = safe_audio(assets / "answer1.mp3", duration=1.5)
    answer2_audio = safe_audio(assets / "answer2.mp3", duration=1.5)
    answer3_audio = safe_audio(assets / "answer3.mp3", duration=1.5)
    cheer_audio = safe_audio(assets / "cheer.mp3", duration=2.0)

    count10 = safe_video(assets / "count10.mp4", duration=10.0)
    alarm = safe_video(assets / "alarm.mp4", duration=2.0)

    image_start = float(timing.get("image_start_delay", 0.5))
    countdown_start = image_start
    countdown_duration = float(timing.get("countdown_seconds", 90.0))
    answer_gap_after_seconds = float(timing.get("answer_gap_after_seconds", 4.0))

    after_countdown_t = countdown_start + countdown_duration
    alarm_start = after_countdown_t
    answer_start = alarm_start + alarm.duration
    answer1_start = answer_start + answer_audio.duration
    answer2_start = answer1_start + answer1_audio.duration + answer_gap_after_seconds
    answer3_start = answer2_start + answer2_audio.duration + answer_gap_after_seconds
    cheer_start = answer3_start + answer3_audio.duration + 2.0
    scene_duration = cheer_start + cheer_audio.duration + 2.0

    bg_loop = loop_background(bg_base, scene_duration)

    left_img = slide_in_image(
        assets / q_data["left_image"],
        target_x=20,
        target_y=150,
        start_t=image_start,
        side="left",
    )
    right_img = slide_in_image(
        assets / q_data["right_image"],
        target_x=970,
        target_y=150,
        start_t=image_start,
        side="right",
    )

    question_title_clip = None
    question_title_path = assets / "question_title.png"
    if question_title_path.exists():
        question_title_clip = (
            ImageClip(str(question_title_path))
            .resized(width=880)
            .with_start(countdown_start)
            .with_duration(countdown_duration)
            .with_position(("center", 0))
        )

    count10_start = countdown_start + max(0.0, countdown_duration - 10.0)
    count10_clip = (
        apply_chroma_key(
            count10.resized(height=170),
            key_color=(0, 255, 0),
            threshold=float(timing.get("count10_chroma_threshold", 90)),
        )
        .with_start(count10_start)
        .with_position((VIDEO_W - 230, 16))
    )
    alarm_clip = apply_chroma_key(
        alarm.resized((VIDEO_W, VIDEO_H)),
        key_color=(0, 0, 255),
        threshold=float(timing.get("alarm_chroma_threshold", 90)),
    ).with_start(alarm_start)

    diffs = q_diff_points(q_data)
    colors = [
        (0, 120, 255, 255),
        (255, 220, 0, 255),
        (255, 0, 0, 255),
    ]
    marker_starts = [answer1_start, answer2_start, answer3_start]

    marker_clips = []
    for idx, diff in enumerate(diffs[:3]):
        marker = circle_overlay(
            duration=scene_duration - marker_starts[idx],
            points=[(diff.left_x, diff.left_y), (diff.right_x, diff.right_y)],
            radius=diff.radius,
            rgba=colors[idx],
        ).with_start(marker_starts[idx])
        marker_clips.append(marker)

    scene_layers = [bg_loop, left_img, right_img]
    if question_title_clip is not None:
        scene_layers.append(question_title_clip)
    scene_layers.extend([count10_clip, *marker_clips, alarm_clip])
    scene_video = CompositeVideoClip(scene_layers, size=(VIDEO_W, VIDEO_H)).with_duration(scene_duration)

    scene_audio_layers = [
        description_audio.with_start(image_start),
        cue60_audio.with_start(countdown_start + max(0.0, countdown_duration - 60.0)),
        cue30_audio.with_start(countdown_start + max(0.0, countdown_duration - 30.0)),
        answer_audio.with_start(answer_start),
        answer1_audio.with_start(answer1_start),
        answer2_audio.with_start(answer2_start),
        answer3_audio.with_start(answer3_start),
        cheer_audio.with_start(cheer_start),
    ]
    if count10.audio is not None:
        scene_audio_layers.append(count10.audio.with_start(count10_start))
    if alarm.audio is not None:
        scene_audio_layers.append(alarm.audio.with_start(alarm_start))

    scene_audio = CompositeAudioClip(scene_audio_layers)
    scene_video = scene_video.with_audio(scene_audio)

    return concatenate_videoclips([question_clip, scene_video], method="compose")


def build_video(job: dict, assets: Path, output_path: Path):
    random.seed(job.get("random_seed", 42))
    timing = job.get("timing", {})

    opening = safe_video(assets / "opening.mp4", duration=2.0)
    ending = safe_video(assets / "ending.mp4", duration=2.0)
    main_bgm = safe_audio(assets / "main_bgm.mp3", duration=300.0, volume=0.35)

    used_backgrounds = set()
    questions = []
    for i, q in enumerate(job["questions"], start=1):
        questions.append(build_question_scene(i, q, assets, used_backgrounds, timing))

    main_part = concatenate_videoclips(questions, method="compose")
    bgm_clip = loop_audio(main_bgm, main_part.duration)

    if main_part.audio is not None:
        main_audio = CompositeAudioClip([main_part.audio, bgm_clip.with_start(0)])
    else:
        main_audio = CompositeAudioClip([bgm_clip.with_start(0)])
    main_part = main_part.with_audio(main_audio)

    final = concatenate_videoclips([opening, main_part, ending], method="compose")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
    )


def parse_args():
    p = argparse.ArgumentParser(description="Spot-the-difference video renderer")
    p.add_argument("--job", type=Path, required=True, help="Job JSON path")
    p.add_argument("--assets", type=Path, required=True, help="Assets directory path")
    p.add_argument("--output", type=Path, default=Path("out/final.mp4"), help="Output mp4")
    return p.parse_args()


def main():
    args = parse_args()
    job = load_json(args.job)
    build_video(job, args.assets, args.output)


if __name__ == "__main__":
    main()
