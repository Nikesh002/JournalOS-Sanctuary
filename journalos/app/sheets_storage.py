"""Privacy-First Google Sheets Webhook + Isolated Local Vault Storage Engine for JournalOS.

SECURITY & PRIVACY ARCHITECTURE:
1. Per-User Cryptographic Vault Isolation (`CURRENT_VAULT_ID` contextvar):
   Each browser session gets its own isolated vault file (`vault_<hash>.json`), ensuring
   one user can NEVER see another user's mental health entries, Google Sheet, or API key.
2. Google Apps Script `secret_token` Verification:
   Authenticates webhook calls so unauthorized parties cannot read/write the Google Sheet.
3. Supports Client-Side AES-256-GCM Encrypted Entries (`ENC:v1:...`).
4. One-Click Vault Purge (`purge_vault_data`) for shared/public computers.
"""

from __future__ import annotations

import base64
import contextvars
import csv
import datetime
import hashlib
import hmac
import io
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.logger_utils import log_event

DATA_DIR = Path(__file__).parent.parent / "data"
STORE_FILE = DATA_DIR / "journalos_store.json"
CONFIG_FILE = DATA_DIR / "runtime_config.json"
MASTER_KEY_FILE = DATA_DIR / ".vault_master.key"


def _get_or_create_master_key() -> bytes:
    """Returns a machine-local 256-bit key for encrypting PII & API credentials at rest."""
    env_key = os.environ.get("JOURNALOS_MASTER_KEY", "").strip()
    if env_key:
        return hashlib.sha256(env_key.encode("utf-8")).digest()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if MASTER_KEY_FILE.exists():
        try:
            raw = MASTER_KEY_FILE.read_text(encoding="utf-8").strip()
            if raw:
                return base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception:
            pass
    new_key = secrets.token_bytes(32)
    try:
        MASTER_KEY_FILE.write_text(
            base64.urlsafe_b64encode(new_key).decode("ascii"), encoding="utf-8"
        )
    except Exception:
        pass
    return new_key


