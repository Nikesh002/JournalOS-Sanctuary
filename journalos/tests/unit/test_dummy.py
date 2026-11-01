# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

"""Unit tests for JournalOS v2 — Security, Mental-Health Privacy, Vault Isolation & Moodscapes."""

import json
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.firestore_tools import (
    add_journal_entry,
    generate_journal_image,
    generate_reflective_prompt,
    get_journaling_analytics,
    list_journal_entries,
    log_habit_or_goal,
    render_animated_moodscape_svg,
    save_user_memory,
)
from app.logger_utils import get_recent_logs, log_event, redact_sensitive_details
from app.sheets_storage import (
    EMOTIONS_CATALOG,
    METHODOLOGIES_CATALOG,
    STORE_FILE,
    _calculate_consecutive_day_streak,
    _get_vault_paths,
    export_entries_csv,
    get_runtime_config,
    get_time_based_recommendation,
    purge_vault_data,
    save_runtime_config,
    set_current_vault_id,
    store_add_entry,
    store_list_entries,
)
from frontend.main import handle_chat_message


class TestJournalOSWebApp(unittest.TestCase):
    def setUp(self) -> None:
        set_current_vault_id("default")
        self._backup = (
            STORE_FILE.read_text(encoding="utf-8") if STORE_FILE.exists() else None
        )

    def tearDown(self) -> None:
        set_current_vault_id("default")
        if self._backup is not None:
            STORE_FILE.write_text(self._backup, encoding="utf-8")

    def test_19_methodologies_and_emotions_catalog(self) -> None:
        self.assertEqual(len(METHODOLOGIES_CATALOG), 19)
        self.assertGreaterEqual(len(EMOTIONS_CATALOG), 10)
        rec = get_time_based_recommendation(local_hour=7, timezone_name="Asia/Calcutta")
        self.assertEqual(rec["recommended_id"], "morning-pages")
        rec_eve = get_time_based_recommendation(
            local_hour=19, timezone_name="Asia/Calcutta"
        )
        self.assertEqual(rec_eve["recommended_id"], "gratitude-journaling")

    def test_single_day_streak_is_1_day(self) -> None:
        self.assertEqual(_calculate_consecutive_day_streak({"2026-11-01"}), 1)
        self.assertEqual(
            _calculate_consecutive_day_streak({"2026-11-01", "2026-10-31"}), 2
        )

    def test_entry_and_analytics_lifecycle(self) -> None:
        res = json.loads(
            add_journal_entry(
                title="Evening Reflection on AI Sanctuary",
                content="Today I focused on building a warm companion journaling app with clear emotional vocabulary.",
                methodology="Gratitude Journaling",
                mood="Deeply Grateful",
                tags=["gratitude", "sanctuary"],
            )
        )
        self.assertEqual(res["status"], "SUCCESS")

        entries = json.loads(list_journal_entries(limit=5))
        self.assertGreaterEqual(len(entries), 1)

        stats = json.loads(get_journaling_analytics())
        self.assertGreaterEqual(stats["total_entries"], 1)
        self.assertIn("Deeply Grateful", stats["mood_counts"])

    def test_prompts_habit_and_memory_tools(self) -> None:
        p = json.loads(generate_reflective_prompt("Mindfulness Journaling"))
        self.assertEqual(p["category"], "Mindfulness Journaling")
        self.assertIn("question_meaning", p)
        self.assertIn("visual_url", p)

        mem = json.loads(save_user_memory("User Goals", "Journal 10 minutes daily"))
        self.assertEqual(mem["status"], "SUCCESS")

        hab = json.loads(log_habit_or_goal("Evening Gratitude", category="Habit"))
        self.assertEqual(hab["status"], "SUCCESS")

        csv_text = export_entries_csv()
        self.assertIn("entry_id,timestamp,title,methodology", csv_text)

    def test_rate_limit_free_animated_moodscape_svg(self) -> None:
        img = json.loads(generate_journal_image("serene mountain lake at dawn"))
        self.assertEqual(img["status"], "SUCCESS")
        self.assertTrue(img["public_url"].startswith("/api/moodscape.svg"))

        svg = render_animated_moodscape_svg(
            prompt="Gratitude Journaling — Rewire attention toward abundance & everyday gifts",
            theme="warmth",
            subtitle="Instead of listing generic things, zoom in on one tiny micro-moment (a warm cup, a kind word, a quiet breath) to savor its emotional imprint.",
        )
        self.assertIn("<svg", svg)
        self.assertIn("<animate", svg)
        self.assertIn("everyday gifts", svg)
        self.assertIn("savor its emotional imprint.", svg)

    def test_coach_chat_guide_and_entries_gui(self) -> None:
        parts_guide = handle_chat_message(
            message="Guide me through a Mindfulness Journaling session",
            active_methodology="Mindfulness Journaling",
        )
        kinds = {p["kind"] for p in parts_guide}
        self.assertIn("a2ui", kinds)
        self.assertIn("guide_interactive", kinds)

        parts_entries = handle_chat_message(
            message="Show my recent journal entries and mood trends",
            active_methodology="Reflective Journaling",
        )
        kinds_entries = {p["kind"] for p in parts_entries}
        self.assertIn("entries_gui", kinds_entries)

    def test_privacy_redaction_and_vault_isolation(self) -> None:
        # 1. Verify PII and mental-state fields are redacted from logs
        raw_details = {
            "content": "My private mental health reflection",
            "emotion": "Restless & Anxious",
            "gemini_api_key": "AIzaSySecretKey123",
            "methodology": "Morning Pages",
            "word_count": 6,
        }
        redacted = redact_sensitive_details(raw_details)
        self.assertEqual(redacted["content"], "[REDACTED_FOR_PRIVACY]")
        self.assertEqual(redacted["emotion"], "[REDACTED_FOR_PRIVACY]")
        self.assertEqual(redacted["gemini_api_key"], "[REDACTED_FOR_PRIVACY]")
        self.assertEqual(redacted["methodology"], "Morning Pages")
        self.assertEqual(redacted["word_count"], 6)

        # 2. Verify isolated vault separation, dynamic user_name & at-rest PII encryption
        set_current_vault_id("isolated-test-user-999")
        try:
            cfg_initial = get_runtime_config()
            self.assertEqual(cfg_initial["user_name"], "")
            self.assertEqual(cfg_initial["display_name"], "Friend")
            self.assertFalse(cfg_initial["onboarding_complete"])

            save_runtime_config(
                user_name="Aarav",
                gemini_api_key="AIzaSyTestKey999",
                google_sheets_webhook_url="https://script.google.com/macros/s/test1234567890/exec",
            )
            _, vault_cfg_file = _get_vault_paths()
            raw_disk = vault_cfg_file.read_text(encoding="utf-8")
            self.assertIn("VAULT_ENC:v1:", raw_disk)
            self.assertNotIn("Aarav", raw_disk)
            self.assertNotIn("AIzaSyTestKey999", raw_disk)

            cfg_loaded = get_runtime_config()
            self.assertEqual(cfg_loaded["user_name"], "Aarav")
            self.assertTrue(cfg_loaded["onboarding_complete"])

            add_journal_entry(
                title="Private Vault Entry",
                content="Strictly private reflection for isolated user.",
                methodology="Expressive Writing",
                mood="Tender & Vulnerable",
            )
            isolated_entries = json.loads(list_journal_entries(limit=10))
            titles = {e["title"] for e in isolated_entries}
            self.assertIn("Private Vault Entry", titles)
        finally:
            purge_res = purge_vault_data()
            self.assertEqual(purge_res["status"], "SUCCESS")
            set_current_vault_id("default")

        log_event("TEST", "privacy_audit_check", status="OK", duration_ms=1.0)
        logs = get_recent_logs(limit=5)
        self.assertEqual(logs["privacy_mode"], "STRICT_PII_REDACTION_ACTIVE")

    def test_no_duplicate_entries_on_fallback_or_upsert(self) -> None:
        set_current_vault_id("dedup-test-vault-888")
        try:
            # Configure a fake API key so _call_gemini_rest_api runs and falls back to _smart_mindful_coach_fallback
            save_runtime_config(user_name="Tester", gemini_api_key="AIzaSyFakeKeyForFallbackTest")
            reflection_text = (
                "🌿 Emotion: Grounded & Serene — I feel grounded, steady, and quietly at ease in my body right now.\n"
                "Concept / Skill Explored: JournalOS app enhancement\n"
                "Key Insight in my own words: Daily planner framework"
            )
            handle_chat_message(
                message=reflection_text,
                active_methodology="Learning Journaling",
                selected_emotion="Grounded & Serene",
            )
            entries_after_chat = [
                e for e in store_list_entries(limit=20) if e["content"] == reflection_text
            ]
            # Must create ONLY 1 entry even when Gemini API falls back to built-in coach
            self.assertEqual(len(entries_after_chat), 1)
            first_id = entries_after_chat[0]["entry_id"]
            self.assertEqual(entries_after_chat[0]["tags"], ["learning", "grounded"])
            self.assertTrue(bool(entries_after_chat[0].get("coach_insight")))

            # Calling store_add_entry again with the same content should upsert in-place (merging tags & extra columns)
            store_add_entry(
                title="🌿 Emotion: Grounded & Serene — Full Updated Title",
                content=reflection_text,
                methodology="Learning Journaling",
                mood="Grounded & Serene",
                tags=["learning", "productivity"],
                coach_insight="Updated coach insight in extra column",
                sync_sheets=False,
            )
            entries_after_upsert = [
                e for e in store_list_entries(limit=20) if e["content"] == reflection_text
            ]
            self.assertEqual(len(entries_after_upsert), 1)
            self.assertEqual(entries_after_upsert[0]["entry_id"], first_id)
            self.assertEqual(
                entries_after_upsert[0]["tags"],
                ["learning", "grounded", "productivity"],
            )
            self.assertEqual(
                entries_after_upsert[0]["coach_insight"],
                "Updated coach insight in extra column",
            )
        finally:
            purge_vault_data()
            set_current_vault_id("default")


if __name__ == "__main__":
    unittest.main()
