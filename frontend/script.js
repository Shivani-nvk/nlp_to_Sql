const API_BASE = "http://127.0.0.1:5000";

const runBtn = document.getElementById("runBtn");
const statusText = document.getElementById("statusText");
const userInput = document.getElementById("userInput");

const authScreen = document.getElementById("authScreen");
const appSection = document.getElementById("appSection");
const authUsername = document.getElementById("authUsername");
const authPassword = document.getElementById("authPassword");
const authStatusText = document.getElementById("authStatusText");
const authSubmitBtn = document.getElementById("authSubmitBtn");
const authSubmitLabel = document.getElementById("authSubmitLabel");
const authModeLabel = document.getElementById("authModeLabel");
const authToggleText = document.getElementById("authToggleText");
const authToggleBtn = document.getElementById("authToggleBtn");
const userBadge = document.getElementById("userBadge");
const userBadgeText = document.getElementById("userBadgeText");
const adminSection = document.getElementById("adminSection");

// Chatbot/feedback DOM refs
const chatLog = document.getElementById("chatLog");
const chatSatisfaction = document.getElementById("chatSatisfaction");
const chatFeedbackInput = document.getElementById("chatFeedbackInput");
const chatFeedbackText = document.getElementById("chatFeedbackText");
const chatStatusText = document.getElementById("chatStatusText");
const chatSubmitBtn = document.getElementById("chatSubmitBtn");

let lastSQL = "";
let authMode = "login"; // or "signup"
let originalQuestion = "";

// ---------------- THEME MANAGEMENT ----------------

function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark" || (!saved && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  if (isDark) {
    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem("theme", "light");
    showToast("Light mode enabled");
  } else {
    document.documentElement.setAttribute("data-theme", "dark");
    localStorage.setItem("theme", "dark");
    showToast("Dark mode enabled");
  }
}

// Immediately apply theme
initTheme();

// ---------------- TOAST NOTIFICATIONS ----------------

function showToast(message) {
  const toast = document.getElementById("toastNotification");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 2200);
}

// ---------------- DRAWERS & MODALS ----------------

function toggleDrawer(drawerId) {
  const drawer = document.getElementById(drawerId);
  const backdrop = document.getElementById("drawerBackdrop");
  if (!drawer) return;

  const isOpen = drawer.classList.contains("open");
  closeAllDrawers();

  if (!isOpen) {
    drawer.classList.add("open");
    if (backdrop) backdrop.classList.add("open");
    if (drawerId === "schemaDrawer") {
      loadSchemaTree();
    } else if (drawerId === "historyDrawer") {
      renderQueryHistory();
    }
  }
}

function closeDrawer(drawerId) {
  const drawer = document.getElementById(drawerId);
  if (drawer) drawer.classList.remove("open");
  const backdrop = document.getElementById("drawerBackdrop");
  if (backdrop) backdrop.classList.remove("open");
}

function closeAllDrawers() {
  document.querySelectorAll(".drawer").forEach((d) => d.classList.remove("open"));
  const backdrop = document.getElementById("drawerBackdrop");
  if (backdrop) backdrop.classList.remove("open");
}

// ---------------- AUTH STATE ----------------

function getToken() {
  return sessionStorage.getItem("token");
}

function getRole() {
  return sessionStorage.getItem("role");
}

function saveSession(token, username, role) {
  sessionStorage.setItem("token", token);
  sessionStorage.setItem("username", username);
  sessionStorage.setItem("role", role);
}

function clearSession() {
  sessionStorage.removeItem("token");
  sessionStorage.removeItem("username");
  sessionStorage.removeItem("role");
}

function resetConsoleState() {
  userInput.value = "";
  lastSQL = "";
  originalQuestion = "";
  window.resultData = null;
  window.filteredData = null;
  setStatus("", false);
  document.getElementById("sqlSection").style.display = "none";
  document.getElementById("outputSection").style.display = "none";
  document.getElementById("queryOutput").innerText = "";
  document.getElementById("resultsTable").innerHTML = "";
  document.getElementById("sqlSourceBadge").style.display = "none";
  document.getElementById("chatSection").style.display = "none";

  const expBox = document.getElementById("queryExplanationBox");
  if (expBox) expBox.style.display = "none";
  const timeBadge = document.getElementById("executionTimeBadge");
  if (timeBadge) timeBadge.style.display = "none";
  const progBar = document.getElementById("queryProgressBar");
  if (progBar) progBar.style.display = "none";

  toggleClearButton();
  resetChat();
}

function showApp() {
  const username = sessionStorage.getItem("username");
  const role = getRole();

  resetConsoleState();

  authScreen.style.display = "none";
  appSection.style.display = "block";

  userBadge.style.display = "flex";
  userBadgeText.textContent = `${username} - ${role}`;

  const schemaBtn = document.getElementById("schemaToggleBtn");
  if (schemaBtn) schemaBtn.style.display = "inline-flex";
  const historyBtn = document.getElementById("historyToggleBtn");
  if (historyBtn) historyBtn.style.display = "inline-flex";

  adminSection.style.display = role === "admin" ? "block" : "none";

  if (role === "admin") {
    loadAdminPanel();
  }
}

function showAuthScreen() {
  authScreen.style.display = "block";
  appSection.style.display = "none";
  userBadge.style.display = "none";

  const schemaBtn = document.getElementById("schemaToggleBtn");
  if (schemaBtn) schemaBtn.style.display = "none";
  const historyBtn = document.getElementById("historyToggleBtn");
  if (historyBtn) historyBtn.style.display = "none";
  closeAllDrawers();
}

function logout() {
  clearSession();
  window.resultData = null;
  window.filteredData = null;
  showAuthScreen();
  setAuthStatus("Logged out.", false);
}

// On load: if we already have a token, skip straight to the app
if (getToken()) {
  showApp();
} else {
  showAuthScreen();
}

// ---------------- LOGIN / SIGNUP FORM ----------------

function setAuthStatus(message, isError) {
  authStatusText.textContent = message;
  authStatusText.classList.toggle("is-error", Boolean(isError));
}

function toggleAuthMode() {
  authMode = authMode === "login" ? "signup" : "login";

  if (authMode === "signup") {
    authModeLabel.textContent = "signup.session";
    authSubmitLabel.textContent = "Sign up";
    authToggleText.textContent = "Already have an account?";
    authToggleBtn.textContent = "Log in";
  } else {
    authModeLabel.textContent = "login.session";
    authSubmitLabel.textContent = "Log in";
    authToggleText.textContent = "Don't have an account?";
    authToggleBtn.textContent = "Sign up";
  }

  setAuthStatus("", false);
}

function submitAuth() {
  const username = authUsername.value.trim();
  const password = authPassword.value;

  if (!username || !password) {
    setAuthStatus("Enter a username and password.", true);
    return;
  }

  const endpoint = authMode === "signup" ? "/signup" : "/login";

  authSubmitBtn.disabled = true;
  setAuthStatus(authMode === "signup" ? "Creating account..." : "Logging in...", false);

  fetch(API_BASE + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  })
    .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
    .then(({ ok, data }) => {
      authSubmitBtn.disabled = false;

      if (!ok || data.error) {
        setAuthStatus(data.error || "Something went wrong.", true);
        return;
      }

      saveSession(data.token, data.username, data.role);
      authPassword.value = "";
      setAuthStatus("", false);
      showApp();
    })
    .catch((error) => {
      authSubmitBtn.disabled = false;
      setAuthStatus("Couldn't reach the backend. Is the Flask server running?", true);
      console.log(error);
    });
}

// ---------------- VOICE INPUT ----------------

const micBtn = document.getElementById("micBtn");
const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;
let isListening = false;

