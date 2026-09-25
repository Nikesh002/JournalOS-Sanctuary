import base64
import datetime
import json
import os
import subprocess
import time
import urllib.request
from typing import Optional
from google import genai
from google.adk.tools import ToolContext
import google.auth
import google.oauth2.credentials
from google.cloud import firestore, storage
from google.genai import types

# Hardcoded project ID string as required
PROJECT_ID = "qwiklabs-gcp-02-f96e03251dae"

# Hardcoded bucket name string as required
BUCKET_NAME = "journalos-media-qwiklabs-gcp-02-f96e03251dae"


def _get_db() -> firestore.Client:
    try:
        creds, _ = google.auth.default()
        client = firestore.Client(project=PROJECT_ID, credentials=creds)
        list(client.collections())
        return client
    except Exception:
        token = (
            subprocess.check_output(["gcloud", "auth", "print-access-token"])
            .decode("utf-8")
            .strip()
        )
        creds = google.oauth2.credentials.Credentials(token)
        return firestore.Client(project=PROJECT_ID, credentials=creds)


async def generate_journal_image(tool_context: ToolContext, prompt: str) -> str:
    """Generates a visual artwork or moodscape for a journal entry using gemini-3.1-flash-lite-image in the global region.

    Saves the generated image as a session artifact for the Playground UI and uploads it to public Cloud Storage.

    Args:
        tool_context: ADK tool execution context injected automatically.
        prompt: Detailed visual prompt describing the scene, mood, or dream imagery to generate.

    Returns:
        JSON string containing status, artifact_filename, and public_url.
    """
    genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
    res = genai_client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
    )

    part = res.candidates[0].content.parts[0]
    image_bytes = part.inline_data.data
    mime_type = part.inline_data.mime_type or "image/jpeg"

    ext = "png" if "png" in mime_type else "jpg"
    filename = f"journal_moodscape_{int(time.time())}.{ext}"

    # 1. Save artifact so it shows up in Playground's Artifacts panel
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    await tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload image bytes directly to public Cloud Storage bucket
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

    return json.dumps(
        {
            "status": "SUCCESS",
            "artifact_filename": filename,
            "public_url": public_url,
        },
        indent=2,
    )


async def generate_journal_video(tool_context: ToolContext, prompt: str) -> str:
    """Generates a short video or moodscape video for a journal item using gemini-omni-flash-preview in the global region.

    Saves the generated video as a session artifact for the Playground UI and uploads it directly to public Cloud Storage.

    Args:
        tool_context: ADK tool execution context injected automatically.
        prompt: Detailed visual prompt describing the scene, mood, or dream video to generate.

    Returns:
        JSON string containing status, artifact_filename, and public_url.
    """
    genai_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="global",
        http_options=types.HttpOptions(api_version="v1beta1"),
    )
    interaction = genai_client.interactions.create(
        model="gemini-omni-flash-preview",
        input=prompt,
    )

    video_bytes = None
    mime_type = "video/mp4"

    for step in getattr(interaction, "steps", []):
        if getattr(step, "type", "") == "model_output":
            for item in getattr(step, "content", []):
                if hasattr(item, "data") and item.data:
                    data_val = item.data
                    if isinstance(data_val, str):
                        video_bytes = base64.b64decode(data_val)
                    else:
                        video_bytes = data_val
                    mime_type = getattr(item, "mime_type", "") or "video/mp4"
                    break

    if not video_bytes:
        raise RuntimeError("No video bytes returned from gemini-omni-flash-preview model.")

    filename = f"journal_moodscape_video_{int(time.time())}.mp4"

    # 1. Save artifact so it shows up in Playground's Artifacts panel
    artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
    await tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload video bytes directly to public Cloud Storage bucket
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(video_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

    return json.dumps(
        {
            "status": "SUCCESS",
            "artifact_filename": filename,
            "public_url": public_url,
        },
        indent=2,
    )


def fetch_inspirational_quote() -> str:
    """Fetches a real-time inspirational or reflective quote from ZenQuotes API to inspire journaling.

    Reads ZENQUOTES_API_KEY / QUOTE_API_KEY from environment variables if present,
    passing it via header or query parameter according to Developer Knowledge spec.

    Returns:
        JSON string containing the quote, author, and source attribution.
    """
    api_key = os.getenv("ZENQUOTES_API_KEY") or os.getenv("QUOTE_API_KEY")
    url = "https://zenquotes.io/api/random"

    headers = {"User-Agent": "JournalOS/1.0"}
    if api_key:
        headers["X-goog-api-key"] = api_key

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
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
                "quote": "The journey of a thousand miles begins with one step.",
                "author": "Lao Tzu",
                "source": "Fallback Quote",
                "error": str(e),
            },
            indent=2,
        )

    return json.dumps(
        {
            "quote": "Do small things with great love.",
            "author": "Mother Teresa",
            "source": "Fallback Quote",
        },
        indent=2,
    )


