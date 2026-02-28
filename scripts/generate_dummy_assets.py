#!/usr/bin/env python3
import math
from pathlib import Path

from moviepy import AudioClip, ColorClip, CompositeVideoClip, TextClip
from PIL import Image, ImageDraw
import numpy as np

VIDEO_W = 1920
VIDEO_H = 1080


def tone(path: Path, sec: float, freq: float = 440.0, volume: float = 0.18):
    if path.exists():
        return

    clip = AudioClip(
        lambda t: volume * np.sin(2 * math.pi * freq * t),
        duration=sec,
        fps=44100,
    )
    clip.write_audiofile(str(path), fps=44100)


def panel(path: Path, title: str, circles):
    img = Image.new("RGB", (930, 780), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 929, 779), outline=(30, 30, 30), width=4)
    draw.text((30, 20), title, fill=(20, 20, 20))
    for x, y, color in circles:
        draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill=color)
    img.save(path)


def simple_video(path: Path, text: str, sec: float, color=(30, 30, 60)):
    if path.exists():
        return

    bg = ColorClip((VIDEO_W, VIDEO_H), color=color, duration=sec)
    txt = TextClip(text=text, font_size=88, color="white", method="caption", size=(1400, 300))
    txt = txt.with_position((260, 390)).with_duration(sec)
    CompositeVideoClip([bg, txt], size=(VIDEO_W, VIDEO_H)).write_videofile(
        str(path), fps=30, codec="libx264", audio=False
    )


def count10_video(path: Path):
    if path.exists():
        return

    bg = ColorClip((300, 220), color=(0, 0, 0), duration=10)
    txt = TextClip(text="10", font_size=120, color="red")
    txt = txt.with_duration(10).with_position((100, 40))
    CompositeVideoClip([bg, txt], size=(300, 220)).write_videofile(
        str(path), fps=30, codec="libx264", audio=False
    )


def main():
    out = Path("assets/dummy")
    out.mkdir(parents=True, exist_ok=True)

    simple_video(out / "opening.mp4", "OPENING", 3, (20, 80, 120))
    simple_video(out / "ending.mp4", "ENDING", 3, (120, 50, 20))

    for i in [1, 2, 3]:
        simple_video(out / f"question{i}.mp4", f"QUESTION {i}", 4, (30 + i * 20, 30, 60 + i * 20))

    for i in range(1, 12):
        simple_video(out / f"S{i}.mp4", f"BG S{i}", 6, (10 + i * 12, 20 + i * 7, 25 + i * 5))

    count10_video(out / "count10.mp4")
    simple_video(out / "alarm.mp4", "TIME UP", 2, (170, 20, 20))

    tone(out / "main_bgm.mp3", 400, 220, 0.06)
    tone(out / "description.mp3", 3, 520)
    tone(out / "60s.mp3", 1, 740)
    tone(out / "30s.mp3", 1, 900)
    tone(out / "answer.mp3", 2, 440)
    tone(out / "answer1.mp3", 1.5, 500)
    tone(out / "answer2.mp3", 1.5, 600)
    tone(out / "answer3.mp3", 1.5, 700)

    panel(out / "Q1_Level1_Left.png", "Q1 LEFT", [(250, 230, "red"), (400, 420, "blue"), (700, 540, "green")])
    panel(out / "Q1_Level1_Right.png", "Q1 RIGHT", [(280, 250, "red"), (420, 430, "blue"), (740, 560, "green")])

    panel(out / "Q2_Level2_Left.png", "Q2 LEFT", [(200, 210, "red"), (470, 410, "blue"), (650, 500, "green")])
    panel(out / "Q2_Level2_Right.png", "Q2 RIGHT", [(220, 220, "red"), (500, 430, "blue"), (690, 530, "green")])

    panel(out / "Q3_Level3_Left.png", "Q3 LEFT", [(210, 240, "red"), (420, 340, "blue"), (760, 550, "green")])
    panel(out / "Q3_Level3_Right.png", "Q3 RIGHT", [(240, 260, "red"), (450, 370, "blue"), (790, 570, "green")])

    print("dummy assets created at assets/dummy")


if __name__ == "__main__":
    main()
