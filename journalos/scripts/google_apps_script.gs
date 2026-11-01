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
      "word_count",
      "updated_at",
      "coach_insight"
    ]);
    entriesSheet.getRange("A1:J1").setFontWeight("bold").setBackground("#e0e7ff");
  } else {
    // Ensure extra columns exist on previously created sheets without losing data
    const headerRow = entriesSheet.getRange(1, 1, 1, Math.max(10, entriesSheet.getLastColumn())).getValues()[0];
    if (!headerRow[8]) entriesSheet.getRange(1, 9).setValue("updated_at").setFontWeight("bold").setBackground("#e0e7ff");
    if (!headerRow[9]) entriesSheet.getRange(1, 10).setValue("coach_insight").setFontWeight("bold").setBackground("#e0e7ff");
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
    const newContentNorm = String(d.content || "").trim().replace(/\s+/g, " ");
    const rows = entriesSheet.getDataRange().getValues();
    let updatedRowIndex = -1;

    for (let i = 1; i < rows.length; i++) {
      const existingId = String(rows[i][0] || "");
      const existingContentNorm = String(rows[i][5] || "").trim().replace(/\s+/g, " ");
      if ((d.entry_id && existingId === String(d.entry_id)) || (newContentNorm && existingContentNorm === newContentNorm)) {
        updatedRowIndex = i + 1;
        // Merge tags without duplicates
        let existingTags = [];
        try {
          existingTags = JSON.parse(rows[i][6] || "[]");
        } catch (err) {
          existingTags = [];
        }
        const incomingTags = Array.isArray(d.tags) ? d.tags : [];
        const mergedTags = Array.from(new Set([].concat(existingTags, incomingTags)));

        const existingTitle = String(rows[i][2] || "");
        const bestTitle = (d.title && String(d.title).length > existingTitle.length) ? d.title : (existingTitle || "Untitled Reflection");
        const existingMood = String(rows[i][4] || "");
        const bestMood = (d.mood && d.mood !== "Reflective") ? d.mood : (existingMood || d.mood || "Grounded & Serene");
        const nowIso = d.updated_at || new Date().toISOString();
        const coachInsight = d.coach_insight || rows[i][9] || "";

        entriesSheet.getRange(updatedRowIndex, 1, 1, 10).setValues([[
          existingId || d.entry_id || ("entry-" + Date.now()),
          rows[i][1] || d.timestamp || nowIso,
          bestTitle,
          d.methodology || rows[i][3] || "Reflective Journaling",
          bestMood,
          d.content || rows[i][5] || "",
          JSON.stringify(mergedTags),
          d.word_count || rows[i][7] || (d.content ? d.content.split(/\s+/).length : 0),
          nowIso,
          coachInsight
        ]]);
        break;
      }
    }

    if (updatedRowIndex === -1) {
      const nowIso = d.timestamp || new Date().toISOString();
      entriesSheet.appendRow([
        d.entry_id || ("entry-" + Date.now()),
        nowIso,
        d.title || "Untitled Reflection",
        d.methodology || "Reflective Journaling",
        d.mood || "Grounded & Serene",
        d.content || "",
        JSON.stringify(d.tags || []),
        d.word_count || (d.content ? d.content.split(/\s+/).length : 0),
        d.updated_at || nowIso,
        d.coach_insight || ""
      ]);
    }
    return jsonResponse({ status: "SUCCESS", upserted: updatedRowIndex !== -1, message: "Entry saved to Google Sheet" });
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

