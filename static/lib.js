// Pure helpers + shared constants. No app state, and no DOM access at load time,
// so everything here can be unit-tested in plain node.
//
// These are classic <script>s that share one global scope. Load order (index.html):
//   lib.js -> assistant.js -> modal.js -> app.js   (app.js runs init() last)

// ---- DOM shorthand -----------------------------------------------------------
const $ = (id) => document.getElementById(id);

// ---- shared constants ----------------------------------------------------------
const TAGS = {
  "movie":       { color: "var(--movie)",     label: "Movie" },
  "out of town": { color: "var(--outoftown)", label: "Out of town" },
  "game":        { color: "var(--game)",      label: "Game" },
  "schedule":    { color: "var(--schedule)",  label: "Schedule" },
  "busy":        { color: "var(--busy)",      label: "Busy" },
};
// tags that need an extra "what?" field
const DETAIL_LABELS = { "game": "What game?", "movie": "What movie?" };

// ---- formatting ----------------------------------------------------------------
const pad = (n) => String(n).padStart(2, "0");
const ymd = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
const minToHM = (m) => `${pad(Math.floor(m / 60) % 24)}:${pad(m % 60)}`;
// wrap a possibly out-of-range minute into HH:MM, noting +/- day rollover
function hmWrap(min) {
  let day = 0;
  while (min < 0) { min += 1440; day--; }
  while (min >= 1440) { min -= 1440; day++; }
  const s = `${pad(Math.floor(min / 60))}:${pad(min % 60)}`;
  return day === 0 ? s : `${s} (${day > 0 ? "+" : ""}${day}d)`;
}
const niceDay = (day) => new Date(day + "T00:00:00")
  .toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const tagColor = (t) => (TAGS[t] ? TAGS[t].color : "var(--muted)");

// Anything a person typed (names, titles, details) MUST go through esc() before it is placed in an
// innerHTML template, in element text or in a quoted attribute. (textContent and .value are safe.)
const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
// colors end up inside style="...": accept only a plain #rrggbb, else the default blue
const DEFAULT_COLOR = "#6c8cff";
const safeColor = (c) => (/^#[0-9a-fA-F]{6}$/.test(c) ? c : DEFAULT_COLOR);
function evLabel(e) {
  // prefer title, then the game/movie detail, then the tag name
  return e.title || e.detail || TAGS[e.tag].label;
}
const signed = (m) => (m === 0 ? "same" : `${m > 0 ? "+" : "−"}${Math.abs(m / 60)}h`);

// ---- date math on YYYY-MM-DD strings -------------------------------------------
function addDays(day, n) {
  const d = new Date(day + "T00:00:00");
  d.setDate(d.getDate() + n);
  return ymd(d.getFullYear(), d.getMonth(), d.getDate());
}
// add months, clamping to the last valid day (Jan 31 +1mo -> Feb 28/29)
function addMonths(day, n) {
  const [y, m, d] = day.split("-").map(Number);
  const t = new Date(y, (m - 1) + n, 1);           // first of target month
  const lastDay = new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate();
  return ymd(t.getFullYear(), t.getMonth(), Math.min(d, lastDay));
}

// add years, clamping Feb 29 -> Feb 28 in non-leap years
function addYears(day, n) {
  const [y, m, d] = day.split("-").map(Number);
  const lastDay = new Date(y + n, m, 0).getDate();  // last day of month m in target year
  return ymd(y + n, m - 1, Math.min(d, lastDay));
}

// expand one base day into a recurrence series
function recur(day, freq, count) {
  const out = [];
  for (let i = 0; i < count; i++) {
    if (freq === "week") out.push(addDays(day, i * 7));
    else if (freq === "biweek") out.push(addDays(day, i * 14));
    else if (freq === "month") out.push(addMonths(day, i));
    else if (freq === "year") out.push(addYears(day, i));
    else out.push(addDays(day, i * 7));
  }
  return out;
}

// ---- availability ------------------------------------------------------------------
// merge [start,end] intervals and return the free gaps within [dayStart,dayEnd]
function freeGaps(intervals, dayStart, dayEnd) {
  const merged = [];
  intervals.slice().sort((a, b) => a[0] - b[0]).forEach(([s, e]) => {
    const last = merged[merged.length - 1];
    if (last && s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  });
  const free = [];
  let cur = dayStart;
  merged.forEach(([s, e]) => {
    if (s > cur) free.push([cur, Math.min(s, dayEnd)]);
    cur = Math.max(cur, e);
  });
  if (cur < dayEnd) free.push([cur, dayEnd]);
  return free.filter(([s, e]) => e - s >= 30);   // ignore slivers < 30 min
}

// ---- timezones -----------------------------------------------------------------------
const US_ZONES = [
  { id: "America/New_York",    label: "Eastern",   abbr: "ET"  },
  { id: "America/Chicago",     label: "Central",   abbr: "CT"  },
  { id: "America/Denver",      label: "Mountain",  abbr: "MT"  },
  { id: "America/Phoenix",     label: "Arizona",   abbr: "MST" },
  { id: "America/Los_Angeles", label: "Pacific",   abbr: "PT"  },
  { id: "America/Anchorage",   label: "Alaska",    abbr: "AKT" },
  { id: "Pacific/Honolulu",    label: "Hawaii",    abbr: "HT"  },
];
const DEFAULT_TZ = "America/Los_Angeles";
const zoneOf = (tz) => US_ZONES.find((z) => z.id === tz) || US_ZONES[4];

// UTC offset (minutes, east-positive) for a tz at a given instant (DST-aware)
function tzOffsetMinutes(tz, date) {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hour12: false, year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const p = dtf.formatToParts(date).reduce((a, x) => (a[x.type] = x.value, a), {});
  let hh = p.hour === "24" ? 0 : +p.hour;
  const asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, hh, +p.minute, +p.second);
  return Math.round((asUTC - date.getTime()) / 60000);
}

// hour difference between two zones on a given day (viewer - owner)
function tzDiffMinutes(fromTz, toTz, day) {
  const ref = new Date((day || ymd(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())) + "T12:00:00Z");
  return tzOffsetMinutes(toTz, ref) - tzOffsetMinutes(fromTz, ref);
}