if (SpeechRecognitionAPI) {
  recognition = new SpeechRecognitionAPI();
  recognition.lang = "en-US";
  recognition.continuous = false;    // auto-stop after a pause in speech
  recognition.interimResults = true; // show text live while still talking

  recognition.onstart = () => {
    isListening = true;
    micBtn.classList.add("listening");
    setStatus("Listening...", false);
  };

  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    userInput.value = transcript;
  };

  recognition.onerror = (event) => {
    setStatus(`Mic error: ${event.error}`, true);
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    if (statusText.textContent === "Listening...") {
      setStatus("", false);
    }
    userInput.focus();
  };
} else {
  micBtn.disabled = true;
  micBtn.title = "Voice input isn't supported in this browser. Try Chrome or Edge.";
}

function toggleMic() {
  if (!recognition) return;

  if (isListening) {
    recognition.stop();
  } else {
    userInput.value = "";
    recognition.start();
  }
}

// ---------------- PROMPT ACTIONS & SHORTCUTS ----------------

function toggleClearButton() {
  const btn = document.getElementById("clearInputBtn");
  if (!btn) return;
  btn.style.display = userInput.value.trim().length > 0 ? "flex" : "none";
}

function clearInput() {
  userInput.value = "";
  toggleClearButton();
  userInput.focus();
}

function finishAndClearQuery() {
  resetConsoleState();
  setStatus("Cleared! Ready for your next query.", false);
  userInput.focus();
  showToast("Query and results cleared!");
}

userInput.addEventListener("input", toggleClearButton);

// Enter to run, Shift+Enter for newline, Ctrl+Enter or Cmd+Enter anytime
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    showSQL();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeAllDrawers();
    const expBox = document.getElementById("queryExplanationBox");
    if (expBox) expBox.style.display = "none";
  }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    showSQL();
  }
});

// ---------------- CHIPS (Sample queries) ----------------

document.getElementById("chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  userInput.value = chip.dataset.q;
  toggleClearButton();
  userInput.focus();
});

// ---------------- QUERY CONSOLE & EXECUTION ----------------

function setStatus(message, isError) {
  statusText.textContent = message;
  statusText.classList.toggle("is-error", Boolean(isError));
}

// ---------------- SOURCE BADGE (hybrid engine indicator) ----------------
// Maps the backend's source field to a badge + optional self-heal note.

function applySourceBadge(data) {
  const badge = document.getElementById("sqlSourceBadge");
  if (!badge) return;

  const source = data.source || (data.used_ai_fallback ? "agentic" : "rule_based");
  const repairs = data.repair_attempts || 0;

  if (source === "agentic_self_healed") {
    badge.textContent = "\uD83D\uDEE0\uFE0F Agentic AI \u2014 Self-Healed";
    badge.className = "source-badge source-badge-healed";
    setStatus(`Rule-based generation failed. Agentic AI corrected the SQL after ${repairs} attempt${repairs === 1 ? "" : "s"}.`, false);
  } else if (source === "agentic") {
    badge.textContent = "\uD83E\uDD16 Agentic AI";
    badge.className = "source-badge source-badge-ai";
    badge.title = (data.trace && data.trace.length) ? data.trace.join(" \u2192 ") : "";
  } else {
    badge.textContent = "\u2699\uFE0F Rule-Based";
    badge.className = "source-badge source-badge-rule";
    badge.title = (data.trace && data.trace.length) ? data.trace.join(" \u2192 ") : "";
  }
  badge.style.display = "inline-flex";
}

function showSQL() {
  const question = userInput.value.trim();

  if (!question) {
    setStatus("Type a question first.", true);
    return;
  }

  const token = getToken();
  if (!token) {
    showAuthScreen();
    setAuthStatus("Please log in first.", true);
    return;
  }

  runBtn.disabled = true;
  setStatus("Generating SQL...", false);
  const progBar = document.getElementById("queryProgressBar");
  if (progBar) progBar.style.display = "block";
  document.getElementById("outputSection").style.display = "none";
  const expBox = document.getElementById("queryExplanationBox");
  if (expBox) expBox.style.display = "none";

  const startTime = performance.now();

  fetch(API_BASE + "/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + token
    },
    body: JSON.stringify({ question: question })
  })
    .then((response) => response.json().then((data) => ({ status: response.status, data })))
    .then(({ status, data }) => {
      runBtn.disabled = false;
      if (progBar) progBar.style.display = "none";
      const elapsedMs = Math.round(performance.now() - startTime);

      if (status === 401) {
        clearSession();
        showAuthScreen();
        setAuthStatus("Your session expired. Please log in again.", true);
        return;
      }

      if (data.error) {
        setStatus(data.error, true);
        return;
      }

      setStatus("Done.", false);

      lastSQL = data.sql || "";
      originalQuestion = question;
      document.getElementById("sqlSection").style.display = "block";
      renderSQLOutput(lastSQL);

      const timeBadge = document.getElementById("executionTimeBadge");
      if (timeBadge) {
        let icon = "⚡";
        let sourceLabel = "Rule-Based";
        if (data.source === "agentic_self_healed") {
          icon = "🛠️";
          sourceLabel = "Self-Healed";
        } else if (data.source === "agentic") {
          icon = "🤖";
          sourceLabel = "Agentic AI";
        }
        timeBadge.textContent = `${icon} ${elapsedMs} ms (${sourceLabel})`;
        timeBadge.style.display = "inline-flex";
      }

      applySourceBadge(data);

      window.resultData = data.data;
      window.lastTrace = data.trace || [];
      window.lastSource = data.source || "";
      window.lastRepairs = data.repair_attempts || 0;

      // Add to query history
      addQueryHistory({
        question: question,
        sql: lastSQL,
        source: data.source || (data.used_ai_fallback ? "agentic" : "rule_based"),
        repair_attempts: data.repair_attempts || 0,
        used_ai_fallback: Boolean(data.used_ai_fallback),
        rowCount: (data.data ? data.data.length : 0),
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      });

      // Auto-show output if option is checked (including 0-row sets)
      const autoToggle = document.getElementById("autoShowOutputToggle");
      if (autoToggle && autoToggle.checked && Array.isArray(data.data)) {
        showOutput();
      }

      resetChat();
      updateQuickRefineSuggestions(lastSQL);
      document.getElementById("chatSection").style.display = "block";
    })
    .catch((error) => {
      runBtn.disabled = false;
      if (progBar) progBar.style.display = "none";
      setStatus("Couldn't reach the backend. Is the Flask server running?", true);
      console.log(error);
    });
}

function copySQL() {
  if (!lastSQL) return;

  navigator.clipboard.writeText(lastSQL)
    .then(() => {
      showToast("SQL query copied to clipboard!");
      const copyBtn = document.getElementById("copyBtn");
      const original = copyBtn.innerHTML;
      copyBtn.innerText = "Copied!";
      setTimeout(() => {
        copyBtn.innerHTML = original;
      }, 1200);
    })
    .catch(() => {
      const queryOutput = document.getElementById("queryOutput");
      const range = document.createRange();
      range.selectNodeContents(queryOutput);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      setStatus("Select the SQL text and press Ctrl+C.", false);
      selection.removeAllRanges();
    });
}

// ---------------- SQL SYNTAX HIGHLIGHTING & FORMATTING ----------------

