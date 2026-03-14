#!/usr/bin/env python3
"""
漢字穴埋めクロスワード動画生成スクリプト
video_render.json を読み込み、MoviePy + PIL で動画を生成する

video_render.json フォーマット:
{
  "layout": "type1" | "type2" | "type3",   // type1/2: 斜め4隅, type3: 上下左右
  "random_seed": 42,
  "timing": {
    "countdown_seconds": 30,
    "answer_gap_after_seconds": 1.0
  },
  "questions": [
    {
      "question_no": 1,
      "top_left":     "手",   // type1/2: 左上枠, type3: 上枠
      "top_right":    "花",   // type1/2: 右上枠, type3: 左枠
      "bottom_left":  "電",   // type1/2: 左下枠, type3: 右枠
      "bottom_right": "形",   // type1/2: 右下枠, type3: 下枠
      "answer":       "気",
      "words": [
        {"word": "手気", "reading": "てき"},
        ...
      ]
    }
  ]
}
"""
import argparse
import json
import os
import random
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
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

# ── 動画制御定数（JSON非依存） ────────────────────────────────────────────
COUNTDOWN_SECONDS = 30        # 本番用。テスト時はここを10に変更
ANSWER_GAP_SECONDS = 1.0

# ── 動画基本定数 ─────────────────────────────────────────────────────────
VIDEO_W = 1920
VIDEO_H = 1080
FPS = 30

# ── type画像の実測定数 ───────────────────────────────────────────────────
# type1 (1064x1008): 斜め4隅配置、矢印が中央向き
TYPE1_SIZE = (1064, 1008)
TYPE1_Q_CENTER = (529, 498)   # ?マーク中心
TYPE1_Q_BOX = (392, 360, 667, 636)  # ?マーク赤枠 (x1,y1,x2,y2)
TYPE1_CELLS = {
    "top_left":     (38,  23,  390, 365),
    "top_right":    (668, 23,  1022, 365),
    "bottom_left":  (41,  638, 390, 976),
    "bottom_right": (676, 634, 1022, 974),
}

# type2 (1024x1024): 斜め4隅配置、矢印が外向き
TYPE2_SIZE = (1024, 1024)
TYPE2_Q_CENTER = (512, 486)
TYPE2_Q_BOX = (379, 362, 645, 611)
TYPE2_CELLS = {
    "top_left":     (48,  59,  380, 364),
    "top_right":    (644, 59,  972, 364),
    "bottom_left":  (49,  609, 379, 935),
    "bottom_right": (644, 609, 973, 935),
}

# type3 (1069x992): 上下左右の十字配置（小さい4枠）
TYPE3_SIZE = (1069, 992)
TYPE3_Q_CENTER = (532, 489)
TYPE3_Q_BOX = (394, 350, 671, 629)
TYPE3_CELLS = {
    "top":    (393,  8,   672, 286),   # 上枠
    "left":   (48,  350,  326, 629),   # 左枠
    "right":  (740, 350, 1018, 629),   # 右枠
    "bottom": (393, 694,  672, 973),   # 下枠
}

# ── レイアウト定数 ───────────────────────────────────────────────────────
# type画像を画面左寄りに配置（幅の約55%）
TYPE_IMG_TARGET_H = 960   # type画像の表示高さ
TYPE_IMG_X = 60           # type画像左端X

# 答えパネル（画面右側）
ANS_PANEL_X = 1200
ANS_PANEL_Y = 250
ANS_PANEL_W = 660
ANS_PANEL_H = 760
ANS_PANEL_RADIUS = 20

# main_question.png の配置（上部）
MQ_Y = 20
MQ_X = 0   # 左端から

# Nt.png の固定高さ（main_questionと独立）
NT_HEIGHT = 90


# 字幕（赤文字「矢印の向きにご注意ください」）
CAPTION_X = 1100
CAPTION_Y = 900

# s30タイマー（右下）
S30_X = VIDEO_W - 420
S30_Y = VIDEO_H - 280

# Noto Sans JP Bold フォントパス（GitHub Actions環境）
FONT_PATHS = [
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
    "/Library/Fonts/Arial Unicode MS.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/home/runner/work/_temp/fonts/NotoSansJP-Bold.ttf",
    "assets/fonts/NotoSansJP-Bold.ttf",
    "/tmp/NotoSansJP-Bold.ttf",
]

VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://localhost:50021")
VOICEVOX_SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "1"))


def debug_type2_cells(assets: Path):
    """type2.pngの枠座標を自動検出してprintする"""
    from PIL import Image
    import numpy as np
    
    img = Image.open(str(assets / "type2.png")).convert("RGBA")
    arr = np.array(img)
    print(f"type2.png サイズ: {img.size}")
    
    # 黒いピクセル（枠線）を検出: R<50, G<50, B<50, A>200
    black_mask = (arr[:,:,0] < 50) & (arr[:,:,1] < 50) & (arr[:,:,2] < 50) & (arr[:,:,3] > 200)
    
    # 画像を4象限に分割して各象限の黒ピクセル範囲を検出
    h, w = arr.shape[:2]
    quadrants = {
        "top_left":     (0,      0,      h//2,  w//2),
        "top_right":    (0,      w//2,   h//2,  w),
        "bottom_left":  (h//2,   0,      h,     w//2),
        "bottom_right": (h//2,   w//2,   h,     w),
    }
    
    for name, (r1, c1, r2, c2) in quadrants.items():
        region = black_mask[r1:r2, c1:c2]
        rows = np.where(region.any(axis=1))[0]
        cols = np.where(region.any(axis=0))[0]
        if len(rows) > 0 and len(cols) > 0:
            print(f"{name}: ({c1+cols.min()}, {r1+rows.min()}, {c1+cols.max()}, {r1+rows.max()})")


def resolve_layout_per_question(job: dict) -> List[str]:
    """
    各問のlayoutを返す。
    layout_mode:
      "type1_type2" : 前半(type1_questions問)=type1, 残り=type2
      "type3"       : 全問type3
      "type1"       : 全問type1  (後方互換)
      "type2"       : 全問type2  (後方互換)
    """
    mode = job.get("layout_mode", "type3")
    questions = job["questions"]
    n = len(questions)

    if mode == "type1_type2":
        split = int(job.get("type1_questions", n // 2))  # なければ半々
        return ["type1"] * split + ["type2"] * (n - split)
    elif mode == "type3":
        return ["type3"] * n
    else:
        return [mode] * n


# ── ユーティリティ ───────────────────────────────────────────────────────

def get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


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
    def make_frame(_t):
        return 0.0
    return AudioClip(make_frame, duration=duration, fps=44100)


def loop_background(bg_clip: VideoFileClip, duration: float):
    base = bg_clip.resized((VIDEO_W, VIDEO_H)).without_audio()
    if base.duration >= duration:
        return base.subclipped(0, duration)
    loops = int(duration // base.duration) + 1
    return concatenate_videoclips([base] * loops, method="compose").subclipped(0, duration)


def loop_audio(audio_clip, duration: float):
    if audio_clip.duration >= duration:
        return audio_clip.subclipped(0, duration)
    loops = int(duration // audio_clip.duration) + 1
    return concatenate_audioclips([audio_clip] * loops).subclipped(0, duration)


def apply_chroma_key(clip, key_color, threshold=90, stiffness=6):
    return clip.with_effects(
        [MaskColor(color=key_color, threshold=threshold, stiffness=stiffness)]
    )


# ── VOICEVOX 音声生成 ────────────────────────────────────────────────────

def generate_voice(text: str, output_path: Path, speaker: int = VOICEVOX_SPEAKER) -> bool:
    """VOICEVOXで音声生成。失敗時はFalseを返す。"""
    try:
        # 音声クエリ生成
        query_url = f"{VOICEVOX_URL}/audio_query?text={urllib.request.quote(text)}&speaker={speaker}"
        req = urllib.request.Request(query_url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            query_data = r.read()

        # 音声合成
        synth_url = f"{VOICEVOX_URL}/synthesis?speaker={speaker}"
        req2 = urllib.request.Request(
            synth_url,
            data=query_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            output_path.write_bytes(r.read())
        return True
    except Exception as e:
        print(f"[VOICEVOX] 失敗: {e}")
        return False


def prepare_voice_files(questions: list, assets: Path) -> Dict[int, Path]:
    """全問の音声ファイルを事前生成して返す。"""
    voice_dir = assets / "voice_cache"
    voice_dir.mkdir(exist_ok=True)
    result = {}
    for q in questions:
        n = q["question_no"]
        words = q.get("words", [])
        # 読み上げテキスト: 「正解は○○です。熟語1、熟語2、熟語3、熟語4」
        readings = "、".join(w.get("reading", w["word"]) for w in words)
        text = f"正解は{q['answer']}です。{readings}"
        out = voice_dir / f"voice_q{n}.wav"
        if not out.exists():
            ok = generate_voice(text, out)
            if not ok:
                print(f"[voice] Q{n}: VOICEVOXなし、サイレント使用")
        result[n] = out
    return result


# ── セル描画（共通ヘルパー） ──
def draw_centered(draw, cx, cy, text, font, fill):
    """
    cx, cy を中心にテキストを描画。
    一旦オフスクリーンに描いて実ピクセル範囲を計測する完全中央揃え。
    """
    # フォントサイズより少し大きいキャンバスに描画してピクセル範囲を実測
    tmp_size = font.size * 3
    tmp = Image.new("RGBA", (tmp_size, tmp_size), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    tmp_draw.text((tmp_size // 2, tmp_size // 2), text, fill=(255, 255, 255, 255), font=font)
    
    arr = np.array(tmp)
    # 実際に描画されたピクセルの範囲を検出（アルファ > 0）
    rows = np.where(arr[:, :, 3] > 0)[0]
    cols = np.where(arr[:, :, 3] > 0)[1]
    
    if len(rows) == 0 or len(cols) == 0:
        # フォールバック
        draw.text((cx, cy), text, fill=fill, font=font)
        return
    
    # 実ピクセル中心からのオフセットを計算
    pixel_cx = (cols.min() + cols.max()) / 2
    pixel_cy = (rows.min() + rows.max()) / 2
    offset_x = tmp_size // 2 - pixel_cx
    offset_y = tmp_size // 2 - pixel_cy
    
    # 視覚的補正：漢字は少し下にずれる傾向があるため微調整
    visual_adjust_y = font.size * 0.05  # フォントサイズの5%下に調整
    
    # 本描画: 実ピクセル重心が cx, cy に来るよう補正
    draw.text((cx + offset_x, cy + offset_y + visual_adjust_y), text, fill=fill, font=font)


# ── type画像への漢字描画 ──────────────────────────────────────────────────

def get_type_config(layout: str):
    if layout == "type1":
        return TYPE1_SIZE, TYPE1_Q_CENTER, TYPE1_Q_BOX, TYPE1_CELLS
    elif layout == "type2":
        return TYPE2_SIZE, TYPE2_Q_CENTER, TYPE2_Q_BOX, TYPE2_CELLS
    else:  # type3
        return TYPE3_SIZE, TYPE3_Q_CENTER, TYPE3_Q_BOX, TYPE3_CELLS


def render_type_image(
    type_img_path: Path,
    q_data: dict,
    layout: str,
    show_answer: bool,
) -> np.ndarray:
    """
    type画像に漢字を描き込んだ画像をndarrayで返す。
    show_answer=True のとき中央に答えを表示。
    """
    img = Image.open(str(type_img_path)).convert("RGBA")
    draw = ImageDraw.Draw(img)

    type_cells_data = q_data.get("type_cells", {})

    if layout == "type3":
        cells = TYPE3_CELLS
        q_center = TYPE3_Q_CENTER
        q_box = TYPE3_Q_BOX
    elif layout == "type2":
        cells = TYPE2_CELLS
        q_center = TYPE2_Q_CENTER
        q_box = TYPE2_Q_BOX
    else:  # type1
        cells = TYPE1_CELLS
        q_center = TYPE1_Q_CENTER
        q_box = TYPE1_Q_BOX

    # 各セルに漢字を描画
    qcx, qcy = q_center  # 中央?マークの中心座標

    for key, (x1, y1, x2, y2) in cells.items():
        kanji = type_cells_data.get(key, "")
        if not kanji:
            continue
        cell_w = x2 - x1
        cell_h = y2 - y1

        # フォントサイズを小さく
        font_size = int(min(cell_w, cell_h) * 0.60)  # 0.75 → 0.60
        font = get_font(font_size)

        # セル中心
        cx = x1 + cell_w // 2
        cy = y1 + cell_h // 2

        # 中央?枠から見た方向ベクトル（正規化）
        dx = cx - qcx
        dy = cy - qcy
        dist = max(abs(dx), abs(dy), 1)
        nx = dx / dist
        ny = dy / dist

        # 中央から離れる方向にオフセット（セルサイズの15%）
        offset = min(cell_w, cell_h) * 0.15
        draw_x = cx + nx * offset
        draw_y = cy + ny * offset

        # bboxオフセット補正ありで中央描画
        draw_centered(draw, draw_x, draw_y, kanji, font, fill=(0, 0, 0, 255))

    # 答え表示（白四角 + 黒字）
    if show_answer:
        qx1, qy1, qx2, qy2 = q_box
        qcx, qcy = q_center
        box_w = qx2 - qx1
        box_h = qy2 - qy1
        # 白塗り（?マークを消す）
        draw.rectangle([qx1, qy1, qx2, qy2], fill=(255, 255, 255, 255))
        # 赤枠は残す（type画像のまま）→ 再描画
        draw.rectangle([qx1, qy1, qx2, qy2], outline=(220, 30, 30, 255), width=8)
        # 答え漢字
        answer = q_data.get("answer", "")
        font_size = int(min(box_w, box_h) * 0.75)
        font = get_font(font_size)
        # bboxオフセット補正ありで中央描画
        draw_centered(draw, qcx, qcy, answer, font, fill=(220, 30, 30, 255))

    return np.array(img)


# ── 答えパネル描画 ────────────────────────────────────────────────────────

def make_answer_panel(q_data: dict, duration: float) -> VideoClip:
    """画面右側の答えパネル（正解 + 4熟語）をVideoClipで返す。"""
    panel_w = ANS_PANEL_W
    panel_h = ANS_PANEL_H

    def make_frame(_t):
        img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 赤枠パネル
        draw.rounded_rectangle(
            (0, 0, panel_w - 1, panel_h - 1),
            radius=ANS_PANEL_RADIUS,
            fill=(255, 255, 255, 230),
            outline=(220, 30, 30, 255),
            width=6,
        )
        # 「正解」ヘッダ
        header_font = get_font(52)
        header_text = "正解"
        draw_centered(draw, panel_w // 2, 46, header_text, header_font, fill=(220, 30, 30, 255))

        # 4熟語
        words = q_data.get("words", [])
        item_h = (panel_h - 100) // max(len(words), 1)
        for i, w in enumerate(words):
            word = w.get("word", "")
            reading = w.get("reading", "")
            y_base = 95 + i * item_h

            # 読みがな（小さめ）
            reading_font = get_font(28)
            draw_centered(draw, panel_w // 2, y_base + 14, reading, reading_font, fill=(80, 80, 80, 255))
            
            # 熟語（大きめ・太字）
            word_font = get_font(72)
            draw_centered(draw, panel_w // 2, y_base + 34 + 36, word, word_font, fill=(0, 0, 0, 255))

        return np.array(img)

    return (
        VideoClip(frame_function=make_frame, duration=duration)
        .with_fps(FPS)
        .with_position((ANS_PANEL_X, ANS_PANEL_Y))
    )


# ── カウントダウン字幕 ────────────────────────────────────────────────────

def make_caption_clip(text: str, duration: float, color=(220, 30, 30)) -> VideoClip:
    """赤文字字幕クリップ。"""
    font = get_font(44)
    dummy = Image.new("RGBA", (1, 1))
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0] + 20
    th = bbox[3] - bbox[1] + 12

    def make_frame(_t):
        img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((0, 0, tw-1, th-1), radius=8, fill=(255, 255, 255, 180))
        draw.text((10, 6), text, fill=(*color, 255), font=font)
        return np.array(img)

    return (
        VideoClip(frame_function=make_frame, duration=duration)
        .with_fps(FPS)
        .with_position((CAPTION_X, CAPTION_Y))
    )


# ── 1問パート構築 ─────────────────────────────────────────────────────────

def build_question_scene(
    q_data: dict,
    layout: str,
    assets: Path,
    used_backgrounds: set,
    timing: dict,
    voice_files: Dict[int, Path],
    is_first_question: bool,
) -> Tuple[VideoClip, float]:
    """
    1問分のVideoClipと所要秒数を返す。
    チャプタータイムスタンプ計算用に所要秒数も返す。
    """
    n = q_data["question_no"]
    countdown_seconds = float(timing.get("countdown_seconds", 30))
    answer_gap = float(timing.get("answer_gap_after_seconds", 1.0))

    # ── アセット読み込み ──
    qs_clip = safe_video(assets / f"q{n}s.mp4", duration=3.0)

    all_bgs = sorted(assets.glob("S*.mp4"))
    candidates = [p for p in all_bgs if p.name not in used_backgrounds] or list(all_bgs)
    bg_path = random.choice(candidates) if candidates else None
    if bg_path:
        used_backgrounds.add(bg_path.name)
        bg_base = VideoFileClip(str(bg_path))
    else:
        bg_base = ColorClip(size=(VIDEO_W, VIDEO_H), color=(40, 40, 40), duration=10.0)

    type_img_path = assets / f"{layout}.png"
    mq_img_path = assets / "main_question.png"
    nt_img_path = assets / f"{n}t.png"
    alarm_clip = safe_video(assets / "alarm.mp4", duration=2.0)
    s30_clip = safe_video(assets / "s30.mp4", duration=countdown_seconds)

    explanation1 = safe_audio(assets / "explanation1.mp3", duration=2.0)
    explanation2 = safe_audio(assets / "explanation2.mp3", duration=2.0)
    answer_sfx = safe_audio(assets / "answer.mp3", duration=1.5)
    cheer = safe_audio(assets / "cheer.mp3", duration=2.0)

    # VOICEVOX音声
    voice_path = voice_files.get(n, Path("__none__"))
    voice_audio = safe_audio(voice_path, duration=3.0)

    # ── タイミング計算 ──
    # [問題パート]
    expl1_start = 1.0   # qs_clip終了+1秒後
    expl1_end = expl1_start + explanation1.duration
    expl2_end = expl1_end + (explanation2.duration if is_first_question else 0.0)

    # s30は問題パート開始と同時（qs_clip終了後）
    s30_start = 0.0  # 問題シーン内の時刻
    s30_end = s30_start + countdown_seconds

    alarm_start = s30_end
    alarm_end = alarm_start + alarm_clip.duration

    answer_show_start = alarm_end + answer_gap
    voice_start = answer_show_start
    voice_end = voice_start + voice_audio.duration
    cheer_start = voice_end
    # 答え表示パートは「VOICEVOX長 + 1秒」を基準、cheerが長い場合は切れないよう延長
    answer_display_duration = voice_audio.duration + 1.0
    min_scene_end = cheer_start + cheer.duration
    scene_duration = max(answer_show_start + answer_display_duration, min_scene_end)

    # ── 背景ループ ──
    bg_loop = loop_background(bg_base, scene_duration)

    # ── type画像クリップ（問題時・答え時） ──
    def make_type_frame_question(_t):
        arr = render_type_image(type_img_path, q_data, layout, show_answer=False)
        return arr

    def make_type_frame_answer(_t):
        arr = render_type_image(type_img_path, q_data, layout, show_answer=True)
        return arr

    layers = []
    # 1. 白背景（最下層）
    white_bg = ColorClip(size=(VIDEO_W, VIDEO_H), color=(255, 255, 255), duration=scene_duration)
    layers.append(white_bg)
    # 2. 背景動画（白背景の上）
    layers.append(bg_loop)

    mq_h = 0
    if mq_img_path.exists():
        # main_question.png: PILで先にリサイズしてから配置（posの干渉を回避）
        mq_target_w = 1100
        mq_pil_raw = Image.open(str(mq_img_path)).convert("RGBA")
        print(f"[DEBUG] main_question.png 実サイズ: {mq_pil_raw.size}")
        arr_check = np.array(mq_pil_raw)
        non_transparent_rows = np.where(arr_check[:, :, 3] > 0)[0]
        if len(non_transparent_rows) > 0:
            print(f"[DEBUG] 最初の非透明行: y={non_transparent_rows.min()}, 最後: y={non_transparent_rows.max()}")

        # 透明余白をトリミング
        rows = np.where(arr_check[:, :, 3] > 0)[0]
        cols = np.where(arr_check[:, :, 3] > 0)[1]
        if len(rows) > 0:
            mq_pil = mq_pil_raw.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))
        else:
            mq_pil = mq_pil_raw
        orig_w, orig_h = mq_pil.size
        scale = mq_target_w / orig_w
        mq_target_h = int(orig_h * scale)
        mq_pil = mq_pil.resize((mq_target_w, mq_target_h), Image.LANCZOS)
        mq_arr = np.array(mq_pil)
        mq_h = mq_target_h

        mq_x = (VIDEO_W - mq_target_w) // 2
        mq_y = 0
        mq_resized = (
            ImageClip(mq_arr)
            .with_duration(scene_duration)
            .with_position((mq_x, mq_y))
        )
        layers.append(mq_resized)

        # Nt.png: main_questionの左に小さく配置（PILで先にリサイズ）
        if nt_img_path.exists():
            nt_pil = Image.open(str(nt_img_path)).convert("RGBA")
            nt_w_orig, nt_h_orig = nt_pil.size
            nt_scale = NT_HEIGHT / nt_h_orig
            nt_w = int(nt_w_orig * nt_scale)
            nt_pil = nt_pil.resize((nt_w, NT_HEIGHT), Image.LANCZOS)
            nt_arr = np.array(nt_pil)

            nt_x = mq_x - nt_w - 8
            nt_y = mq_y + max(0, (mq_h - NT_HEIGHT) // 2)
            nt_resized = (
                ImageClip(nt_arr)
                .with_duration(scene_duration)
                .with_position((nt_x, nt_y))
            )
            layers.append(nt_resized)

    # ── type画像（main_questionの下に配置） ──
    # type画像のリサイズ後サイズを計算
    type_size, _, _, _ = get_type_config(layout)

    type_top_y = mq_h + 5                          # 余白を10→5に
    type_avail_h = VIDEO_H - type_top_y
    type_target_h = min(TYPE_IMG_TARGET_H, type_avail_h)
    type_center_y = type_top_y                     # 上詰め（中央寄せをやめる）

    scale = type_target_h / type_size[1]
    type_display_w = int(type_size[0] * scale)

    type_q_clip = (
        VideoClip(frame_function=make_type_frame_question, duration=answer_show_start)
        .with_fps(FPS)
        .resized(height=type_target_h)
        .with_position((TYPE_IMG_X, type_center_y))
    )
    type_a_clip = (
        VideoClip(frame_function=make_type_frame_answer, duration=scene_duration - answer_show_start)
        .with_fps(FPS)
        .resized(height=type_target_h)
        .with_position((TYPE_IMG_X, type_center_y))
        .with_start(answer_show_start)
    )

    layers.append(type_q_clip)
    layers.append(type_a_clip)

    # ── s30タイマー（クロマキー・問題時のみ） ──
    s30_video = s30_clip.resized(height=240)
    s30_chroma = apply_chroma_key(s30_video, key_color=(0, 0, 255), threshold=150, stiffness=4)
    s30_placed = (
        s30_chroma
        .with_start(s30_start)
        .with_end(s30_end)
        .with_position((S30_X, S30_Y))
    )
    layers.append(s30_placed)

    # ── alarm（クロマキー） ──
    alarm_resized = alarm_clip.resized((VIDEO_W, VIDEO_H))
    alarm_chroma = apply_chroma_key(alarm_resized, key_color=(0, 255, 0), threshold=150, stiffness=4)
    alarm_placed = alarm_chroma.with_start(alarm_start)
    layers.append(alarm_placed)

    # ── 字幕（答え表示で消える） ──
    caption_x = ANS_PANEL_X
    caption_y = ANS_PANEL_Y - 60
    caption = make_caption_clip("矢印の向きにご注意ください", duration=answer_show_start)
    caption = caption.with_position((caption_x, caption_y))
    layers.append(caption)

    # ── 答えパネル（answer_show_start以降） ──
    ans_panel = make_answer_panel(q_data, duration=scene_duration - answer_show_start)
    ans_panel = ans_panel.with_start(answer_show_start)
    layers.append(ans_panel)

    # ── 合成 ──
    scene_video = CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H)).with_duration(scene_duration)

    # ── 音声 ──
    audio_layers = [
        explanation1.with_start(expl1_start),
        answer_sfx.with_start(answer_show_start),
        voice_audio.with_start(voice_start),
        cheer.with_start(cheer_start),
    ]
    if is_first_question:
        audio_layers.append(explanation2.with_start(expl1_end))
    if alarm_clip.audio is not None:
        audio_layers.append(alarm_clip.audio.with_start(alarm_start))

    scene_audio = CompositeAudioClip(audio_layers)
    scene_video = scene_video.with_audio(scene_audio)

    # qs_clipと問題シーンを結合
    full_scene = concatenate_videoclips([qs_clip, scene_video], method="compose")
    total_duration = qs_clip.duration + scene_duration

    return full_scene, total_duration


# ── メイン動画構築 ────────────────────────────────────────────────────────

def build_video(job: dict, assets: Path, output_path: Path, test_mode: bool = False):
    random.seed()              # ← シード指定なし→完全ランダム
    questions = job["questions"]

    # テストモードは1問のみ
    if test_mode:
        questions = questions[:1]

    layouts = resolve_layout_per_question(job)

    timing = {
        "countdown_seconds": 10 if test_mode else COUNTDOWN_SECONDS,
        "answer_gap_after_seconds": ANSWER_GAP_SECONDS,
    }

    # VOICEVOX音声を事前生成
    print("[build_video] VOICEVOX音声生成中...")
    voice_files = prepare_voice_files(questions, assets)

    # チャプタータイムスタンプ計算用
    chapters = []
    opening = safe_video(assets / "opening.mp4", duration=3.0)
    ending = safe_video(assets / "ending.mp4", duration=3.0)
    main_bgm = safe_audio(assets / "main_bgm.mp3", duration=600.0, volume=0.3)

    current_time = opening.duration
    used_backgrounds = set()
    question_clips = []

    for i, q in enumerate(questions):
        n = q["question_no"]
        layout = layouts[i]   # ← 問ごとに切り替え
        chapters.append({"no": n, "start": current_time, "label": f"第{n}問"})
        print(f"[build_video] 第{n}問シーン構築中... (layout={layout})")

        clip, duration = build_question_scene(
            q_data=q,
            layout=layout,      # ← 動的に渡す
            assets=assets,
            used_backgrounds=used_backgrounds,
            timing=timing,
            voice_files=voice_files,
            is_first_question=(i == 0),
        )
        question_clips.append(clip)
        current_time += duration

    # チャプターリスト出力
    chapters_text = "\n=== YouTubeチャプター ===\n"
    chapters_text += "0:00 オープニング\n"
    for c in chapters:
        m, s = divmod(int(c["start"]), 60)
        chapters_text += f"{m}:{s:02d} {c['label']}\n"
    m, s = divmod(int(current_time), 60)
    chapters_text += f"{m}:{s:02d} エンディング\n"
    chapters_text += "========================\n"
    print(chapters_text)
    
    # チャプター情報をログファイルに保存
    try:
        log_file = output_path.with_suffix('.log')
        with log_file.open('w', encoding='utf-8') as f:
            f.write(chapters_text)
        print(f"チャプター情報を保存: {log_file}")
    except Exception as e:
        print(f"チャプターログ保存失敗: {e}")

    # 動画結合
    main_part = concatenate_videoclips(question_clips, method="compose")
    bgm_loop = loop_audio(main_bgm, main_part.duration)

    if main_part.audio is not None:
        main_audio = CompositeAudioClip([main_part.audio, bgm_loop])
    else:
        main_audio = bgm_loop
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
    print(f"[完了] {output_path}")


# ── エントリーポイント ────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="漢字クロスワード動画生成")
    p.add_argument("--job",    type=Path, required=True, help="video_render.json のパス")
    p.add_argument("--assets", type=Path, required=True, help="アセットディレクトリ")
    p.add_argument("--output", type=Path, default=Path("out/kanji_quiz.mp4"))
    p.add_argument("--test",   action="store_true", help="テストモード: 1問のみ・10秒カウントダウン")
    return p.parse_args()


def main():
    args = parse_args()
    job = load_json(args.job)
    build_video(job, args.assets, args.output, test_mode=args.test)


if __name__ == "__main__":
    main()
