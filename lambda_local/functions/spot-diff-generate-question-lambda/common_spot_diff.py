from __future__ import annotations

import base64
import datetime
import io
import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple
import requests as _requests
from typing import Optional

LOGGER = logging.getLogger(__name__)

GRID_COLS = 4
GRID_ROWS = 3
DIFF_COUNT = 3
QUESTION_COUNT = 3

VIDEO_LEFT_X = 20
VIDEO_RIGHT_X = 970
VIDEO_IMAGE_Y = 150
VIDEO_IMAGE_W = 930
VIDEO_IMAGE_H = 780

DEFAULT_BASE_MIN_WIDTH = 768
DEFAULT_BASE_MIN_HEIGHT = 1024
REPLICATE_PORTRAIT_WIDTH = 768
REPLICATE_PORTRAIT_HEIGHT = 1024

@dataclass
class VisionDiffTarget:
    diff_id: int
    diff_type: str
    object_name: str
    description: str
    cx: int
    cy: int
    radius: int
    x1: Optional[int] = None
    y1: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None

DIFFICULTY_ALIASES = {
    "easy": "easy",
    "beginner": "easy",
    "initial": "easy",
    "shokyu": "easy",
    "初級": "easy",
    "medium": "medium",
    "intermediate": "medium",
    "chukyu": "medium",
    "中級": "medium",
    "hard": "hard",
    "advanced": "hard",
    "jokyu": "hard",
    "上級": "hard",
}

DIFF_TYPES_BY_DIFFICULTY = {
    "easy": ["色変更", "数量変更", "欠損"],
    "medium": ["色変更", "数量変更", "向き変更", "欠損"],
    "hard": ["位置変更", "サイズ変更", "欠損"],
}

QUESTION_CATEGORY_RULES = {
    1: {"difficulty": "easy", "category": "food-centered scene"},
    2: {"difficulty": "medium", "category": "daily life or social scene"},
    3: {"difficulty": "hard", "category": "outdoor or seasonal scene"},
}

_FOOD_KEYWORDS = (
    "food", "meal", "dish", "fruit", "vegetable", "dessert", "sweets", "snack",
    "breakfast", "lunch", "dinner", "kitchen", "cafe", "bakery", "market",
    "料理", "食事", "果物", "野菜", "スイーツ", "お菓子", "朝食", "昼食", "夕食", "市場",
)

_Q1_MAIN_MENUS_BASE: List[str] = [
    "a Japanese home breakfast with grilled fish",
    "a brunch table with pancakes",
    "an Italian pasta lunch plate",
    "a ramen and dumpling set",
    "a colorful bento arrangement",
    "a sushi and side-dish set",
    "a curry rice dinner plate",
    "a bakery-style bread and pastry spread",
    "a soba and tempura set meal",
    "an udon bowl with simple toppings",
    "an onigiri assortment with side dishes",
    "a rice porridge breakfast tray",
    "a hamburger steak plate with rice",
    "an omurice lunch plate",
    "a yakisoba and side salad set",
    "a sandwich and soup cafe plate",
    "a croissant and quiche brunch plate",
    "a gratin and bread comfort meal",
    "a pizza slice platter with sides",
    "a taco plate with fresh salsa",
    "a burrito bowl with vegetables",
    "a stir-fried noodles and soup combo",
    "a seafood rice bowl set",
    "a chicken and vegetable stew plate",
    "a tofu and seasonal vegetable set meal",
    "a hotpot ingredients table setup",
    "a grilled meat and vegetable platter",
    "a fish and chips style plate",
    "a waffle and fruit brunch plate",
    "a crepe and dessert-style lunch plate",
]

_Q1_SIDE_COMBINATIONS_BASE: List[str] = [
    "a miso soup bowl and pickles",
    "a fresh green salad and fruit slices",
    "a warm soup cup and toasted bread",
    "a yogurt cup with berries and nuts",
    "a tea pot with small sweets",
    "a juice set with seasonal fruits",
    "a small bowl of simmered vegetables and tofu",
    "a corn soup cup and mini bread roll",
    "a clear soup and steamed vegetables",
    "a side of roasted potatoes and carrots",
    "a bean salad and herb tea",
    "a mini dessert plate and coffee cup",
    "a fruit yogurt parfait and iced tea",
    "a kimchi side plate and warm tea",
    "a boiled egg and avocado slices",
    "a cheese board and grape cup",
    "a pumpkin soup and cracker set",
    "a seasonal fruit bowl and milk tea",
    "a coleslaw cup and lemonade glass",
    "a mushroom soup and toasted garlic bread",
]

_Q1_TABLE_CONTEXTS_BASE: List[str] = [
    "a cozy home dining table",
    "a bright kitchen counter",
    "a compact cafe table by the window",
    "a weekend picnic-style setup",
    "a small neighborhood market tasting corner",
    "a family breakfast table with soft morning light",
    "a lunch setup on a wooden terrace",
    "a calm indoor table near houseplants",
    "a simple outdoor garden table",
    "a food court table with trays neatly arranged",
    "a bakery counter seat facing display shelves",
    "a riverside picnic blanket setup",
    "a community event food table",
    "a small diner table with condiments arranged",
    "a clean studio-kitchen table layout",
]


def _expand_with_modifiers(
    base_items: List[str],
    modifiers: List[str],
    fmt: str,
    min_count: int,
) -> List[str]:
    expanded: List[str] = []
    for item in base_items:
        expanded.append(item)
    for mod in modifiers:
        for item in base_items:
            expanded.append(fmt.format(mod=mod, item=item))

    deduped: List[str] = []
    seen: set[str] = set()
    for text in expanded:
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)

    if len(deduped) < min_count:
        raise RuntimeError(f"expanded list must have >= {min_count} entries, got {len(deduped)}")
    return deduped


_Q1_MAIN_MODIFIERS: List[str] = [
    "seasonal",
    "homestyle",
    "colorful",
    "balanced",
    "weekend",
    "comfort",
    "fresh",
    "light",
    "hearty",
    "modern",
]

_Q1_SIDE_MODIFIERS: List[str] = [
    "light",
    "fresh",
    "colorful",
    "protein-rich",
    "fiber-rich",
    "homestyle",
    "seasonal",
    "simple",
    "cafeteria-style",
    "balanced",
]