function escapeHTML(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    // Quotes matter for attribute values: <div title="it's"> terminates the
    // attribute early without them. (Note this is NOT enough on its own for
    // inline onclick="..." handlers - the HTML parser decodes entities before
    // the browser compiles the JS, so &#39; turns back into a quote. Anything
    // interpolated into an inline handler has to go through a data attribute
    // and a delegated listener instead.)
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatSQL(sql) {
  if (!sql) return "";
  let clean = sql.trim().replace(/\s+/g, " ");

  const clauses = [
    "SELECT", "FROM", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "JOIN",
    "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT"
  ];

  clauses.forEach((kw) => {
    const reg = new RegExp(`\\b${kw}\\b`, "gi");
    clean = clean.replace(reg, (match) => `\n${match.toUpperCase()}`);
  });

  return clean.trim();
}

function highlightSQL(sql) {
  if (!sql) return "";

  // String literals are lifted out FIRST, on the raw SQL, and put back at the
  // end. The previous order escaped first, which turned every quote into an
  // entity and left the literal pattern below with nothing to match, so
  // quoted values silently lost their highlighting. Masking first also means
  // the placeholder is never double-escaped.
  //
  // The placeholder uses private-use codepoints, which cannot appear in a
  // schema-derived value, so a literal that literally spells
  // "___SQL_STR_0___" can no longer collide with a real placeholder.
  const literals = [];
  let masked = String(sql).replace(/'(?:\\.|[^'\\])*'/g, (match) => {
    literals.push(match);
    return `\uE000${literals.length - 1}\uE001`;
  });

  let safe = escapeHTML(masked);

  // Aggregation & Built-in Functions
  const funcs = ["COUNT", "SUM", "AVG", "MIN", "MAX", "CONCAT", "ROUND", "UPPER", "LOWER", "IFNULL", "COALESCE"];
  funcs.forEach((fn) => {
    const reg = new RegExp(`\\b(${fn})\\b(?=\\s*\\()`, "gi");
    safe = safe.replace(reg, '<span class="sql-fn">$1</span>');
  });

  // SQL Keywords
  const kws = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "LIKE", "BETWEEN",
    "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET", "AS", "JOIN",
    "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "ON", "ASC", "DESC", "DISTINCT", "IS", "NULL",
    "EXISTS", "UNION", "ALL", "ANY", "CASE", "WHEN", "THEN", "ELSE", "END"
  ];
  kws.forEach((kw) => {
    const reg = new RegExp(`\\b(${kw.replace(/ /g, "\\s+")})\\b`, "gi");
    safe = safe.replace(reg, (m) => `<span class="sql-kw">${m.toUpperCase()}</span>`);
  });

  // Numbers. The placeholder alternative is matched first and passed through
  // untouched - its index is a bare digit sitting between two non-word
  // characters, so \b would otherwise happily wrap it in a sql-num span and
  // break the restore step below.
  safe = safe.replace(/\uE000\d+\uE001|\b(\d+(?:\.\d+)?)\b/g, (m, num) =>
    num === undefined ? m : `<span class="sql-num">${num}</span>`
  );

  // Restore string literals wrapped in the sql-str span
  safe = safe.replace(/\uE000(\d+)\uE001/g, (_, idx) =>
    `<span class="sql-str">${escapeHTML(literals[Number(idx)])}</span>`
  );

  return safe;
}

function renderSQLOutput(sql) {
  const queryOutput = document.getElementById("queryOutput");
  if (!queryOutput) return;
  queryOutput.innerHTML = highlightSQL(sql);
}

function formatCurrentSQL() {
  if (!lastSQL) return;
  const formatted = formatSQL(lastSQL);
  lastSQL = formatted;
  renderSQLOutput(formatted);
  showToast("Formatted SQL query.");
}

function toggleExplainSQL() {
  const box = document.getElementById("queryExplanationBox");
  if (!box) return;

  if (box.style.display === "block") {
    box.style.display = "none";
    return;
  }

  if (!lastSQL) return;

  let fullHtml = "";

  // Render execution & reasoning trace if available
  if (window.lastTrace && window.lastTrace.length > 0) {
    const isHealed = window.lastSource === "agentic_self_healed";
    const isAi = window.lastSource === "agentic" || isHealed;
    const sourceClass = isHealed ? "source-badge-healed" : (isAi ? "source-badge-ai" : "source-badge-rule");
    const sourceLabel = isHealed
      ? `🛠️ Self-Healed (${window.lastRepairs || 1} attempt${(window.lastRepairs || 1) === 1 ? "" : "s"})`
      : (isAi ? "🤖 Agentic AI" : "⚙️ Rule-Based");

    const traceItems = window.lastTrace.map((step, idx) => {
      let extraClass = "";
      const lower = step.toLowerCase();
      if (lower.includes("failed") || lower.includes("error")) {
        extraClass = "is-healed";
      } else if (lower.includes("success") || lower.includes("corrected")) {
        extraClass = "is-success";
      }
      return `
        <li class="trace-step-item ${extraClass}">
          <span class="trace-step-num">${idx + 1}</span>
          <span class="trace-step-text">${escapeHTML(step)}</span>
        </li>
      `;
    }).join("");

    fullHtml += `
      <div class="trace-section">
        <div class="trace-header">
          <span class="trace-title">Execution & Reasoning Trace</span>
          <span class="trace-source-pill ${sourceClass}">${sourceLabel}</span>
        </div>
        <ol class="trace-list">
          ${traceItems}
        </ol>
      </div>
    `;
  }

  fullHtml += `
    <div class="sql-analysis-title">🔍 Query Structure Analysis</div>
    ${generateSQLExplanation(lastSQL)}
  `;

  document.getElementById("queryExplanationContent").innerHTML = fullHtml;
  box.style.display = "block";
}

function generateSQLExplanation(sql) {
  const points = [];

  // Every fragment below is a raw slice of the generated SQL, and a WHERE
  // fragment can carry a user's own words inside a string literal
  // ("... WHERE Student_Name = '<img src=x onerror=...>'"). Interpolating
  // those into innerHTML unescaped turned the question box into a script
  // injection point, so each one goes through escapeHTML on the way in.
  const fromMatch = sql.match(/FROM\s+([a-zA-Z0-9_]+)/i);
  if (fromMatch) {
    points.push(`<strong>Source Table:</strong> Queries records from the <code>${escapeHTML(fromMatch[1])}</code> table.`);
  }

  const joinMatches = sql.match(/(?:LEFT\s+|INNER\s+|RIGHT\s+)?JOIN\s+([a-zA-Z0-9_]+)/gi);
  if (joinMatches) {
    const tables = joinMatches.map((j) => escapeHTML(j.replace(/.*JOIN\s+/i, "").trim()));
    points.push(`<strong>Table Joins:</strong> Merges data with <code>${tables.join(", ")}</code>.`);
  }

  const selectMatch = sql.match(/SELECT\s+(.*?)\s+FROM/is);
  if (selectMatch) {
    const cols = selectMatch[1].trim();
    if (cols === "*") {
      points.push(`<strong>Columns:</strong> Retrieves all available attributes (<code>*</code>).`);
    } else {
      points.push(`<strong>Selected Attributes:</strong> Extracts <code>${escapeHTML(cols)}</code>.`);
    }
  }

  const whereMatch = sql.match(/WHERE\s+(.*?)(?:\s+GROUP\s+BY|\s+ORDER\s+BY|\s+LIMIT|$)/is);
  if (whereMatch) {
    points.push(`<strong>Criteria:</strong> Filters rows matching <code>${escapeHTML(whereMatch[1].trim())}</code>.`);
  }

  const groupMatch = sql.match(/GROUP\s+BY\s+(.*?)(?:\s+HAVING|\s+ORDER\s+BY|\s+LIMIT|$)/is);
  if (groupMatch) {
    points.push(`<strong>Grouping:</strong> Aggregates rows by <code>${escapeHTML(groupMatch[1].trim())}</code>.`);
  }

  const orderMatch = sql.match(/ORDER\s+BY\s+(.*?)(?:\s+LIMIT|$)/is);
  if (orderMatch) {
    points.push(`<strong>Sorting:</strong> Arranges output by <code>${escapeHTML(orderMatch[1].trim())}</code>.`);
  }

  const limitMatch = sql.match(/LIMIT\s+(\d+)/i);
  if (limitMatch) {
    points.push(`<strong>Row Limit:</strong> Capped at <strong>${escapeHTML(limitMatch[1])}</strong> records.`);
  }

  if (points.length === 0) {
    return `<p>Custom SQL statement: <code>${escapeHTML(sql)}</code></p>`;
  }

  return `<ul>${points.map((p) => `<li>${p}</li>`).join("")}</ul>`;
}