def generate_reflective_prompt(category: str = "general") -> str:
    """Generates a curated journaling reflection prompt tailored to a methodology or focus category.

    Args:
        category: Reflection focus or methodology (e.g. 'gratitude', 'mindfulness', 'goals', 'learning', 'morning', 'dream', 'general').

    Returns:
        JSON string containing the category and recommended reflection prompt.
    """
    cat = category.lower().strip()
    prompts = {
        "gratitude": "What is a small, overlooked detail from today that brought you unexpected joy or peace?",
        "mindfulness": "Notice your body and feelings right now. What emotion or physical sensation needs your compassionate attention?",
        "goals": "What is the single most impactful action you can take today that aligns with your long-term vision?",
        "learning": "What friction point or mistake did you encounter recently, and what key insight does it teach you?",
        "morning": "What single priority or mindset will guide your energy for the day ahead?",
        "dream": "Describe the key imagery, feelings, and atmosphere of a recent dream without judgment.",
    }

    selected_prompt = prompts.get(
        cat,
        "What is currently occupying your mental bandwidth, and what perspective shift would serve you best right now?",
    )

    return json.dumps({"category": category, "prompt": selected_prompt}, indent=2)


def list_journal_entries(limit: int = 10) -> str:
    """Retrieves recent journal entries stored in Firestore.

    Args:
        limit: Maximum number of entries to return (default: 10).

    Returns:
        JSON string list of journal entry objects.
    """
    db = _get_db()
    docs = (
        db.collection("journal_entries")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    entries = [doc.to_dict() for doc in docs]
    return json.dumps(entries, indent=2)


def get_journal_entry(entry_id: str) -> str:
    """Retrieves a specific journal entry from Firestore by its unique entry_id.

    Args:
        entry_id: Unique identifier for the journal entry (e.g., 'entry-001').

    Returns:
        JSON string details of the requested entry or an error message if not found.
    """
    db = _get_db()
    doc_ref = db.collection("journal_entries").document(entry_id)
    doc = doc_ref.get()
    if not doc.exists:
        return f"Journal entry '{entry_id}' not found."
    return json.dumps(doc.to_dict(), indent=2)


def add_journal_entry(
    title: str,
    content: str,
    methodology: str = "Reflective Journaling",
    mood: str = "Neutral",
    tags: Optional[list[str]] = None,
) -> str:
    """Creates a new journal entry in the Firestore database.

    Args:
        title: Short title of the journal entry.
        content: Detailed body text or reflections of the journal entry.
        methodology: Journaling framework used (e.g. 'Morning Pages', 'Gratitude Journaling', 'Bullet Journaling', 'Reflective Journaling').
        mood: Dominant mood or emotional state (e.g. 'Energized', 'Reflective', 'Calm', 'Grateful', 'Anxious').
        tags: Optional list of descriptive tags (e.g. ['productivity', 'mindset', 'habits']).

    Returns:
        JSON string confirming successful creation with entry_id and timestamp.
    """
    db = _get_db()
    timestamp_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry_id = f"entry-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"

    entry_data = {
        "entry_id": entry_id,
        "title": title,
        "content": content,
        "methodology": methodology,
        "mood": mood,
        "tags": tags or [],
        "timestamp": timestamp_str,
    }

    db.collection("journal_entries").document(entry_id).set(entry_data)
    return json.dumps(
        {"status": "SUCCESS", "message": f"Saved entry '{entry_id}'", "data": entry_data},
        indent=2,
    )