_Q1_CONTEXT_MODIFIERS: List[str] = [
    "sunny",
    "cozy",
    "minimal",
    "family-friendly",
    "modern",
    "vintage",
    "calm",
    "bright",
    "weekend",
    "neighborhood",
]

_Q1_MAIN_MENUS: List[str] = _expand_with_modifiers(
    _Q1_MAIN_MENUS_BASE,
    _Q1_MAIN_MODIFIERS,
    "{mod} variation of {item}",
    100,
)

_Q1_SIDE_COMBINATIONS: List[str] = _expand_with_modifiers(
    _Q1_SIDE_COMBINATIONS_BASE,
    _Q1_SIDE_MODIFIERS,
    "{mod} variation of {item}",
    100,
)

_Q1_TABLE_CONTEXTS: List[str] = _expand_with_modifiers(
    _Q1_TABLE_CONTEXTS_BASE,
    _Q1_CONTEXT_MODIFIERS,
    "{mod} setting of {item}",
    100,
)


def _build_q1_food_variants(max_variants: int = 6000) -> List[str]:
    rng = random.Random(20260303)
    results: List[str] = []
    seen: set[str] = set()

    # Ensure base coverage first.
    for i, main in enumerate(_Q1_MAIN_MENUS[: min(len(_Q1_MAIN_MENUS), 300)]):
        side = _Q1_SIDE_COMBINATIONS[i % len(_Q1_SIDE_COMBINATIONS)]
        context = _Q1_TABLE_CONTEXTS[i % len(_Q1_TABLE_CONTEXTS)]
        phrase = f"featuring {main}, {side}, on {context}"
        if phrase not in seen:
            seen.add(phrase)
            results.append(phrase)
        if len(results) >= max_variants:
            return results

    attempts = 0
    max_attempts = max_variants * 50
    while len(results) < max_variants and attempts < max_attempts:
        attempts += 1
        main = _Q1_MAIN_MENUS[rng.randrange(len(_Q1_MAIN_MENUS))]
        side = _Q1_SIDE_COMBINATIONS[rng.randrange(len(_Q1_SIDE_COMBINATIONS))]
        context = _Q1_TABLE_CONTEXTS[rng.randrange(len(_Q1_TABLE_CONTEXTS))]
        phrase = f"featuring {main}, {side}, on {context}"
        if phrase in seen:
            continue
        seen.add(phrase)
        results.append(phrase)
    return results


_Q1_FOOD_VARIANTS: List[str] = _build_q1_food_variants()

if len(_Q1_FOOD_VARIANTS) < 200:
    raise RuntimeError(f"_Q1_FOOD_VARIANTS must have >= 200 entries, got {len(_Q1_FOOD_VARIANTS)}")

_SEASON_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "spring": ("spring", "hanami", "sakura", "cherry blossom", "桜", "春"),
    "summer": ("summer", "matsuri", "fireworks", "tanabata", "夏", "夏祭り", "花火"),
    "autumn": ("autumn", "fall", "momiji", "harvest", "紅葉", "秋"),
    "winter": ("winter", "snow", "illumination", "new year", "冬", "正月", "雪"),
}


@dataclass
class GridCell:
    col: int
    row: int


def normalize_difficulty(raw: str) -> str:
    key = (raw or "").strip().lower()
    return DIFFICULTY_ALIASES.get(key, "medium")


def http_post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int = 120) -> Dict[str, Any]:
    LOGGER.info("http_post_json called: url=%s", url[:100])
    resp = _requests.post(
        url,
        json=payload,
        headers={**headers, "Content-Type": "application/json"},
        timeout=(10, timeout),
    )
    resp.raise_for_status()
    return resp.json()


def extract_json_block(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Gemini returned empty text")
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        return json.loads(stripped[first : last + 1])
    raise ValueError("Could not parse JSON from Gemini text response")


def extract_text_from_gemini(resp: Dict[str, Any]) -> str:
    texts: List[str] = []
    for candidate in resp.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if "text" in part:
                texts.append(part["text"])
    return "\n".join(t for t in texts if t).strip()


def extract_image_b64_from_gemini(resp: Dict[str, Any]) -> str:
    for candidate in resp.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                return inline_data["data"]
    raise ValueError("Gemini response does not include inline image data")


def call_gemini_text(api_key: str, model: str, prompt: str, temperature: float = 0.4) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = http_post_json(url, payload, headers={})
    text = extract_text_from_gemini(resp)
    if not text:
        raise RuntimeError("Gemini text response was empty")
    return text


def call_gemini_image(api_key: str, model: str, prompt: str) -> bytes:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "responseModalities": ["TEXT", "IMAGE"]},
    }
    resp = http_post_json(url, payload, headers={})
    image_b64 = extract_image_b64_from_gemini(resp)
    return base64.b64decode(image_b64)


def pick_non_adjacent_cells(rng: random.Random, count: int) -> List[GridCell]:
    all_cells = [GridCell(col=c, row=r) for r in range(1, GRID_ROWS + 1) for c in range(1, GRID_COLS + 1)]
    rng.shuffle(all_cells)
    picked: List[GridCell] = []
    for cell in all_cells:
        if len(picked) == count:
            break
        if all(abs(cell.col - p.col) > 1 or abs(cell.row - p.row) > 1 for p in picked):
            picked.append(cell)
    if len(picked) < count:
        for cell in all_cells:
            if len(picked) == count:
                break
            if all(cell.col != p.col or cell.row != p.row for p in picked):
                picked.append(cell)
    if len(picked) != count:
        raise RuntimeError("Failed to pick required number of diff cells")
    return picked


def _choice_by_seed(options: List[str], seed_value: int) -> str:
    if not options:
        return ""
    rng = random.Random(seed_value)
    return rng.choice(options)


def _maybe_by_seed(seed_value: int, probability: float) -> bool:
    rng = random.Random(seed_value)
    return rng.random() < probability


