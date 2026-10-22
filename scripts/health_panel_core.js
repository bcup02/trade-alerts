/* Pure logic of the fleet-health panel on the rollout register page (f-45).  No DOM access, no network: the page script
 * (scripts/render_guides.py) draws with what this returns, and tests/health_panel_node_test.js runs the same file.
 *
 * The cell it reads is HEALTHv1|<base64 of gzip of canonical JSON>|HEALTHEND, written by the A1 ops-notify publisher
 * (trade_alerts.fleet_health).  Everything read from the sheet is untrusted: the shape is checked member by member, sizes
 * are capped, and nothing is ever turned into markup (the page uses textContent only).
 *
 * Three clocks decide what the page may call healthy, all compared with the viewer's "now":
 *   generated_at -- when the publisher packed the table (publisher alive?)
 *   checked_at   -- when ops-notify polled (poller alive?)
 *   each reading's checked_at -- when that axis was read; null = nothing was read (f-62), shown as "no reading time".
 * Stale data is never shown as green.
 */
var HealthPanel = (function () {
  "use strict";

  var MARK_START = "HEALTHv1|";
  var MARK_END = "|HEALTHEND";
  var SCHEMA = "fleet-health-v1";
  var MAX_B64_CHARS = 9000;          // the receiver's cap
  var MAX_JSON_BYTES = 200000;       // what a gunzip may produce (a 9000-character cell cannot honestly need more)
  var MAX_READINGS = 100;
  var MAX_TEXT_CHARS = 200;
  var MIN = 60000;

  var DEFAULTS = {
    publishStaleMs: 25 * MIN,        // the publisher runs every 10 minutes: two missed runs plus slack
    pollStaleMs: 45 * MIN,           // ops-notify's own STALE threshold (OPS_NOTIFY_STALE_AFTER, 2700 s)
    rowStaleMs: 45 * MIN,
    futureSkewMs: 5 * MIN            // the receiver's own freshness window
  };

  var ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
  var B64 = /^[A-Za-z0-9+\/]+={0,2}$/;
  var CONTROL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/;
  var FILE_ID = /^[A-Za-z0-9_-]{20,100}$/;

  function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

  function sameKeys(obj, keys) {
    var have = Object.keys(obj).sort();
    var want = keys.slice().sort();
    return have.length === want.length && have.every(function (k, i) { return k === want[i]; });
  }

  // ---- reading the cell ---------------------------------------------------------------------------------------

  // What the connector returns for a sheet: text blocks (or a string payload).  Anything else is "no text".
  function textOfResult(res) {
    if (!res) return "";
    var out = "";
    var blocks = Array.isArray(res.content) ? res.content : [];
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i] && blocks[i].type === "text" && typeof blocks[i].text === "string") out += blocks[i].text;
    }
    if (out) return out;
    return typeof res.payload === "string" ? res.payload : "";
  }

  // The connector's table view escapes [ ] | _ with a backslash; undo that before looking for the markers.
  function extractCell(raw) {
    if (typeof raw !== "string" || !raw) return { ok: false, code: "no_text" };
    var t = raw.replace(/\\([\[\]|_])/g, "$1");
    var s = t.indexOf(MARK_START);
    if (s < 0) return { ok: false, code: "no_start" };
    var from = s + MARK_START.length;
    var e = t.indexOf(MARK_END, from);
    if (e < 0) return { ok: false, code: "cut_off" };          // started but never ended: the connector cut the cell
    var b64 = t.slice(from, e).replace(/\s+/g, "");
    if (!b64) return { ok: false, code: "empty" };
    if (b64.length > MAX_B64_CHARS) return { ok: false, code: "too_large" };
    if (!B64.test(b64)) return { ok: false, code: "not_base64" };
    return { ok: true, b64: b64 };
  }

  // ---- validating the table ----------------------------------------------------------------------------------

  function parseIso(value) {
    if (typeof value !== "string" || !ISO.test(value)) return NaN;
    var ms = Date.parse(value);
    if (isNaN(ms)) return NaN;
    // Date.parse is lenient about impossible days (Feb 30 -> Mar 2): the calendar date must survive a round trip.
    if (/(Z|\+00:00|-00:00)$/.test(value) && new Date(ms).toISOString().slice(0, 10) !== value.slice(0, 10)) return NaN;
    return ms;
  }

  function cleanText(v) {
    return typeof v === "string" && v.length > 0 && v.length <= MAX_TEXT_CHARS && !CONTROL.test(v);
  }

  function bad(detail) { return { ok: false, code: "bad_schema", detail: detail }; }

  // Same rules as trade_alerts.fleet_health.validate_health_table, plus: a reading's time may be null (f-62).
  function validateTable(t) {
    if (!isObject(t) || !sameKeys(t, ["schema", "generated_at", "checked_at", "readings"])) return bad("members");
    if (t.schema !== SCHEMA) return bad("schema");
    var generatedAtMs = parseIso(t.generated_at);
    var checkedAtMs = parseIso(t.checked_at);
    if (isNaN(generatedAtMs)) return bad("generated_at");
    if (isNaN(checkedAtMs)) return bad("checked_at");
    if (!Array.isArray(t.readings) || t.readings.length < 1) return bad("readings_empty");
    if (t.readings.length > MAX_READINGS) return bad("readings_too_many");
    var readings = [];
    for (var i = 0; i < t.readings.length; i++) {
      var r = t.readings[i];
      if (!isObject(r) || !sameKeys(r, ["target", "axis", "value", "severity", "checked_at"])) return bad("reading_members");
      if (!cleanText(r.target) || !cleanText(r.axis) || !cleanText(r.value) || !cleanText(r.severity)) return bad("reading_text");
      var ms = null;
      if (r.checked_at !== null) {
        ms = parseIso(r.checked_at);
        if (isNaN(ms)) return bad("reading_checked_at");
      }
      readings.push({ target: r.target, axis: r.axis, value: r.value, severity: r.severity, checkedAt: r.checked_at, checkedAtMs: ms });
    }
    return {
      ok: true,
      table: { generatedAt: t.generated_at, generatedAtMs: generatedAtMs, checkedAt: t.checked_at, checkedAtMs: checkedAtMs, readings: readings }
    };
  }

  // gzip -> text, never more than MAX_JSON_BYTES of output.
  async function gunzipText(bytes) {
    if (typeof DecompressionStream === "undefined" || typeof Blob === "undefined") return { ok: false, code: "no_gzip" };
    try {
      var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      var reader = stream.getReader();
      var chunks = [];
      var total = 0;
      for (;;) {
        var step = await reader.read();
        if (step.done) break;
        total += step.value.length;
        if (total > MAX_JSON_BYTES) { try { await reader.cancel(); } catch (ignore) { /* already stopping */ } return { ok: false, code: "too_big" }; }
        chunks.push(step.value);
      }
      var all = new Uint8Array(total);
      var at = 0;
      chunks.forEach(function (c) { all.set(c, at); at += c.length; });
      return { ok: true, text: new TextDecoder("utf-8", { fatal: true }).decode(all) };
    } catch (err) {
      return { ok: false, code: "bad_gzip" };
    }
  }

  async function decodeTable(b64) {
    var bytes;
    try {
      var bin = atob(b64);
      bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    } catch (err) {
      return { ok: false, code: "not_base64" };
    }
    var unzipped = await gunzipText(bytes);
    if (!unzipped.ok) return unzipped;
    var parsed;
    try { parsed = JSON.parse(unzipped.text); } catch (err) { return { ok: false, code: "bad_json" }; }
    return validateTable(parsed);
  }

  // connector result -> table | a reason.  Never throws.
  async function readResult(res) {
    var cell = extractCell(textOfResult(res));
    if (!cell.ok) return cell;
    return decodeTable(cell.b64);
  }

  // ---- what may be called healthy ----------------------------------------------------------------------------

  function severityClass(sev) {
    return sev === "ok" || sev === "warn" || sev === "alert" ? sev : "warn";     // ops-notify's own default for an unknown value
  }

  function assess(table, nowMs, opts) {
    var o = {};
    Object.keys(DEFAULTS).forEach(function (k) { o[k] = opts && typeof opts[k] === "number" ? opts[k] : DEFAULTS[k]; });
    var publishAgeMs = nowMs - table.generatedAtMs;
    var pollAgeMs = nowMs - table.checkedAtMs;
    var future = (table.generatedAtMs - nowMs > o.futureSkewMs) || (table.checkedAtMs - nowMs > o.futureSkewMs);
    var publishStale = publishAgeMs > o.publishStaleMs;
    var pollStale = pollAgeMs > o.pollStaleMs;
    var tableStale = publishStale || pollStale || future;
    var counts = { ok: 0, warn: 0, alert: 0, stale: 0, notime: 0 };
    var rows = table.readings.map(function (r) {
      var noTime = r.checkedAtMs === null;
      var ageMs = noTime ? null : nowMs - r.checkedAtMs;
      var rowStale = !noTime && ageMs > o.rowStaleMs;
      var display = tableStale ? "stale" : noTime ? "notime" : rowStale ? "stale" : severityClass(r.severity);
      counts[display] += 1;
      return { target: r.target, axis: r.axis, value: r.value, severity: r.severity, checkedAt: r.checkedAt, ageMs: ageMs,
               noTime: noTime, rowStale: rowStale, display: display };
    });
    var level = future ? "clock" : publishStale ? "publish_stale" : pollStale ? "poll_stale"
      : counts.alert > 0 ? "alert" : (counts.warn + counts.stale + counts.notime) > 0 ? "warn" : "ok";
    return { level: level, publishAgeMs: publishAgeMs, pollAgeMs: pollAgeMs, future: future, publishStale: publishStale,
             pollStale: pollStale, tableStale: tableStale, counts: counts, rows: rows, limits: o };
  }

  // ---- words and times ---------------------------------------------------------------------------------------

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // Taipei time (UTC+8), "10/22 15:30"; computed by hand so it does not depend on the viewer's locale or zone.
  function formatTaipei(ms) {
    var d = new Date(ms + 8 * 60 * MIN);
    return pad(d.getUTCMonth() + 1) + "/" + pad(d.getUTCDate()) + " " + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
  }

  function formatAge(ms) {
    if (ms === null || ms === undefined || isNaN(ms)) return "不明";
    if (ms < MIN) return "剛剛";
    var minutes = Math.floor(ms / MIN);
    if (minutes < 60) return minutes + " 分鐘前";
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return minutes % 60 === 0 ? hours + " 小時前" : hours + " 小時 " + (minutes % 60) + " 分鐘前";
    return Math.floor(hours / 24) + " 天前";
  }

  function ageWithoutAgo(ms) { return formatAge(ms).replace(/前$/, ""); }

  var LEVEL_LABEL = {
    ok: "全部正常", warn: "有項目要注意", alert: "有項目異常",
    publish_stale: "讀數過期（發布停了）", poll_stale: "讀數過期（輪詢停了）", clock: "時鐘不一致，無法判斷新舊"
  };

  function describeLevel(a) {
    var c = a.counts;
    var detail;
    if (a.level === "clock") {
      detail = "讀數的產生時間比這個瀏覽器的現在還晚（超過 " + Math.round(a.limits.futureSkewMs / MIN) + " 分鐘），無法判斷新舊，所以不顯示為正常。";
    } else if (a.level === "publish_stale") {
      detail = "讀數是 " + formatAge(a.publishAgeMs) + "產生的，發布單元每 10 分鐘會發一次，可能停了。下面的狀態都是舊的，只供參考。";
    } else if (a.level === "poll_stale") {
      detail = "發布還在跑，但 ops-notify 最後一次輪詢是 " + formatAge(a.pollAgeMs) + "，輪詢可能停了。下面的狀態都是舊的，只供參考。";
    } else if (a.level === "alert") {
      detail = c.alert + " 項異常" + (c.warn + c.stale + c.notime ? "、" + (c.warn + c.stale + c.notime) + " 項要注意或不明" : "") + "。";
    } else if (a.level === "warn") {
      detail = (c.warn ? c.warn + " 項要注意" : "") + (c.stale ? (c.warn ? "、" : "") + c.stale + " 項過期" : "") +
        (c.notime ? (c.warn || c.stale ? "、" : "") + c.notime + " 項沒有讀取時間" : "") + "。";
    } else {
      detail = "沒有異常，最近一次輪詢是 " + formatAge(a.pollAgeMs) + "。";
    }
    return { level: a.level, title: LEVEL_LABEL[a.level], detail: detail };
  }

  var FAILURE_TEXT = {
    no_text: "連接器沒有回傳文字內容。",
    no_start: "讀到的內容裡找不到讀數格（試算表是空的，或不是讀數那份）。",
    cut_off: "讀數格被截斷（連接器只回了一部分），無法顯示。",
    empty: "讀數格是空的。",
    too_large: "讀數格比上限大，不是發布單元寫的。",
    not_base64: "讀數格的內容不是有效的編碼。",
    no_gzip: "這個瀏覽器不支援解壓縮（DecompressionStream），無法顯示讀數。",
    bad_gzip: "讀數格解壓縮失敗，內容損壞。",
    too_big: "讀數格解開後比上限大，不是發布單元寫的。",
    bad_json: "讀數格解開後不是有效的資料。",
    bad_schema: "讀數格的結構不符合讀數表格式。"
  };

  function describeFailure(r) {
    var text = FAILURE_TEXT[r && r.code] || "讀數格讀不出來。";
    return { code: r && r.code, text: text, detail: r && r.detail ? r.detail : null };
  }

  // A connector failure -> what to tell the viewer and what the page may do about it.  Branches on the code, never the message.
  function classifyError(err) {
    var code = err && err.code ? err.code : "unknown";
    var message = err && typeof err.message === "string" ? err.message.slice(0, 160) : "";
    var table = {
      approval_required: { kind: "approval", text: "要你同意這個頁面使用 Google Drive 連接器才讀得到讀數。", button: "允許並讀取", retract: true },
      not_in_manifest: { kind: "denied", text: "這個頁面沒有被允許使用 Google Drive 連接器（可能按了不允許）。到頁面的權限選單重新允許後重新整理。", retract: true },
      consent_required: { kind: "denied", text: "你還沒有允許這個頁面使用 Google Drive 連接器。", button: "再試一次", retract: true },
      server_not_connected: { kind: "reconnect", text: "還沒連接 Google Drive：到 claude.ai 設定 → 連接器新增。", retract: true },
      needs_reauth: { kind: "reconnect", text: "Google Drive 連接器要重新登入：到 claude.ai 設定 → 連接器重新連接。", retract: true },
      selection_required: { kind: "reconnect", text: "你有多個 Google Drive 連接器：請在頁面載入時跳出的提示選一個。", retract: true },
      blocked_by_policy: { kind: "denied", text: "組織政策不允許這個連接器。", retract: true },
      not_granted: { kind: "no_mcp", text: "這個檢視沒有連接器功能：要在 claude.ai 裡開這個頁面。", retract: true },
      capability_disabled: { kind: "no_mcp", text: "這個檢視沒有連接器功能：要在 claude.ai 裡開這個頁面。", retract: true },
      capability_removed: { kind: "no_mcp", text: "這個檢視沒有連接器功能：要在 claude.ai 裡開這個頁面。", retract: true },
      server_unavailable: { kind: "transient", text: "暫時讀不到 Google Drive，過一會兒會自動重試；下面是上次成功讀到的。", retract: false },
      upstream_error: { kind: "transient", text: "暫時讀不到 Google Drive，過一會兒會自動重試；下面是上次成功讀到的。", retract: false },
      rate_limited: { kind: "transient", text: "讀取太頻繁，稍後會自動重試；下面是上次成功讀到的。", retract: false },
      tool_error: { kind: "tool", text: "Google Drive 回報錯誤：" + (message || "（沒有說明）") + "。檢查讀數試算表的檔案編號和你的存取權。", retract: false }
    };
    var hit = table[code];
    if (hit) return { code: code, kind: hit.kind, text: hit.text, button: hit.button || null, retract: hit.retract };
    return { code: code, kind: "other", text: "讀取失敗（" + code + "）。", button: null, retract: false };
  }

  // What to do with a configured source: nothing yet, no connector in this view, or read it.
  function planSource(source, mcpAvailable) {
    if (!source || typeof source.file_id !== "string" || !FILE_ID.test(source.file_id)) return "unconfigured";
    return mcpAvailable ? "load" : "no_mcp";
  }

  return {
    DEFAULTS: DEFAULTS, MARK_START: MARK_START, MARK_END: MARK_END, FILE_ID: FILE_ID,
    textOfResult: textOfResult, extractCell: extractCell, validateTable: validateTable, decodeTable: decodeTable,
    readResult: readResult, severityClass: severityClass, assess: assess, formatTaipei: formatTaipei, formatAge: formatAge,
    ageWithoutAgo: ageWithoutAgo, describeLevel: describeLevel, describeFailure: describeFailure, classifyError: classifyError,
    planSource: planSource, parseIso: parseIso
  };
})();