// ---------------- ADMIN PANEL ----------------

let schemaCache = null;
let primaryKeyCache = {}; // { table: pk_column } - not every table uses "id"

function authHeaders() {
  return {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + getToken()
  };
}

// Shared 401 handling for the admin panel - if the JWT expired while the
// admin was mid-edit, bounce them back to the login screen instead of
// leaving them staring at a confusing "Couldn't reach the backend" error.
function handleSessionExpired() {
  clearSession();
  showAuthScreen();
  setAuthStatus("Your session expired. Please log in again.", true);
  return true;
}

// app_users is off-limits in the generic admin panel - handled via
// /signup and manual DB inserts instead, never through this form.
const ADMIN_HIDDEN_TABLES = ["app_users"];

function loadAdminPanel() {
  if (getRole() !== "admin") return;

  Promise.all([
    fetch(API_BASE + "/schema").then((r) => r.json()),
    fetch(API_BASE + "/schema/keys").then((r) => r.json()).catch(() => ({}))
  ])
    .then(([schema, primaryKeys]) => {
      schemaCache = schema;
      primaryKeyCache = primaryKeys || {};

      const select = document.getElementById("adminTableSelect");
      const previouslySelected = select.value;

      select.innerHTML = "";
      Object.keys(schema)
        .filter((table) => !ADMIN_HIDDEN_TABLES.includes(table))
        .forEach((table) => {
          const opt = document.createElement("option");
          opt.value = table;
          opt.textContent = table;
          select.appendChild(opt);
        });

      // keep the same table selected across a refresh (e.g. after adding
      // a column) instead of always resetting to the first option
      if (previouslySelected && schema[previouslySelected]) {
        select.value = previouslySelected;
      }

      renderAdminFields();
      updateRowIdLabels();
    })
    .catch((error) => console.log("Couldn't load schema:", error));
}

// Not every table's primary key is called "id" - in the live schema it is
// only app_users (student_info -> Student_ID, subject -> Subject_ID, course
// -> Course_ID, department -> Department_ID, employee_info -> Employee_ID,
// project -> Project_ID) - so fall back to "id" only when we have no better
// info.
function getPrimaryKeyColumn(table) {
  return primaryKeyCache[table] || "id";
}

// Keeps the "Row ID" labels on the Update/Delete tabs honest about which
// column they actually mean, e.g. "Row student_id" instead of always
// "Row ID" when the table's key isn't literally called id.
function updateRowIdLabels() {
  const table = document.getElementById("adminTableSelect")?.value;
  if (!table) return;
  const pk = getPrimaryKeyColumn(table);

  const updateLabel = document.querySelector('label[for="updateId"]');
  if (updateLabel) updateLabel.textContent = pk === "id" ? "Row ID" : `Row ${pk}`;

  const deleteLabel = document.querySelector('label[for="deleteId"]');
  if (deleteLabel) deleteLabel.textContent = pk === "id" ? "Row ID" : `Row ${pk}`;
}

document.getElementById("adminTableSelect")?.addEventListener("change", () => {
  renderAdminFields();
  updateRowIdLabels();
  clearUpdateForm();
  clearDeleteForm();
});

function renderAdminFields() {
  if (!schemaCache) return;

  const table = document.getElementById("adminTableSelect").value;
  const columns = schemaCache[table] || {};
  const pk = getPrimaryKeyColumn(table);

  const buildFields = (containerId, idPrefix) => {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = "";

    Object.keys(columns).forEach((col) => {
      if (col === pk) return; // auto-increment primary key, handled separately

      const row = document.createElement("div");
      row.className = "field-row";

      const label = document.createElement("label");
      label.className = "field-label";
      label.textContent = `${col} (${columns[col]})`;

      const input = document.createElement("input");
      input.type = "text";
      input.className = "field-input";
      input.id = `${idPrefix}_${col}`;
      input.dataset.column = col;
      input.placeholder = `Enter ${col} to search/autofill`;

      // When user enters a value and leaves or presses Enter in Update or Delete,
      // search and autofill the other fields!
      if (idPrefix === "update" || idPrefix === "delete") {
        input.addEventListener("blur", () => {
          if (input.value.trim()) {
            fetchRowForAdmin(idPrefix, col, input.value.trim());
          }
        });
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (input.value.trim()) {
              fetchRowForAdmin(idPrefix, col, input.value.trim());
            }
          }
        });
      }

      row.appendChild(label);
      row.appendChild(input);
      container.appendChild(row);
    });
  };

  buildFields("insertFields", "insert");
  buildFields("updateFields", "update");
  buildFields("deleteFields", "delete");
}

// Attach auto-fill listeners to Row ID inputs
document.getElementById("updateId")?.addEventListener("blur", () => {
  const table = document.getElementById("adminTableSelect")?.value;
  const pk = getPrimaryKeyColumn(table);
  const val = document.getElementById("updateId").value.trim();
  if (val) fetchRowForAdmin("update", pk, val);
});
document.getElementById("updateId")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const table = document.getElementById("adminTableSelect")?.value;
    const pk = getPrimaryKeyColumn(table);
    const val = document.getElementById("updateId").value.trim();
    if (val) fetchRowForAdmin("update", pk, val);
  }
});

document.getElementById("deleteId")?.addEventListener("blur", () => {
  const table = document.getElementById("adminTableSelect")?.value;
  const pk = getPrimaryKeyColumn(table);
  const val = document.getElementById("deleteId").value.trim();
  if (val) fetchRowForAdmin("delete", pk, val);
});
document.getElementById("deleteId")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const table = document.getElementById("adminTableSelect")?.value;
    const pk = getPrimaryKeyColumn(table);
    const val = document.getElementById("deleteId").value.trim();
    if (val) fetchRowForAdmin("delete", pk, val);
  }
});

function fetchRowForAdmin(panelType, colName, value) {
  const table = document.getElementById("adminTableSelect")?.value;
  if (!table || !value || String(value).trim() === "") return;

  const statusId = panelType === "update" ? "updateStatus" : "deleteStatus";
  setAdminStatus(statusId, `Searching by ${colName}='${value}'...`, false);

  const pk = getPrimaryKeyColumn(table);
  const isPk = colName === pk || colName === "id";
  const url = isPk
    ? `${API_BASE}/admin/row?table=${encodeURIComponent(table)}&id=${encodeURIComponent(value.trim())}`
    : `${API_BASE}/admin/row?table=${encodeURIComponent(table)}&column=${encodeURIComponent(colName)}&value=${encodeURIComponent(value.trim())}`;

  fetch(url, {
    method: "GET",
    headers: authHeaders()
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      if (!ok || body.error) {
        setAdminStatus(statusId, body.error || "No matching record found.", true);
        return;
      }

      const row = body.row || {};
      const idInput = document.getElementById(panelType === "update" ? "updateId" : "deleteId");
      if (idInput && row[pk] !== undefined) {
        idInput.value = row[pk];
      }

      const containerId = panelType === "update" ? "updateFields" : "deleteFields";
      document.querySelectorAll(`#${containerId} [data-column]`).forEach((input) => {
        const col = input.dataset.column;
        const val = row[col];
        input.value = (val === null || val === undefined) ? "" : val;
      });

      const actionPrompt = panelType === "update" ? "Edit fields and click 'Update row'." : "Review record and click 'Delete row'.";
      setAdminStatus(statusId, `Record loaded (${pk}: ${row[pk] || 'N/A'}). ${actionPrompt}`, false);
    })
    .catch((error) => {
      setAdminStatus(statusId, "Couldn't reach the backend.", true);
      console.log(error);
    });
}