def _month_to_season(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _contains_season_keyword(text: str, season: str) -> bool:
    return any(k in text for k in _SEASON_KEYWORDS.get(season, ()))


def _current_month_jst() -> int:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_jst = now_utc + datetime.timedelta(hours=9)
    return now_jst.month


def generate_control_json(seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    questions = []
    for q_no in range(1, QUESTION_COUNT + 1):
        q_rule = QUESTION_CATEGORY_RULES[q_no]
        q_difficulty = q_rule["difficulty"]
        allowed_types = DIFF_TYPES_BY_DIFFICULTY[q_difficulty]

        cells = pick_non_adjacent_cells(rng, DIFF_COUNT)
        diff_types = rng.sample(allowed_types, k=min(DIFF_COUNT, len(allowed_types)))
        while len(diff_types) < DIFF_COUNT:
            diff_types.append(rng.choice(allowed_types))
        controls = []
        for i in range(DIFF_COUNT):
            controls.append(
                {
                    "diff_id": i + 1,
                    "grid_cell": asdict(cells[i]),
                    "diff_type": diff_types[i],
                }
            )
        questions.append(
            {
                "question_no": q_no,
                "difficulty": q_difficulty,
                "category_rule": q_rule["category"],
                "theme_seed": rng.randint(0, 10**9 - 1),
                "diffs": controls,
            }
        )
    return {
        "grid": {"cols": GRID_COLS, "rows": GRID_ROWS},
        "diff_count": DIFF_COUNT,
        "questions": questions,
    }


def build_theme_generation_prompt(control: Dict[str, Any]) -> str:
    current_month = _current_month_jst()
    current_season = _month_to_season(current_month)
    
    # プロンプトの各部分を分割して構築
    prompt_parts = [
        """You are a theme planner and visual director for a senior-friendly spot-the-difference video.
Return exactly one JSON object. Do not use markdown.

Field definitions for diff_plan:
- target_object: the specific object to find and edit (English noun phrase, e.g. "the red apple on the table")
- edit_instruction: precise instruction for inpainting (English imperative, e.g. "change the red apple to a blue apple")
- description: human-readable description of the change (English sentence)

Visual Style Guidelines (crucial):
- Art style: warm, hand-drawn 2D illustration with a clear water-based marker look.
- Lines: clear, slightly thick brown/charcoal-like outlines (avoid harsh pure-black lines or no-line style).
- Coloring: soft pastel tones with clear, solid fills.
- Shading/texture: no heavy 3D shading, no hyper-realistic textures.
- Character design: friendly rounded proportions, simple features, gentle smiles, childlike clarity.
- Fill accuracy: keep color neatly inside outlines; no color bleeding across lines.
- Composition: clear foreground/background separation, easy object recognition, avoid visual clutter.

Global rules:
- Fixed 4x3 grid
- Exactly 3 differences per question
- Natural or pastel visual tone
- Realistic, everyday themes only (no fantasy/sci-fi)
- Senior-friendly readability

Question composition rules:
- No fixed question types - allow full diversity across all questions
- Each question should explore different themes: food, daily life, outdoor activities, hobbies, work, education, entertainment, transportation, nature, etc.
- Vary settings: indoor, outdoor, urban, rural, commercial, residential, natural environments
- Mix of human-centered and object-centric scenes
- Seasonal events are encouraged but not required for any specific question

Character and event preference rules:
- Can occasionally feature a grandmother and a cat, but should mostly use varied themes.
- Encourage featuring children in everyday settings such as crafts, cooking, or playing.
- Can occasionally feature grandparents, but should avoid overusing them.
- Encourage featuring children playing outdoors, at festivals, or enjoying seasonal activities.
- Should often use current-season events or familiar annual events (e.g., hanami, matsuri, autumn leaves, winter illumination, New Year).
- Prioritize events appropriate for current month""",
        str(current_month),
        f"({current_season}).",
        """- Balance character variety across runs (children, family members, friends, couples, solo scenes, with/without pets).
- Object-centric themes are strongly allowed: food, fruits, cars, trains, bicycles, flowers, kitchen tools, market items, and daily objects.
- The main subject does not need to be a person; people can be absent.

Diversity rules (important):
- Make each question clearly different in location, time-of-day, props, and atmosphere.
- Avoid repeating near-identical compositions between runs.
- Use the provided theme_seed per question to vary scene motifs, events, and sub-themes.
- Even when characters are similar, vary activities and setting details.

You must follow this control data exactly:""",
        json.dumps(control, ensure_ascii=False),
        """Required output schema:
{
  "questions": [
    {
      "question_no": 1,
      "theme": "...",
      "space": "...",
      "has_people": true,
      "diff_plan": [
        {
          "diff_id": 1,
          "diff_type": "色変更",
          "target_object": "the red apple on the wooden table",
          "edit_instruction": "change the red apple to a blue apple",
          "description": "specific local edit description"
        }
      ]
    }
  ]
}

Constraints for each diff_plan:
- Keep diff_id and diff_type aligned to control data.
- target_object must be a specific, identifiable object in the scene.
- edit_instruction must be precise and actionable for inpainting.
- description must be localized and concrete.
- Each description must be editable in a small local masked area."""
    ]
    
    return "\n".join(prompt_parts)


# ---------------------------------------------------------------------------
# 月別・重み付き季節イベントカレンダー
# 各エントリ: (weight, q2_indoor_phrase, q3_outdoor_phrase)
#   weight        : 同月内での相対重み
#   q2_indoor     : Q2用「室内・日常」フレーズ（theme末尾に付加）
#   q3_outdoor    : Q3用「屋外・季節」フレーズ（theme末尾に付加）
# ---------------------------------------------------------------------------
# fmt: off
_MONTHLY_EVENTS: Dict[int, List[Tuple[int, str, str]]] = {
    1: [  # 1月 — お正月・冬
        (30, "with a family gathered for New Year's osechi meal at home",
             "at a New Year shrine visit with people in kimono"),
        (25, "with children playing karuta or hanetsuki indoors",
             "with children flying kites or spinning tops on a wintry open field"),
        (20, "with a mochi-pounding (mochitsuki) event inside a community hall",
             "at an outdoor mochitsuki festival with steam rising"),
        (15, "with a family watching the first sunrise (hatsuhinode) on TV",
             "on a hilltop watching the first sunrise of the year"),
        (10, "with adults writing New Year's wishes at a calligraphy (kakizome) table",
             "at a winter illumination walk in a park"),
    ],
    2: [  # 2月 — 節分・バレンタイン・雪
        (30, "with children throwing beans at home for Setsubun",
             "at an outdoor Setsubun bean-throwing ceremony at a shrine"),
        (25, "with someone making Valentine's Day chocolates in the kitchen",
             "at a snow festival with large snow sculptures"),
        (20, "with a family making ehomaki rolls for Setsubun at home",
             "with children building a snowman in a snowy garden"),
        (15, "with two people exchanging handmade sweets on Valentine's Day",
             "at a winter ski slope with colorful ski gear"),
        (10, "with a cozy kotatsu scene with hot drinks on a cold evening",
             "at an outdoor winter market with warm food stalls"),
    ],
    3: [  # 3月 — ひな祭り・卒業・お花見準備
        (30, "with a family displaying hina dolls for Girls' Day (Hinamatsuri)",
             "at an early cherry blossom viewing along a river path"),
        (25, "with a graduation celebration meal at a family dining table",
             "at a graduation ceremony held in a school courtyard"),
        (20, "with children enjoying chirashizushi for Hinamatsuri",
             "with children picking wildflowers in a spring meadow"),
        (15, "with a farewell party scene with balloons and cake indoors",
             "at a spring kite-flying event in a park"),
        (10, "with someone arranging spring flowers in a vase at home",
             "at an outdoor tulip garden in full bloom"),
    ],
    4: [  # 4月 — お花見・入学
        (35, "with a family preparing hanami bento at home",
             "at a cherry blossom picnic under full-bloom sakura trees"),
        (25, "with a school entrance ceremony celebration at home",
             "at a school entrance ceremony outdoors with blooming cherry trees"),
        (20, "with children playing in a park surrounded by spring flowers",
             "with families flying carp streamers (koinobori) early in a garden"),
        (10, "with a spring lunch scene with seasonal vegetables",
             "at a riverside hanami party with lanterns at dusk"),
        (10, "with a spring flower arrangement class indoors",
             "at an outdoor flower market with colorful spring blooms"),
    ],
    5: [  # 5月 — こどもの日・ゴールデンウィーク
        (30, "with a family celebrating Children's Day with kashiwa-mochi",
             "with koinobori carp streamers flying in a blue sky over a house"),
        (25, "with a Golden Week family outing picnic lunch at home",
             "at a Golden Week outdoor festival with food stalls"),
        (20, "with children making kabuto helmets from newspaper indoors",
             "with children enjoying a field day race on a sunny school ground"),
        (15, "with a family BBQ scene in a backyard or balcony",
             "at an outdoor rose garden festival in May"),
        (10, "with a cozy tea ceremony scene using fresh green tea",
             "at a seaside park with families flying colorful kites"),
    ],
    6: [  # 6月 — 梅雨・紫陽花
        (35, "with someone making tsuyu (rainy season) themed sweets indoors",
             "at a hydrangea (ajisai) garden path on a misty day"),
        (25, "with a family making umeshu plum wine in the kitchen",
             "at an outdoor ajisai festival with umbrella-carrying visitors"),
        (20, "with children making paper frogs or snails for a rainy day craft",
             "with children splashing in puddles under colorful umbrellas"),
        (10, "with a cozy reading scene by a window with rain outside",
             "at an outdoor firefly (hotaru) viewing spot at twilight"),
        (10, "with a homemade kakigori shaved ice preparation scene",
             "at a seaside promenade with early summer ocean scenery"),
    ],
    7: [  # 7月 — 夏祭り・七夕・花火
        (30, "with a family decorating a Tanabata bamboo wish tree indoors",
             "at a Tanabata festival street with colorful paper streamers"),
        (30, "with children in yukata eating kakigori at a summer festival table",
             "at a summer fireworks festival with yukatas and food stalls"),
        (20, "with someone making cold somen noodles in the kitchen",
             "at a beach scene with sunshades and watermelon"),
        (10, "with a family watching fireworks from a balcony",
             "at an outdoor bon-odori dance circle at dusk"),
        (10, "with a goldfish scooping (kingyo-sukui) scene at home in a bowl",
             "at a riverside fireworks launch with spectators on blankets"),
    ],
    8: [  # 8月 — お盆・海水浴・スイカ割り
        (30, "with a family gathering for Obon holiday meal at home",
             "at a beach with children playing in the waves and building sandcastles"),
        (25, "with children playing watermelon splitting (suikawari) in a garden",
             "at an outdoor bon-odori festival with paper lanterns at night"),
        (20, "with a family making kakigori shaved ice on a hot afternoon",
             "at a summer camp with children by a mountain river"),
        (15, "with children catching insects with nets in a summer evening scene",
             "at an outdoor cinema event on a grassy field at night"),
        (10, "with someone writing in a summer diary or postcards indoors",
             "at a sunflower field in full midsummer bloom"),
    ],
    9: [  # 9月 — 敬老の日・お月見・秋の始まり
        (30, "with a family setting up a tsukimi moon-viewing tray with dango",
             "at an outdoor tsukimi event with pampas grass and full moon"),
        (25, "with grandparents and grandchildren having a Respect for the Aged Day meal",
             "at an autumn harvest festival in the countryside"),
        (20, "with someone arranging autumn flowers and pampas grass in a vase",
             "with children catching dragonflies in a rice field at golden hour"),
        (15, "with a family making seasonal sweet potatoes or chestnut dishes",
             "at an outdoor autumn sports day (undoukai) on a school field"),
        (10, "with a cozy scene of reading books with autumn colors outside",
             "at a grape or pear picking orchard in early autumn"),
    ],
    10: [  # 10月 — ハロウィン・紅葉
        (35, "with children in Halloween costumes carving pumpkins indoors",
             "at a Halloween street parade with costumes and decorations"),
        (30, "with a family enjoying autumn leaf viewing with bento boxes",
             "at a mountain trail with brilliant red and yellow autumn foliage"),
        (15, "with someone making Halloween-themed sweets in the kitchen",
             "at an outdoor autumn harvest market with apple and chestnut stalls"),
        (10, "with children doing a Halloween trick-or-treat around a neighborhood",
             "at a pumpkin patch farm with families and colorful gourds"),
        (10, "with a cozy autumn evening reading by a lamp with falling leaves outside",
             "at a riverside park with golden ginkgo tree avenue"),
    ],
    11: [  # 11月 — 七五三・紅葉・収穫
        (30, "with a family celebrating Shichi-Go-San with chitose-ame candy bags",
             "at a shrine with children dressed in traditional kimono for Shichi-Go-San"),
        (25, "with a family enjoying a kotatsu with autumn harvest foods",
             "at an autumn foliage park with a family walking on leaf-covered paths"),
        (20, "with someone making apple or chestnut pie in a cozy kitchen",
             "at an outdoor chrysanthemum (kiku) flower festival"),
        (15, "with a cultural festival (bunkasai) display or performance indoors",
             "at a school cultural festival with outdoor food and game booths"),
        (10, "with a family preparing for the year-end with cleaning supplies around",
             "at a winter illumination park that just started lighting up"),
    ],
    12: [  # 12月 — クリスマス・大晦日・冬至
        (35, "with a family decorating a Christmas tree and wrapping gifts indoors",
             "at a Christmas illumination street with couples and families"),
        (25, "with children making Christmas cookies or cake in the kitchen",
             "at an outdoor Christmas market with ornament and food stalls"),
        (20, "with a family preparing toshikoshi soba noodles on New Year's Eve",
             "at a winter illumination park with colorful light tunnels"),
        (10, "with a family gathering for a Christmas party meal at a table",
             "at a countdown event in a town square on New Year's Eve"),
        (10, "with someone making yuzu bath (toji) preparations in winter",
             "at a shrine preparing for New Year hatsumode visits"),
    ],
}
# fmt: on

# 汎用フォールバック（季節イベントに依存しない普遍的シーン）
_Q2_FALLBACK: List[str] = [
    "with a fruit stand display and colorful baskets",
    "with a cozy tea table and assorted pastries",
    "with a compact car parked beside a small neighborhood shop",
    "with kitchen tools and fresh ingredients on a counter",
    "with a bicycle and potted flowers near a sunny window",
    "with a market shelf full of boxed snacks and jars",
    "with a grandmother and her cat having tea time",
]

_Q3_FALLBACK: List[str] = [
    "at a local community weekend market",
    "at an outdoor family activity event in a town square",
    "at a park event with food booths and games",
    "at a neighborhood fair with simple decorations",
    "at an outdoor craft and food pop-up event",
    "at a city promenade event with stalls and visitors",
]

# Q3キャラクターバリアント（屋外・季節問わず使える人物描写）
_Q3_CHARACTER_VARIANTS: List[str] = [
    "with children running and playing in the park",
    "with a child and a parent flying a kite",
    "with kids enjoying a picnic on the grass",
    "with children catching insects near a flower bed",
    "with children watching fireworks at a summer festival",
    "with two adults enjoying a seasonal outing",
    "with a grandfather and a grandmother enjoying a walk",
]

# キーワード検出用
_CHILD_KEYWORDS = ("child", "children", "kid", "boy", "girl", "子供", "男の子", "女の子")
_GRANDPARENT_KEYWORDS = ("grandfather", "grandpa", "おじい", "grandmother", "grandma", "おばあ")


def _get_seasonal_variants(
    month: int,
    rng_seed: int | None = None,
    blend_adjacent: bool = True,
) -> Tuple[List[str], List[str]]:
    """
    指定した月に対応する Q2用・Q3用テーマフレーズリストを返す。

    Parameters
    ----------
    month : int
        1〜12の月番号
    rng_seed : int | None
        再現性が必要な場合にシードを指定。None の場合はランダム。
    blend_adjacent : bool
        True の場合、前後月のイベントも低確率で混入させる。

    Returns
    -------
    (q2_variants, q3_variants) : Tuple[List[str], List[str]]
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1–12, got {month}")

    rng = random.Random(rng_seed)

    current = list(_MONTHLY_EVENTS[month])
    blended: List[Tuple[int, str, str]] = list(current)

    if blend_adjacent:
        prev_month = 12 if month == 1 else month - 1
        next_month = 1 if month == 12 else month + 1
        for w, q2, q3 in _MONTHLY_EVENTS[prev_month]:
            blended.append((max(1, w // 4), q2, q3))
        for w, q2, q3 in _MONTHLY_EVENTS[next_month]:
            blended.append((max(1, w // 4), q2, q3))

    def weighted_unique(pool: List[Tuple[int, str]], count: int) -> List[str]:
        population = [phrase for w, phrase in pool for _ in range(w)]
        result: List[str] = []
        seen: set = set()
        attempts = 0
        while len(result) < count and attempts < 50000:
            attempts += 1
            phrase = rng.choice(population)
            if phrase not in seen:
                seen.add(phrase)
                result.append(phrase)
        return result

    pool_q2 = [(w, q2) for w, q2, _ in blended]
    pool_q3 = [(w, q3) for w, _, q3 in blended]

    q2_seasonal = weighted_unique(pool_q2, 6)
    q3_seasonal = weighted_unique(pool_q3, 8)

    return q2_seasonal + _Q2_FALLBACK, q3_seasonal + _Q3_FALLBACK


# ---------------------------------------------------------------------------
# 実行時に今日の月（JST）でバリアントを初期化
# ---------------------------------------------------------------------------
_today_month = _current_month_jst()
_Q2_VARIANTS, _Q3_EVENT_VARIANTS = _get_seasonal_variants(_today_month)


def parse_theme_output(raw_text: str, control: Dict[str, Any]) -> List[Dict[str, Any]]:
    parsed = extract_json_block(raw_text)
    by_q = {q.get("question_no"): q for q in parsed.get("questions", []) if isinstance(q, dict)}
    final_questions: List[Dict[str, Any]] = []
    for q_control in control["questions"]:
        q_no = q_control["question_no"]
        src = by_q.get(q_no, {})
        diff_desc_by_id = {
            d.get("diff_id"): d.get("description", "")
            for d in src.get("diff_plan", [])
            if isinstance(d, dict)
        }
        final_diffs = []
        for d in q_control["diffs"]:
            desc = diff_desc_by_id.get(d["diff_id"]) or f"{d['diff_type']} variation in the selected object"
            
            # diff_idでマッチするdiff_planを探す
            matching_diff = None
            for diff_plan_item in src.get("diff_plan", []):
                if diff_plan_item.get("diff_id") == d["diff_id"]:
                    matching_diff = diff_plan_item
                    break
            
            # Geminiから直接取得
            target_object = matching_diff.get("target_object", "") if matching_diff else ""
            edit_instruction = matching_diff.get("edit_instruction", "") if matching_diff else ""
            
            # target_objectが空の場合のフォールバック
            if not target_object:
                LOGGER.warning("target_object missing for diff_id=%s, using description", d["diff_id"])
                target_object = desc
            
            final_diffs.append(
                {
                    "diff_id": d["diff_id"],
                    "grid_cell": d["grid_cell"],
                    "diff_type": d["diff_type"],
                    "description": desc,
                    "target_object": target_object,
                    "edit_instruction": edit_instruction or desc,
                }
            )
        theme_text = src.get("theme", f"Q{q_no} pastel daily life illustration")
        theme_lower = str(theme_text).lower()
        q_seed = int(q_control.get("theme_seed", q_no))

        # Q1: 食事テーマのバリエーションを追加して単調化を抑える
        if q_no == 1 and _maybe_by_seed(q_seed + 41, 0.7):
            if not any(k in theme_lower for k in _FOOD_KEYWORDS):
                theme_text = f"{theme_text} {_choice_by_seed(_Q1_FOOD_VARIANTS, q_seed + 3)}"
            else:
                theme_text = f"{theme_text} with a distinct menu style and table composition"

        # ------------------------------------------------------------------
        # Q2: 季節バリアント追加（45%の確率）
        # Geminiがすでに子供・祖母・猫を含んでいる場合はスキップ
        # ------------------------------------------------------------------
        if q_no == 2:
            already_has_character = any(
                k in theme_lower for k in _CHILD_KEYWORDS + _GRANDPARENT_KEYWORDS + ("cat", "猫")
            )
            if not already_has_character and _maybe_by_seed(q_seed + 101, 0.45):
                theme_text = f"{theme_text} {_choice_by_seed(_Q2_VARIANTS, q_seed)}"

        # ------------------------------------------------------------------
        # Q3: キャラクターバリアント追加（45%の確率）
        # Geminiがすでに子供・祖父母を含んでいる場合はスキップ
        # イベント句はキャラクターバリアントを追加しなかった場合のみ実行
        # ------------------------------------------------------------------
        if q_no == 3:
            already_has_character = any(
                k in theme_lower for k in _CHILD_KEYWORDS + _GRANDPARENT_KEYWORDS
            )
            added_character_variant = False
            if not already_has_character and _maybe_by_seed(q_seed + 211, 0.45):
                theme_text = f"{theme_text} {_choice_by_seed(_Q3_CHARACTER_VARIANTS, q_seed)}"
                added_character_variant = True

            # イベント句：当季節（JST基準）を優先
            current_month = _current_month_jst()
            current_season = _month_to_season(current_month)
            theme_lower_after = theme_text.lower()
            has_current_season = _contains_season_keyword(theme_lower_after, current_season)
            seasonal_pool = _Q3_EVENT_VARIANTS[:8] if len(_Q3_EVENT_VARIANTS) >= 8 else _Q3_EVENT_VARIANTS
            if (not added_character_variant and not has_current_season and _maybe_by_seed(q_seed + 307, 0.85)):
                theme_text = f"{theme_text} {_choice_by_seed(seasonal_pool, q_seed + 17)}"

        final_questions.append(
            {
                "question_no": q_no,
                "difficulty": q_control["difficulty"],
                "theme": theme_text,
                "space": src.get("space", "indoor"),
                "has_people": bool(src.get("has_people", False)),
                "diff_plan": final_diffs,
            }
        )
    return final_questions


def build_base_image_prompt(
    q_theme: Dict[str, Any],
    difficulty_key: str,
    min_width: int = DEFAULT_BASE_MIN_WIDTH,
    min_height: int = DEFAULT_BASE_MIN_HEIGHT,
    diff_plan: List[Dict[str, Any]] | None = None,
) -> str:
    density_hint = {
        "easy": "low object count, large separated objects, minimal overlap",
        "medium": "moderate object count, clear separations, controlled overlap",
        "hard": "moderate-to-high object count but keep medium-sized objects; avoid tiny background clutter",
    }[difficulty_key]
    people_hint = "include 1-2 people naturally in scene (a single person is fine)" if q_theme["has_people"] else "no people in scene"

    target_objects = [d["target_object"] for d in (diff_plan or []) if d.get("target_object")]
    required_objects_block = ""
    if target_objects:
        required_objects_block = (
            "MANDATORY OBJECTS (must appear prominently in the image):\n"
            + "\n".join(f"- {obj}" for obj in target_objects)
            + "\nEach object above MUST be clearly visible, recognizable, and unambiguous.\n"
            + "Do NOT omit any of the above objects.\n"
        )
    return f"""
Create a single base image for a spot-the-difference puzzle.

Theme: {q_theme['theme']}
Scene space: {q_theme['space']}
People rule: {people_hint}
Difficulty: {difficulty_key}

{required_objects_block}

Style constraints:
- Natural / pastel tone
- Cute and warm atmosphere
- Flat 2D illustration with rounded, friendly shapes and childlike clarity
- Uniform thick outlines with soft brown/charcoal-like impression
- Water-based marker-like finish with clear filled areas
- Mostly solid fills (avoid vague gradients)
- Keep all fills inside outlines; no color bleeding across lines
- No hyper-realistic textures and no 3D rendering
- Maximum 30 colors
- No text
- Senior-friendly clarity and readability

    Canvas and layout:
    - Vertical 3:4 aspect ratio (768x1024)
- Render at least {min_width}x{min_height} pixels (or higher)
- Background MUST fill the entire canvas from edge to edge with NO white border, NO empty margins, NO blank corners. Every pixel must contain scene content.
- Keep key objects mostly in center 70%
- Do not place important objects in outer 5% margins
- Objects fully visible in frame
- Background elements should stay medium-to-large and easy to read (no tiny distant details)
- {density_hint}

Output only the image.
""".strip()


def cell_to_image_point(cell: GridCell, image_w: int, image_h: int, rng: random.Random) -> Tuple[int, int, int]:
    cell_w = image_w / GRID_COLS
    cell_h = image_h / GRID_ROWS
    cx = int((cell.col - 0.5) * cell_w)
    cy = int((cell.row - 0.5) * cell_h)
    jitter_x = int(cell_w * 0.18)
    jitter_y = int(cell_h * 0.18)
    cx += rng.randint(-jitter_x, jitter_x)
    cy += rng.randint(-jitter_y, jitter_y)
    cx = max(0, min(image_w - 1, cx))
    cy = max(0, min(image_h - 1, cy))
    image_radius = max(18, int(min(cell_w, cell_h) * 0.39))
    return cx, cy, image_radius


def build_mask_png(
    image_size: Tuple[int, int],
    center: Tuple[int, int],
    radius: int,
    bbox: Tuple[int, int, int, int] | None = None,
) -> bytes:
    from PIL import Image, ImageDraw

    w, h = image_size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        draw.rectangle((x1, y1, x2, y2), fill=255)
    else:
        cx, cy = center
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    out = io.BytesIO()
    mask.save(out, format="PNG")
    return out.getvalue()


def build_inpaint_prompt(theme: str, diff_type: str, diff_description: str) -> str:
    return f"""
Scene theme: {theme}
Edit type: {diff_type}
Edit instruction: {diff_description}

Critical constraints:
1. Edit only inside the provided WHITE mask area.
2. Keep all unmasked pixels visually identical.
3. Preserve original illustration style, line width, and palette.
4. Keep perspective and object geometry natural.
5. Do not add text, watermark, or new background artifacts.
""".strip()


REPLICATE_MODEL_VERSION = "stability-ai/stable-diffusion-inpainting:95b7223104132402a9ae91cc677285bc5eb997834bd2349fa486f53910fd68b3"
REPLICATE_API_BASE = "https://api.replicate.com/v1"


def _replicate_post(url: str, payload: Dict[str, Any], api_token: str, timeout: int = 30) -> Dict[str, Any]:
    LOGGER.info("_replicate_post called: url=%s", url[:100])
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_token}",
        "Prefer": "wait",
    }
    last_resp = None
    for attempt in range(5):  # 3→5回に増やす
        resp = _requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=(10, timeout),
        )
        last_resp = resp
        if int(resp.status_code) == 429:
            wait_s = 30 * (attempt + 1)  # 10→30秒に延ばす
            LOGGER.warning("Replicate 429, waiting %ds (attempt %d)", wait_s, attempt + 1)
            time.sleep(wait_s)
            continue
        resp.raise_for_status()
        return resp.json()
    if last_resp is not None:
        last_resp.raise_for_status()
    raise RuntimeError("Replicate POST failed")


def _replicate_get(url: str, api_token: str, timeout: int = 15) -> Dict[str, Any]:
    resp = _requests.get(
        url,
        headers={"Authorization": f"Token {api_token}"},
        timeout=(10, timeout),
    )
    resp.raise_for_status()
    return resp.json()


def _download_url(url: str, timeout: int = 60) -> bytes:
    resp = _requests.get(url, timeout=(10, timeout))
    resp.raise_for_status()
    return resp.content


def call_inpaint(
    api_url: str,
    api_token: str,
    image_bytes: bytes,
    mask_bytes: bytes,
    prompt: str,
    negative_prompt: str,
    steps: int,
    guidance_scale: float,
    strength: float,
) -> bytes:
    if not api_token:
        raise ValueError("INPAINT_API_TOKEN (Replicate API token) is required")

    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as src_img:
        image_width, image_height = src_img.size

    image_data_uri = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
    mask_data_uri = f"data:image/png;base64,{base64.b64encode(mask_bytes).decode('ascii')}"
    payload = {
        "version": REPLICATE_MODEL_VERSION,
        "input": {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image": image_data_uri,
            "mask": mask_data_uri,
            "width": image_width,
            "height": image_height,
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "prompt_strength": strength,
            "num_outputs": 1,
            "refine": "no_refiner",
            "scheduler": "K_EULER",
            "apply_watermark": False,
        },
    }
    submit_resp = _replicate_post(
        url=f"{REPLICATE_API_BASE}/predictions",
        payload=payload,
        api_token=api_token,
        timeout=90,
    )

    status = submit_resp.get("status", "")
    if status == "succeeded":
        return _extract_image(submit_resp)
    if status in ("starting", "processing"):
        poll_url = submit_resp.get("urls", {}).get("get", "")
        if not poll_url:
            raise RuntimeError(f"Replicate did not return polling URL: {submit_resp}")
        return _poll_result(poll_url, api_token)
    raise RuntimeError(f"Replicate unexpected status '{status}': {submit_resp}")


def _poll_result(poll_url: str, api_token: str, max_wait: int = 180, poll_interval: int = 3) -> bytes:
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = _replicate_get(poll_url, api_token)
        status = resp.get("status", "")
        if status == "succeeded":
            return _extract_image(resp)
        if status == "failed":
            raise RuntimeError(f"Replicate job failed: {resp.get('error', resp)}")
        if status == "canceled":
            raise RuntimeError("Replicate job was canceled")
    raise TimeoutError(f"Replicate inpainting timed out after {max_wait}s ({poll_url})")


def _extract_image(resp: Dict[str, Any]) -> bytes:
    output = resp.get("output", [])
    if not output:
        raise ValueError(f"Replicate returned no output: {resp}")
    first = output[0]
    if not first or not isinstance(first, str) or not first.startswith("http"):
        raise ValueError(f"Replicate output URL is invalid: {first}")
    return _download_url(first)


def build_video_diff_point(image_w: int, image_h: int, image_x: int, image_y: int, image_radius: int) -> Dict[str, int]:
    x_scale = VIDEO_IMAGE_W / image_w
    y_scale = VIDEO_IMAGE_H / image_h
    left_x = VIDEO_LEFT_X + int(round(image_x * x_scale))
    left_y = VIDEO_IMAGE_Y + int(round(image_y * y_scale))
    right_x = VIDEO_RIGHT_X + int(round(image_x * x_scale))
    right_y = VIDEO_IMAGE_Y + int(round(image_y * y_scale))
    radius = max(24, int(round(image_radius * min(x_scale, y_scale))))
    return {"left_x": left_x, "left_y": left_y, "right_x": right_x, "right_y": right_y, "radius": radius}


def ensure_png(image_bytes: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        out = io.BytesIO()
        img.convert("RGBA").save(out, format="PNG")
        return out.getvalue()


def ensure_min_resolution(image_bytes: bytes, min_width: int, min_height: int) -> Tuple[bytes, bool]:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        if width >= min_width and height >= min_height:
            out = io.BytesIO()
            img.convert("RGBA").save(out, format="PNG")
            return out.getvalue(), False

        scale = max(min_width / width, min_height / height)
        new_width = int(round(width * scale))
        new_height = int(round(height * scale))
        resized = img.convert("RGBA").resize((new_width, new_height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        resized.save(out, format="PNG")
        return out.getvalue(), True


def _snap_dim_to_replicate(value: int) -> int:
    value = max(64, min(value, 1024))
    return ((value + 63) // 64) * 64 if value < 1024 else 1024


def ensure_replicate_compatible_resolution(image_bytes: bytes) -> Tuple[bytes, bool]:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        target_width = REPLICATE_PORTRAIT_WIDTH
        target_height = REPLICATE_PORTRAIT_HEIGHT

        if (img.size[0], img.size[1]) == (target_width, target_height):
            out = io.BytesIO()
            img.convert("RGBA").save(out, format="PNG")
            return out.getvalue(), False

        resized = img.convert("RGBA").resize((target_width, target_height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        resized.save(out, format="PNG")
        return out.getvalue(), True


def make_daily_seed(date: datetime.date, slot: int = 0) -> int:
    """
    日付とスロット番号からの再現可能なシード値を返す。
    
    Parameters
    ----------
    date : datetime.date
        基準日
    slot : int
        スロット番号（同じ日に複数回生成する場合に区別する）
    
    Returns
    -------
    int
        再現可能なシード値
    """
    date_int = int(date.strftime("%Y%m%d"))
    return date_int * 1000 + slot


def _vision_find_bbox(
    api_key: str,
    model: str,
    image_bytes: bytes,
    diff_id: int,
    target_object: str,
    image_w: int,
    image_h: int,
) -> VisionDiffTarget:
    import base64
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = f"""You are analyzing an image to find the bounding box of a specific object.

Target object: "{target_object}"

CRITICAL: Return ONLY a valid JSON object. No text, no markdown.

{{
  "x1": <left pixel coordinate>,
  "y1": <top pixel coordinate>, 
  "x2": <right pixel coordinate>,
  "y2": <bottom pixel coordinate>
}}

Image size: {image_w}x{image_h} pixels.
Coordinates must be integers within bounds (x: 0-{image_w-1}, y: 0-{image_h-1}).

Find the object and return its bounding box coordinates.
If object is not found, return {{"x1": 0, "y1": 0, "x2": 0, "y2": 0}}

Return ONLY JSON object."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {"temperature": 0.1},
    }
    resp = http_post_json(url, payload, headers={})
    LOGGER.info("vision_find_bbox resp_keys=%s", list(resp.keys()))
    text = extract_text_from_gemini(resp)
    LOGGER.info("vision_find_bbox text_len=%d text=%s", len(text), text[:500])
    LOGGER.info("vision_find_bbox raw_response=%s", text[:500])

    parsed = extract_json_block(text)
    LOGGER.info("vision_find_bbox parsed_keys=%s", list(parsed.keys()))
    x1 = int(parsed["x1"])
    y1 = int(parsed["y1"])
    x2 = int(parsed["x2"])
    y2 = int(parsed["y2"])
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    
    # Python側で225%パディングを適用
    width = x2 - x1
    height = y2 - y1
    padded_width = int(width * 2.25)  # 225% = 2.25倍拡張
    padded_height = int(height * 2.25)
    
    x1 = max(0, cx - padded_width // 2)
    y1 = max(0, cy - padded_height // 2)
    x2 = min(image_w - 1, cx + padded_width // 2)
    y2 = min(image_h - 1, cy + padded_height // 2)
    
    radius = max(200, min(400, max(x2 - x1, y2 - y1) // 2))

    return VisionDiffTarget(
        diff_id=diff_id,
        diff_type="",
        object_name=target_object,
        description="",
        cx=cx,
        cy=cy,
        radius=radius,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )


def call_gemini_vision_analysis(
    api_key: str,
    model: str,
    image_bytes: bytes,
    diff_plan: List[Dict[str, Any]],
    image_w: int,
    image_h: int,
    skip_validation: bool = False,
) -> List[VisionDiffTarget]:
    results = []
    for diff in diff_plan:
        target_object = diff.get("target_object", "")
        if target_object:
            # 新フロー：target_objectのbboxを検索
            target = _vision_find_bbox(
                api_key=api_key,
                model=model,
                image_bytes=image_bytes,
                diff_id=diff["diff_id"],
                target_object=target_object,
                image_w=image_w,
                image_h=image_h,
            )
            target.diff_type = diff.get("diff_type", "")
            target.description = diff.get("edit_instruction") or diff.get("description", "")
        else:
            # vision検出失敗時はエラーを投げる
            raise RuntimeError(f"Vision detection failed for diff_id={diff['diff_id']} after multiple attempts. No fallback available.")
        results.append(target)
    return results


def call_gemini_refine_edit_region(*args, **kwargs):
    """旧フローの残骸 - 新フローでは使用しない"""
    return None


def call_gemini_describe_diff_targets_from_pair(*args, **kwargs):
    """旧フローの残骸 - 新フローでは使用しない"""
    return None


def call_gemini_verify_diff_targets_from_pair(*args, **kwargs):
    """旧フローの残骸 - 新フローでは使用しない"""
    return None


def generate_base_image_with_guardrails(api_key: str, model: str, base_prompt: str, min_width: int, min_height: int, max_attempts: int = 3) -> bytes:
    """ガードレール付きベース画像生成"""
    for attempt in range(max_attempts):
        try:
            image_bytes = call_gemini_image(api_key, model, base_prompt)
            if not image_bytes:
                continue
            
            # 画像の妥当性チェック
            try:
                from PIL import Image
                with Image.open(io.BytesIO(image_bytes)) as img:
                    width, height = img.size
                    if width < min_width or height < min_height:
                        continue
                return image_bytes
            except Exception:
                continue
                
        except (ValueError, KeyError) as e:
            # Gemini APIが画像データを返さなかった場合
            continue
        except Exception as e:
            # その他のエラー
            continue
    
    raise RuntimeError(f"Failed to generate base image after {max_attempts} attempts")


def refine_edit_region_from_images(*args, **kwargs):
    """旧フローの残骸 - 新フローでは使用しない"""
    return None


def allowed_diff_types_for_difficulty(*args, **kwargs):
    """旧フローの残骸 - 新フローでは使用しない"""
    return []
