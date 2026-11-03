// Friend Calendar front-end: state, data loading, and the calendar / snapshot / timeline views.
//
// Classic scripts share one global scope. Load order (index.html):
//   lib.js (pure helpers) -> assistant.js -> modal.js (event editor) -> app.js
// app.js holds the shared state and calls init() last, once everything above is defined.

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const SWATCHES = ["#6c8cff", "#4bd07b", "#ff9f43", "#a970ff", "#ff5c72", "#4aa3ff", "#f7d154", "#2dd4bf"];

let viewYear, viewMonth;          // month currently displayed
let selectedDays = new Set();     // multi-selected YYYY-MM-DD days
let focusDay = null;              // day shown in snapshot/timeline
let events = [];                  // events for viewed month
let userColors = {};              // name -> hex color
let userTz = {};                  // name -> IANA timezone
let involved = new Set();         // scheduling-assistant: people to consider
let involvedInit = false;         // have we seeded 'involved' from users yet?

const userColor = (name) => userColors[name] || "#6c8cff";
// event fill = a gradient from the owner's user color (left) into the tag color
// (right) -- e.g. a "busy" event owned by a blue user goes blue -> red.
const evGradient = (e) => `linear-gradient(90deg, ${userColor(e.owner)}, ${tagColor(e.tag)})`;

function me() { return $("me").value; }  // "" means none selected

// timezone of a user (fallback to viewer default)
const tzOf = (name) => userTz[name] || DEFAULT_TZ;
// the "viewer": the currently-selected user, else default
function viewerTz() { return me() ? tzOf(me()) : DEFAULT_TZ; }

// convert an event's owner-local times into the viewer's timezone.
// returns viewer-local start/end (clamped to the day for drawing),
// the raw (unclamped) values, and the hour diff.
function toViewer(e) {
  const diff = tzDiffMinutes(tzOf(e.owner), viewerTz(), e.day);
  const rawS = e.start_min + diff, rawE = e.end_min + diff;
  return {
    diff,
    rawS, rawE,
    start: Math.max(0, Math.min(1440, rawS)),
    end: Math.max(0, Math.min(1440, rawE)),
    sameZone: diff === 0,
    abbr: zoneOf(tzOf(e.owner)).abbr,
  };
}

// ---- server calls ------------------------------------------------------------
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) { alert("Error: " + (await res.text())); throw new Error(res.status); }
  return res.status === 204 ? null : res.json();
}
const sendJson = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// ---- users -----------------------------------------------------------------------
async function loadUsers() {
  const users = await api("/api/users");  // [{name, color, timezone}]
  const prevNames = Object.keys(userColors);
  userColors = Object.fromEntries(users.map((u) => [u.name, u.color]));
  userTz = Object.fromEntries(users.map((u) => [u.name, u.timezone || DEFAULT_TZ]));
  const names = users.map((u) => u.name);
  // seed the assistant with everyone the first time; afterwards just auto-include
  // any brand-new users, preserving whatever the user has toggled off.
  if (!involvedInit && names.length) { involved = new Set(names); involvedInit = true; }
  else names.filter((n) => !prevNames.includes(n)).forEach((n) => involved.add(n));
  const sel = $("me");
  const current = sel.value || localStorage.getItem("fc_me") || "";
  sel.innerHTML = `<option value="">-- none --</option>` +
    names.map((n) => `<option value="${n}">${n}</option>`).join("");
  sel.value = names.includes(current) ? current : "";
}

function renderSwatches() {
  $("uSwatches").innerHTML = SWATCHES.map((c) =>
    `<button type="button" class="tagbtn" data-color="${c}"
       style="background:${c};width:26px;height:26px;padding:0"></button>`
  ).join("");
  $("uSwatches").querySelectorAll("[data-color]").forEach((b) =>
    b.addEventListener("click", () => { $("uColor").value = b.dataset.color; }));
}

function openUserModal() {
  $("uName").value = "";
  $("uColor").value = SWATCHES[Object.keys(userColors).length % SWATCHES.length];
  $("uTz").innerHTML = US_ZONES.map((z) =>
    `<option value="${z.id}">${z.label} (${z.abbr})</option>`).join("");
  $("uTz").value = viewerTz();  // default to viewer's zone as a convenience
  renderSwatches();
  $("userOverlay").classList.add("show");
  $("uName").focus();
}

async function saveUser() {
  const name = $("uName").value.trim();
  if (!name) { alert("Enter a name."); return; }
  await api("/api/users", sendJson("POST", {
    name, color: $("uColor").value, timezone: $("uTz").value,
  }));
  $("userOverlay").classList.remove("show");
  await loadUsers();
  $("me").value = name;
  localStorage.setItem("fc_me", name);
  render();
}