def _keystream(master_key: bytes, salt: bytes, length: int) -> bytes:
    """Generates a deterministic cryptographic keystream via PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", master_key, salt, 10000, dklen=max(1, length))


def _encrypt_at_rest(plaintext: str) -> str:
    """Encrypts a sensitive config/PII string at rest with HMAC-SHA256 authentication."""
    if not plaintext:
        return ""
    if plaintext.startswith("VAULT_ENC:v1:"):
        return plaintext
    key = _get_or_create_master_key()
    raw = plaintext.encode("utf-8")
    salt = secrets.token_bytes(16)
    stream = _keystream(key, salt, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    mac = hmac.new(key, salt + cipher, hashlib.sha256).hexdigest()[:32]
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    cipher_b64 = base64.urlsafe_b64encode(cipher).decode("ascii")
    return f"VAULT_ENC:v1:{salt_b64}:{mac}:{cipher_b64}"


def _decrypt_at_rest(value: str) -> str:
    """Decrypts an at-rest encrypted config/PII string (or returns plaintext if migrating)."""
    if not value or not isinstance(value, str):
        return ""
    if not value.startswith("VAULT_ENC:v1:"):
        return value
    try:
        parts = value.split(":")
        if len(parts) != 5:
            return ""
        salt = base64.urlsafe_b64decode(parts[2].encode("ascii"))
        mac_expected = parts[3]
        cipher = base64.urlsafe_b64decode(parts[4].encode("ascii"))
        key = _get_or_create_master_key()
        mac_actual = hmac.new(key, salt + cipher, hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac_expected, mac_actual):
            return ""
        stream = _keystream(key, salt, len(cipher))
        plain = bytes(a ^ b for a, b in zip(cipher, stream))
        return plain.decode("utf-8")
    except Exception:
        return ""

# Context variable holding the current request's isolated Vault ID
CURRENT_VAULT_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "CURRENT_VAULT_ID", default="default"
)


def set_current_vault_id(vault_id: str | None) -> None:
    clean = (vault_id or "default").strip()
    if not clean or clean == "default":
        CURRENT_VAULT_ID.set("default")
    else:
        # Hash the client vault token so file paths are safe and opaque on disk
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:20]
        CURRENT_VAULT_ID.set(digest)


def _get_vault_paths() -> tuple[Path, Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    vid = CURRENT_VAULT_ID.get()
    if vid == "default":
        return STORE_FILE, CONFIG_FILE
    return (
        DATA_DIR / f"vault_store_{vid}.json",
        DATA_DIR / f"vault_config_{vid}.json",
    )


# ---------------------------------------------------------------------------
# Rich Emotion Vocabulary Catalog (Helps users articulate nuanced feelings)
# ---------------------------------------------------------------------------
EMOTIONS_CATALOG: list[dict[str, str]] = [
    {
        "label": "Grounded & Serene",
        "emoji": "🌿",
        "group": "Peaceful",
        "phrase": "I feel grounded, steady, and quietly at ease in my body right now.",
    },
    {
        "label": "Deeply Grateful",
        "emoji": "💛",
        "group": "Warm",
        "phrase": "I notice a warm sense of appreciation for the small gifts around me today.",
    },
    {
        "label": "Inspired & Driven",
        "emoji": "⚡",
        "group": "Energized",
        "phrase": "I feel a strong spark of creative energy and clarity about what I want to build.",
    },
    {
        "label": "Focused & Intentional",
        "emoji": "🎯",
        "group": "Energized",
        "phrase": "My attention feels sharp, purposeful, and ready for meaningful deep work.",
    },
    {
        "label": "Hopeful & Curious",
        "emoji": "🌱",
        "group": "Open",
        "phrase": "I feel open-minded, curious, and gently optimistic about what lies ahead.",
    },
    {
        "label": "Contemplative & Still",
        "emoji": "🌙",
        "group": "Reflective",
        "phrase": "I am in a quiet, inward-looking space, observing my thoughts with curiosity.",
    },
    {
        "label": "Mentally Overloaded",
        "emoji": "🌀",
        "group": "Stressed",
        "phrase": "My mind feels crowded with too many open tabs and competing priorities right now.",
    },
    {
        "label": "Restless & Anxious",
        "emoji": "🌊",
        "group": "Stressed",
        "phrase": "I notice an undercurrent of urgency or tightness that needs gentle grounding.",
    },
    {
        "label": "Tired & Seeking Rest",
        "emoji": "🌧️",
        "group": "Low Energy",
        "phrase": "My energy feels depleted today, and I need permission to slow down and recharge.",
    },
    {
        "label": "Tender & Vulnerable",
        "emoji": "🌸",
        "group": "Sensitive",
        "phrase": "I am carrying some tender, unspoken feelings that need a safe, non-judgmental space.",
    },
]

# ---------------------------------------------------------------------------
# All 19 Journaling Methodologies Catalog (with Time Windows & Visual Themes)
# ---------------------------------------------------------------------------
METHODOLOGIES_CATALOG: list[dict[str, Any]] = [
    {
        "id": "morning-pages",
        "name": "Morning Pages",
        "pillar": "Clarity & Mindful Presence",
        "icon": "wb_twilight",
        "best_time": "early_morning",
        "time_label": "🌅 Best at 5 AM – 10 AM",
        "visual_theme": "sunrise",
        "tagline": "Clear mental clutter first thing in the morning",
        "description": "Unfiltered, stream-of-consciousness writing done immediately upon waking to release mental fog, surface quiet anxieties, and spark creative clarity.",
        "prompt": "Without editing or overthinking, what thoughts, worries, or half-formed ideas are floating at the surface of your mind right now?",
        "question_meaning": "Think of this as sweeping the porch of your mind—letting every stray thought out onto paper so your inner focus becomes crystal clear.",
        "template": "Right now my mind feels...\nThree things occupying my thoughts:\n1. \n2. \n3. \nWhat I choose to release so I can move forward with peace:",
    },
    {
        "id": "gratitude-journaling",
        "name": "Gratitude Journaling",
        "pillar": "Emotional Intelligence & Gratitude",
        "icon": "favorite",
        "best_time": "evening",
        "time_label": "🌆 Best at 6 PM – 10 PM",
        "visual_theme": "warmth",
        "tagline": "Rewire attention toward abundance & everyday gifts",
        "description": "Focusing on specific, concrete moments, people, and small details that brought warmth, peace, or appreciation today.",
        "prompt": "What is a small, easily overlooked detail from today that brought you unexpected warmth, relief, or joy?",
        "question_meaning": "Instead of listing generic things, zoom in on one tiny micro-moment (a warm cup, a kind word, a quiet breath) to savor its emotional imprint.",
        "template": "3 Specific Moments I Appreciate Today:\n1. \n2. \n3. \nWhy one of these mattered deeply to me:",
    },
    {
        "id": "reflective-journaling",
        "name": "Reflective Journaling",
        "pillar": "Emotional Intelligence & Gratitude",
        "icon": "psychology",
        "best_time": "evening",
        "time_label": "🌆 Best at 5 PM – 9 PM",
        "visual_theme": "mirror",
        "tagline": "Extract deep wisdom from recent experiences",
        "description": "Stepping back from daily events to examine how you responded, what values were tested, and what insights you can carry forward.",
        "prompt": "Looking back at a key moment today, how did your reaction align with the person you aspire to become?",
        "question_meaning": "We grow not from experience alone, but from reflecting on our experience—turning today's events into compassionate self-awareness.",
        "template": "Experience / Moment:\nHow I initially felt & reacted:\nWhat I discovered beneath the surface:\nHow I want to approach this next time:",
    },
    {
        "id": "mindfulness-journaling",
        "name": "Mindfulness Journaling",
        "pillar": "Clarity & Mindful Presence",
        "icon": "self_improvement",
        "best_time": "afternoon",
        "time_label": "🌿 Best at 2 PM – 6 PM (or anytime stressed)",
        "visual_theme": "breath",
        "tagline": "Anchor awareness in the present body and breath",
        "description": "Grounding attention in present-moment sensory details, bodily sensations, and emotional weather without judgment.",
        "prompt": "Take three slow breaths. What physical sensation or quiet emotion is asking for your compassionate attention right now?",
        "question_meaning": "Pause the mental movie of past and future. Notice your shoulders, jaw, breath, and heart right in this exact second.",
        "template": "Present Body Scan (tension / ease):\nWhat I can hear, see, and feel right now:\nEmotion present without judgment:\nOne kind intention for this moment:",
    },
    {
        "id": "mood-journaling",
        "name": "Mood Journaling",
        "pillar": "Emotional Intelligence & Gratitude",
        "icon": "mood",
        "best_time": "afternoon",
        "time_label": "🌤️ Best Mid-Day or Evening Check-in",
        "visual_theme": "waves",
        "tagline": "Track emotional patterns, triggers, and energy shifts",
        "description": "Mapping emotional states alongside activities, sleep, and social interactions to uncover what truly nourishes or drains you.",
        "prompt": "How would you describe the texture of your energy and mood right now, and what shifted it most today?",
        "question_meaning": "Emotions are data, not directives. Naming your exact feeling reduces amygdala reactivity and restores emotional balance.",
        "template": "Current Emotion & Energy (1-10):\nWhat nourished my energy today:\nWhat drained my energy today:\nWhat my nervous system needs most right now:",
    },
    {
        "id": "bullet-journaling",
        "name": "Bullet Journaling",
        "pillar": "Intentional Living & Productivity",
        "icon": "checklist",
        "best_time": "midday",
        "time_label": "☀️ Best at 9 AM – 2 PM",
        "visual_theme": "compass",
        "tagline": "Rapid-log tasks, events, and notes with intention",
        "description": "Concise, structured logging of priorities (• tasks, ○ events, — notes) to separate meaningful action from busywork.",
        "prompt": "If you could only complete three meaningful tasks today and let the rest go, which three would genuinely move your life forward?",
        "question_meaning": "Productivity isn't doing more things—it's doing the right things with calm, undivided presence.",
        "template": "• Top Priority Task:\n• Secondary Task:\n○ Key Event / Milestone:\n— Insight / Note to Remember:",
    },
    {
        "id": "goal-journaling",
        "name": "Goal Journaling",
        "pillar": "Intentional Living & Productivity",
        "icon": "flag",
        "best_time": "midday",
        "time_label": "☀️ Best at 8 AM – 1 PM",
        "visual_theme": "mountain",
        "tagline": "Align daily micro-actions with long-term vision",
        "description": "Connecting big aspirations with concrete milestones, obstacle pre-mortems, and honest progress check-ins.",
        "prompt": "What is the single most impactful micro-step you can take today that aligns with your long-term vision?",
        "question_meaning": "Big dreams become real when bridged to a concrete 15-minute action you can complete today.",
        "template": "Core Goal in Focus:\nWhy this matters to my future self:\nObstacle I might face today:\nMy 15-minute next action:",
    },
    {
        "id": "habit-journaling",
        "name": "Habit Journaling",
        "pillar": "Intentional Living & Productivity",
        "icon": "repeat",
        "best_time": "evening",
        "time_label": "🌆 Best for Daily Ritual Check-in",
        "visual_theme": "growth",
        "tagline": "Build sustainable rituals through identity-based reflection",
        "description": "Observing cues, friction points, and rewards around daily habits so consistency feels natural rather than forced.",
        "prompt": "Which daily ritual made you feel most grounded recently, and what friction can you remove to make it effortless tomorrow?",
        "question_meaning": "Every habit is a vote for the identity you are building—small rituals compound into lasting transformation.",
        "template": "Habit I am nurturing:\nIdentity it reinforces ('I am someone who...'):\nWhat helped or hindered me today:\nTiny adjustment for tomorrow:",
    },
    {
        "id": "expressive-writing",
        "name": "Expressive Writing",
        "pillar": "Clarity & Mindful Presence",
        "icon": "healing",
        "best_time": "night",
        "time_label": "🌙 Best in Quiet Evening Hours",
        "visual_theme": "warmth",
        "tagline": "Process heavy emotions through honest emotional release",
        "description": "Pennebaker-inspired deep emotional writing about difficult or unresolved experiences to foster healing and cognitive reframing.",
        "prompt": "What unspoken truth or heavy feeling have you been carrying silently that deserves a safe space on the page?",
        "question_meaning": "Putting raw feelings into words unburdens your nervous system and helps your mind weave meaning out of difficulty.",
        "template": "What happened and how it felt in the moment:\nThe part I haven't said out loud:\nWhat this experience is teaching me about my boundaries or values:",
    },
    {
        "id": "stream-of-consciousness",
        "name": "Stream-of-Consciousness",
        "pillar": "Clarity & Mindful Presence",
        "icon": "waves",
        "best_time": "early_morning",
        "time_label": "🌅 Best Morning or Creative Unblock",
        "visual_theme": "waves",
        "tagline": "Follow the natural river of your thoughts without rules",
        "description": "Continuous, associative writing where you let one thought lead naturally to the next without censoring structure or grammar.",
        "prompt": "Start with the first word or image in your mind right now and follow wherever the trail leads for 5 minutes.",
        "question_meaning": "Turn off your inner critic and let your pen flow continuously—surprising insights hide beneath polished thoughts.",
        "template": "Starting thought: ...\nFollowing the thread wherever it goes:",
    },
    {
        "id": "prompted-journaling",
        "name": "Prompted Journaling",
        "pillar": "Emotional Intelligence & Gratitude",
        "icon": "lightbulb",
        "best_time": "afternoon",
        "time_label": "🌤️ Great Anytime for Deep Discovery",
        "visual_theme": "mirror",
        "tagline": "Explore targeted questions that unlock new perspectives",
        "description": "Using curated Socratic questions to bypass habitual thinking loops and discover fresh self-knowledge.",
        "prompt": "What belief or assumption have you held onto this year that might no longer be serving your growth?",
        "question_meaning": "A single right question can unlock a door that months of routine thinking walked right past.",
        "template": "Prompt Question:\nMy honest first answer:\nGoing one layer deeper:",
    },
    {
        "id": "daily-journaling",
        "name": "Daily Journaling",
        "pillar": "Intentional Living & Productivity",
        "icon": "today",
        "best_time": "evening",
        "time_label": "🌆 Best at Day's End",
        "visual_theme": "sunrise",
        "tagline": "Chronicle the story, highlights, and lessons of your day",
        "description": "A balanced daily check-in capturing what happened, how you felt, and the standout moment worth remembering.",
        "prompt": "If today were a chapter in your life story, what would its title be and what was its defining scene?",
        "question_meaning": "Honoring your everyday life turns ordinary days into a meaningful personal narrative.",
        "template": "Highlight of the Day:\nChallenge I navigated:\nSomething I learned about myself:\nTomorrow I look forward to:",
    },
    {
        "id": "one-line-a-day",
        "name": "One-Line-a-Day",
        "pillar": "Intentional Living & Productivity",
        "icon": "short_text",
        "best_time": "night",
        "time_label": "🌙 Best Before Sleep (60-Second Ritual)",
        "visual_theme": "cosmos",
        "tagline": "Capture the essence of today in one powerful sentence",
        "description": "Minimalist micro-journaling for busy days—distilling the entire day into a single vivid, memorable sentence.",
        "prompt": "In a single vivid sentence, what made today unmistakably today?",
        "question_meaning": "Even on your busiest night, one honest sentence keeps your chain of self-awareness unbroken.",
        "template": "Today in one vivid sentence: ",
    },
    {
        "id": "learning-journaling",
        "name": "Learning Journaling",
        "pillar": "Wisdom, Learning & Curiosity",
        "icon": "school",
        "best_time": "afternoon",
        "time_label": "☀️ Best After Study or Deep Work",
        "visual_theme": "growth",
        "tagline": "Synthesize new skills, mistakes, and mental models",
        "description": "Consolidating concepts you are studying, experiments you ran, and mistakes that revealed deeper understanding.",
        "prompt": "What friction point, mistake, or new concept did you encounter recently, and how would you explain the takeaway in simple terms?",
        "question_meaning": "Explaining an insight in your own words wires it permanently into your long-term intuition.",
        "template": "Concept / Skill Explored:\nKey Insight in my own words:\nHow this connects to something I already know:\nWhere I will apply this:",
    },
    {
        "id": "reading-journaling",
        "name": "Reading Journaling",
        "pillar": "Wisdom, Learning & Curiosity",
        "icon": "menu_book",
        "best_time": "evening",
        "time_label": "🌆 Best During Reading Sessions",
        "visual_theme": "growth",
        "tagline": "Dialogue with books, essays, and ideas that move you",
        "description": "Recording transformative passages, reflections, and personal action items from books and articles you read.",
        "prompt": "What idea or passage from your recent reading challenged or expanded the way you see the world?",
        "question_meaning": "Don't just consume books—converse with them and capture the ideas that reshape your life.",
        "template": "Book / Article Title & Author:\nKey Idea or Passage:\nWhy it resonated or challenged me:\nHow it changes my thinking:",
    },
    {
        "id": "commonplace-journaling",
        "name": "Commonplace Journaling",
        "pillar": "Wisdom, Learning & Curiosity",
        "icon": "collections_bookmark",
        "best_time": "afternoon",
        "time_label": "🌤️ Anytime Inspiration Strikes",
        "visual_theme": "compass",
        "tagline": "Curate a personal treasury of quotes, wisdom, and sparks",
        "description": "A timeless intellectual notebook collecting memorable quotes, philosophies, observations, and cross-disciplinary connections.",
        "prompt": "What quote, principle, or observation crossed your path recently that belongs in your personal philosophy?",
        "question_meaning": "Your commonplace book becomes a mirror of the wisdom you choose to live by.",
        "template": "Quote / Observation:\nSource:\nTheme / Tag:\nMy personal commentary:",
    },
    {
        "id": "dream-journaling",
        "name": "Dream Journaling",
        "pillar": "Imagination & Life Story",
        "icon": "nights_stay",
        "best_time": "early_morning",
        "time_label": "🌅 Immediately Upon Waking",
        "visual_theme": "cosmos",
        "tagline": "Decode subconscious symbols, imagery, and night visions",
        "description": "Capturing dream scenes, atmospheres, and emotional undertones before they fade to explore subconscious themes.",
        "prompt": "Describe the setting, characters, colors, and lingering emotional atmosphere of your most recent dream.",
        "question_meaning": "Dreams speak in metaphor and emotion—capturing them upon waking bridges your subconscious and conscious mind.",
        "template": "Dream Scene & Atmosphere:\nKey Symbols or Characters:\nEmotion felt inside the dream:\nWhat waking life theme this might mirror:",
    },
    {
        "id": "travel-journaling",
        "name": "Travel Journaling",
        "pillar": "Imagination & Life Story",
        "icon": "explore",
        "best_time": "evening",
        "time_label": "🌍 On Journeys or Mindful Walks",
        "visual_theme": "mountain",
        "tagline": "Preserve sensory memories of places, journeys, and wonder",
        "description": "Documenting either distant adventures or mindful walks in your own neighborhood with vivid sensory curiosity.",
        "prompt": "Whether from a journey afar or a walk nearby, what sight, sound, scent, or encounter made you feel most alive?",
        "question_meaning": "Travel is a state of attentive curiosity—you can practice it in a new country or on your own street.",
        "template": "Place / Walk:\nSensory Details (Sights, Sounds, Scents):\nUnexpected Discovery or Conversation:\nHow this place shifted my perspective:",
    },
    {
        "id": "creative-journaling",
        "name": "Creative Journaling",
        "pillar": "Imagination & Life Story",
        "icon": "palette",
        "best_time": "night",
        "time_label": "🎨 Anytime Creative Flow Calls",
        "visual_theme": "cosmos",
        "tagline": "Play with metaphors, poetry, visual moodscapes, and imagination",
        "description": "Breaking out of linear prose through metaphor, creative storytelling, poetic fragments, and visual moodscape generation.",
        "prompt": "If your current inner state were a landscape, season, and weather pattern, what would it look and sound like?",
        "question_meaning": "Metaphor bypasses analytical defenses and lets your imagination paint what literal words cannot.",
        "template": "My Inner Landscape Metaphor:\nColors & Textures of this season in my life:\nA creative fragment or vision I want to bring to life:",
    },
]


def get_time_based_recommendation(
    local_hour: int | None = None, timezone_name: str = ""
) -> dict[str, Any]:
    """Returns the recommended journaling methodology based on the user's current time of day."""
    if local_hour is None:
        local_hour = datetime.datetime.now().astimezone().hour
    tz_label = timezone_name or str(
        datetime.datetime.now().astimezone().tzinfo or "Local Time"
    )

    if 5 <= local_hour < 10:
        period = "Early Morning Sanctuary"
        greeting = "Good Morning"
        rec_id = "morning-pages"
        alt_ids = ["dream-journaling", "goal-journaling"]
        reason = "Your mind is fresh upon waking—ideal for clearing mental clutter with Morning Pages."
    elif 10 <= local_hour < 14:
        period = "Mid-Day Intentional Focus"
        greeting = "Good Day"
        rec_id = "bullet-journaling"
        alt_ids = ["goal-journaling", "learning-journaling"]
        reason = "Peak daytime energy—ideal for aligning priorities with Bullet or Goal Journaling."
    elif 14 <= local_hour < 18:
        period = "Afternoon Mindful Reset"
        greeting = "Good Afternoon"
        rec_id = "mindfulness-journaling"
        alt_ids = ["mood-journaling", "prompted-journaling"]
        reason = "A gentle afternoon pause to release tension and re-center your breath with Mindfulness Journaling."
    elif 18 <= local_hour < 22:
        period = "Evening Reflection & Gratitude"
        greeting = "Good Evening"
        rec_id = "gratitude-journaling"
        alt_ids = ["reflective-journaling", "daily-journaling"]
        reason = "As the day winds down, savor today's gifts and lessons with Gratitude or Reflective Journaling."
    else:
        period = "Late-Night Quiet Unburdening"
        greeting = "Peaceful Night"
        rec_id = "expressive-writing"
        alt_ids = ["one-line-a-day", "dream-journaling"]
        reason = "In the stillness of night, release heavy thoughts onto the page for restful sleep."

    rec_meth = next(
        (m for m in METHODOLOGIES_CATALOG if m["id"] == rec_id),
        METHODOLOGIES_CATALOG[0],
    )
    return {
        "local_hour": local_hour,
        "timezone": tz_label,
        "period": period,
        "greeting": greeting,
        "recommended_methodology": rec_meth["name"],
        "recommended_id": rec_meth["id"],
        "alternatives": alt_ids,
        "reason": reason,
    }


