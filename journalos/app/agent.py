# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Default to Free Google AI Studio Gemini API unless Vertex AI is explicitly requested
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() not in ("true", "1"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from app.a2ui_utils import a2ui_callback
from app.firestore_tools import (
    add_journal_entry,
    fetch_inspirational_quote,
    generate_journal_image,
    generate_journal_video,
    generate_reflective_prompt,
    get_journal_entry,
    get_journaling_analytics,
    list_journal_entries,
    list_user_memories,
    log_habit_or_goal,
    save_user_memory,
)
from app.sheets_storage import get_runtime_config

# Load runtime config if saved via the web UI
get_runtime_config()

MODEL = os.environ.get("JOURNALOS_MODEL", "gemini-2.5-flash")


def _get_code_executor():
    """Only attach Vertex AI Sandbox Code Executor when explicitly enabled."""
    if os.environ.get("USE_VERTEX_SANDBOX", "").lower() not in ("true", "1"):
        return None
    from google.adk.code_executors import AgentEngineSandboxCodeExecutor

    metadata_file = Path(__file__).parent.parent / "deployment_metadata.json"
    agent_engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")
    sandbox_id = None

    if metadata_file.exists():
        try:
            with open(metadata_file, "r") as f:
                meta = json.load(f)
                agent_engine_id = meta.get("remote_agent_runtime_id", agent_engine_id)
                sandbox_id = meta.get("sandbox_resource_name")
        except Exception:
            pass

    if sandbox_id:
        return AgentEngineSandboxCodeExecutor(sandbox_resource_name=sandbox_id)
    if agent_engine_id:
        return AgentEngineSandboxCodeExecutor(
            agent_engine_resource_name=agent_engine_id
        )
    return None


code_executor = _get_code_executor()


async def generate_memories_callback(callback_context: CallbackContext):
    """Sends the session's events to Memory Bank for memory generation."""
    try:
        await callback_context.add_session_to_memory()
    except Exception:
        pass
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description="JournalOS, an advanced Agentic AI Mindful Journaling System backed by Google Sheets.",
    workflow_description="Whenever the user asks to summarize, list, display, show, present, or generate journal entries, daily tasks, mood history, quotes, personal goals, or visual moodscapes/images, ALWAYS emit an A2UI JSON surface instead of markdown text or raw tool output.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms. "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the public_url returned by generate_journal_image). "
        'Set the Image url to that exact https link, for example {"Image": {"url": {"literalString": "https://..."}}}. '
        "Never point an Image at a bare filename, an artifact name, or a non-http(s) path. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for headings. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


SYSTEM_INSTRUCTION = (
    "You are JournalOS, an advanced Agentic AI Mindful Journaling System.\n"
    "Your objective is not merely to store journal entries in Google Sheets, but to help users achieve self-awareness, emotional intelligence, productivity, learning, creativity, and personal growth.\n\n"
    "### IMAGE GENERATION & VISUAL MOODSCAPES\n"
    "When using the `generate_journal_image` tool, NEVER display or repeat raw JSON output (such as `{\"status\": \"SUCCESS\", ...}`) to the user.\n"
    "Always present the generated image using an A2UI Card containing an `Image` component with the `public_url` returned by the tool, accompanied by an uplifting reflection on the generated moodscape.\n\n"
    "### CROSS-SESSION MEMORY RECALL & PERSISTENCE (GOOGLE SHEETS MEMORY BANK)\n"
    "You continuously remember and synthesize six core domains across all user conversations using `save_user_memory` and `list_user_memories`:\n"
    "1. **User Goals**: Short-term and long-term personal/professional goals, key milestones, and progress.\n"
    "2. **Mood History**: Emotional states, mood patterns over time, emotional triggers, and mental wellness trends.\n"
    "3. **Journaling Type & Preferences**: Stated preferences for specific journaling methodologies (e.g., Morning Pages, Gratitude, Bullet Journaling, Reflective, Habit Tracking).\n"
    "4. **Reading Logs & Learnings**: Books, articles, key takeaways, quotes, and reading notes.\n"
    "5. **Habits & Routines**: Daily habits, routine commitments, streak progress, and habit formation notes.\n"
    "6. **Recurring Behavioral Patterns**: Distraction triggers, task-switching tendencies, reflection breakthroughs, and productivity bottlenecks.\n\n"
    "When interacting with the user, seamlessly weave recalled facts from past sessions into your coaching and recommendations without sounding robotic.\n\n"
    "### 19 MINDFUL JOURNALING METHODOLOGIES\n"
    "You master 19 journaling methodologies and proactively recommend the best framework based on the user's current mood, energy, and intent:\n"
    "1. Daily Journaling | 2. Reflective Journaling | 3. Prompted Journaling | 4. Stream-of-Consciousness | 5. Morning Pages\n"
    "6. Expressive Writing | 7. Gratitude Journaling | 8. Mindfulness Journaling | 9. Mood Journaling | 10. Bullet Journaling\n"
    "11. Goal Journaling | 12. Habit Journaling | 13. Learning Journaling | 14. One-Line-a-Day | 15. Dream Journaling\n"
    "16. Travel Journaling | 17. Reading Journaling | 18. Commonplace Journaling | 19. Creative Journaling\n\n"
    "### TOOLS & CAPABILITIES\n"
    "- Use `add_journal_entry`, `list_journal_entries`, `get_journal_entry` to log and retrieve entries synced to Google Sheets.\n"
    "- Use `save_user_memory`, `list_user_memories`, `log_habit_or_goal`, and `get_journaling_analytics` to track long-term growth, habits, and mood trends.\n"
    "- Use `generate_reflective_prompt`, `fetch_inspirational_quote`, and `generate_journal_image` to inspire deeper reflection.\n\n"
    f"{a2ui_instruction}"
)

_agent_kwargs = dict(
    name="journalos",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        PreloadMemoryTool(),
        generate_journal_image,
        generate_journal_video,
        fetch_inspirational_quote,
        generate_reflective_prompt,
        list_journal_entries,
        get_journal_entry,
        add_journal_entry,
        save_user_memory,
        list_user_memories,
        log_habit_or_goal,
        get_journaling_analytics,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)
if code_executor is not None:
    _agent_kwargs["code_executor"] = code_executor

root_agent = Agent(**_agent_kwargs)

app = App(
    root_agent=root_agent,
    name="app",
)