// ---- data ----------------------------------------------------------------
async function loadEvents() {
  const month = `${viewYear}-${pad(viewMonth + 1)}`;
  events = await api(`/api/events?month=${month}`);
  render();
}

// ---- rendering -----------------------------------------------------------
function renderLegend() {
  $("legend").innerHTML = Object.entries(TAGS).map(([, t]) =>
    `<span class="chip"><span class="dot" style="background:${t.color}"></span>${t.label}</span>`
  ).join("");
}

// live US timezone reference table (updates every second)
function renderTzTable() {
  const now = new Date();
  const vTz = viewerTz();
  const vZone = zoneOf(vTz);
  $("tzViewerNote").textContent = me()
    ? `— times below are also shown relative to you (${me()}, ${vZone.abbr})`
    : "— pick yourself (top-right) to see offsets relative to you";
  $("tzTable").innerHTML = US_ZONES.map((z) => {
    const t = new Intl.DateTimeFormat("en-US", {
      timeZone: z.id, hour: "2-digit", minute: "2-digit", hour12: true,
    }).format(now);
    const diff = tzDiffMinutes(z.id, vTz, ymd(now.getFullYear(), now.getMonth(), now.getDate()));
    const rel = z.id === vTz ? "you" : signed(-diff);  // how their clock compares to yours
    return `<div class="tz-card ${z.id === vTz ? "viewer" : ""}">
              <div class="z">${z.label} (${z.abbr})</div>
              <div class="t">${t}</div>
              <div class="o">${z.id === vTz ? "your zone" : rel + " vs you"}</div>
            </div>`;
  }).join("");
}

function render() {
  $("monthLabel").textContent = new Date(viewYear, viewMonth, 1)
    .toLocaleString(undefined, { month: "long", year: "numeric" });
  $("dow").innerHTML = DOW.map((d) => `<div class="dow">${d}</div>`).join("");
  renderTzTable();
  renderCalendar();
  renderSnapshot();
  renderTimeline();
  renderAssistant();
}

function eventsOn(day) {
  return events.filter((e) => e.day === day).sort((a, b) => a.start_min - b.start_min);
}

function renderCalendar() {
  const first = new Date(viewYear, viewMonth, 1);
  const startDow = first.getDay();
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const todayStr = ymd(new Date().getFullYear(), new Date().getMonth(), new Date().getDate());

  let cells = "";
  // leading blanks from previous month
  const prevDays = new Date(viewYear, viewMonth, 0).getDate();
  for (let i = startDow - 1; i >= 0; i--) {
    cells += `<div class="cell dim"><span class="num">${prevDays - i}</span></div>`;
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const day = ymd(viewYear, viewMonth, d);
    const evs = eventsOn(day);
    const shown = evs.slice(0, 3).map((e) =>
      `<div class="evline" style="background:${evGradient(e)}" title="${e.owner}: ${evLabel(e)}">${e.owner}: ${evLabel(e)}</div>`
    ).join("");
    const more = evs.length > 3 ? `<span class="more">+${evs.length - 3} more</span>` : "";
    const cls = ["cell",
      day === todayStr ? "today" : "",
      selectedDays.has(day) ? "selected" : "",
      day === focusDay ? "focus" : ""].join(" ");
    cells += `<div class="${cls}" data-day="${day}"><span class="num">${d}</span>${shown}${more}</div>`;
  }
  const cal = $("cal");
  cal.innerHTML = cells;
  cal.querySelectorAll(".cell[data-day]").forEach((c) =>
    c.addEventListener("click", (ev) => selectDay(c.dataset.day, ev.ctrlKey || ev.metaKey || ev.shiftKey)));
}

function selectDay(day, additive) {
  if (additive) {
    if (selectedDays.has(day) && selectedDays.size > 1) selectedDays.delete(day);
    else selectedDays.add(day);
  } else {
    selectedDays = new Set([day]);
  }
  focusDay = day;
  render();
}

