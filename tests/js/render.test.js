// Renders the real UI scripts against a fake DOM, with hostile names and titles, and checks that
// nothing user-typed reaches the page as live HTML. Run:  node --test "tests/js/**/*.test.js"
//
// The scripts are classic <script>s that share one global scope, so we load them in the same
// vm context in index.html's order (lib -> assistant -> modal -> app) and then poke the shared
// state directly, exactly as the browser would have it.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const STATIC = path.join(__dirname, "..", "..", "static");

// ---- a just-big-enough fake DOM ---------------------------------------------------
function fakeElement() {
  const el = {
    innerHTML: "", textContent: "", value: "", checked: false, style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, focus() {}, select() {},
  };
  el.closest = () => el;
  return el;
}

function loadApp() {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, fakeElement());
      return elements.get(id);
    },
    querySelectorAll: () => [],
  };
  const context = vm.createContext({
    document, console, setInterval: () => 0, alert() {}, confirm: () => true,
    localStorage: { getItem: () => null, setItem() {} },
    fetch: () => Promise.reject(new Error("no network in tests")),
  });
  for (const file of ["lib.js", "assistant.js", "modal.js", "app.js"]) {
    let code = fs.readFileSync(path.join(STATIC, file), "utf8");
    if (file === "app.js") code = code.replace(/^init\(\);\s*$/m, ""); // don't boot the real app
    vm.runInContext(code, context, { filename: file });
  }
  return { context, elements, run: (code) => vm.runInContext(code, context) };
}

// ---- hostile input ----------------------------------------------------------------
const NAME = '<b>Mallory</b>"><script>alert("name")</script>';
const TITLE = '<img src=x onerror=alert("title")>';
const DETAIL = '" onmouseover="alert(1)" x="';
const RAW_PAYLOADS = ["<b>Mallory", "<img", "<script", 'onmouseover="alert(1)" x="', '"><script'];

function seed(app) {
  app.run(`
    userColors = { ${JSON.stringify(NAME)}: "#112233" };
    userTz = { ${JSON.stringify(NAME)}: "America/New_York" };
    events = [{ id: 1, owner: ${JSON.stringify(NAME)}, day: "2026-11-05", title: ${JSON.stringify(TITLE)},
                tag: "movie", detail: ${JSON.stringify(DETAIL)}, note: "", start_min: 1200, end_min: 1320,
                series_id: null }];
    viewYear = 2026; viewMonth = 10;
    focusDay = "2026-11-05"; selectedDays = new Set([focusDay]);
    involved = new Set(Object.keys(userColors)); involvedInit = true;
  `);
  app.elements.get("asstToggle") ?? app.run('$("asstToggle")');
  app.run('$("asstToggle").checked = true');
}

function assertNoLivePayload(label, html) {
  for (const payload of RAW_PAYLOADS) {
    assert.ok(!html.includes(payload), `${label}: raw payload ${JSON.stringify(payload)} reached the HTML:\n${html}`);
  }
}

// ---- the tests --------------------------------------------------------------------
test("calendar cells escape owner and title", () => {
  const app = loadApp(); seed(app);
  app.run("renderCalendar()");
  const html = app.elements.get("cal").innerHTML;
  assert.ok(html.includes("&lt;img"), "the title should still be shown, as text");
  assertNoLivePayload("calendar", html);
});

test("snapshot chips escape owner, title and detail", () => {
  const app = loadApp(); seed(app);
  app.run("renderSnapshot()");
  const html = app.elements.get("snapChips").innerHTML;
  assert.ok(html.includes("&lt;b&gt;Mallory"), "the name should still be shown, as text");
  assertNoLivePayload("snapshot", html);
});

test("timeline escapes owner and title", () => {
  const app = loadApp(); seed(app);
  app.run("renderTimeline()");
  assertNoLivePayload("timeline", app.elements.get("timeline").innerHTML);
});

test("scheduling assistant escapes people and titles", () => {
  const app = loadApp(); seed(app);
  app.run("renderAssistant()");
  for (const id of ["asstPeople", "asstRows", "asstFreeText"]) {
    assertNoLivePayload(`assistant ${id}`, app.elements.get(id).innerHTML);
  }
});

test("the who-am-I dropdown escapes names", async () => {
  const app = loadApp(); seed(app);
  app.run(`api = async () => [{ name: ${JSON.stringify(NAME)}, color: "#112233", timezone: "America/New_York" }]`);
  await app.run("loadUsers()");
  assertNoLivePayload("dropdown", app.elements.get("me").innerHTML);
});

test("a user color that is not a plain hex never reaches a style attribute", () => {
  const app = loadApp(); seed(app);
  app.run(`userColors = { ${JSON.stringify(NAME)}: 'red;background:url(javascript:alert(1))' }`);
  app.run("renderCalendar(); renderTimeline(); renderAssistant();");
  for (const id of ["cal", "timeline", "asstPeople", "asstRows"]) {
    assert.ok(!app.elements.get(id).innerHTML.includes("javascript:"), `${id} leaked the bad color`);
  }
});

test("ordinary names and titles still render normally (no over-escaping)", () => {
  const app = loadApp(); seed(app);
  app.run(`userColors = { "Sam": "#112233" }; userTz = { "Sam": "America/Chicago" };
           involved = new Set(["Sam"]);
           events[0].owner = "Sam"; events[0].title = "Movie night"; events[0].detail = "Dune";`);
  app.run("renderCalendar(); renderSnapshot();");
  assert.ok(app.elements.get("cal").innerHTML.includes("Sam: Movie night"));
  assert.ok(app.elements.get("snapChips").innerHTML.includes("<b>Sam</b>"));
});
