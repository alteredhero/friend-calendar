// Event editor modal: add events (single / multi-day / recurring) and edit or delete
// them (this one, this + following, or a whole series).
//
// Classic script; at call time it relies on lib.js and on app.js (state, api, sendJson,
// me, loadEvents, ...). The 'wireModal()' call in app.js init() attaches the listeners.

let pickedTag = "movie";
let editingId = null;      // id of the event being edited; null while adding
let origEvent = null;      // the event as it was when the editor opened (we diff against it)
let seriesInfo = null;     // {total, following, first_day, last_day} if it belongs to a series
let timeTouched = false;   // did the user touch the time controls? The sliders snap to 15-minute
                           // steps, so an untouched control must never count as a change.

function updateDetailField() {
  const label = DETAIL_LABELS[pickedTag];
  if (label) {
    $("detailLabel").textContent = label;
    $("fDetail").placeholder = label;
    $("detailField").style.display = "";
  } else {
    $("detailField").style.display = "none";
  }
}

function renderTagPicker() {
  $("fTags").innerHTML = Object.entries(TAGS).map(([key, t]) =>
    `<button type="button" class="tagbtn ${key === pickedTag ? "active" : ""}"
       data-tag="${key}" style="background:${t.color};color:#10131a">${t.label}</button>`
  ).join("");
  $("fTags").querySelectorAll(".tagbtn").forEach((b) =>
    b.addEventListener("click", () => { pickedTag = b.dataset.tag; renderTagPicker(); updateDetailField(); }));
  updateDetailField();
}

// --- time <-> slider syncing (sliders and typed time inputs stay in lockstep) ---
const minToTimeVal = (m) => (m >= 1440 ? "00:00" : `${pad(Math.floor(m / 60))}:${pad(m % 60)}`);
function timeValToMin(str, isEnd) {
  if (!str) return isEnd ? 600 : 540;
  const [h, m] = str.split(":").map(Number);
  let v = h * 60 + m;
  if (isEnd && v === 0) v = 1440;   // an end of 00:00 means midnight / end of day
  return v;
}
function updateDurRead(s, e) {
  const mins = Math.max(0, e - s);
  const h = Math.floor(mins / 60), m = mins % 60;
  $("durRead").textContent = `${h ? h + "h " : ""}${m || !h ? m + "m" : ""}`.trim();
}
function clampOrder() {
  let s = +$("fStart").value, e = +$("fEnd").value;
  if (e <= s) { e = Math.min(1440, s + 15); $("fEnd").value = e; }
  return [s, e];
}
// slider moved -> refresh the typed times
function syncFromSliders() {
  const [s, e] = clampOrder();
  $("fStartTime").value = minToTimeVal(s);
  $("fEndTime").value = minToTimeVal(e);
  updateDurRead(s, e);
}
// time typed -> refresh the sliders
function syncFromTimes() {
  const s = Math.max(0, Math.min(1440, timeValToMin($("fStartTime").value, false)));
  const e = Math.max(0, Math.min(1440, timeValToMin($("fEndTime").value, true)));
  $("fStart").value = s;
  $("fEnd").value = e;
  const [cs, ce] = clampOrder();
  $("fEndTime").value = minToTimeVal(ce);
  updateDurRead(cs, ce);
}

// --- what the form currently says ---
function formFields() {
  return {
    title: $("fTitle").value.trim(),
    tag: pickedTag,
    detail: DETAIL_LABELS[pickedTag] ? $("fDetail").value.trim() : "",
    note: $("fNote").value.trim(),
    start_min: +$("fStart").value,
    end_min: +$("fEnd").value,
  };
}

// Only the fields the user actually changed. Sending just these is what makes a series
// edit safe: fixing a tag must not rewrite every day's individual start/end time.
function changedFields() {
  const now = formFields(), was = origEvent, out = {};
  for (const k of ["title", "tag", "detail", "note"]) {
    if (now[k] !== (was[k] || "")) out[k] = now[k];
  }
  if (timeTouched && (now.start_min !== was.start_min || now.end_min !== was.end_min)) {
    out.start_min = now.start_min;   // the server wants the pair together
    out.end_min = now.end_min;
  }
  return out;
}
const FIELD_NAMES = { title: "title", tag: "tag", detail: "game/movie", note: "note", start_min: "time", end_min: "time" };
const describeChanges = (changes) =>
  [...new Set(Object.keys(changes).map((k) => FIELD_NAMES[k]))].join(", ");

// --- series scope ("apply to: this event / this and following / entire series") ---
const scopeRadio = () => document.querySelector('input[name="scope"]:checked');
const currentScope = () => (seriesInfo && scopeRadio() ? scopeRadio().value : "single");
function scopeCount(scope) {
  if (!seriesInfo || scope === "single") return 1;
  return scope === "all" ? seriesInfo.total : seriesInfo.following;
}

// reveal the scope picker if the event being edited really belongs to a series
async function loadSeriesInfo(ev) {
  if (!ev || !ev.series_id) return;
  const info = await api(`/api/events/${ev.id}/series`);
  if (editingId !== ev.id || info.total < 2) return;   // modal moved on / not really a series
  seriesInfo = info;
  $("scopeFollowing").textContent = info.following;
  $("scopeAll").textContent = info.total;
  $("scopeRange").textContent = `${niceDay(info.first_day)} – ${niceDay(info.last_day)}`;
  document.querySelector('input[name="scope"][value="single"]').checked = true;
  $("scopeField").style.display = "";
  updateApplyHint();
}