function renderSnapshot() {
  const extra = selectedDays.size > 1 ? `  (+${selectedDays.size - 1} more day(s) selected)` : "";
  if (!focusDay) {
    $("snapTitle").textContent = "Snapshot — pick a day";
    $("snapChips").innerHTML = `<span class="empty">Click a day. Ctrl/Shift-click to multi-select.</span>`;
    return;
  }
  const nice = new Date(focusDay + "T00:00:00")
    .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  $("snapTitle").textContent = `Snapshot — ${nice}${extra}`;
  const evs = eventsOn(focusDay);
  if (!evs.length) {
    $("snapChips").innerHTML = `<span class="empty">Nothing planned. Add something!</span>`;
    return;
  }
  $("snapChips").innerHTML = evs.map((e) => {
    const v = toViewer(e);
    const theirs = v.sameZone ? ""
      : `<span style="color:var(--muted)">(${v.abbr} ${minToHM(e.start_min)}–${minToHM(e.end_min)}, ${signed(v.diff)})</span>`;
    const mark = e.series_id
      ? `<span class="series-mark" title="Part of a series - open it to edit them all">↻</span>` : "";
    return `<span class="chip" data-id="${e.id}" style="cursor:pointer" title="Click to edit">
       <span class="dot" style="background:${evGradient(e)}"></span>
       <b>${e.owner}</b> · ${evLabel(e)}${mark}
       <span style="color:var(--muted)">${hmWrap(v.rawS)}–${hmWrap(v.rawE)}</span>
       ${theirs}
       <span class="chip-x" data-del="${e.id}" title="Delete this event only">×</span>
     </span>`;
  }).join("");
  $("snapChips").querySelectorAll(".chip-x").forEach((x) =>
    x.addEventListener("click", (ev) => { ev.stopPropagation(); quickDelete(+x.dataset.del); }));
  $("snapChips").querySelectorAll(".chip[data-id]").forEach((c) =>
    c.addEventListener("click", () => openModal(events.find((e) => e.id == c.dataset.id))));
}

function renderTimeline() {
  const day = focusDay;
  $("tlTitle").textContent = day
    ? `Everyone's day — ${new Date(day + "T00:00:00").toLocaleDateString()}`
    : "Everyone's day — pick a day";

  // hour ruler (every 3h)
  $("tlHours").innerHTML = [0, 3, 6, 9, 12, 15, 18, 21].map((h) =>
    `<span>${pad(h)}:00</span>`).join("");

  if (!day) { $("timeline").innerHTML = ""; return; }
  const evs = eventsOn(day);
  const owners = [...new Set(evs.map((e) => e.owner))];
  if (me() && !owners.includes(me())) owners.unshift(me());
  if (!owners.length) { $("timeline").innerHTML = `<span class="empty" style="color:var(--muted)">No one has plans yet.</span>`; return; }

  $("timeline").innerHTML = owners.map((owner) => {
    const abbr = zoneOf(tzOf(owner)).abbr;
    const blocks = evs.filter((e) => e.owner === owner).map((e) => {
      const v = toViewer(e);
      const left = (v.start / 1440) * 100;
      const width = Math.max(0, ((v.end - v.start) / 1440) * 100);
      const theirs = v.sameZone ? "" : ` · ${abbr} ${minToHM(e.start_min)}-${minToHM(e.end_min)}`;
      return `<div class="tl-block" style="left:${left}%;width:${width}%;background:${evGradient(e)}"
                title="${evLabel(e)}: ${hmWrap(v.rawS)}-${hmWrap(v.rawE)} your time${theirs}">${evLabel(e)}</div>`;
    }).join("");
    return `<div class="tl-row"><div class="tl-name"><span class="dot" style="background:${userColor(owner)}"></span> ${owner} <span style="color:var(--muted)">${abbr}</span></div><div class="tl-track">${blocks}</div></div>`;
  }).join("");
}

// ---- wiring --------------------------------------------------------------
function shiftMonth(delta) {
  viewMonth += delta;
  if (viewMonth < 0) { viewMonth = 11; viewYear--; }
  if (viewMonth > 11) { viewMonth = 0; viewYear++; }
  loadEvents();
}

function init() {
  const now = new Date();
  viewYear = now.getFullYear();
  viewMonth = now.getMonth();
  focusDay = ymd(now.getFullYear(), now.getMonth(), now.getDate());
  selectedDays = new Set([focusDay]);

  $("me").addEventListener("change", () => {
    localStorage.setItem("fc_me", $("me").value);
    render();  // viewer changed -> re-convert everything to their timezone
  });
  setInterval(renderTzTable, 1000);  // live clocks in the reference table
  $("addUserBtn").addEventListener("click", openUserModal);
  $("uCancel").addEventListener("click", () => $("userOverlay").classList.remove("show"));
  $("uSave").addEventListener("click", saveUser);
  $("userOverlay").addEventListener("click", (e) => { if (e.target.id === "userOverlay") $("userOverlay").classList.remove("show"); });

  renderLegend();
  loadUsers();
  $("prev").addEventListener("click", () => shiftMonth(-1));
  $("next").addEventListener("click", () => shiftMonth(1));
  $("asstToggle").addEventListener("change", renderAssistant);
  wireModal();

  loadEvents();
}

init();