function clearUpdateForm() {
  const idInput = document.getElementById("updateId");
  if (idInput) idInput.value = "";
  document.querySelectorAll("#updateFields [data-column]").forEach((input) => input.value = "");
  setAdminStatus("updateStatus", "", false);
}

function clearDeleteForm() {
  const idInput = document.getElementById("deleteId");
  if (idInput) idInput.value = "";
  document.querySelectorAll("#deleteFields [data-column]").forEach((input) => input.value = "");
  setAdminStatus("deleteStatus", "", false);
}

document.getElementById("adminTabs")?.addEventListener("click", (e) => {
  const tabBtn = e.target.closest(".admin-tab");
  if (!tabBtn) return;

  document.querySelectorAll(".admin-tab").forEach((b) => b.classList.remove("active"));
  tabBtn.classList.add("active");

  const tab = tabBtn.dataset.tab;
  document.getElementById("adminPanelInsert").style.display = tab === "insert" ? "block" : "none";
  document.getElementById("adminPanelUpdate").style.display = tab === "update" ? "block" : "none";
  document.getElementById("adminPanelDelete").style.display = tab === "delete" ? "block" : "none";
  document.getElementById("adminPanelColumn").style.display = tab === "column" ? "block" : "none";
  document.getElementById("adminPanelTable").style.display = tab === "table" ? "block" : "none";
  document.getElementById("adminPanelDropTable").style.display = tab === "droptable" ? "block" : "none";

  const tableSelectRow = document.getElementById("adminTableSelectRow");
  if (tableSelectRow) {
    tableSelectRow.style.display = tab === "table" ? "none" : "flex";
  }

  if (tab === "table" && document.getElementById("newTableColumns").children.length === 0) {
    addTableColumnRow();
  }

  if (tab === "droptable") {
    updateDropTableLabel();
  }
});

document.getElementById("adminTableSelect")?.addEventListener("change", () => {
  const confirmInput = document.getElementById("dropTableConfirmInput");
  if (confirmInput) confirmInput.value = "";
  updateDropTableLabel();
});

function updateDropTableLabel() {
  const label = document.getElementById("dropTableTargetName");
  const select = document.getElementById("adminTableSelect");
  if (!label || !select) return;
  label.textContent = select.value || "this table";
}

function collectFields(containerId) {
  const data = {};
  document.querySelectorAll(`#${containerId} [data-column]`).forEach((input) => {
    if (input.value !== "") {
      data[input.dataset.column] = input.value;
    }
  });
  return data;
}

function setAdminStatus(elId, message, isError) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("is-error", Boolean(isError));
}

function submitInsert() {
  const table = document.getElementById("adminTableSelect").value;
  const data = collectFields("insertFields");

  setAdminStatus("insertStatus", "Inserting...", false);

  fetch(API_BASE + "/admin/insert", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ table, data })
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      if (!ok || body.error) {
        setAdminStatus("insertStatus", body.error || "Insert failed.", true);
        return;
      }
      setAdminStatus("insertStatus", `Inserted row with id ${body.id}.`, false);
    })
    .catch((error) => {
      setAdminStatus("insertStatus", "Couldn't reach the backend.", true);
      console.log(error);
    });
}

function submitUpdate() {
  const table = document.getElementById("adminTableSelect").value;
  const id = document.getElementById("updateId").value.trim();
  const data = collectFields("updateFields");

  if (!id) {
    setAdminStatus("updateStatus", "Enter a Row ID to update.", true);
    return;
  }

  setAdminStatus("updateStatus", "Updating...", false);

  fetch(API_BASE + "/admin/update", {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify({ table, id, data })
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      if (!ok || body.error) {
        setAdminStatus("updateStatus", body.error || "Update failed.", true);
        return;
      }
      setAdminStatus("updateStatus", `Updated ${body.rows_affected} row(s).`, false);
    })
    .catch((error) => {
      setAdminStatus("updateStatus", "Couldn't reach the backend.", true);
      console.log(error);
    });
}

function submitDelete(confirmMulti = false) {
  const table = document.getElementById("adminTableSelect").value;
  const id = document.getElementById("deleteId")?.value.trim();
  const data = collectFields("deleteFields");

  if (!id && Object.keys(data).length === 0) {
    setAdminStatus("deleteStatus", "Enter a Row ID or at least one column value to delete.", true);
    return;
  }

  const deleteDesc = id ? `Row ID ${id}` : `records matching ${JSON.stringify(data)}`;
  // On the re-send after a multi-row warning the admin has already confirmed,
  // so asking the generic question again would just be a second dialog.
  if (!confirmMulti && !confirm(`Delete ${deleteDesc} from '${table}'? This cannot be undone.`)) {
    return;
  }

  setAdminStatus("deleteStatus", "Deleting...", false);

  fetch(API_BASE + "/admin/delete", {
    method: "DELETE",
    headers: authHeaders(),
    body: JSON.stringify({
      table,
      id: id || null,
      data: Object.keys(data).length > 0 ? data : null,
      confirm: confirmMulti
    })
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      // Deleting by column values is a bulk operation unless those values pin
      // down exactly one row, so the backend refuses a wider match and asks
      // for an explicit confirm. Re-ask with the count in the prompt rather
      // than silently deleting N rows off the first click.
      if (body.requires_confirmation && body.matches > 1) {
        if (confirmMulti) {
          setAdminStatus("deleteStatus", body.error || "Delete failed.", true);
          return;
        }
        const goAhead = confirm(
          `${body.matches} rows in '${table}' match those values.\n\n` +
          `Delete all ${body.matches} of them? This cannot be undone.`
        );
        if (goAhead) {
          submitDelete(true);
        } else {
          setAdminStatus("deleteStatus", "Delete cancelled - nothing was removed.", false);
        }
        return;
      }
      if (!ok || body.error) {
        setAdminStatus("deleteStatus", body.error || "Delete failed.", true);
        return;
      }
      setAdminStatus("deleteStatus", `Deleted ${body.rows_affected} row(s).`, false);
      clearDeleteForm();
    })
    .catch((error) => {
      setAdminStatus("deleteStatus", "Couldn't reach the backend.", true);
      console.log(error);
    });
}

// ---------------- ADD COLUMN ----------------

function submitAddColumn() {
  const table = document.getElementById("adminTableSelect").value;
  const column_name = document.getElementById("newColumnName").value.trim();
  const column_type = document.getElementById("newColumnType").value.trim();
  const nullable = document.getElementById("newColumnNullable").checked;
  const defaultVal = document.getElementById("newColumnDefault").value.trim();

  if (!column_name || !column_type) {
    setAdminStatus("columnStatus", "Enter a column name and type.", true);
    return;
  }

  setAdminStatus("columnStatus", "Adding column...", false);

  fetch(API_BASE + "/admin/column/add", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      table,
      column_name,
      column_type,
      nullable,
      default: defaultVal || null
    })
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      if (!ok || body.error) {
        setAdminStatus("columnStatus", body.error || "Add column failed.", true);
        return;
      }

      setAdminStatus("columnStatus", `Column '${column_name}' added to '${table}'.`, false);

      // clear the form
      document.getElementById("newColumnName").value = "";
      document.getElementById("newColumnType").value = "";
      document.getElementById("newColumnDefault").value = "";
      document.getElementById("newColumnNullable").checked = true;

      // refresh schema cache + Insert/Update fields so the new column
      // shows up immediately without a page reload
      loadAdminPanel();
    })
    .catch((error) => {
      setAdminStatus("columnStatus", "Couldn't reach the backend.", true);
      console.log(error);
    });
}