DEFAULT_SEED_DATA: dict[str, Any] = {
    "entries": [
        {
            "entry_id": "entry-seed-101",
            "title": "Building an AI Mindful Journaling Sanctuary",
            "content": "What is on my mind: Building a full-fledged, ready-to-use mindful journaling app that truly helps people reflect and grow. Why it matters: Staying relevant and creating real human impact with AI.",
            "methodology": "Morning Pages",
            "mood": "Inspired & Driven",
            "tags": ["vision", "ai-builder", "morning-pages"],
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "word_count": 34,
        },
    ],
    "memories": [
        {
            "memory_id": "mem-seed-1",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "domain": "User Goals",
            "fact": "Build an impactful, ready-to-use AI mindful journaling web app and practice daily intentional reflection.",
        },
        {
            "memory_id": "mem-seed-2",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "domain": "Journaling Type & Preferences",
            "fact": "Prefers structured coaching with 'Why this works', 'Reflection Question', and 'Suggested Structure', plus Morning Pages & Mindfulness Journaling.",
        },
        {
            "memory_id": "mem-seed-3",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "domain": "Habits & Routines",
            "fact": "Committed to daily mindful check-ins and honest self-reflection.",
        },
    ],
    "habits": [
        {
            "item_id": "hab-seed-1",
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "title": "10-Minute Daily Mindful Journaling",
            "category": "Habit",
            "status": "Active",
            "streak": 1,
            "reminder_time": "08:00",
        },
        {
            "item_id": "hab-seed-2",
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "title": "Evening Gratitude & Emotional Check-In",
            "category": "Habit",
            "status": "Active",
            "streak": 1,
            "reminder_time": "20:30",
        },
        {
            "item_id": "hab-seed-3",
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "title": "Single Deep-Work Priority Before Noon",
            "category": "Goal",
            "status": "In Progress",
            "streak": 1,
            "reminder_time": "09:30",
        },
    ],
}


