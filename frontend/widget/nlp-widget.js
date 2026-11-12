(function () {
  "use strict";

  var SCRIPT = document.currentScript;
  if (!SCRIPT) {
    var scripts = document.getElementsByTagName("script");
    SCRIPT = scripts[scripts.length - 1];
  }

  var API_BASE = (SCRIPT.getAttribute("data-api-base") || window.location.origin || "http://localhost:5000").replace(/\/$/, "");
  var API_KEY = SCRIPT.getAttribute("data-api-key") || "demo";
  var TITLE = SCRIPT.getAttribute("data-title") || "Data Assistant";
  var THEME = SCRIPT.getAttribute("data-theme") || "auto";
  var POSITION = SCRIPT.getAttribute("data-position") || "right";

  function prefersDark() {
    if (THEME === "dark") return true;
    if (THEME === "light") return false;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  var css = [
    "#nlp-widget-root{all:initial;font-family:Inter,Segoe UI,system-ui,sans-serif;position:fixed;z-index:2147483000;bottom:24px;",
    POSITION === "left" ? "left:24px;" : "right:24px;",
    "}",
    "#nlp-widget-root *{box-sizing:border-box;font-family:inherit;}",
    "#nlp-widget-root .nlp-fab{width:56px;height:56px;border:0;border-radius:50%;cursor:pointer;color:#fff;font-size:22px;",
    "background:linear-gradient(135deg,#2563eb,#7c3aed);box-shadow:0 10px 30px rgba(37,99,235,.4);}",
    "#nlp-widget-root .nlp-panel{display:none;position:absolute;bottom:68px;width:min(420px,calc(100vw - 32px));height:560px;",
    "max-height:calc(100vh - 100px);border-radius:16px;overflow:hidden;flex-direction:column;",
    POSITION === "left" ? "left:0;" : "right:0;",
    "box-shadow:0 20px 50px rgba(15,23,42,.28);}",
    "#nlp-widget-root.open .nlp-panel{display:flex;}",
    "#nlp-widget-root .nlp-head{padding:14px 16px;display:flex;align-items:center;justify-content:space-between;color:#fff;",
    "background:linear-gradient(135deg,#2563eb,#7c3aed);}",
    "#nlp-widget-root .nlp-head h2{margin:0;font-size:15px;font-weight:650;}",
    "#nlp-widget-root .nlp-head small{display:block;opacity:.85;font-size:11px;margin-top:2px;}",
    "#nlp-widget-root .nlp-x{background:transparent;border:0;color:#fff;font-size:20px;cursor:pointer;}",
    "#nlp-widget-root .nlp-body{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px;}",
    "#nlp-widget-root .nlp-msg{max-width:95%;padding:10px 12px;border-radius:12px;font-size:13px;line-height:1.45;white-space:pre-wrap;}",
    "#nlp-widget-root .nlp-user{align-self:flex-end;background:#2563eb;color:#fff;}",
    "#nlp-widget-root .nlp-bot{align-self:flex-start;}",
    "#nlp-widget-root .nlp-badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.03em;padding:2px 7px;border-radius:999px;margin-right:6px;text-transform:uppercase;}",
    "#nlp-widget-root .nlp-table-wrap{overflow:auto;max-height:220px;margin-top:8px;border-radius:8px;}",
    "#nlp-widget-root table{border-collapse:collapse;width:100%;font-size:12px;}",
    "#nlp-widget-root th,#nlp-widget-root td{padding:6px 8px;border-bottom:1px solid rgba(148,163,184,.35);text-align:left;white-space:nowrap;}",
    "#nlp-widget-root .nlp-sql{margin-top:8px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;padding:8px;border-radius:8px;overflow:auto;}",
    "#nlp-widget-root .nlp-actions{display:flex;gap:8px;margin-top:8px;}",
    "#nlp-widget-root .nlp-actions button{font-size:11px;border-radius:8px;padding:5px 8px;cursor:pointer;}",
    "#nlp-widget-root .nlp-foot{display:flex;gap:8px;padding:10px;border-top:1px solid rgba(148,163,184,.3);}",
    "#nlp-widget-root .nlp-foot input{flex:1;border-radius:10px;padding:10px 12px;font-size:13px;outline:none;}",
    "#nlp-widget-root .nlp-foot button{border:0;border-radius:10px;padding:0 14px;color:#fff;background:#2563eb;cursor:pointer;font-weight:600;}",
    "#nlp-widget-root.light .nlp-panel{background:#fff;color:#0f172a;}",
    "#nlp-widget-root.light .nlp-bot{background:#f1f5f9;color:#0f172a;}",
    "#nlp-widget-root.light .nlp-foot{background:#fff;}",
    "#nlp-widget-root.light .nlp-foot input{border:1px solid #e2e8f0;background:#fff;color:#0f172a;}",
    "#nlp-widget-root.light .nlp-sql{background:#0f172a;color:#e2e8f0;}",
    "#nlp-widget-root.light .nlp-actions button{border:1px solid #cbd5e1;background:#fff;}",
    "#nlp-widget-root.dark .nlp-panel{background:#0f172a;color:#e2e8f0;}",
    "#nlp-widget-root.dark .nlp-bot{background:#1e293b;color:#e2e8f0;}",
    "#nlp-widget-root.dark .nlp-foot{background:#0f172a;border-top-color:#1e293b;}",
    "#nlp-widget-root.dark .nlp-foot input{border:1px solid #334155;background:#1e293b;color:#e2e8f0;}",
    "#nlp-widget-root.dark .nlp-sql{background:#020617;color:#cbd5e1;}",
    "#nlp-widget-root.dark .nlp-actions button{border:1px solid #334155;background:#1e293b;color:#e2e8f0;}",
    "#nlp-widget-root .ok{background:#dcfce7;color:#166534;}",
    "#nlp-widget-root .heal{background:#fef3c7;color:#92400e;}",
    "#nlp-widget-root .fail{background:#fee2e2;color:#991b1b;}",
    "#nlp-widget-root .info{background:#dbeafe;color:#1e40af;}"
  ].join("");

  var style = document.createElement("style");
  style.appendChild(document.createTextNode(css));
  document.head.appendChild(style);

  var root = document.createElement("div");
  root.id = "nlp-widget-root";
  root.className = prefersDark() ? "dark" : "light";
  root.innerHTML =
    '<button class="nlp-fab" type="button" aria-label="Open data assistant">✦</button>' +
    '<div class="nlp-panel" role="dialog" aria-label="' + TITLE.replace(/"/g, "") + '">' +
      '<div class="nlp-head"><div><h2></h2><small>Ask a question about your data</small></div>' +
      '<button class="nlp-x" type="button" aria-label="Close">×</button></div>' +
      '<div class="nlp-body"></div>' +
      '<form class="nlp-foot"><input type="text" placeholder="e.g. list employees in Sales" autocomplete="off" />' +
      '<button type="submit">Ask</button></form>' +
    "</div>";
  document.body.appendChild(root);
  root.querySelector("h2").textContent = TITLE;

  var body = root.querySelector(".nlp-body");
  var input = root.querySelector("input");
  var form = root.querySelector("form");

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function addBot(html) {
    var el = document.createElement("div");
    el.className = "nlp-msg nlp-bot";
    el.innerHTML = html;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
    return el;
  }

  function addUser(text) {
    var el = document.createElement("div");
    el.className = "nlp-msg nlp-user";
    el.textContent = text;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
  }

  function csvEscape(value) {
    var s = String(value == null ? "" : value);
    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function downloadCsv(columns, rows) {
    var lines = [columns.map(csvEscape).join(",")];
    rows.forEach(function (row) {
      lines.push(columns.map(function (c) { return csvEscape(row[c]); }).join(","));
    });
    var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "query-results.csv";
    a.click();
  }

  function headers() {
    return {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY
    };
  }

  function badgeFor(source) {
    if (source === "agentic_self_healed") return '<span class="nlp-badge heal">self-healed</span>';
    if (source === "agentic") return '<span class="nlp-badge info">agentic</span>';
    if (source === "rule_based") return '<span class="nlp-badge ok">rule-based</span>';
    if (source === "failed" || source === "unanswerable") return '<span class="nlp-badge fail">' + esc(source) + "</span>";
    return "";
  }

  function renderResult(payload) {
    var columns = payload.columns && payload.columns.length
      ? payload.columns
      : (payload.data && payload.data[0] ? Object.keys(payload.data[0]) : []);
    var html = badgeFor(payload.source);
    if (payload.execution_time_ms != null) {
      html += '<span class="nlp-badge info">' + esc(payload.execution_time_ms) + " ms</span>";
    }
    if (payload.error) {
      html += "<div>" + esc(payload.error) + "</div>";
    } else if (!payload.data || !payload.data.length) {
      html += "<div>No rows matched.</div>";
    } else {
      html += '<div class="nlp-table-wrap"><table><thead><tr>' +
        columns.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") +
        "</tr></thead><tbody>" +
        payload.data.map(function (row) {
          return "<tr>" + columns.map(function (c) { return "<td>" + esc(row[c]) + "</td>"; }).join("") + "</tr>";
        }).join("") +
        "</tbody></table></div>";
    }
    if (payload.sql) {
      html += '<div class="nlp-sql">' + esc(payload.sql) + "</div>";
    }
    html += '<div class="nlp-actions">';
    if (payload.data && payload.data.length) {
      html += '<button type="button" data-csv="1">Export CSV</button>';
    }
    html += "</div>";
    var el = addBot(html);
    var csvBtn = el.querySelector("[data-csv]");
    if (csvBtn) {
      csvBtn.addEventListener("click", function () {
        downloadCsv(columns, payload.data);
      });
    }
  }

  function connect() {
    addBot("Connecting to your database…");
    fetch(API_BASE + "/api/v1/plugin/connect", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ api_key: API_KEY })
    })
      .then(function (res) { return res.json().then(function (body) { return { ok: res.ok, body: body }; }); })
      .then(function (out) {
        if (!out.ok) {
          addBot('<span class="nlp-badge fail">error</span>' + esc(out.body.error || "Could not connect."));
          return;
        }
        var names = (out.body.tables || []).map(function (t) { return t.name; }).join(", ");
        addBot(
          '<span class="nlp-badge ok">connected</span>' +
          esc(out.body.dialect || "sql") + " · " + esc(out.body.table_count) + " tables" +
          (names ? "<div>" + esc(names) + "</div>" : "") +
          "<div>Try: list employees in Sales</div>"
        );
      })
      .catch(function (err) {
        addBot('<span class="nlp-badge fail">error</span>' + esc(err.message || err));
      });
  }

  var connected = false;
  root.querySelector(".nlp-fab").addEventListener("click", function () {
    root.classList.toggle("open");
    if (root.classList.contains("open") && !connected) {
      connected = true;
      connect();
      input.focus();
    }
  });
  root.querySelector(".nlp-x").addEventListener("click", function () {
    root.classList.remove("open");
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var question = (input.value || "").trim();
    if (!question) return;
    input.value = "";
    addUser(question);
    var pending = addBot("Generating SQL…");
    fetch(API_BASE + "/api/v1/plugin/query", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ question: question, api_key: API_KEY })
    })
      .then(function (res) { return res.json().then(function (body) { return { ok: res.ok, body: body }; }); })
      .then(function (out) {
        pending.remove();
        renderResult(out.body);
      })
      .catch(function (err) {
        pending.remove();
        addBot('<span class="nlp-badge fail">error</span>' + esc(err.message || err));
      });
  });
})();