// ---------------- ADD TABLE ----------------
// Builds a table from a name + a list of columns entered in dynamic rows.
// Each row mirrors what /admin/column/add already asks for (name, type,
// nullable, default) - create_table() on the backend accepts exactly
// that shape, so a new table's columns and later-added columns go
// through the same validation path.

let tableColumnRowId = 0;

function addTableColumnRow() {
  const container = document.getElementById("newTableColumns");
  const rowId = `tcol_${tableColumnRowId++}`;

  const row = document.createElement("div");
  row.className = "table-column-row";
  row.dataset.rowId = rowId;

  row.innerHTML = `
    <input type="text" class="field-input" placeholder="Column name" data-field="name">
    <input type="text" class="field-input" placeholder="Type, e.g. VARCHAR(255)" data-field="type">
    <label class="checkbox-label">
      <input type="checkbox" data-field="nullable" checked>
      Nullable
    </label>
    <input type="text" class="field-input" placeholder="Default (optional)" data-field="default">
    <button type="button" class="table-column-remove" title="Remove column" onclick="removeTableColumnRow('${rowId}')">&times;</button>
  `;

  container.appendChild(row);
}

function removeTableColumnRow(rowId) {
  const row = document.querySelector(`.table-column-row[data-row-id="${rowId}"]`);
  if (row) row.remove();
}

function collectTableColumns() {
  const columns = [];
  document.querySelectorAll("#newTableColumns .table-column-row").forEach((row) => {
    const name = row.querySelector('[data-field="name"]').value.trim();
    const type = row.querySelector('[data-field="type"]').value.trim();
    const nullable = row.querySelector('[data-field="nullable"]').checked;
    const defaultVal = row.querySelector('[data-field="default"]').value.trim();

    // A fully blank row (user added one but never filled it in) is
    // silently skipped rather than sent as a column with no name/type.
    if (!name && !type) return;

    columns.push({
      name,
      type,
      nullable,
      default: defaultVal || null
    });
  });
  return columns;
}

function resetAddTableForm() {
  document.getElementById("newTableName").value = "";
  document.getElementById("newTableColumns").innerHTML = "";
  tableColumnRowId = 0;
  addTableColumnRow();
}

function submitCreateTable() {
  const tableName = document.getElementById("newTableName").value.trim();
  const columns = collectTableColumns();

  if (!tableName) {
    setAdminStatus("tableStatus", "Enter a table name.", true);
    return;
  }

  // Catch incomplete rows client-side too - a row with just a name and no
  // type (or vice versa) would fail the backend's column-type validation
  // anyway, so flag it here with a clearer message.
  const incomplete = columns.some((c) => !c.name || !c.type);
  if (incomplete) {
    setAdminStatus("tableStatus", "Every column needs both a name and a type.", true);
    return;
  }

  setAdminStatus("tableStatus", "Creating table...", false);

  fetch(API_BASE + "/admin/table/add", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ table_name: tableName, columns })
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      if (!ok || body.error) {
        setAdminStatus("tableStatus", body.error || "Create table failed.", true);
        return;
      }

      setAdminStatus("tableStatus", `Table '${body.table}' created.`, false);
      resetAddTableForm();

      // refresh the table dropdown so the new table is immediately
      // selectable from Insert/Update/Delete/Add Column without a reload
      loadAdminPanel();
    })
    .catch((error) => {
      setAdminStatus("tableStatus", "Couldn't reach the backend.", true);
      console.log(error);
    });
}

// ---------------- DELETE TABLE ----------------
// Deliberately does NOT use a confirm() popup or a plain button click -
// the admin has to type the exact table name, same posture the backend
// comments already call for on drop_table()'s confirm flag. This makes
// an accidental click (or a stray Enter keypress) harmless.

function submitDropTable() {
  const table = document.getElementById("adminTableSelect").value;
  const typed = document.getElementById("dropTableConfirmInput").value.trim();

  if (!table) {
    setAdminStatus("dropTableStatus", "No table selected.", true);
    return;
  }

  if (typed !== table) {
    setAdminStatus("dropTableStatus", `Type '${table}' exactly to confirm.`, true);
    return;
  }

  setAdminStatus("dropTableStatus", "Deleting table...", false);

  fetch(API_BASE + "/admin/table/delete", {
    method: "DELETE",
    headers: authHeaders(),
    body: JSON.stringify({ table_name: table, confirm: true })
  })
    .then((r) => r.json().then((body) => ({ status: r.status, ok: r.ok, body })))
    .then(({ status, ok, body }) => {
      if (status === 401) {
        handleSessionExpired();
        return;
      }
      if (!ok || body.error) {
        setAdminStatus("dropTableStatus", body.error || "Delete table failed.", true);
        return;
      }

      setAdminStatus("dropTableStatus", `Table '${body.table}' deleted.`, false);
      document.getElementById("dropTableConfirmInput").value = "";

      // refresh the table dropdown so the deleted table disappears from
      // every tab immediately, instead of lingering until reload
      loadAdminPanel();
      updateDropTableLabel();
    })
    .catch((error) => {
      setAdminStatus("dropTableStatus", "Couldn't reach the backend.", true);
      console.log(error);
    });
}

// ---------------- OUTPUT TABLE & EXPORT TOOLS ----------------

function renderTableFromData(data) {
  const tableEl = document.getElementById("resultsTable");
  const noResultsEl = document.getElementById("noResultsFiltered");
  const rowCountEl = document.getElementById("rowCount");

  if (!data || data.length === 0) {
    tableEl.innerHTML = `
      <div class="empty-table-state" style="display:block; padding: 28px 16px; text-align: center;">
        <p style="font-weight: 600; color: var(--text); margin-bottom: 4px;">0 rows returned</p>
        <p style="font-size: 13px; color: var(--text-dim);">No database records matched your query criteria.</p>
      </div>
    `;
    if (noResultsEl) noResultsEl.style.display = "none";
    if (rowCountEl) rowCountEl.textContent = "0 rows";
    return;
  }

  if (noResultsEl) noResultsEl.style.display = "none";
  if (rowCountEl) rowCountEl.textContent = `${data.length} ${data.length === 1 ? "row" : "rows"}`;

  let headerRow = "<tr>";
  for (let key in data[0]) {
    headerRow += `<th>${escapeHTML(key)}</th>`;
  }
  headerRow += "</tr>";

  let bodyRows = "";
  data.forEach((row) => {
    bodyRows += "<tr>";
    for (let key in row) {
      const val = row[key] !== null && row[key] !== undefined ? row[key] : "NULL";
      bodyRows += `<td>${escapeHTML(String(val))}</td>`;
    }
    bodyRows += "</tr>";
  });

  tableEl.innerHTML = `<thead>${headerRow}</thead><tbody>${bodyRows}</tbody>`;
}

function showOutput() {
  const data = window.resultData;
  const section = document.getElementById("outputSection");
  if (!section) return;

  const searchInput = document.getElementById("tableSearchInput");
  if (searchInput) searchInput.value = "";
  window.filteredData = data || [];

  section.style.display = "block";
  renderTableFromData(data || []);
}

