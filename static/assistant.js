// Scheduling assistant: pick the people involved and see when they're all free.
// Classic script; at call time it relies on lib.js helpers and on app.js state/helpers
// (userColors, involved, focusDay, eventsOn, toViewer, evGradient, viewerTz, ...).

function renderAssistant() {
  const on = $("asstToggle").checked;
  $("asstBody").style.display = on ? "" : "none";
  if (!on) return;

  const names = Object.keys(userColors);
  // people chips with checkboxes
  $("asstPeople").innerHTML = names.map((n) =>
    `<label class="asst-person ${involved.has(n) ? "" : "off"}" data-name="${esc(n)}">
       <input type="checkbox" ${involved.has(n) ? "checked" : ""} />
       <span class="dot" style="background:${userColor(n)}"></span>${esc(n)}
     </label>`).join("") || `<span class="empty" style="color:var(--muted)">Add some users first.</span>`;
  $("asstPeople").querySelectorAll(".asst-person input").forEach((cb) =>
    cb.addEventListener("change", () => {
      const n = cb.closest(".asst-person").dataset.name;
      cb.checked ? involved.add(n) : involved.delete(n);
      renderAssistant();
    }));

  $("asstHours").innerHTML = [0, 3, 6, 9, 12, 15, 18, 21].map((h) =>
    `<span>${pad(h)}:00</span>`).join("");

  const picked = names.filter((n) => involved.has(n));
  if (!focusDay || !picked.length) {
    $("asstRows").innerHTML = "";
    $("asstFreeText").innerHTML = `<span class="empty" style="color:var(--muted)">Pick a day and at least one person.</span>`;
    return;
  }

  const dayEvs = eventsOn(focusDay);
  // per-person busy rows (converted to YOUR timezone)
  const rows = picked.map((owner) => {
    const abbr = zoneOf(tzOf(owner)).abbr;
    const blocks = dayEvs.filter((e) => e.owner === owner).map((e) => {
      const v = toViewer(e);
      const left = (v.start / 1440) * 100;
      const width = Math.max(0, ((v.end - v.start) / 1440) * 100);
      return `<div class="tl-block" style="left:${left}%;width:${width}%;background:${evGradient(e)}"
                title="${esc(evLabel(e))}: ${hmWrap(v.rawS)}-${hmWrap(v.rawE)} your time">${esc(evLabel(e))}</div>`;
    }).join("");
    return `<div class="tl-row"><div class="tl-name"><span class="dot" style="background:${userColor(owner)}"></span> ${esc(owner)} <span style="color:var(--muted)">${abbr}</span></div><div class="tl-track">${blocks}</div></div>`;
  }).join("");

  // combined free windows for everyone picked, in the viewer's timezone
  const intervals = dayEvs.filter((e) => involved.has(e.owner))
    .map((e) => { const v = toViewer(e); return [v.start, v.end]; });
  const gaps = freeGaps(intervals, 0, 1440);
  const freeBlocks = gaps.map(([s, e]) => {
    const left = (s / 1440) * 100, width = ((e - s) / 1440) * 100;
    return `<div class="tl-block free" style="left:${left}%;width:${width}%"
              title="Everyone free ${minToHM(s)}-${minToHM(e)}">${minToHM(s)}-${minToHM(e)}</div>`;
  }).join("");
  const freeRow = `<div class="tl-row"><div class="tl-name"><b>Everyone free</b></div>
                   <div class="tl-track" style="background:rgba(255,92,114,.18)">${freeBlocks}</div></div>`;

  $("asstRows").innerHTML = rows + freeRow;
  const vAbbr = zoneOf(viewerTz()).abbr;
  $("asstFreeText").innerHTML = gaps.length
    ? `<b>Open slots</b> for ${picked.map(esc).join(", ")} <span style="color:var(--muted)">(your time, ${vAbbr})</span>: ` +
      gaps.map(([s, e]) => `<span class="asst-free-chip">${minToHM(s)} – ${minToHM(e)}</span>`).join("")
    : `<span style="color:var(--busy)">No 30+ min slot where everyone is free that day.</span>`;
}
