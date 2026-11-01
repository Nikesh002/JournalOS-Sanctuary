"""Unified Standalone Web Application Server for JournalOS (Free Tier Edition).

Addresses all user feedback:
1. Companion Counsellor & Life Coach persona that calls the user by name
2. Rate-limit-free Animated Moodscape Studio (`/api/moodscape.svg`)
3. Rich "Guide Me in Chat" cards with `[Why this works, Reflection Question, Suggested Structure]`,
   Question-Meaning animated visual, and interactive Nuanced Emotion Vocabulary selectors
4. Rich GUI Dashboard response for "My Entries & Trends"
5. Timezone & Time-of-Day Smart Methodology Recommendation (`/api/recommendation`)
6. Structured Debug Logging & Live Diagnostics (`/api/logs`)
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_env_file(ROOT_DIR / ".env")

from app.firestore_tools import (  # noqa: E402
    fetch_inspirational_quote,
    generate_journal_image,
    generate_reflective_prompt,
    render_animated_moodscape_svg,
)
from app.logger_utils import clear_all_logs, get_recent_logs, log_event  # noqa: E402
from app.sheets_storage import (  # noqa: E402
    EMOTIONS_CATALOG,
    METHODOLOGIES_CATALOG,
    _mask_url,
    export_entries_csv,
    get_runtime_config,
    get_time_based_recommendation,
    purge_vault_data,
    save_runtime_config,
    set_current_vault_id,
    store_add_entry,
    store_add_memory,
    store_get_analytics,
    store_list_entries,
    store_upsert_habit,
    sync_from_google_sheets,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _build_a2ui_card(
    title: str,
    subtitle: str,
    body_lines: list[str],
    footer: str = "",
    image_url: str | None = None,
) -> list[dict[str, Any]]:
    """Constructs a clean A2UI v0.8 Card surface."""
    children_ids = ["title_txt", "sub_txt"]
    components: list[dict[str, Any]] = [
        {
            "id": "title_txt",
            "component": {
                "Text": {"text": {"literalString": title}, "usageHint": "h2"}
            },
        },
        {
            "id": "sub_txt",
            "component": {
                "Text": {"text": {"literalString": subtitle}, "usageHint": "caption"}
            },
        },
    ]

    for idx, line in enumerate(body_lines):
        if not line:
            continue
        cid = f"body_{idx}"
        children_ids.append(cid)
        components.append(
            {
                "id": cid,
                "component": {
                    "Text": {"text": {"literalString": line}, "usageHint": "body"}
                },
            }
        )

    if image_url and (image_url.startswith("http") or image_url.startswith("/")):
        children_ids.append("card_img")
        components.append(
            {
                "id": "card_img",
                "component": {
                    "Image": {
                        "url": {"literalString": image_url},
                        "alt": {"literalString": title},
                    }
                },
            }
        )

    if footer:
        children_ids.append("footer_txt")
        components.append(
            {
                "id": "footer_txt",
                "component": {
                    "Text": {"text": {"literalString": footer}, "usageHint": "caption"}
                },
            }
        )

    components.extend(
        [
            {
                "id": "main_col",
                "component": {"Column": {"children": {"explicitList": children_ids}}},
            },
            {"id": "root", "component": {"Card": {"child": "main_col"}}},
        ]
    )

    return [
        {"beginRendering": {"surfaceId": "default", "root": "root"}},
        {"surfaceUpdate": {"surfaceId": "default", "components": components}},
    ]


def _is_system_prompt_command(message: str) -> bool:
    """Checks if a chat message is a UI quick-action prompt rather than a personal journal entry."""
    m = message.lower().strip()
    prefixes = (
        "guide me through",
        "show my recent",
        "show my entries",
        "generate a visual moodscape",
        "generate a serene visual moodscape",
        "generate a moodscape",
        "give me an inspirational quote",
        "start guided reflection",
    )
    return any(m.startswith(p) for p in prefixes)


def _infer_mood_and_tags(
    message: str,
    active_methodology: str,
    selected_emotion: str = "",
    encrypted_content: str = "",
) -> tuple[str, str, str, list[str]]:
    """Computes consistent (mood, stored_title, stored_body, tags_list) for a journal reflection."""
    msg_low = message.lower().strip()
    mood = selected_emotion or "Grounded & Serene"
    if not selected_emotion:
        for m_kw, m_val in [
            ("grateful", "Deeply Grateful"),
            ("thankful", "Deeply Grateful"),
            ("anxious", "Restless & Anxious"),
            ("stressed", "Mentally Overloaded"),
            ("overwhelmed", "Mentally Overloaded"),
            ("excited", "Inspired & Driven"),
            ("energized", "Inspired & Driven"),
            ("race", "Inspired & Driven"),
            ("build", "Focused & Intentional"),
            ("tired", "Tired & Seeking Rest"),
            ("focus", "Focused & Intentional"),
        ]:
            if m_kw in msg_low:
                mood = m_val
                break

    first_line = message.splitlines()[0].split(".")[0][:62].strip()
    title = first_line if len(first_line) >= 6 else f"{active_methodology} Reflection"
    stored_title = f"🔒 {active_methodology} Reflection" if encrypted_content else title
    stored_body = encrypted_content if encrypted_content else message
    tags_list = list(
        dict.fromkeys([active_methodology.lower().split()[0], mood.lower().split()[0]])
    )
    if encrypted_content:
        tags_list.insert(0, f"wc:{len(message.split())}")
    return mood, stored_title, stored_body, tags_list


def _should_log_reflection(message: str) -> bool:
    """Determines whether a chat message is a personal journal reflection that should be saved."""
    if _is_system_prompt_command(message):
        return False
    msg_low = message.lower().strip()
    return (
        any(
            w in msg_low
            for w in (
                "what is on my mind",
                "present body scan",
                "3 specific moments",
                "right now my mind",
                "grateful",
                "today i",
                "i feel",
                "feeling ",
                "my goal",
            )
        )
        or len(message.split()) >= 10
    )


def _smart_mindful_coach_fallback(
    message: str,
    active_methodology: str = "Reflective Journaling",
    selected_emotion: str = "",
    encrypted_content: str = "",
) -> list[dict[str, Any]]:
    """Empathetic & Non-judgmental Companion Counsellor & Life Coach engine."""
    cfg = get_runtime_config()
    user_name = cfg.get("display_name") or "Friend"
    msg_low = message.lower().strip()

    # 1. Moodscape / Visual Art Generation Request
    if any(
        w in msg_low
        for w in ("moodscape", "image", "picture", "visual", "art", "draw", "paint")
    ):
        res = json.loads(generate_journal_image(prompt=message))
        url = res.get("public_url", "")
        card = _build_a2ui_card(
            title=f"🎨 Mindful Visual Moodscape for {user_name}",
            subtitle=f"Framework: {active_methodology} · Animated Breathing Sanctuary",
            body_lines=[
                f"{user_name}, I am right here with you. Take three slow, grounding breaths as you watch the gentle rhythm of this moodscape.",
                "Notice what colors, movement, or feelings draw your attention first—and ask yourself what they mirror in your inner world today.",
            ],
            footer="✨ Instant Rate-Limit-Free Animated Moodscape · JournalOS Sanctuary",
            image_url=url,
        )
        return [{"kind": "a2ui", "data": m} for m in card]

    # 2. Inspirational Quote & Reflection Spark
    if any(w in msg_low for w in ("quote", "inspire", "inspiration", "wisdom")):
        q_data = json.loads(fetch_inspirational_quote())
        p_data = json.loads(generate_reflective_prompt(active_methodology))
        card = _build_a2ui_card(
            title=f"💡 Mindful Spark for {user_name}",
            subtitle=f"{p_data.get('category', active_methodology)} · Wisdom by {q_data.get('author', 'Unknown')}",
            body_lines=[
                f'“{q_data.get("quote", "")}” — {q_data.get("author", "")}',
                f"🤝 Counsellor Note: {user_name}, let this thought sit gently with you for a moment.",
                f"💬 Reflection Question: {p_data.get('prompt', '')}",
            ],
            footer="Click any emotion pill below or use Shift+Enter in the chat box to write multi-line reflections.",
        )
        return [{"kind": "a2ui", "data": m} for m in card]

    # 3. "My Entries & Trends" — Rich Visual GUI Dashboard Card (Feedback Item #8)
    if any(
        w in msg_low
        for w in (
            "list",
            "show",
            "entries",
            "history",
            "recent",
            "trend",
            "analytics",
            "stats",
        )
    ):
        stats = store_get_analytics()
        entries = store_list_entries(limit=6)
        card = _build_a2ui_card(
            title=f"📊 {user_name}'s Mindful Journaling Chronicle & Trends",
            subtitle=f"🟢 {'Connected to Google Sheets' if stats.get('sheets_connected') else 'Local Sanctuary Store'} · 🔥 {stats['best_streak']}-Day Active Streak",
            body_lines=[
                f"🤝 {user_name}, here is a clear look at your journey so far—every reflection you write is a step toward deeper self-understanding.",
            ],
            footer="Click 'Write & Entries' or 'Insights & Habits' in the top bar for full analytics & Google Calendar reminders.",
        )
        out = [{"kind": "a2ui", "data": m} for m in card]
        out.append(
            {
                "kind": "entries_gui",
                "data": {
                    "user_name": user_name,
                    "stats": stats,
                    "entries": entries,
                },
            }
        )
        return out

    # 4. Log / Save a Real Personal Reflection Entry (when not a system command)
    if _should_log_reflection(message):
        mood, stored_title, stored_body, tags_list = _infer_mood_and_tags(
            message=message,
            active_methodology=active_methodology,
            selected_emotion=selected_emotion,
            encrypted_content=encrypted_content,
        )
        coach_note = "Notice the intention beneath your words—when you name what truly matters to you, you turn pressure into purposeful clarity."
        saved = store_add_entry(
            title=stored_title,
            content=stored_body,
            methodology=active_methodology,
            mood=mood,
            tags=tags_list,
            coach_insight=coach_note,
        )
        p_data = json.loads(generate_reflective_prompt(active_methodology))
        card = _build_a2ui_card(
            title=f"🤝 I Hear You, {user_name} — Reflection Safely Logged",
            subtitle=f"{active_methodology} · Emotion: {mood} · {saved['storage']}",
            body_lines=[
                f"Thank you for sharing this openly with me, {user_name}. I have recorded your {saved['data']['word_count']}-word reflection.",
                f"💡 Companion Counsellor Reflection: {coach_note}",
                f"🌱 Gentle Next Question ({active_methodology}): {p_data.get('prompt')}",
            ],
            footer="I am right here with you whenever you want to unpack this further.",
        )
        return [{"kind": "a2ui", "data": m} for m in card]

    # 5. Default / "Guide Me in Chat": Rich 3-Part Guide Card + Animated Question Visual + Emotion Picker (Feedback Items #3, #5, #6)
    p_data = json.loads(generate_reflective_prompt(active_methodology))
    cat_name = p_data.get("category", active_methodology)
    card = _build_a2ui_card(
        title=f"🧭 {cat_name} Guide — With You, {user_name}",
        subtitle=f"{p_data.get('pillar', '')} · {p_data.get('time_label', '')}",
        body_lines=[
            f"🤝 Hello {user_name}, take a gentle breath. As your companion coach, I'm here with you—no rush, no judgment.",
            f"✨ Why this works: {p_data.get('tagline', '')}",
            f"💬 Reflection Question: {p_data.get('prompt', '')}",
            f"💡 Meaning of this Question: {p_data.get('question_meaning', '')}",
            f"📝 Suggested Structure:\n{p_data.get('template', '')}",
        ],
        footer="Select how you feel below to pre-fill the structure into your chat box, or use Shift+Enter for multi-line writing.",
        image_url=p_data.get("visual_url"),
    )
    out = [{"kind": "a2ui", "data": m} for m in card]
    out.append(
        {
            "kind": "guide_interactive",
            "data": {
                "user_name": user_name,
                "methodology": cat_name,
                "prompt": p_data.get("prompt", ""),
                "question_meaning": p_data.get("question_meaning", ""),
                "template": p_data.get("template", ""),
                "emotions": EMOTIONS_CATALOG,
            },
        }
    )
    return out


def _call_gemini_rest_api(
    api_key: str,
    message: str,
    active_methodology: str,
    selected_emotion: str = "",
    encrypted_content: str = "",
) -> list[dict[str, Any]] | None:
    """Calls Google AI Studio's free Gemini Flash REST API directly via standard library."""
    # For explicit UI views like "Show my recent entries" or "Guide me through", use the structured GUI cards directly
    if _is_system_prompt_command(message):
        return None

    cfg = get_runtime_config()
    user_name = cfg.get("display_name") or "Friend"
    stats = store_get_analytics()
    recent_entries = store_list_entries(limit=3)
    memories = stats.get("memories", [])[:5]

    image_url = None
    if any(
        w in message.lower()
        for w in ("moodscape", "image", "picture", "visual", "art")
    ):
        img_res = json.loads(generate_journal_image(prompt=message))
        image_url = img_res.get("public_url")

    sys_prompt = (
        f"You are JournalOS, a highly professional, deeply empathetic & non-judgmental companion counsellor and mindful life coach.\n"
        f"Your client's name is {user_name}. Always address {user_name} warmly by name and stand beside them as a supportive, wise companion in any situation.\n"
        f"Active Methodology: {active_methodology}. Selected Emotion: {selected_emotion or 'Not specified'}.\n"
        f"Recent entries context: {json.dumps(recent_entries)}\n"
        f"Remembered insights: {json.dumps(memories)}\n"
        "Respond with a JSON object containing:\n"
        '  "title": string (warm heading addressing the user by name),\n'
        '  "subtitle": string (methodology & emotional tone),\n'
        '  "paragraphs": array of 3 thoughtful strings: [1] empathetic validation of what they shared, [2] deeper insight or pattern noticed, [3] one gentle follow-up reflection question,\n'
        '  "memory_to_save": optional object {"domain": string, "fact": string} if the user shared a personal goal, habit, or preference.\n'
        "Return ONLY valid JSON."
    )

    payload = {
        "system_instruction": {"parts": [{"text": sys_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }

    t0 = time.perf_counter()
    raw = None
    used_model = "gemini-2.5-flash"
    last_err: Exception | None = None
    for candidate_model in ("gemini-2.5-flash", "gemini-2.0-flash"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent?key={urllib.parse.quote(api_key)}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                used_model = candidate_model
                break
        except urllib.error.HTTPError as he:
            last_err = he
            if he.code == 404:
                continue
            break
        except Exception as e:
            last_err = e
            break

    if raw is None:
        ms = (time.perf_counter() - t0) * 1000
        log_event("GEMINI_API", "generateContent", status="FALLBACK", duration_ms=ms, error=last_err)
        return None

    try:
        ms = (time.perf_counter() - t0) * 1000
        cand_text = (
            raw.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if not cand_text:
            return None
        parsed = json.loads(cand_text)
        if isinstance(parsed.get("memory_to_save"), dict):
            mem = parsed["memory_to_save"]
            if mem.get("fact"):
                store_add_memory(
                    domain=mem.get("domain", "User Goals"), fact=mem["fact"]
                )

        paragraphs = parsed.get("paragraphs") or []
        if isinstance(paragraphs, str):
            paragraphs = [paragraphs]

        # Save the entry ONLY AFTER Gemini succeeds, storing coach_insight in the extra column of the SAME single row!
        auto_saved_note = ""
        if _should_log_reflection(message):
            mood, stored_title, stored_body, tags_list = _infer_mood_and_tags(
                message=message,
                active_methodology=active_methodology,
                selected_emotion=selected_emotion,
                encrypted_content=encrypted_content,
            )
            coach_insight_str = str(paragraphs[1] if len(paragraphs) > 1 else (paragraphs[0] if paragraphs else "")).strip()
            saved = store_add_entry(
                title=stored_title,
                content=stored_body,
                methodology=active_methodology,
                mood=mood,
                tags=tags_list,
                coach_insight=coach_insight_str,
            )
            auto_saved_note = f"Logged to {saved['storage']}"

        footer = f"🤝 Companion Coach for {user_name} · Powered by {used_model}"
        if auto_saved_note:
            footer = f"✅ {auto_saved_note} · {footer}"

        log_event("GEMINI_API", "generateContent", status="OK", duration_ms=ms)
        card = _build_a2ui_card(
            title=parsed.get("title") or f"🌿 With You, {user_name} — {active_methodology}",
            subtitle=parsed.get("subtitle") or active_methodology,
            body_lines=paragraphs,
            footer=footer,
            image_url=image_url,
        )
        return [{"kind": "a2ui", "data": m} for m in card]
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        log_event("GEMINI_API", "generateContent", status="FALLBACK", duration_ms=ms, error=e)
        return None


def handle_chat_message(
    message: str,
    user_id: str = "web-user",
    active_methodology: str = "Reflective Journaling",
    selected_emotion: str = "",
    encrypted_content: str = "",
) -> list[dict[str, Any]]:
    t0 = time.perf_counter()
    cfg = get_runtime_config()
    api_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    res = None
    if api_key:
        res = _call_gemini_rest_api(
            api_key,
            message,
            active_methodology,
            selected_emotion,
            encrypted_content=encrypted_content,
        )
    if not res:
        res = _smart_mindful_coach_fallback(
            message,
            active_methodology,
            selected_emotion,
            encrypted_content=encrypted_content,
        )
    ms = (time.perf_counter() - t0) * 1000
    log_event(
        "CHAT",
        "handle_chat_message",
        duration_ms=ms,
        details={
            "methodology": active_methodology,
            "emotion": selected_emotion,
            "msg_preview": message[:60],
        },
    )
    return res


def _build_dashboard_payload(
    methodology: str | None = None, mood: str | None = None
) -> dict[str, Any]:
    analytics = store_get_analytics()
    entries = store_list_entries(limit=25, methodology=methodology, mood=mood)
    cfg = get_runtime_config()
    return {
        "analytics": analytics,
        "entries": entries,
        "emotions": EMOTIONS_CATALOG,
        "config": {
            "user_name": cfg.get("user_name", ""),
            "display_name": cfg.get("display_name", "Friend"),
            "onboarding_complete": cfg.get("onboarding_complete", False),
            "sheets_connected": bool(cfg.get("google_sheets_webhook_url")),
            "google_sheets_webhook_masked": _mask_url(
                cfg.get("google_sheets_webhook_url", "")
            ),
            "gemini_configured": bool(cfg.get("gemini_api_key")),
            "vault_token_set": bool(cfg.get("secret_vault_token")),
        },
    }


# ---------------------------------------------------------------------------
# Mode 1: FastAPI Application (when `fastapi` is installed)
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="JournalOS - Mindful Journaling Web App")

    @app.middleware("http")
    async def vault_and_security_middleware(request: Request, call_next):
        set_current_vault_id(request.headers.get("X-JournalOS-Vault-ID"))
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.get("/favicon.ico")
    @app.get("/favicon.svg")
    @app.get("/logo.svg")
    async def api_logo_svg():
        logo_file = STATIC_DIR / "logo.svg"
        svg_text = logo_file.read_text(encoding="utf-8") if logo_file.exists() else ""
        return Response(content=svg_text, media_type="image/svg+xml")

    @app.get("/api/methodologies")
    async def api_methodologies():
        return JSONResponse(
            {
                "methodologies": METHODOLOGIES_CATALOG,
                "emotions": EMOTIONS_CATALOG,
                "time_recommendation": get_time_based_recommendation(),
            }
        )

    @app.get("/api/recommendation")
    async def api_recommendation(hour: int | None = None, tz: str = ""):
        return JSONResponse(get_time_based_recommendation(local_hour=hour, timezone_name=tz))

    @app.get("/api/moodscape.svg")
    async def api_moodscape_svg(
        prompt: str = "Serene Mindful Sanctuary",
        theme: str = "auto",
        subtitle: str = "Breathe in clarity · Breathe out tension",
    ):
        svg = render_animated_moodscape_svg(prompt=prompt, theme=theme, subtitle=subtitle)
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/api/dashboard")
    async def api_dashboard(
        methodology: str | None = None, mood: str | None = None
    ):
        return JSONResponse(_build_dashboard_payload(methodology=methodology, mood=mood))

    @app.get("/api/logs")
    async def api_logs(limit: int = 80, category: str | None = None):
        return JSONResponse(get_recent_logs(limit=limit, category=category))

    @app.post("/api/logs/clear")
    async def api_logs_clear():
        return JSONResponse(clear_all_logs())

    @app.post("/api/privacy/purge")
    async def api_privacy_purge():
        return JSONResponse(purge_vault_data())

    @app.post("/api/entries")
    async def api_create_entry(req: Request):
        body = await req.json()
        result = store_add_entry(
            title=body.get("title", "Mindful Reflection"),
            content=body.get("content", ""),
            methodology=body.get("methodology", "Reflective Journaling"),
            mood=body.get("mood", "Grounded & Serene"),
            tags=body.get("tags", []),
        )
        return JSONResponse(result)

    @app.post("/api/habits")
    async def api_upsert_habit(req: Request):
        body = await req.json()
        result = store_upsert_habit(
            title=body.get("title", "Daily Journaling"),
            category=body.get("category", "Habit"),
            status=body.get("status", "Active"),
            increment_streak=bool(body.get("increment_streak", True)),
            reminder_time=body.get("reminder_time"),
        )
        return JSONResponse(result)

    @app.post("/api/config")
    async def api_save_config(req: Request):
        body = await req.json()
        status = save_runtime_config(
            google_sheets_webhook_url=body.get("google_sheets_webhook_url"),
            gemini_api_key=body.get("gemini_api_key"),
            user_name=body.get("user_name"),
            secret_vault_token=body.get("secret_vault_token"),
        )
        sync_res = (
            sync_from_google_sheets() if status.get("sheets_connected") else None
        )
        return JSONResponse({"status": "SUCCESS", "config": status, "sync": sync_res})

    @app.post("/api/sync")
    async def api_sync_sheets():
        return JSONResponse(sync_from_google_sheets())

    @app.get("/api/export.csv")
    async def api_export_csv():
        csv_data = export_entries_csv()
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="journalos_entries.csv"'
            },
        )

    @app.get("/api/apps-script")
    async def api_apps_script():
        script_path = ROOT_DIR / "scripts" / "google_apps_script.gs"
        if script_path.exists():
            return PlainTextResponse(script_path.read_text(encoding="utf-8"))
        return PlainTextResponse("// Script not found")

    @app.post("/chat")
    async def chat(req: Request):
        body = await req.json()
        parts = handle_chat_message(
            message=body.get("message", ""),
            user_id=body.get("user_id") or "web-user",
            active_methodology=body.get("methodology") or "Reflective Journaling",
            selected_emotion=body.get("emotion") or "",
            encrypted_content=body.get("encrypted_content") or "",
        )
        return JSONResponse({"parts": parts})

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    _HAS_FASTAPI = True
except ImportError:
    app = None
    _HAS_FASTAPI = False


# ---------------------------------------------------------------------------
# Mode 2: Zero-Dependency Standard Library HTTP Server
# ---------------------------------------------------------------------------
class JournalOSRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(
        self,
        text: str,
        content_type: str = "text/plain; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        raw = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self._send_security_headers()
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:
        set_current_vault_id(self.headers.get("X-JournalOS-Vault-ID"))
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/favicon.ico", "/favicon.svg", "/logo.svg"):
            logo_file = STATIC_DIR / "logo.svg"
            svg_text = logo_file.read_text(encoding="utf-8") if logo_file.exists() else ""
            self._send_text(svg_text, content_type="image/svg+xml; charset=utf-8")
            return

        if path == "/api/methodologies":
            self._send_json(
                {
                    "methodologies": METHODOLOGIES_CATALOG,
                    "emotions": EMOTIONS_CATALOG,
                    "time_recommendation": get_time_based_recommendation(),
                }
            )
            return

        if path == "/api/recommendation":
            hour_str = qs.get("hour", [None])[0]
            hour = int(hour_str) if hour_str is not None and hour_str.isdigit() else None
            tz = qs.get("tz", [""])[0]
            self._send_json(get_time_based_recommendation(local_hour=hour, timezone_name=tz))
            return

        if path == "/api/moodscape.svg":
            prompt = qs.get("prompt", ["Serene Mindful Sanctuary"])[0]
            theme = qs.get("theme", ["auto"])[0]
            subtitle = qs.get("subtitle", ["Breathe in clarity · Breathe out tension"])[0]
            svg = render_animated_moodscape_svg(
                prompt=prompt, theme=theme, subtitle=subtitle
            )
            self._send_text(svg, content_type="image/svg+xml; charset=utf-8")
            return

        if path == "/api/logs":
            limit = int(qs.get("limit", ["80"])[0])
            cat = qs.get("category", [None])[0]
            self._send_json(get_recent_logs(limit=limit, category=cat))
            return

        if path == "/api/dashboard":
            meth = qs.get("methodology", [None])[0]
            mood = qs.get("mood", [None])[0]
            self._send_json(_build_dashboard_payload(methodology=meth, mood=mood))
            return

        if path == "/api/export.csv":
            csv_data = export_entries_csv()
            self._send_text(
                csv_data,
                content_type="text/csv; charset=utf-8",
                extra_headers={
                    "Content-Disposition": 'attachment; filename="journalos_entries.csv"'
                },
            )
            return

        if path == "/api/apps-script":
            script_path = ROOT_DIR / "scripts" / "google_apps_script.gs"
            txt = (
                script_path.read_text(encoding="utf-8")
                if script_path.exists()
                else "// Script not found"
            )
            self._send_text(txt)
            return

        rel = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            target = STATIC_DIR / "index.html"

        mime, _ = mimetypes.guess_type(str(target))
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        set_current_vault_id(self.headers.get("X-JournalOS-Vault-ID"))
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        if path == "/api/logs/clear":
            self._send_json(clear_all_logs())
            return

        if path == "/api/privacy/purge":
            self._send_json(purge_vault_data())
            return

        if path == "/api/entries":
            res = store_add_entry(
                title=body.get("title", "Mindful Reflection"),
                content=body.get("content", ""),
                methodology=body.get("methodology", "Reflective Journaling"),
                mood=body.get("mood", "Grounded & Serene"),
                tags=body.get("tags", []),
            )
            self._send_json(res)
            return

        if path == "/api/habits":
            res = store_upsert_habit(
                title=body.get("title", "Daily Journaling"),
                category=body.get("category", "Habit"),
                status=body.get("status", "Active"),
                increment_streak=bool(body.get("increment_streak", True)),
                reminder_time=body.get("reminder_time"),
            )
            self._send_json(res)
            return

        if path == "/api/config":
            status = save_runtime_config(
                google_sheets_webhook_url=body.get("google_sheets_webhook_url"),
                gemini_api_key=body.get("gemini_api_key"),
                user_name=body.get("user_name"),
                secret_vault_token=body.get("secret_vault_token"),
            )
            sync_res = (
                sync_from_google_sheets() if status.get("sheets_connected") else None
            )
            self._send_json(
                {"status": "SUCCESS", "config": status, "sync": sync_res}
            )
            return

        if path == "/api/sync":
            self._send_json(sync_from_google_sheets())
            return

        if path == "/chat":
            parts = handle_chat_message(
                message=body.get("message", ""),
                user_id=body.get("user_id") or "web-user",
                active_methodology=body.get("methodology")
                or "Reflective Journaling",
                selected_emotion=body.get("emotion") or "",
                encrypted_content=body.get("encrypted_content") or "",
            )
            self._send_json({"parts": parts})
            return

        self._send_json({"error": "Not found"}, status=404)


def run_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    log_event("SERVER", "startup", details={"port": port, "fastapi": _HAS_FASTAPI})
    if _HAS_FASTAPI:
        try:
            import uvicorn

            print(
                f"🌿 JournalOS Web App running at http://localhost:{port} (FastAPI mode)"
            )
            uvicorn.run(app, host="0.0.0.0", port=port)
            return
        except ImportError:
            pass

    server = http.server.ThreadingHTTPServer(
        ("0.0.0.0", port), JournalOSRequestHandler
    )
    print(
        f"🌿 JournalOS Live Web App running at http://localhost:{port} (Zero-Dependency Mode)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    run_server()
