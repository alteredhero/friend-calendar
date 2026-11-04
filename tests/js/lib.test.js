// Tests for the pure helpers in static/lib.js. Run:  node --test "tests/js/**/*.test.js"
//
// lib.js is a classic <script> (top-level consts, no exports), so we evaluate it in a vm context
// and read the helpers back out with an expression appended to the source.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "..", "static", "lib.js"), "utf8");
const raw = vm.runInNewContext(
  source + "\n;({ addDays, addMonths, addYears, recur, freeGaps, hmWrap, evLabel, minToHM, " +
    "signed, zoneOf, tzOffsetMinutes, tzDiffMinutes, esc, safeColor })"
);
// Arrays built inside the vm have a different Array.prototype, which deepStrictEqual rejects,
// so copy array results across the boundary.
const plain = (value) => JSON.parse(JSON.stringify(value));
const lib = {
  ...raw,
  recur: (...args) => plain(raw.recur(...args)),
  freeGaps: (...args) => plain(raw.freeGaps(...args)),
};

// ---- date math -------------------------------------------------------------------
test("addDays crosses month and year boundaries, forwards and backwards", () => {
  assert.equal(lib.addDays("2026-11-30", 1), "2026-12-01");
  assert.equal(lib.addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(lib.addDays("2026-03-01", -1), "2026-02-28");
  assert.equal(lib.addDays("2028-03-01", -1), "2028-02-29"); // leap year
  assert.equal(lib.addDays("2026-11-05", 0), "2026-11-05");
});

test("addDays is not thrown by daylight-saving changes", () => {
  assert.equal(lib.addDays("2026-03-07", 1), "2026-03-08"); // US spring forward
  assert.equal(lib.addDays("2026-03-08", 1), "2026-03-09");
  assert.equal(lib.addDays("2026-10-31", 1), "2026-11-01"); // US fall back
  assert.equal(lib.addDays("2026-11-01", 1), "2026-11-02");
});

test("addMonths clamps to the last valid day", () => {
  assert.equal(lib.addMonths("2026-01-31", 1), "2026-02-28");
  assert.equal(lib.addMonths("2028-01-31", 1), "2028-02-29");
  assert.equal(lib.addMonths("2026-03-31", 1), "2026-04-30");
  assert.equal(lib.addMonths("2026-12-15", 1), "2027-01-15");
  assert.equal(lib.addMonths("2026-01-15", -2), "2025-11-15");
});

test("addYears clamps Feb 29 in non-leap years", () => {
  assert.equal(lib.addYears("2028-02-29", 1), "2029-02-28");
  assert.equal(lib.addYears("2028-02-29", 4), "2032-02-29");
  assert.equal(lib.addYears("2026-06-15", 2), "2028-06-15");
});

test("recur expands each frequency from the base day", () => {
  assert.deepEqual(lib.recur("2026-11-02", "week", 3), ["2026-11-02", "2026-11-09", "2026-11-16"]);
  assert.deepEqual(lib.recur("2026-11-02", "biweek", 3), ["2026-11-02", "2026-11-16", "2026-11-30"]);
  assert.deepEqual(lib.recur("2026-11-02", "year", 2), ["2026-11-02", "2027-11-02"]);
  assert.deepEqual(lib.recur("2026-11-02", "anything-else", 2), ["2026-11-02", "2026-11-09"]); // weekly default
  assert.deepEqual(lib.recur("2026-11-02", "week", 0), []);
});

test("monthly recurrence is computed from the base day, not chained", () => {
  // chaining would drift to the 28th forever after February; each month should recover
  assert.deepEqual(lib.recur("2026-01-31", "month", 4), ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]);
});

// ---- availability ----------------------------------------------------------------
test("freeGaps: an empty day is one big gap", () => {
  assert.deepEqual(lib.freeGaps([], 0, 1440), [[0, 1440]]);
});

test("freeGaps: a fully booked day has no gaps", () => {
  assert.deepEqual(lib.freeGaps([[0, 1440]], 0, 1440), []);
});

test("freeGaps merges overlapping and touching intervals", () => {
  const gaps = lib.freeGaps([[600, 720], [700, 800], [800, 900]], 0, 1440);
  assert.deepEqual(gaps, [[0, 600], [900, 1440]]);
});

test("freeGaps ignores unsorted input order", () => {
  assert.deepEqual(lib.freeGaps([[900, 1000], [100, 200]], 0, 1440), [[0, 100], [200, 900], [1000, 1440]]);
});

test("freeGaps drops slivers shorter than 30 minutes", () => {
  assert.deepEqual(lib.freeGaps([[0, 600], [620, 1440]], 0, 1440), []); // 20 min gap ignored
  assert.deepEqual(lib.freeGaps([[0, 600], [630, 1440]], 0, 1440), [[600, 630]]); // exactly 30 kept
});