function targetDays() {
  const base = [...selectedDays];
  if (!$("fRepeat").checked) return [...new Set(base)];
  const freq = $("fFreq").value;
  const count = Math.max(2, Math.min(60, +$("fCount").value || 2));
  const set = new Set();
  base.forEach((d) => recur(d, freq, count).forEach((x) => set.add(x)));
  return [...set];
}

function updateApplyHint() {
  $("repeatOpts").style.display = $("fRepeat").checked ? "" : "none";
  if (editingId) {
    const n = scopeCount(currentScope());
    $("applyHint").textContent = n > 1 ? `Changes will be applied to ${n} events.` : "Editing this single event.";
    return;
  }
  const n = targetDays().length;
  $("applyHint").textContent = `Will create ${n} event${n === 1 ? "" : "s"} (one per day).`;
}

function openModal(ev) {
  if (!selectedDays.size) { alert("Pick a day on the calendar first."); return; }
  if (!me()) { alert("Select a user first (top-right). Add one with the '+ user' button."); return; }
  editingId = ev ? ev.id : null;
  origEvent = ev ? { ...ev } : null;
  seriesInfo = null;
  timeTouched = false;
  const dayCount = selectedDays.size;
  $("modalTitle").textContent = ev
    ? "Edit event"
    : `Add event — ${dayCount > 1 ? dayCount + " days" : focusDay} (as ${me()})`;
  $("fTitle").value = ev ? ev.title : "";
  $("fNote").value = ev ? ev.note : "";
  $("fDetail").value = ev ? (ev.detail || "") : "";
  pickedTag = ev ? ev.tag : "movie";
  $("fStart").value = ev ? ev.start_min : 540;
  $("fEnd").value = ev ? ev.end_min : 600;
  // times are stored in the OWNER's local time, so say whose clock these controls are on
  const timeOwner = ev ? ev.owner : me();
  const whose = timeOwner === me() ? "your" : `${timeOwner}'s`;
  $("timeLabel").textContent = `Time — ${whose} local time (${zoneOf(tzOf(timeOwner)).abbr})`;
  $("delBtn").style.display = ev ? "inline-block" : "none";
  // recurrence only applies when creating; the scope picker only when editing a series
  $("fRepeat").checked = false;
  $("fRepeat").closest(".field").style.display = ev ? "none" : "";
  $("scopeField").style.display = "none";
  renderTagPicker();
  syncFromSliders();
  updateApplyHint();
  $("overlay").classList.add("show");
  loadSeriesInfo(ev);   // async: reveals the scope picker once we know the series size
}

function closeModal() {
  $("overlay").classList.remove("show");
  editingId = null;
  origEvent = null;
  seriesInfo = null;
}

async function saveNew() {
  await api("/api/events/bulk", sendJson("POST", {
    owner: me(), ...formFields(), days: targetDays(),
  }));
  return true;
}

// returns false if the user backed out at the confirmation
async function saveEdit() {
  const changes = changedFields();
  if (!Object.keys(changes).length) return true;   // nothing changed: just close
  const scope = currentScope(), n = scopeCount(scope);
  if (n > 1 && !confirm(`Apply to ${n} of ${origEvent.owner}'s events (${describeChanges(changes)})?`)) {
    return false;
  }
  await api(`/api/events/${editingId}?scope=${scope}`, sendJson("PATCH", changes));
  return true;
}

async function saveEvent() {
  if (!me()) { alert("Select a user first."); return; }
  const done = editingId ? await saveEdit() : await saveNew();
  if (!done) return;
  closeModal();
  await loadEvents();
}

async function deleteEvent() {
  if (!editingId) return;
  const scope = currentScope(), n = scopeCount(scope);
  const msg = n > 1
    ? `Delete ${n} of ${origEvent.owner}'s events (${scope === "all" ? "the entire series" : "this and following"})?`
    : "Delete this event?";
  if (!confirm(msg)) return;
  await api(`/api/events/${editingId}?scope=${scope}`, { method: "DELETE" });
  closeModal();
  await loadEvents();
}

// the little x on a snapshot chip: always just that one event
async function quickDelete(id) {
  const e = events.find((x) => x.id === id);
  const what = e ? `"${evLabel(e)}" (${e.owner})` : "this event";
  const only = e && e.series_id ? " - just this one (open it to delete the whole series)" : "";
  if (!confirm(`Delete ${what}${only}?`)) return;
  await api(`/api/events/${id}`, { method: "DELETE" });
  await loadEvents();
}

function wireModal() {
  $("addBtn").addEventListener("click", () => openModal(null));
  $("cancelBtn").addEventListener("click", closeModal);
  $("saveBtn").addEventListener("click", saveEvent);
  $("delBtn").addEventListener("click", deleteEvent);
  const slid = () => { timeTouched = true; syncFromSliders(); };
  const typed = () => { timeTouched = true; syncFromTimes(); };
  $("fStart").addEventListener("input", slid);
  $("fEnd").addEventListener("input", slid);
  $("fStartTime").addEventListener("input", typed);
  $("fEndTime").addEventListener("input", typed);
  $("fRepeat").addEventListener("change", updateApplyHint);
  $("fFreq").addEventListener("change", updateApplyHint);
  $("fCount").addEventListener("input", updateApplyHint);
  document.querySelectorAll('input[name="scope"]').forEach((r) =>
    r.addEventListener("change", updateApplyHint));
  $("overlay").addEventListener("click", (e) => { if (e.target.id === "overlay") closeModal(); });
}
