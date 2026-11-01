"""JournalOS Tools powered by Free Google Sheets Webhook + Local Fallback Storage.

Includes:
- Instant, Rate-Limit-Free Animated Moodscape & Question Visual Generator (`/api/moodscape.svg`)
- Google Sheets Web App sync + instant local JSON persistence (`app.sheets_storage`)
- All 19 Journaling Methodologies prompt engine with Question Meaning & Emotion Vocabulary
- Cross-session Memory & Habit/Goal tracking stored directly in Google Sheets
"""

from __future__ import annotations

import html
import json
import os
import textwrap
import time
import urllib.parse
import urllib.request
from typing import Optional

from app.logger_utils import log_event
from app.sheets_storage import (
    EMOTIONS_CATALOG,
    METHODOLOGIES_CATALOG,
    store_add_entry,
    store_add_memory,
    store_get_analytics,
    store_get_entry,
    store_list_entries,
    store_list_memories,
    store_upsert_habit,
)


def render_animated_moodscape_svg(
    prompt: str = "Serene Mindful Sanctuary",
    theme: str = "auto",
    subtitle: str = "Breathe in clarity · Breathe out tension",
) -> str:
    """Generates a rich, living, animated SVG artwork (60fps GIF-like visual) with zero rate limits."""
    p_low = (prompt + " " + theme).lower()

    if theme == "breath" or any(w in p_low for w in ("mindful", "breath", "body", "present", "calm")):
        bg1, bg2, bg3 = "#0f172a", "#1e3a5f", "#0d9488"
        accent = "#5eead4"
        scene_type = "breath_lotus"
    elif theme == "sunrise" or any(w in p_low for w in ("morning", "dawn", "wake", "sunrise", "daily")):
        bg1, bg2, bg3 = "#1e1b4b", "#7c2d12", "#f59e0b"
        accent = "#fde68a"
        scene_type = "mountain_sunrise"
    elif theme == "warmth" or any(w in p_low for w in ("gratitude", "grateful", "heart", "expressive", "warm", "joy")):
        bg1, bg2, bg3 = "#4c1d95", "#be185d", "#f97316"
        accent = "#fed7aa"
        scene_type = "golden_meadow"
    elif theme == "cosmos" or any(w in p_low for w in ("dream", "night", "one-line", "creative", "star", "sleep")):
        bg1, bg2, bg3 = "#090d16", "#1e1b4b", "#3b0764"
        accent = "#c4b5fd"
        scene_type = "starlight_cosmos"
    elif theme == "waves" or any(w in p_low for w in ("stream", "mood", "ocean", "water", "flow", "river")):
        bg1, bg2, bg3 = "#0c4a6e", "#0369a1", "#2dd4bf"
        accent = "#bae6fd"
        scene_type = "ocean_waves"
    else:
        bg1, bg2, bg3 = "#134e4a", "#0f766e", "#34d399"
        accent = "#a7f3d0"
        scene_type = "mountain_sunrise"

    raw_title = (
        prompt.replace("Generate a visual moodscape image for", "")
        .replace("Generate a serene visual moodscape image for", "")
        .strip()
        or "Mindful Sanctuary"
    )
    raw_sub = (subtitle or "Breathe in clarity · Breathe out tension").strip()

    title_lines = textwrap.wrap(raw_title, width=62) or ["Mindful Sanctuary"]
    title_lines = title_lines[:2]
    sub_lines = textwrap.wrap(raw_sub, width=78) or [
        "Breathe in clarity · Breathe out tension"
    ]
    sub_lines = sub_lines[:4]

    if scene_type == "breath_lotus":
        center_art = f"""
        <g transform="translate(400, 132)">
          <circle cx="0" cy="0" r="38" fill="{accent}" opacity="0.18">
            <animate attributeName="r" values="34;74;34" dur="6s" repeatCount="indefinite"/>
            <animate attributeName="opacity" values="0.28;0.08;0.28" dur="6s" repeatCount="indefinite"/>
          </circle>
          <circle cx="0" cy="0" r="26" fill="{accent}" opacity="0.3">
            <animate attributeName="r" values="24;50;24" dur="6s" repeatCount="indefinite"/>
          </circle>
          <circle cx="0" cy="0" r="14" fill="#ffffff" opacity="0.85">
            <animate attributeName="r" values="12;20;12" dur="6s" repeatCount="indefinite"/>
          </circle>
          <text x="0" y="96" text-anchor="middle" fill="#e2e8f0" font-family="Plus Jakarta Sans, sans-serif" font-size="12.5" font-weight="600" letter-spacing="2">
            INHALE · HOLD · EXHALE WITH THE GLOW
          </text>
        </g>
        """
    elif scene_type == "starlight_cosmos":
        center_art = f"""
        <g>
          <circle cx="150" cy="70" r="2" fill="#fff"><animate attributeName="opacity" values="0.2;1;0.2" dur="3s" repeatCount="indefinite"/></circle>
          <circle cx="640" cy="65" r="2.5" fill="#fff"><animate attributeName="opacity" values="1;0.3;1" dur="4s" repeatCount="indefinite"/></circle>
          <circle cx="520" cy="115" r="1.8" fill="#fff"><animate attributeName="opacity" values="0.3;1;0.3" dur="2.5s" repeatCount="indefinite"/></circle>
          <circle cx="260" cy="105" r="2.2" fill="#fff"><animate attributeName="opacity" values="0.8;0.2;0.8" dur="3.5s" repeatCount="indefinite"/></circle>
          <g transform="translate(400, 135)">
            <circle cx="0" cy="0" r="44" fill="{accent}" opacity="0.22">
              <animate attributeName="r" values="40;58;40" dur="7s" repeatCount="indefinite"/>
            </circle>
            <path d="M10,-32 A34,34 0 1,0 32,20 A26,26 0 1,1 10,-32 Z" fill="#fef08a" opacity="0.92"/>
          </g>
          <path d="M0,255 Q200,215 400,245 T800,235 L800,460 L0,460 Z" fill="#1e1b4b" opacity="0.7"/>
        </g>
        """
    elif scene_type == "golden_meadow":
        center_art = f"""
        <g>
          <circle cx="400" cy="135" r="52" fill="#fde047" opacity="0.25">
            <animate attributeName="r" values="46;72;46" dur="5s" repeatCount="indefinite"/>
          </circle>
          <circle cx="400" cy="135" r="30" fill="#fef9c3" opacity="0.88"/>
          <circle cx="280" cy="185" r="4" fill="#fde047" opacity="0.8">
            <animate attributeName="cy" values="195;140;195" dur="5s" repeatCount="indefinite"/>
          </circle>
          <circle cx="510" cy="175" r="3.5" fill="#fde047" opacity="0.75">
            <animate attributeName="cy" values="185;130;185" dur="6s" repeatCount="indefinite"/>
          </circle>
          <path d="M0,240 Q240,195 450,235 T800,220 L800,460 L0,460 Z" fill="#3b0764" opacity="0.45"/>
          <path d="M0,268 Q320,232 560,262 T800,252 L800,460 L0,460 Z" fill="#1e1b4b" opacity="0.65"/>
        </g>
        """
    else:
        center_art = f"""
        <g>
          <circle cx="400" cy="140" r="48" fill="{accent}" opacity="0.32">
            <animate attributeName="cy" values="148;122;148" dur="8s" repeatCount="indefinite"/>
            <animate attributeName="r" values="44;64;44" dur="8s" repeatCount="indefinite"/>
          </circle>
          <circle cx="400" cy="140" r="26" fill="#ffffff" opacity="0.88">
            <animate attributeName="cy" values="148;122;148" dur="8s" repeatCount="indefinite"/>
          </circle>
          <polygon points="80,265 250,145 430,265" fill="#0f172a" opacity="0.45"/>
          <polygon points="310,265 490,130 690,265" fill="#0f172a" opacity="0.58"/>
          <polygon points="200,265 375,160 560,265" fill="#1e293b" opacity="0.42"/>
          <path d="M0,260 Q200,245 400,260 T800,255 L800,460 L0,460 Z" fill="#0f172a" opacity="0.78"/>
        </g>
        """

    title_start_y = 304 if len(title_lines) == 1 else 296
    title_tspans = "".join(
        f'<tspan x="400" dy="{0 if idx == 0 else 22}">{html.escape(line)}</tspan>'
        for idx, line in enumerate(title_lines)
    )

    sub_start_y = title_start_y + (len(title_lines) * 22) + 10
    sub_tspans = "".join(
        f'<tspan x="400" dy="{0 if idx == 0 else 20}">{html.escape(line)}</tspan>'
        for idx, line in enumerate(sub_lines)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
      <defs>
        <linearGradient id="skyGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="{bg1}"/>
          <stop offset="55%" stop-color="{bg2}"/>
          <stop offset="100%" stop-color="{bg3}"/>
        </linearGradient>
      </defs>
      <rect width="800" height="450" rx="18" fill="url(#skyGrad)"/>
      {center_art}
      <rect x="24" y="266" width="752" height="164" rx="16" fill="#0f172a" opacity="0.76" stroke="#ffffff" stroke-opacity="0.16" stroke-width="1"/>
      <text x="400" y="{title_start_y}" text-anchor="middle" fill="#ffffff" font-family="Plus Jakarta Sans, system-ui, sans-serif" font-size="16" font-weight="700">
        {title_tspans}
      </text>
      <text x="400" y="{sub_start_y}" text-anchor="middle" fill="{accent}" font-family="Plus Jakarta Sans, system-ui, sans-serif" font-size="13.5" font-weight="500">
        {sub_tspans}
      </text>
    </svg>"""


def generate_journal_image(prompt: str) -> str:
    """Generates an instant, rate-limit-free animated visual moodscape for a journal entry.

    Returns a local `/api/moodscape.svg` URL that renders inside A2UI Image cards with zero external rate limits.
    """
    encoded = urllib.parse.quote(prompt.strip() or "Serene Mindful Sanctuary")
    seed = int(time.time()) % 100000
    public_url = f"/api/moodscape.svg?prompt={encoded}&s={seed}"
    filename = f"journal_moodscape_{seed}.svg"

    log_event(
        "MOODSCAPE",
        "generate_journal_image",
        details={"prompt": prompt[:80], "url": public_url},
    )
    return json.dumps(
        {
            "status": "SUCCESS",
            "artifact_filename": filename,
            "public_url": public_url,
            "prompt": prompt,
        },
        indent=2,
    )


def generate_journal_video(prompt: str) -> str:
    """Generates an animated visual moodscape preview link for a journal entry."""
    return generate_journal_image(prompt=prompt)


def fetch_inspirational_quote() -> str:
    """Fetches a real-time inspirational or reflective quote from ZenQuotes API to inspire journaling."""
    api_key = os.getenv("ZENQUOTES_API_KEY") or os.getenv("QUOTE_API_KEY")
    url = "https://zenquotes.io/api/random"

    headers = {"User-Agent": "JournalOS/2.0"}
    if api_key:
        headers["X-goog-api-key"] = api_key

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                return json.dumps(
                    {
                        "quote": item.get("q"),
                        "author": item.get("a"),
                        "source": "ZenQuotes API",
                    },
                    indent=2,
                )
    except Exception as e:
        return json.dumps(
            {
                "quote": "Almost everything will work again if you unplug it for a few minutes, including you.",
                "author": "Anne Lamott",
                "source": "Mindful Sanctuary Quote",
                "note": str(e),
            },
            indent=2,
        )

    return json.dumps(
        {
            "quote": "Knowing yourself is the beginning of all wisdom.",
            "author": "Aristotle",
            "source": "Mindful Sanctuary Quote",
        },
        indent=2,
    )


def generate_reflective_prompt(category: str = "general") -> str:
    """Generates a curated journaling reflection prompt tailored to any of the 19 methodologies."""
    cat = (category or "general").lower().strip()
    matched = None

    for item in METHODOLOGIES_CATALOG:
        if (
            cat in item["id"].lower()
            or cat in item["name"].lower()
            or item["name"].lower() in cat
        ):
            matched = item
            break

    if not matched:
        keyword_map = {
            "morning": "morning-pages",
            "gratitude": "gratitude-journaling",
            "mindful": "mindfulness-journaling",
            "mood": "mood-journaling",
            "bullet": "bullet-journaling",
            "goal": "goal-journaling",
            "habit": "habit-journaling",
            "learn": "learning-journaling",
            "dream": "dream-journaling",
            "read": "reading-journaling",
            "quote": "commonplace-journaling",
            "express": "expressive-writing",
            "stream": "stream-of-consciousness",
            "travel": "travel-journaling",
            "creative": "creative-journaling",
            "one-line": "one-line-a-day",
        }
        for kw, target_id in keyword_map.items():
            if kw in cat:
                matched = next(
                    (m for m in METHODOLOGIES_CATALOG if m["id"] == target_id),
                    None,
                )
                break

    if not matched:
        matched = next(
            (m for m in METHODOLOGIES_CATALOG if m["id"] == "reflective-journaling"),
            METHODOLOGIES_CATALOG[0],
        )

    visual_url = (
        f"/api/moodscape.svg?prompt={urllib.parse.quote(matched['name'] + ' — ' + matched['tagline'])}"
        f"&theme={urllib.parse.quote(matched.get('visual_theme', 'breath'))}"
        f"&subtitle={urllib.parse.quote(matched.get('question_meaning', ''))}"
    )

    return json.dumps(
        {
            "category": matched["name"],
            "pillar": matched["pillar"],
            "tagline": matched["tagline"],
            "time_label": matched.get("time_label", ""),
            "prompt": matched["prompt"],
            "question_meaning": matched.get("question_meaning", ""),
            "template": matched["template"],
            "visual_url": visual_url,
            "emotions": EMOTIONS_CATALOG,
        },
        indent=2,
    )


def list_journal_entries(
    limit: int = 10,
    methodology: Optional[str] = None,
    mood: Optional[str] = None,
) -> str:
    """Retrieves recent journal entries stored in Google Sheets / local storage."""
    entries = store_list_entries(limit=limit, methodology=methodology, mood=mood)
    return json.dumps(entries, indent=2)


def get_journal_entry(entry_id: str) -> str:
    """Retrieves a specific journal entry by its unique entry_id."""
    entry = store_get_entry(entry_id)
    if not entry:
        return f"Journal entry '{entry_id}' not found."
    return json.dumps(entry, indent=2)


def add_journal_entry(
    title: str,
    content: str,
    methodology: str = "Reflective Journaling",
    mood: str = "Grounded & Serene",
    tags: Optional[list[str]] = None,
) -> str:
    """Creates a new journal entry in Google Sheets (and local store)."""
    result = store_add_entry(
        title=title,
        content=content,
        methodology=methodology,
        mood=mood,
        tags=tags,
    )
    return json.dumps(result, indent=2)


def save_user_memory(domain: str, fact: str) -> str:
    """Saves an important long-term memory or insight about the user into Google Sheets Memory Bank."""
    result = store_add_memory(domain=domain, fact=fact)
    return json.dumps(result, indent=2)


def list_user_memories(domain: Optional[str] = None) -> str:
    """Retrieves stored long-term user memories and patterns across sessions."""
    memories = store_list_memories(domain=domain)
    return json.dumps(memories, indent=2)


def log_habit_or_goal(
    title: str,
    category: str = "Habit",
    status: str = "Active",
    increment_streak: bool = True,
) -> str:
    """Logs or increments a habit streak or personal goal in Google Sheets."""
    result = store_upsert_habit(
        title=title,
        category=category,
        status=status,
        increment_streak=increment_streak,
    )
    return json.dumps(result, indent=2)


def get_journaling_analytics() -> str:
    """Returns summary statistics of the user's journaling practice."""
    stats = store_get_analytics()
    return json.dumps(stats, indent=2)