function filterResultsTable(filterQuery) {
  if (!window.resultData) return;
  const q = filterQuery.trim().toLowerCase();

  if (!q) {
    window.filteredData = window.resultData;
  } else {
    window.filteredData = window.resultData.filter((row) => {
      return Object.values(row).some((val) =>
        String(val).toLowerCase().includes(q)
      );
    });
  }

  renderTableFromData(window.filteredData);
}

function exportToCSV() {
  const data = window.filteredData || window.resultData;
  if (!data || data.length === 0) {
    showToast("No data to export.");
    return;
  }

  const headers = Object.keys(data[0]);
  const rows = data.map((row) =>
    headers
      .map((header) => {
        let val = row[header] === null || row[header] === undefined ? "" : String(row[header]);
        val = val.replace(/"/g, '""');
        return `"${val}"`;
      })
      .join(",")
  );

  const csvContent = [headers.map((h) => `"${h}"`).join(","), ...rows].join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `query_result_${Date.now()}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("CSV exported successfully!");
}

function exportToJSON() {
  const data = window.filteredData || window.resultData;
  if (!data || data.length === 0) {
    showToast("No data to export.");
    return;
  }

  const jsonStr = JSON.stringify(data, null, 2);
  const blob = new Blob([jsonStr], { type: "application/json;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `query_result_${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("JSON exported successfully!");
}

function copyTableData() {
  const data = window.filteredData || window.resultData;
  if (!data || data.length === 0) {
    showToast("No data to copy.");
    return;
  }

  const headers = Object.keys(data[0]);
  const rows = data.map((row) =>
    headers.map((h) => (row[h] !== null && row[h] !== undefined ? String(row[h]) : "")).join("\t")
  );
  const tsv = [headers.join("\t"), ...rows].join("\n");

  navigator.clipboard.writeText(tsv).then(() => {
    showToast("Table copied (TSV) - ready to paste in Excel!");
  }).catch(() => {
    showToast("Could not copy table to clipboard.");
  });
}

// ---------------- QUERY FEEDBACK CHATBOT ----------------

function resetChat() {
  if (!chatLog) return;
  chatLog.innerHTML = "";
  chatFeedbackText.value = "";
  setChatStatus("", false);
  chatSatisfaction.style.display = "block";
  chatFeedbackInput.style.display = "none";
}

function setChatStatus(message, isError) {
  chatStatusText.textContent = message;
  chatStatusText.classList.toggle("is-error", Boolean(isError));
}

function appendChatMessage(text, role) {
  const bubble = document.createElement("div");
  bubble.className = `chat-msg chat-msg-${role}`;
  bubble.textContent = text;
  chatLog.appendChild(bubble);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function handleSatisfaction(satisfied) {
  if (satisfied) {
    resetConsoleState();
    setStatus("Query confirmed & cleared! Ready for your next query.", false);
    userInput.focus();
    showToast("Done! Query and results cleared for new search.");
    return;
  }

  appendChatMessage("What would you like to change, or what's incorrect?", "bot");
  chatSatisfaction.style.display = "none";
  chatFeedbackInput.style.display = "block";
  chatFeedbackText.focus();
}

function applyQuickRefine(suggestionText) {
  chatFeedbackText.value = suggestionText;
  chatFeedbackText.focus();
}

function updateQuickRefineSuggestions(sql) {
  const container = document.getElementById("quickPillsWrap");
  if (!container) return;

  const sqlLower = (sql || "").toLowerCase();

  // Ordered most-specific first: "employee_info" also appears inside a
  // join to "performance", and "marks" inside a query whose SQL merely
  // SELECTs marks, so match the table that the FROM clause is actually on
  // and fall back to narrower keyword checks.
  let suggestions = [];

  if (sqlLower.includes("from employee_info")) {
    suggestions = [
      "sort by employee_id ascending",
      "only show employee_name and phone_no",
      "show employees from the IT department",
      "limit to 5"
    ];
  } else if (sqlLower.includes("from project")) {
    suggestions = [
      "sort by start_year descending",
      "only show project_name and budget",
      "projects with budget above 1000000",
      "limit to 5"
    ];
  } else if (sqlLower.includes("from performance")) {
    suggestions = [
      "only show result and rating",
      "show only excellent results",
      "sort by rating descending",
      "limit to 5"
    ];
  } else if (sqlLower.includes("from department")) {
    suggestions = [
      "only show department_name",
      "sort by department_name ascending",
      "limit to 5"
    ];
  } else if (sqlLower.includes("from marks")) {
    suggestions = [
      "sort by marks descending",
      "show marks above 60",
      "average marks per subject",
      "student name along with their marks"
    ];
  } else if (sqlLower.includes("from student_info")) {
    suggestions = [
      "sort by student_id ascending",
      "only show student_name and phone_no",
      "show only students from Bengaluru",
      "limit to 5"
    ];
  } else if (sqlLower.includes("from subject")) {
    suggestions = [
      "sort by max_marks descending",
      "subjects with max marks above 50",
      "only show subject_name and semester",
      "average marks per subject"
    ];
  } else if (sqlLower.includes("from course")) {
    suggestions = [
      "only show course_name",
      "subjects under each course",
      "limit to 5"
    ];
  } else {
    suggestions = [
      "sort descending",
      "limit to 5",
      "only show key columns",
      "group by department"
    ];
  }

  // Same reasoning as the schema drawer: the text rides in a data attribute
  // read via .dataset, not inside an inline onclick="applyQuickRefine('...')"
  // string, so a suggestion containing a quote can't terminate the handler.
  if (!container.dataset.refineListenerBound) {
    container.dataset.refineListenerBound = "1";
    container.addEventListener("click", (event) => {
      const pill = event.target.closest("[data-refine]");
      if (pill && container.contains(pill)) applyQuickRefine(pill.dataset.refine);
    });
  }

  container.innerHTML = suggestions
    .map((s) => `<button type="button" class="quick-pill" data-refine="${escapeHTML(s)}">${escapeHTML(s)}</button>`)
    .join("");
}

function submitChatFeedback() {
  const feedback = chatFeedbackText.value.trim();

  if (!feedback) {
    setChatStatus("Type what you'd like to change first.", true);
    return;
  }

  if (!lastSQL) {
    setChatStatus("There's no previous query to refine yet.", true);
    return;
  }

  const token = getToken();
  if (!token) {
    showAuthScreen();
    setAuthStatus("Please log in first.", true);
    return;
  }

  appendChatMessage(feedback, "user");
  chatFeedbackText.value = "";
  chatSubmitBtn.disabled = true;
  setChatStatus("Refining query with feedback...", false);

  fetch(API_BASE + "/query/refine", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      previous_sql: lastSQL,
      feedback: feedback
    })
  })
    .then((response) => response.json().then((data) => ({ status: response.status, data })))
    .then(({ status, data }) => {
      chatSubmitBtn.disabled = false;
      if (status === 401) {
        clearSession();
        showAuthScreen();
        setAuthStatus("Your session expired. Please log in again.", true);
        return;
      }

      if (data.error) {
        setChatStatus("", false);
        appendChatMessage(data.error, "error");
        return;
      }

      lastSQL = data.sql || lastSQL;
      renderSQLOutput(lastSQL);

      applySourceBadge(data);

      window.resultData = data.data;
      window.lastTrace = data.trace || [];
      window.lastSource = data.source || "";
      window.lastRepairs = data.repair_attempts || 0;
      updateQuickRefineSuggestions(lastSQL);
      showOutput();

      // Add to query history
      addQueryHistory({
        question: `(Refined) ${feedback}`,
        sql: lastSQL,
        source: data.source || (data.used_ai_fallback ? "agentic" : "rule_based"),
        repair_attempts: data.repair_attempts || 0,
        used_ai_fallback: Boolean(data.used_ai_fallback),
        rowCount: (data.data ? data.data.length : 0),
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      });

      setChatStatus("", false);
      const changeSummary = (data.applied_changes && data.applied_changes.length)
        ? `Updated: ${data.applied_changes.join(", ")}.`
        : "Updated the query.";
      appendChatMessage(changeSummary, "bot");

      // When the backend had to give up on finding a version of the query
      // that matches, say so here. The results table's own empty state reads
      // "No database records matched your query criteria", which sounds like
      // confirmation that the filters were right - but the real situation is
      // usually that the request named something this database doesn't have
      // (a "final exam", a first name where the column stores a full name).
      if (data.empty_result) {
        appendChatMessage(
          "This matched 0 rows and I couldn't find a better version - the thing you asked about may not exist in this database. Check the values in the SQL above, or try naming it differently.",
          "error"
        );
      }

      appendChatMessage("Does this query and output satisfy you?", "bot");
      chatFeedbackInput.style.display = "none";
      chatSatisfaction.style.display = "block";
    })
    .catch((error) => {
      chatSubmitBtn.disabled = false;
      setChatStatus("Couldn't reach the backend. Is the Flask server running?", true);
      console.log(error);
    });
}