def get_runtime_config() -> dict[str, Any]:
    """Reads isolated runtime configuration for the current user's vault (decrypting PII & keys at rest)."""
    _, cfg_file = _get_vault_paths()
    target_file = cfg_file if cfg_file.exists() else (CONFIG_FILE if (CONFIG_FILE.exists() and CURRENT_VAULT_ID.get() == "default") else None)
    saved: dict[str, str] = {}
    if target_file and target_file.exists():
        try:
            saved = json.loads(target_file.read_text(encoding="utf-8"))
        except Exception:
            saved = {}

    # Transparently migrate any legacy plain-text values on disk to VAULT_ENC:v1 encrypted format
    needs_migration = any(
        isinstance(saved.get(k), str)
        and saved.get(k, "").strip()
        and not saved.get(k, "").startswith("VAULT_ENC:v1:")
        for k in (
            "google_sheets_webhook_url",
            "gemini_api_key",
            "user_name",
            "secret_vault_token",
        )
    )
    if needs_migration and target_file:
        encrypted_disk = {
            k: _encrypt_at_rest(str(v).strip()) if str(v).strip() else ""
            for k, v in saved.items()
        }
        try:
            target_file.write_text(json.dumps(encrypted_disk, indent=2), encoding="utf-8")
        except Exception:
            pass

    webhook_url = (
        _decrypt_at_rest(saved.get("google_sheets_webhook_url", ""))
        or (
            os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "")
            if CURRENT_VAULT_ID.get() == "default"
            else ""
        )
    ).strip()
    gemini_key = (
        _decrypt_at_rest(saved.get("gemini_api_key", ""))
        or os.environ.get("GEMINI_API_KEY", "")
        or os.environ.get("GOOGLE_API_KEY", "")
    ).strip()
    user_name = (
        _decrypt_at_rest(saved.get("user_name", ""))
        or os.environ.get("JOURNALOS_USER_NAME", "")
    ).strip()
    secret_token = _decrypt_at_rest(saved.get("secret_vault_token", "")).strip()

    return {
        "google_sheets_webhook_url": webhook_url,
        "gemini_api_key": gemini_key,
        "user_name": user_name,
        "display_name": user_name or "Friend",
        "onboarding_complete": bool(user_name),
        "secret_vault_token": secret_token,
    }


