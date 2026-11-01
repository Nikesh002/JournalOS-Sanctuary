# 🌿 JournalOS Sanctuary — Technical & Developer Guide

<p align="center">
  <img src="frontend/static/logo.svg" alt="JournalOS Logo" width="72" height="72">
</p>

**JournalOS Sanctuary** is a **100% free, open-source, privacy-first Mindful AI Journaling Web Application**. It combines an empathetic **Companion Counsellor** persona, **19 evidence-based journaling frameworks**, **rate-limit-free animated SVG moodscapes**, **client-side AES-256-GCM encryption**, and **Google Sheets / local vault persistence**.

![JournalOS Animated Demo](assets/demo.gif)

---

## 📸 Visual Tour of Updated Codebase

| View | Screenshot |
| :--- | :--- |
| **1. First-Time Sanctuary Onboarding** *(Dynamic `user_name` & optional AES-256 PIN)* | ![First-Time Setup](assets/screenshot_onboarding.png) |
| **2. Companion Coach & Uncropped Multi-Line Moodscape** *(19 Frameworks + `NOW` badge + Emotion Pills)* | ![Companion Coach](assets/screenshot_coach_moodscape.png) |
| **3. My Entries & Trends GUI Dashboard** *(KPI Tiles + Encrypted Reflection Badges)* | ![Entries & Trends](assets/screenshot_entries_trends.png) |
| **4. Insights, Distribution Bars & Google Calendar Studio** *(Progress Bars + `.ics` / Google Calendar)* | ![Insights & Calendar](assets/screenshot_insights_calendar.png) |
| **5. End-to-End Privacy, `VAULT_ENC:v1` & Redacted Logs** *(Persistent API Keys + `[REDACTED_FOR_PRIVACY]`)* | ![Privacy & Logs](assets/screenshot_privacy_security.png) |

---

## 🧩 System Architecture

```mermaid
flowchart TD
    Browser["User Browser (index.html)\n• First-Time Setup & Dynamic User Name\n• WebCrypto AES-256-GCM Encryption\n• Esc Key Privacy Shield & Calendar Studio"]
    Server["Dual-Mode Python Server (frontend/main.py)\n• Zero-Dependency ThreadingHTTPServer OR FastAPI\n• Security Headers & Per-Vault Isolation"]
    Coach["Companion Counsellor Engine\n• Gemini 2.5 Flash REST API (Free Tier)\n• Built-In Empathetic Coach Fallback"]
    Storage["Encrypted Storage Engine (app/sheets_storage.py)\n• VAULT_ENC:v1 At-Rest Config & PII Encryption\n• 19 Methodologies & 10 Nuanced Emotions\n• Circadian Timezone Recommendation"]
    Visuals["Animated Moodscape Studio (app/firestore_tools.py)\n• 60fps Multi-Line SVG Art (/api/moodscape.svg)"]
    Logger["Redacted Diagnostics (app/logger_utils.py)\n• Strict PII & Mental-State Redaction"]
    Sheets[("Personal Google Sheet\n(scripts/google_apps_script.gs)")]

    Browser <-->|"REST + X-JournalOS-Vault-ID"| Server
    Server --> Coach
    Server --> Storage
    Server --> Visuals
    Server --> Logger
    Storage <-->|"HTTPS Webhook + secret_token"| Sheets
```

---

## 📂 Repository Structure

```text
journalos/
├── app/
│   ├── agent.py              # Optional ADK Agent definition (Gemini 2.5 Flash)
│   ├── a2ui_utils.py         # A2UI v0.8 card schema validator & callback
│   ├── firestore_tools.py    # 19-methodology prompt engine & multi-line animated SVG moodscapes
│   ├── logger_utils.py       # Rotating file + JSONL logger with strict PII redaction
│   └── sheets_storage.py     # Encrypted vault storage, Google Sheets sync & streak analytics
├── assets/
│   ├── demo.gif              # Animated multi-frame walkthrough of the updated web app
│   ├── screenshot_onboarding.png
│   ├── screenshot_coach_moodscape.png
│   ├── screenshot_entries_trends.png
│   ├── screenshot_insights_calendar.png
│   └── screenshot_privacy_security.png
├── frontend/
│   ├── main.py               # Dual-mode HTTP/FastAPI server (runs with zero pip dependencies)
│   └── static/
│       ├── index.html        # Single-page Sanctuary UI, Onboarding Modal & WebCrypto AES-256-GCM
│       └── logo.svg          # Custom JournalOS Sanctuary vector logo & browser tab favicon
├── scripts/
│   └── google_apps_script.gs # Free Google Sheets Web App database connector
└── tests/
    └── unit/
        └── test_dummy.py     # Unit tests for 19 frameworks, SVG wrapping, encryption & privacy
```

---

## ⚡ Running Locally & Testing

### Start the Web App
```bash
python frontend/main.py
```
Then open **http://localhost:8080**.

### Run Unit Tests
```bash
python -m unittest tests/unit/test_dummy.py -v
```