// ---- formatting ------------------------------------------------------------------
test("hmWrap wraps out-of-range minutes and flags the day shift", () => {
  assert.equal(lib.hmWrap(90), "01:30");
  assert.equal(lib.hmWrap(1500), "01:00 (+1d)");
  assert.equal(lib.hmWrap(-60), "23:00 (-1d)");
});

test("minToHM pads and wraps at 24h", () => {
  assert.equal(lib.minToHM(5), "00:05");
  assert.equal(lib.minToHM(1380), "23:00");
  assert.equal(lib.minToHM(1440), "00:00");
});

test("evLabel prefers title, then detail, then the tag name", () => {
  assert.equal(lib.evLabel({ title: "Movie night", detail: "Dune", tag: "movie" }), "Movie night");
  assert.equal(lib.evLabel({ title: "", detail: "Dune", tag: "movie" }), "Dune");
  assert.equal(lib.evLabel({ title: "", detail: "", tag: "out of town" }), "Out of town");
});

test("signed shows the hour difference with a sign", () => {
  assert.equal(lib.signed(0), "same");
  assert.equal(lib.signed(180), "+3h");
  assert.equal(lib.signed(-120), "\u22122h");
});

// ---- escaping --------------------------------------------------------------------
test("esc escapes the five HTML-significant characters", () => {
  assert.equal(lib.esc(`<a href="x" title='y'>&</a>`),
    "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;");
});

test("esc handles null, undefined and non-strings", () => {
  assert.equal(lib.esc(null), "");
  assert.equal(lib.esc(undefined), "");
  assert.equal(lib.esc(42), "42");
  assert.equal(lib.esc(0), "0");
  assert.equal(lib.esc(""), "");
});

test("esc leaves ordinary text, unicode and spaces alone", () => {
  assert.equal(lib.esc("Movie night \u2013 caf\u00e9 \u65e5\u672c\u8a9e"), "Movie night \u2013 caf\u00e9 \u65e5\u672c\u8a9e");
});

test("esc is not idempotent on purpose: already-escaped text is shown literally", () => {
  assert.equal(lib.esc("&lt;"), "&amp;lt;");
});

test("esc stops an attribute breakout", () => {
  const attr = `title="${lib.esc('" onmouseover="alert(1)')}"`;
  assert.ok(!attr.includes('" onmouseover="'));
});

test("safeColor accepts #rrggbb only", () => {
  assert.equal(lib.safeColor("#6c8cff"), "#6c8cff");
  assert.equal(lib.safeColor("#ABCDEF"), "#ABCDEF");
  for (const bad of [undefined, null, "", "red", "#fff", "#12345", "#1234567", "#12345g",
                     "red;background:url(javascript:alert(1))", "#112233;x"]) {
    assert.equal(lib.safeColor(bad), "#6c8cff", String(bad));
  }
});

// ---- timezones -------------------------------------------------------------------
test("zoneOf falls back to Pacific for unknown zones", () => {
  assert.equal(lib.zoneOf("America/New_York").abbr, "ET");
  assert.equal(lib.zoneOf("Mars/Olympus_Mons").abbr, "PT");
});

test("tzDiffMinutes between the big US zones", () => {
  assert.equal(lib.tzDiffMinutes("America/Los_Angeles", "America/New_York", "2026-01-15"), 180);
  assert.equal(lib.tzDiffMinutes("America/Los_Angeles", "America/New_York", "2026-07-15"), 180);
  assert.equal(lib.tzDiffMinutes("America/New_York", "America/Los_Angeles", "2026-07-15"), -180);
  assert.equal(lib.tzDiffMinutes("America/Chicago", "America/Chicago", "2026-07-15"), 0);
});

test("tzDiffMinutes follows daylight saving: Arizona never changes, New York does", () => {
  assert.equal(lib.tzDiffMinutes("America/New_York", "America/Phoenix", "2026-01-15"), -120);
  assert.equal(lib.tzDiffMinutes("America/New_York", "America/Phoenix", "2026-07-15"), -180);
  assert.equal(lib.tzDiffMinutes("America/Phoenix", "Pacific/Honolulu", "2026-07-15"), -180);
});

test("tzOffsetMinutes is east-positive and DST-aware", () => {
  assert.equal(lib.tzOffsetMinutes("America/New_York", new Date("2026-01-15T12:00:00Z")), -300);
  assert.equal(lib.tzOffsetMinutes("America/New_York", new Date("2026-07-15T12:00:00Z")), -240);
  assert.equal(lib.tzOffsetMinutes("Pacific/Honolulu", new Date("2026-07-15T12:00:00Z")), -600);
});