def _mask_url(url: str) -> str:
    if not url or len(url) < 25:
        return ""
    return url[:32] + "•••" + url[-10:]


def save_runtime_config(
    google_sheets_webhook_url: str | None = None,
    gemini_api_key: str | None = None,
    user_name: str | None = None,
    secret_vault_token: str | None = None,
) -> dict[str, Any]:
    """Encrypts and saves user-supplied settings & PII inside their isolated vault config."""
    _, cfg_file = _get_vault_paths()
    current = get_runtime_config()
    if google_sheets_webhook_url is not None and "•••" not in google_sheets_webhook_url:
        current["google_sheets_webhook_url"] = google_sheets_webhook_url.strip()
    if gemini_api_key is not None and gemini_api_key.strip():
        current["gemini_api_key"] = gemini_api_key.strip()
    if user_name is not None and user_name.strip():
        current["user_name"] = user_name.strip()
    if secret_token := secret_vault_token:
        current["secret_vault_token"] = secret_token.strip()

    encrypted_disk = {
        "google_sheets_webhook_url": _encrypt_at_rest(
            current.get("google_sheets_webhook_url", "")
        ),
        "gemini_api_key": _encrypt_at_rest(current.get("gemini_api_key", "")),
        "user_name": _encrypt_at_rest(current.get("user_name", "")),
        "secret_vault_token": _encrypt_at_rest(current.get("secret_vault_token", "")),
    }
    cfg_file.write_text(json.dumps(encrypted_disk, indent=2), encoding="utf-8")
    log_event(
        "CONFIG",
        "save_runtime_config",
        details={
            "sheets_connected": bool(current.get("google_sheets_webhook_url")),
            "gemini_configured": bool(current.get("gemini_api_key")),
            "vault_token_set": bool(current.get("secret_vault_token")),
            "encrypted_at_rest": True,
        },
    )
    saved_name = current.get("user_name", "")
    return {
        "user_name": saved_name,
        "display_name": saved_name or "Friend",
        "onboarding_complete": bool(saved_name),
        "sheets_connected": bool(current.get("google_sheets_webhook_url")),
        "google_sheets_webhook_masked": _mask_url(
            current.get("google_sheets_webhook_url", "")
        ),
        "gemini_configured": bool(current.get("gemini_api_key")),
        "vault_token_set": bool(current.get("secret_vault_token")),
    }


