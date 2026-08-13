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

let lastSQL = "";
let authMode = "login"; // or "signup"

// ---------------- AUTH STATE ----------------

function getToken() {
  return localStorage.getItem("token");
}

function getRole() {
  return localStorage.getItem("role");
}

function saveSession(token, username, role) {
  localStorage.setItem("token", token);
  localStorage.setItem("username", username);
  localStorage.setItem("role", role);
}

function clearSession() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  localStorage.removeItem("role");
}

function resetConsoleState() {
  userInput.value = "";
  lastSQL = "";
  window.resultData = null;
  setStatus("", false);
  document.getElementById("sqlSection").style.display = "none";
  document.getElementById("outputSection").style.display = "none";
  document.querySelector(".query").innerText = "";
  document.querySelector("table").innerHTML = "";
}

function showApp() {
  const username = localStorage.getItem("username");
  const role = getRole();

  resetConsoleState();

  authScreen.style.display = "none";
  appSection.style.display = "block";

  userBadge.style.display = "flex";
  userBadgeText.textContent = `${username} - ${role}`;

  adminSection.style.display = role === "admin" ? "block" : "none";

  if (role === "admin") {
    loadAdminPanel();
  }
}

function showAuthScreen() {
  authScreen.style.display = "block";
  appSection.style.display = "none";
  userBadge.style.display = "none";
}

function logout() {
  clearSession();
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

// Press Enter to run the query, Shift+Enter for a new line
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    showSQL();
  }
});

// ---------------- CHIPS (existing behaviour) ----------------

document.getElementById("chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  userInput.value = chip.dataset.q;
  userInput.focus();
});

// ---------------- QUERY CONSOLE ----------------

function setStatus(message, isError) {
  statusText.textContent = message;
  statusText.classList.toggle("is-error", Boolean(isError));
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
  setStatus("Running query...", false);
  document.getElementById("outputSection").style.display = "none";

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

      if (status === 401) {
        // Token missing/expired - send them back to login
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
      document.getElementById("sqlSection").style.display = "block";
      document.querySelector(".query").innerText = lastSQL;

      window.resultData = data.data;
    })
    .catch((error) => {
      runBtn.disabled = false;
      setStatus("Couldn't reach the backend. Is the Flask server running?", true);
      console.log(error);
    });
}

function copySQL() {
  if (!lastSQL) return;

  navigator.clipboard.writeText(lastSQL).then(() => {
    const copyBtn = document.getElementById("copyBtn");
    const original = copyBtn.textContent;
    copyBtn.textContent = "Copied";
    setTimeout(() => {
      copyBtn.textContent = original;
    }, 1200);
  });
}

// ---------------- ADMIN PANEL ----------------

let schemaCache = null;

function authHeaders() {
  return {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + getToken()
  };
}

// app_users is off-limits in the generic admin panel - handled via
// /signup and manual DB inserts instead, never through this form.
const ADMIN_HIDDEN_TABLES = ["app_users"];

function loadAdminPanel() {
  if (getRole() !== "admin") return;

  fetch(API_BASE + "/schema")
    .then((r) => r.json())
    .then((schema) => {
      schemaCache = schema;

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
    })
    .catch((error) => console.log("Couldn't load schema:", error));
}

document.getElementById("adminTableSelect")?.addEventListener("change", renderAdminFields);

function renderAdminFields() {
  if (!schemaCache) return;

  const table = document.getElementById("adminTableSelect").value;
  const columns = schemaCache[table] || {};

  const buildFields = (containerId, idPrefix) => {
    const container = document.getElementById(containerId);
    container.innerHTML = "";

    Object.keys(columns).forEach((col) => {
      if (col === "id") return; // auto-increment primary key, not user-editable

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

      row.appendChild(label);
      row.appendChild(input);
      container.appendChild(row);
    });
  };

  buildFields("insertFields", "insert");
  buildFields("updateFields", "update");
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
});

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
    .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
    .then(({ ok, body }) => {
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
  const id = document.getElementById("updateId").value;
  const data = collectFields("updateFields");

  if (!id) {
    setAdminStatus("updateStatus", "Enter a row ID.", true);
    return;
  }

  setAdminStatus("updateStatus", "Updating...", false);

  fetch(API_BASE + "/admin/update", {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify({ table, id, data })
  })
    .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
    .then(({ ok, body }) => {
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

function submitDelete() {
  const table = document.getElementById("adminTableSelect").value;
  const id = document.getElementById("deleteId").value;

  if (!id) {
    setAdminStatus("deleteStatus", "Enter a row ID.", true);
    return;
  }

  if (!confirm(`Delete row ${id} from ${table}? This can't be undone.`)) {
    return;
  }

  setAdminStatus("deleteStatus", "Deleting...", false);

  fetch(API_BASE + "/admin/delete", {
    method: "DELETE",
    headers: authHeaders(),
    body: JSON.stringify({ table, id })
  })
    .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
    .then(({ ok, body }) => {
      if (!ok || body.error) {
        setAdminStatus("deleteStatus", body.error || "Delete failed.", true);
        return;
      }
      setAdminStatus("deleteStatus", `Deleted ${body.rows_affected} row(s).`, false);
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
    .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
    .then(({ ok, body }) => {
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

function showOutput() {
  const data = window.resultData;

  if (!data || data.length === 0) {
    setStatus("No rows found for that query.", true);
    return;
  }

  let table = "<tr>";

  for (let key in data[0]) {
    table += `<th>${key}</th>`;
  }
  table += "</tr>";

  data.forEach((row) => {
    table += "<tr>";
    for (let key in row) {
      table += `<td>${row[key]}</td>`;
    }
    table += "</tr>";
  });

  document.getElementById("outputSection").style.display = "block";
  document.getElementById("rowCount").textContent =
    data.length + (data.length === 1 ? " row" : " rows");
  document.querySelector("table").innerHTML = table;
}