// ---------------- SCHEMA EXPLORER DRAWER ----------------

let fullSchemaCache = null;

function loadSchemaTree() {
  const container = document.getElementById("schemaTree");
  if (!container) return;

  if (fullSchemaCache) {
    renderSchemaTree(fullSchemaCache);
    return;
  }

  fetch(API_BASE + "/schema")
    .then((r) => r.json())
    .then((schema) => {
      fullSchemaCache = schema;
      renderSchemaTree(schema);
    })
    .catch((err) => {
      container.innerHTML = `<div class="empty-history-text">Could not load schema from backend.</div>`;
      console.log(err);
    });
}

function renderSchemaTree(schema, filter = "") {
  const container = document.getElementById("schemaTree");
  if (!container) return;

  // One delegated listener for the whole drawer, attached to the container so
  // it survives the innerHTML swaps below. The table/column name travels in a
  // data attribute rather than an inline onclick="insertIntoPrompt('...')" -
  // escaping quotes is not enough inside an inline handler, because the HTML
  // parser decodes &#39; back to ' before the browser compiles the JS, so a
  // name like x');alert(1);// would break out and run.
  if (!container.dataset.insertListenerBound) {
    container.dataset.insertListenerBound = "1";
    container.addEventListener("click", (event) => {
      const target = event.target.closest("[data-insert]");
      if (!target || !container.contains(target)) return;
      const value = target.dataset.insert;
      if (value) insertIntoPrompt(value);
    });
  }

  const q = filter.trim().toLowerCase();
  const tables = Object.keys(schema).filter((t) => !ADMIN_HIDDEN_TABLES.includes(t));

  let html = "";
  let matchCount = 0;

  tables.forEach((table) => {
    const columns = schema[table] || {};
    const colEntries = Object.entries(columns);

    const tableMatches = table.toLowerCase().includes(q);
    const matchingCols = colEntries.filter(([col, type]) =>
      col.toLowerCase().includes(q) || String(type).toLowerCase().includes(q)
    );

    if (q && !tableMatches && matchingCols.length === 0) {
      return;
    }

    matchCount++;
    const colsToRender = q && !tableMatches ? matchingCols : colEntries;

    html += `
      <div class="schema-table-card">
        <div class="schema-table-header" data-insert="${escapeHTML(table)}" title="Click to insert table name into prompt">
          <span>\uD83D\uDDC3\uFE0F ${escapeHTML(table)}</span>
          <span class="schema-col-type">${colEntries.length} cols</span>
        </div>
        <ul class="schema-col-list">
          ${colsToRender.map(([col, type]) => `
            <li class="schema-col-item" data-insert="${escapeHTML(col)}" title="Click to insert column into prompt">
              <span>${escapeHTML(col)}</span>
              <span class="schema-col-type">${escapeHTML(type)}</span>
            </li>
          `).join("")}
        </ul>
      </div>
    `;
  });

  if (matchCount === 0) {
    html = `<div class="empty-history-text">No tables or columns match "${escapeHTML(filter)}"</div>`;
  }

  container.innerHTML = html;
}

function filterSchemaTree(val) {
  if (fullSchemaCache) {
    renderSchemaTree(fullSchemaCache, val);
  }
}

function insertIntoPrompt(text) {
  const input = userInput;
  const start = input.selectionStart || input.value.length;
  const end = input.selectionEnd || input.value.length;
  const current = input.value;

  const needsSpaceBefore = start > 0 && current[start - 1] !== " ";
  const needsSpaceAfter = end < current.length && current[end] !== " ";

  const insertion = (needsSpaceBefore ? " " : "") + text + (needsSpaceAfter ? " " : " ");
  input.value = current.substring(0, start) + insertion + current.substring(end);
  input.focus();
  const newPos = start + insertion.length;
  input.setSelectionRange(newPos, newPos);

  toggleClearButton();
  showToast(`Inserted "${text}" into query prompt`);
}

// ---------------- QUERY HISTORY STORAGE ----------------

const HISTORY_STORAGE_PREFIX = "nlq_sql_query_history_";

// Every logged-in user has their OWN history. The storage key is scoped to
// the current username (from sessionStorage) so one user never sees another
// user's queries, even on the same browser.
function getHistoryStorageKey() {
  const username = (sessionStorage.getItem("username") || "guest").toLowerCase();
  return HISTORY_STORAGE_PREFIX + username;
}

function getQueryHistory() {
  try {
    return JSON.parse(localStorage.getItem(getHistoryStorageKey()) || "[]");
  } catch {
    return [];
  }
}

function addQueryHistory(item) {
  const history = getQueryHistory();
  if (history.length > 0 && history[0].question === item.question && history[0].sql === item.sql) {
    return;
  }
  history.unshift(item);
  if (history.length > 30) history.pop();
  localStorage.setItem(getHistoryStorageKey(), JSON.stringify(history));
}

function clearQueryHistory() {
  localStorage.removeItem(getHistoryStorageKey());
  renderQueryHistory();
  showToast("Query history cleared.");
}

function renderQueryHistory() {
  const container = document.getElementById("historyList");
  if (!container) return;

  const history = getQueryHistory();
  if (history.length === 0) {
    container.innerHTML = `<div class="empty-history-text">No queries executed yet. Run a query to see it saved here!</div>`;
    return;
  }

  container.innerHTML = history.map((item, idx) => {
    const src = item.source || (item.used_ai_fallback ? "agentic" : "rule_based");
    let badgeClass = "source-badge-rule";
    let badgeText = "\u2699\uFE0F Rule";
    if (src === "agentic_self_healed") {
      badgeClass = "source-badge-healed";
      badgeText = "\uD83D\uDEE0\uFE0F Healed";
    } else if (src === "agentic") {
      badgeClass = "source-badge-ai";
      badgeText = "\uD83E\uDD16 AI";
    }
    return `
    <div class="history-card" onclick="loadHistoryItem(${idx})">
      <div class="history-card-top">
        <span class="history-question">${escapeHTML(item.question)}</span>
        <span class="source-badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="history-sql-preview">${escapeHTML(item.sql)}</div>
      <div class="history-meta">
        <span>${escapeHTML(item.rowCount)} ${item.rowCount === 1 ? "row" : "rows"}</span>
        <span>${escapeHTML(item.timestamp || "")}</span>
      </div>
    </div>
    `;
  }).join("");
}

function loadHistoryItem(index) {
  const history = getQueryHistory();
  const item = history[index];
  if (!item) return;

  userInput.value = item.question;
  toggleClearButton();
  closeAllDrawers();
  showSQL();
  showToast("Loaded query from history");
}