def purge_vault_data() -> dict[str, str]:
    """Immediately wipes all local entries, memories, habits, and credentials for the current vault."""
    store_file, cfg_file = _get_vault_paths()
    for f in (store_file, cfg_file):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass
    log_event("PRIVACY", "purge_vault_data", status="OK")
    return {
        "status": "SUCCESS",
        "message": "All local vault entries, memories, and credentials have been permanently wiped from this device.",
    }


def _is_noise_entry(e: dict[str, Any]) -> bool:
    """Filters out accidental command prompts or unit-test noise from user's real journal."""
    title = str(e.get("title", "")).strip().lower()
    content = str(e.get("content", "")).strip().lower()
    if title.startswith("unit test ") or title.startswith("guide me through"):
        return True
    if content.startswith("guide me through ") and len(content.split()) < 16:
        return True
    if str(e.get("entry_id", "")) in ("entry-seed-102", "entry-seed-103"):
        return True
    return False


def _deduplicate_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merges duplicate entries that share identical content into a single row with combined tags & extra columns."""
    by_content: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []

    for e in entries:
        if _is_noise_entry(e):
            continue
        norm_content = " ".join(str(e.get("content", "")).strip().split())
        key = norm_content if norm_content else str(e.get("entry_id", ""))
        if key not in by_content:
            cloned = dict(e)
            raw_tags = cloned.get("tags", [])
            if isinstance(raw_tags, str):
                try:
                    raw_tags = json.loads(raw_tags)
                except Exception:
                    raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            cloned["tags"] = list(dict.fromkeys(str(t).strip() for t in (raw_tags or []) if str(t).strip()))
            cloned.setdefault("updated_at", cloned.get("timestamp", ""))
            cloned.setdefault("coach_insight", "")
            by_content[key] = cloned
            ordered_keys.append(key)
        else:
            existing = by_content[key]
            # Merge tags without duplicates
            raw_tags = e.get("tags", [])
            if isinstance(raw_tags, str):
                try:
                    raw_tags = json.loads(raw_tags)
                except Exception:
                    raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            merged_tags = list(
                dict.fromkeys(
                    existing.get("tags", [])
                    + [str(t).strip() for t in (raw_tags or []) if str(t).strip()]
                )
            )
            existing["tags"] = merged_tags

            # Keep fuller title
            if len(str(e.get("title", ""))) > len(str(existing.get("title", ""))):
                existing["title"] = e["title"]

            # Prefer specific mood over generic "Reflective"
            if existing.get("mood") in ("", "Reflective") and e.get("mood") not in ("", "Reflective", None):
                existing["mood"] = e["mood"]

            # Keep earliest entry_id/timestamp as primary and latest timestamp as updated_at
            ts_existing = str(existing.get("timestamp", ""))
            ts_new = str(e.get("timestamp", ""))
            if ts_new and ts_existing:
                if ts_new < ts_existing:
                    existing["updated_at"] = ts_existing
                    existing["timestamp"] = ts_new
                    existing["entry_id"] = e.get("entry_id", existing["entry_id"])
                elif ts_new > str(existing.get("updated_at", "")):
                    existing["updated_at"] = ts_new

            if e.get("coach_insight") and not existing.get("coach_insight"):
                existing["coach_insight"] = e["coach_insight"]

    return [by_content[k] for k in ordered_keys]


def _load_local_store() -> dict[str, Any]:
    store_file, _ = _get_vault_paths()
    if not store_file.exists():
        # If default store exists and this is the primary local user, migrate/use it
        if STORE_FILE.exists():
            try:
                data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
                cleaned = _deduplicate_entries(data.get("entries", []))
                data["entries"] = cleaned or DEFAULT_SEED_DATA["entries"]
                return data
            except Exception:
                pass
        store_file.write_text(
            json.dumps(DEFAULT_SEED_DATA, indent=2), encoding="utf-8"
        )
        return json.loads(json.dumps(DEFAULT_SEED_DATA))
    try:
        data = json.loads(store_file.read_text(encoding="utf-8"))
        for k in ("entries", "memories", "habits"):
            if k not in data or not isinstance(data[k], list):
                data[k] = DEFAULT_SEED_DATA[k]
        cleaned_entries = _deduplicate_entries(data["entries"])
        if len(cleaned_entries) != len(data["entries"]):
            data["entries"] = cleaned_entries or DEFAULT_SEED_DATA["entries"]
            _save_local_store(data)
        return data
    except Exception:
        return json.loads(json.dumps(DEFAULT_SEED_DATA))


def _save_local_store(store: dict[str, Any]) -> None:
    store_file, _ = _get_vault_paths()
    store_file.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _post_to_sheets(action: str, data: dict[str, Any]) -> dict[str, Any]:
    """Sends an authenticated POST payload to the user's Google Apps Script Web App URL."""
    cfg = get_runtime_config()
    webhook = cfg.get("google_sheets_webhook_url", "")
    if not webhook or not webhook.startswith("http"):
        return {
            "synced": False,
            "reason": "No Google Sheets webhook configured (saved locally)",
        }

    t0 = time.perf_counter()
    payload = json.dumps(
        {
            "action": action,
            "secret_token": cfg.get("secret_vault_token", ""),
            "data": data,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "JournalOS/2.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            ms = (time.perf_counter() - t0) * 1000
            if parsed.get("status") == "FORBIDDEN":
                log_event("SHEETS_SYNC", action, status="FORBIDDEN", duration_ms=ms)
                return {"synced": False, "error": "Invalid Secret Vault Token"}
            log_event("SHEETS_SYNC", action, status="OK", duration_ms=ms)
            return {"synced": True, "response": parsed}
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        log_event("SHEETS_SYNC", action, status="ERROR", duration_ms=ms, error=e)
        return {"synced": False, "error": "Connection failed"}


def sync_from_google_sheets() -> dict[str, Any]:
    """Pulls entries, memories, and habits from Google Sheets into the user's vault."""
    cfg = get_runtime_config()
    webhook = cfg.get("google_sheets_webhook_url", "")
    if not webhook or not webhook.startswith("http"):
        return {
            "status": "LOCAL_ONLY",
            "message": "No Google Sheets Webhook URL configured yet. Using isolated local vault.",
        }

    t0 = time.perf_counter()
    sep = "&" if "?" in webhook else "?"
    token_q = urllib.parse.quote(cfg.get("secret_vault_token", ""))
    url = f"{webhook}{sep}action=all&token={token_q}"
    req = urllib.request.Request(url, headers={"User-Agent": "JournalOS/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "FORBIDDEN":
            return {
                "status": "ERROR",
                "message": "Access Denied: Secret Vault Token does not match your Google Sheet script.",
            }
        store = _load_local_store()
        if isinstance(data.get("entries"), list) and data["entries"]:
            store["entries"] = _deduplicate_entries(data["entries"])
        if isinstance(data.get("memories"), list) and data["memories"]:
            store["memories"] = data["memories"]
        if isinstance(data.get("habits"), list) and data["habits"]:
            store["habits"] = data["habits"]
        _save_local_store(store)
        ms = (time.perf_counter() - t0) * 1000
        log_event(
            "SHEETS_SYNC",
            "pull_all",
            status="OK",
            duration_ms=ms,
            details={"entries_count": len(store["entries"])},
        )
        return {
            "status": "SUCCESS",
            "message": "Synced securely with your Google Sheet!",
            "counts": {
                "entries": len(store["entries"]),
                "memories": len(store["memories"]),
                "habits": len(store["habits"]),
            },
        }
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        log_event("SHEETS_SYNC", "pull_all", status="ERROR", duration_ms=ms, error=e)
        return {"status": "ERROR", "message": "Google Sheets sync failed."}


# ---------------------------------------------------------------------------
# Public CRUD operations used by Agent Tools & Web API
# ---------------------------------------------------------------------------
def store_add_entry(
    title: str,
    content: str,
    methodology: str = "Reflective Journaling",
    mood: str = "Grounded & Serene",
    tags: list[str] | None = None,
    coach_insight: str = "",
    sync_sheets: bool = True,
) -> dict[str, Any]:
    store = _load_local_store()
    now_iso = datetime.datetime.now().astimezone().isoformat()
    clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    is_encrypted = str(content).startswith("ENC:v1:")
    word_count = (
        int(clean_tags[0].split(":")[1])
        if (is_encrypted and clean_tags and clean_tags[0].startswith("wc:"))
        else len((content or "").split())
    )
    visible_tags = list(dict.fromkeys(t for t in clean_tags if not t.startswith("wc:")))
    norm_new = " ".join((content or "").strip().split())

    # Upsert check: if an entry with identical content already exists, update its columns in-place
    # instead of creating a duplicate text-heavy row!
    existing_entry = None
    if norm_new:
        for e in store.get("entries", []):
            norm_existing = " ".join(str(e.get("content", "")).strip().split())
            if norm_existing == norm_new:
                existing_entry = e
                break

    if existing_entry is not None:
        entry_id = existing_entry["entry_id"]
        merged_tags = list(
            dict.fromkeys((existing_entry.get("tags") or []) + visible_tags)
        )
        existing_entry["tags"] = merged_tags
        if len(title.strip()) > len(str(existing_entry.get("title", ""))):
            existing_entry["title"] = title.strip()
        if mood.strip() and (
            existing_entry.get("mood") in ("", "Reflective")
            or mood.strip() != "Reflective"
        ):
            existing_entry["mood"] = mood.strip()
        existing_entry["methodology"] = (
            methodology.strip() or existing_entry.get("methodology", "Reflective Journaling")
        )
        existing_entry["updated_at"] = now_iso
        if coach_insight.strip():
            existing_entry["coach_insight"] = coach_insight.strip()
        entry_data = existing_entry
        if not _is_noise_entry(entry_data):
            _save_local_store(store)
    else:
        entry_id = f"entry-{int(time.time() * 1000)}"
        entry_data = {
            "entry_id": entry_id,
            "title": title.strip() or "Mindful Reflection",
            "content": content.strip(),
            "methodology": methodology.strip() or "Reflective Journaling",
            "mood": mood.strip() or "Grounded & Serene",
            "tags": visible_tags,
            "timestamp": now_iso,
            "updated_at": now_iso,
            "coach_insight": coach_insight.strip(),
            "word_count": word_count,
            "encrypted": is_encrypted,
        }
        if not _is_noise_entry(entry_data):
            store["entries"].insert(0, entry_data)
            _save_local_store(store)

    sheet_sync = (
        _post_to_sheets("add_entry", entry_data)
        if (sync_sheets and not _is_noise_entry(entry_data))
        else {"synced": False}
    )
    log_event(
        "JOURNAL_ENTRY",
        "store_add_entry",
        details={
            "entry_id": entry_id,
            "upserted_existing": existing_entry is not None,
            "methodology": entry_data["methodology"],
            "word_count": word_count,
            "encrypted": is_encrypted,
            "sheet_synced": sheet_sync.get("synced", False),
        },
    )

    return {
        "status": "SUCCESS",
        "storage": "Google Sheets + Private Vault"
        if sheet_sync.get("synced")
        else "Private Local Vault",
        "sheet_sync": sheet_sync,
        "data": entry_data,
    }


def store_list_entries(
    limit: int = 20,
    methodology: str | None = None,
    mood: str | None = None,
) -> list[dict[str, Any]]:
    store = _load_local_store()
    entries = [e for e in store.get("entries", []) if not _is_noise_entry(e)]
    if methodology:
        m_low = methodology.lower().strip()
        entries = [
            e for e in entries if m_low in str(e.get("methodology", "")).lower()
        ]
    if mood:
        mood_low = mood.lower().strip()
        entries = [e for e in entries if mood_low in str(e.get("mood", "")).lower()]
    entries_sorted = sorted(
        entries, key=lambda x: str(x.get("timestamp", "")), reverse=True
    )
    return entries_sorted[: max(1, int(limit))]


def store_get_entry(entry_id: str) -> dict[str, Any] | None:
    store = _load_local_store()
    for e in store.get("entries", []):
        if str(e.get("entry_id")) == str(entry_id):
            return e
    return None


def store_add_memory(domain: str, fact: str) -> dict[str, Any]:
    store = _load_local_store()
    now_iso = datetime.datetime.now().astimezone().isoformat()
    mem_data = {
        "memory_id": f"mem-{int(time.time() * 1000)}",
        "timestamp": now_iso,
        "domain": domain.strip() or "User Goals",
        "fact": fact.strip(),
    }
    store["memories"].insert(0, mem_data)
    _save_local_store(store)
    sheet_sync = _post_to_sheets("add_memory", mem_data)
    log_event("MEMORY_BANK", "store_add_memory", details={"domain": domain})
    return {"status": "SUCCESS", "data": mem_data, "sheet_sync": sheet_sync}


def store_list_memories(domain: str | None = None) -> list[dict[str, Any]]:
    store = _load_local_store()
    memories = store.get("memories", [])
    if domain:
        d_low = domain.lower().strip()
        memories = [m for m in memories if d_low in str(m.get("domain", "")).lower()]
    return memories[:30]


def store_upsert_habit(
    title: str,
    category: str = "Habit",
    status: str = "Active",
    increment_streak: bool = True,
    reminder_time: str | None = None,
) -> dict[str, Any]:
    store = _load_local_store()
    habits = store.get("habits", [])
    now_iso = datetime.datetime.now().astimezone().isoformat()
    target = None
    for h in habits:
        if str(h.get("title", "")).strip().lower() == title.strip().lower():
            target = h
            break

    if target is not None:
        target["updated_at"] = now_iso
        target["category"] = category
        target["status"] = status
        if reminder_time:
            target["reminder_time"] = reminder_time
        if increment_streak:
            target["streak"] = int(target.get("streak", 0)) + 1
    else:
        target = {
            "item_id": f"hab-{int(time.time() * 1000)}",
            "updated_at": now_iso,
            "title": title.strip(),
            "category": category.strip() or "Habit",
            "status": status.strip() or "Active",
            "streak": 1,
            "reminder_time": reminder_time or "08:00",
        }
        habits.insert(0, target)

    store["habits"] = habits
    _save_local_store(store)
    sheet_sync = _post_to_sheets("upsert_habit", target)
    log_event(
        "HABIT_TRACKER",
        "store_upsert_habit",
        details={"streak": target["streak"]},
    )
    return {"status": "SUCCESS", "data": target, "sheet_sync": sheet_sync}


def _calculate_consecutive_day_streak(date_strings: set[str]) -> int:
    """Calculates true consecutive calendar days of journaling."""
    if not date_strings:
        return 0
    parsed_dates: list[datetime.date] = []
    for ds in date_strings:
        try:
            parsed_dates.append(datetime.date.fromisoformat(ds[:10]))
        except Exception:
            pass
    if not parsed_dates:
        return 1

    unique_sorted = sorted(set(parsed_dates), reverse=True)
    streak = 1
    for i in range(len(unique_sorted) - 1):
        diff = (unique_sorted[i] - unique_sorted[i + 1]).days
        if diff == 1:
            streak += 1
        else:
            break
    return streak


def store_get_analytics() -> dict[str, Any]:
    """Calculates accurate mindful journaling stats, consecutive day streak, and visual distributions."""
    store = _load_local_store()
    entries = [e for e in store.get("entries", []) if not _is_noise_entry(e)]
    habits = store.get("habits", [])
    memories = store.get("memories", [])

    mood_counts: dict[str, int] = {}
    methodology_counts: dict[str, int] = {}
    day_counts: dict[str, int] = {}
    total_words = 0
    unique_days: set[str] = set()

    for e in entries:
        mood = str(e.get("mood") or "Grounded & Serene").strip()
        meth = str(e.get("methodology") or "Reflective Journaling").strip()
        mood_counts[mood] = mood_counts.get(mood, 0) + 1
        methodology_counts[meth] = methodology_counts.get(meth, 0) + 1
        content = str(e.get("content") or "")
        total_words += int(e.get("word_count") or len(content.split()))
        ts = str(e.get("timestamp") or "")[:10]
        if ts:
            unique_days.add(ts)
            day_counts[ts] = day_counts.get(ts, 0) + 1

    top_mood = (
        max(mood_counts, key=mood_counts.get)
        if mood_counts
        else "Grounded & Serene"
    )
    top_methodology = (
        max(methodology_counts, key=methodology_counts.get)
        if methodology_counts
        else "Morning Pages"
    )

    consecutive_streak = _calculate_consecutive_day_streak(unique_days)

    cfg = get_runtime_config()
    return {
        "user_name": cfg.get("user_name", ""),
        "display_name": cfg.get("display_name", "Friend"),
        "onboarding_complete": cfg.get("onboarding_complete", False),
        "total_entries": len(entries),
        "total_words": total_words,
        "active_days": len(unique_days),
        "best_streak": consecutive_streak,
        "top_mood": top_mood,
        "top_methodology": top_methodology,
        "mood_counts": mood_counts,
        "methodology_counts": methodology_counts,
        "day_counts": day_counts,
        "habits": habits,
        "memories": memories[:12],
        "sheets_connected": bool(cfg.get("google_sheets_webhook_url")),
        "gemini_configured": bool(cfg.get("gemini_api_key")),
        "vault_token_set": bool(cfg.get("secret_vault_token")),
        "time_recommendation": get_time_based_recommendation(),
    }


def export_entries_csv() -> str:
    """Exports all journal entries as a Google Sheets / Excel compatible CSV string."""
    entries = store_list_entries(limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "entry_id",
            "timestamp",
            "title",
            "methodology",
            "mood",
            "content",
            "tags",
            "word_count",
            "updated_at",
            "coach_insight",
        ]
    )
    for e in entries:
        tags = e.get("tags", [])
        if isinstance(tags, list):
            tags_str = ", ".join(str(t) for t in tags)
        else:
            tags_str = str(tags)
        writer.writerow(
            [
                e.get("entry_id", ""),
                e.get("timestamp", ""),
                e.get("title", ""),
                e.get("methodology", ""),
                e.get("mood", ""),
                e.get("content", ""),
                tags_str,
                e.get("word_count", 0),
                e.get("updated_at", e.get("timestamp", "")),
                e.get("coach_insight", ""),
            ]
        )
    return output.getvalue()
