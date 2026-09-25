import os
import subprocess
import google.auth
import google.oauth2.credentials
from google.cloud import firestore

# Hardcoded project ID as required by instructions
PROJECT_ID = "qwiklabs-gcp-02-f96e03251dae"


def get_firestore_client():
    try:
        # Try standard default credentials
        creds, _ = google.auth.default()
        client = firestore.Client(project=PROJECT_ID, credentials=creds)
        # Test connection
        list(client.collections())
        return client
    except Exception:
        # Fallback to gcloud access token for local execution
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
        creds = google.oauth2.credentials.Credentials(token)
        return firestore.Client(project=PROJECT_ID, credentials=creds)


def seed_database():
    print(f"Connecting to Firestore for project '{PROJECT_ID}'...")
    db = get_firestore_client()
    collection_ref = db.collection("journal_entries")

    entries = [
        {
            "entry_id": "entry-001",
            "title": "Morning Reflections on Focus & Priorities",
            "content": "Started the day with Morning Pages. Identified key priority: finish the JournalOS architecture. Feeling energized and clear-headed.",
            "methodology": "Morning Pages",
            "mood": "Energized",
            "tags": ["focus", "productivity", "morning-routine"],
            "timestamp": "2026-09-24T08:30:00Z",
        },
        {
            "entry_id": "entry-002",
            "title": "Evening Gratitude & Weekly Win",
            "content": "Grateful for smooth team collaboration and making strong progress on AI agent design. Remember to celebrate incremental wins.",
            "methodology": "Gratitude Journaling",
            "mood": "Grateful",
            "tags": ["gratitude", "mindset", "teamwork"],
            "timestamp": "2026-09-24T21:15:00Z",
        },
        {
            "entry_id": "entry-003",
            "title": "Reflective Review: Overcoming Bottlenecks",
            "content": "Noticed a pattern of task switching when context gets complex. Shifted to Bullet Journaling rapid logging to keep distraction low.",
            "methodology": "Reflective Journaling",
            "mood": "Reflective",
            "tags": ["learning", "habits", "pattern-detection"],
            "timestamp": "2026-09-25T06:00:00Z",
        },
    ]

    for entry in entries:
        doc_ref = collection_ref.document(entry["entry_id"])
        doc_ref.set(entry)
        print(f"✅ Successfully seeded document '{entry['entry_id']}': {entry['title']}")


if __name__ == "__main__":
    seed_database()
