/**
 * JournalOS - Free Google Sheets Database Backend (Google Apps Script)
 * ====================================================================
 * Turn any personal Google Sheet into a free, live database for JournalOS!
 *
 * SETUP INSTRUCTIONS (Takes ~60 seconds):
 * 1. Create a new Google Sheet at https://sheets.new
 * 2. Click Extensions -> Apps Script in the top menu.
 * 3. Replace any code in Code.gs with this entire file and click Save (💾).
 * 4. Click "Deploy" -> "New deployment".
 * 5. Select type: "Web app".
 *    - Execute as: "Me"
 *    - Who has access: "Anyone"
 * 6. Click "Deploy", authorize access, and copy the "Web app URL".
 * 7. Paste that URL into JournalOS Settings (or set GOOGLE_SHEETS_WEBHOOK_URL in .env).
 */

const SHEETS = {
  ENTRIES: "Journal_Entries",
  MEMORIES: "Memories_Insights",
  HABITS: "Habits_Goals"
};

function ensureSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let entriesSheet = ss.getSheetByName(SHEETS.ENTRIES);
  if (!entriesSheet) {
    entriesSheet = ss.insertSheet(SHEETS.ENTRIES);
    entriesSheet.appendRow([
      "entry_id",
      "timestamp",
      "title",
      "methodology",
      "mood",
      "content",
      "tags",
      "word_count"
    ]);
    entriesSheet.getRange("A1:H1").setFontWeight("bold").setBackground("#e0e7ff");
  }

  let memoriesSheet = ss.getSheetByName(SHEETS.MEMORIES);
  if (!memoriesSheet) {
    memoriesSheet = ss.insertSheet(SHEETS.MEMORIES);
    memoriesSheet.appendRow([
      "memory_id",
      "timestamp",
      "domain",
      "fact"
    ]);
    memoriesSheet.getRange("A1:D1").setFontWeight("bold").setBackground("#dcfce7");
  }

  let habitsSheet = ss.getSheetByName(SHEETS.HABITS);
  if (!habitsSheet) {
    habitsSheet = ss.insertSheet(SHEETS.HABITS);
    habitsSheet.appendRow([
      "item_id",
      "updated_at",
      "title",
      "category",
      "status",
      "streak"
    ]);
    habitsSheet.getRange("A1:F1").setFontWeight("bold").setBackground("#fef3c7");
  }

  return { ss, entriesSheet, memoriesSheet, habitsSheet };
}

function sheetToObjects(sheet) {
  const rows = sheet.getDataRange().getValues();
  if (rows.length <= 1) return [];
  const headers = rows[0];
  const result = [];
  for (let i = 1; i < rows.length; i++) {
    const obj = {};
    for (let j = 0; j < headers.length; j++) {
      let val = rows[i][j];
      if (headers[j] === "tags" && typeof val === "string") {
        try {
          val = JSON.parse(val);
        } catch (e) {
          val = val ? val.split(",").map(s => s.trim()) : [];
        }
      }
      obj[headers[j]] = val;
    }
    result.push(obj);
  }
  return result;
}

function doGet(e) {
  const { entriesSheet, memoriesSheet, habitsSheet } = ensureSheets();
  const action = (e && e.parameter && e.parameter.action) || "all";

  let payload = {};
  if (action === "entries") {
    payload = { status: "SUCCESS", entries: sheetToObjects(entriesSheet).reverse() };
  } else if (action === "memories") {
    payload = { status: "SUCCESS", memories: sheetToObjects(memoriesSheet).reverse() };
  } else if (action === "habits") {
    payload = { status: "SUCCESS", habits: sheetToObjects(habitsSheet) };
  } else {
    payload = {
      status: "SUCCESS",
      entries: sheetToObjects(entriesSheet).reverse(),
      memories: sheetToObjects(memoriesSheet).reverse(),
      habits: sheetToObjects(habitsSheet)
    };
  }

  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  const { entriesSheet, memoriesSheet, habitsSheet } = ensureSheets();
  const body = JSON.parse(e.postData.contents || "{}");
  const action = body.action || "add_entry";

  if (action === "add_entry") {
    const d = body.data || {};
    entriesSheet.appendRow([
      d.entry_id || ("entry-" + Date.now()),
      d.timestamp || new Date().toISOString(),
      d.title || "Untitled Reflection",
      d.methodology || "Reflective Journaling",
      d.mood || "Calm",
      d.content || "",
      JSON.stringify(d.tags || []),
      d.word_count || (d.content ? d.content.split(/\s+/).length : 0)
    ]);
    return jsonResponse({ status: "SUCCESS", message: "Entry saved to Google Sheet" });
  }

  if (action === "add_memory") {
    const d = body.data || {};
    memoriesSheet.appendRow([
      d.memory_id || ("mem-" + Date.now()),
      d.timestamp || new Date().toISOString(),
      d.domain || "User Goals",
      d.fact || ""
    ]);
    return jsonResponse({ status: "SUCCESS", message: "Memory saved to Google Sheet" });
  }

  if (action === "upsert_habit") {
    const d = body.data || {};
    const rows = habitsSheet.getDataRange().getValues();
    let updated = false;
    for (let i = 1; i < rows.length; i++) {
      if (String(rows[i][2]).toLowerCase() === String(d.title || "").toLowerCase()) {
        habitsSheet.getRange(i + 1, 2, 1, 5).setValues([[
          d.updated_at || new Date().toISOString(),
          d.title,
          d.category || "Habit",
          d.status || "Active",
          d.streak || 1
        ]]);
        updated = true;
        break;
      }
    }
    if (!updated) {
      habitsSheet.appendRow([
        d.item_id || ("hab-" + Date.now()),
        d.updated_at || new Date().toISOString(),
        d.title || "Daily Mindfulness",
        d.category || "Habit",
        d.status || "Active",
        d.streak || 1
      ]);
    }
    return jsonResponse({ status: "SUCCESS", message: "Habit/Goal updated in Google Sheet" });
  }

  return jsonResponse({ status: "ERROR", message: "Unknown action: " + action });
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

