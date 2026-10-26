"""Offline first-chapter charts consuming already aggregated report buckets."""

ECHO_RHYTHM_CSS = r"""
.rhythm-chapter [hidden] { display: none !important; }
#overview { min-height: auto; padding: 34px 64px 24px; }
#overview .chapter-header h2 { font-size: 47px; }
#overview .chapter-intro { margin: 18px 0 22px; font-size: 16px; }
.rhythm-paper-meta { display: flex; justify-content: space-between; margin-bottom: 26px; color: var(--muted); font-size: 10px; letter-spacing: .12em; }
.rhythm-paper-meta span:last-child { max-width: 55%; overflow-wrap: anywhere; text-align: right; }
.rhythm-summary { display: grid; grid-template-columns: 1.5fr 1fr 1fr; padding: 24px 0 25px; align-items: center; border-block: 1px solid var(--ink); }
.rhythm-summary.is-group { grid-template-columns: 1.55fr 1fr 1fr .9fr; }
.rhythm-stat { padding-left: 27px; border-left: 1px solid var(--rule); min-width: 0; }
.rhythm-stat-primary { padding-left: 0; border: 0; }
.rhythm-stat > span { color: var(--muted); font-size: 11px; letter-spacing: .08em; }
.rhythm-stat p { margin: 7px 0 0; display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; line-height: 1.1; }
.rhythm-stat strong { font: 400 32px/1.1 var(--serif); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.rhythm-stat-primary strong { font-size: 51px; letter-spacing: -.04em; }
.rhythm-stat p > span { font-size: 11px; color: var(--muted); }
.rhythm-count-note { margin: 12px 0 26px; color: var(--muted); font-size: 11px; line-height: 1.8; }
.rhythm-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 18px; margin-bottom: 24px; }
.rhythm-toolbar > h3 { margin: 0; font: 500 18px var(--serif); }
.rhythm-toolbar > h3::before { content: ""; display: inline-block; vertical-align: middle; width: 18px; height: 2px; background: var(--accent); margin-right: 11px; }
.rhythm-scopes { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 2px; padding: 3px; background: #e7e1d6; border-radius: 4px; }
.rhythm-scopes button { max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border: 0; border-radius: 2px; padding: 4px 10px; background: transparent; color: var(--muted); font: 11px var(--sans); cursor: pointer; }
.rhythm-scopes button[aria-pressed=true] { background: var(--paper); color: var(--ink); box-shadow: 0 1px 3px #29272010; }
#rhythm-member { min-width: 90px; max-width: 45%; border: 1px solid var(--rule); padding: 5px 10px; background: transparent; color: var(--ink); border-radius: 4px; font: 12px var(--sans); }
.rhythm-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 42px; }
.rhythm-hour-section { padding-right: 34px; border-right: 1px solid var(--rule); min-width: 0; }
.rhythm-week-section { min-width: 0; }
.rhythm-chart-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; min-height: 47px; }
.rhythm-chart-heading h3 { margin: 0; font: 500 20px/1.4 var(--serif); }
.rhythm-chart-heading p { margin: 5px 0 0; font-size: 10px; color: var(--muted); }
.rhythm-view-toggle { display: flex; gap: 5px; }
.rhythm-view-toggle button { min-width: 57px; min-height: 36px; padding: 6px 10px; border: 1px solid var(--rule); border-radius: 4px; background: none; color: var(--muted); font: 12px var(--sans); cursor: pointer; }
.rhythm-view-toggle button[aria-pressed=true] { background: #e7d8cb; border-color: #c49e85; color: #824832; }
.rhythm-dial-wrap { position: relative; width: min(100%, 332px); aspect-ratio: 1; margin: 8px auto 0; }
#hour-dial { display: block; width: 100%; height: 100%; overflow: visible; }
.rhythm-dial-center { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 165px; text-align: center; pointer-events: none; display: flex; align-items: center; flex-direction: column; gap: 2px; }
.rhythm-dial-center > span:first-child { min-height: 16px; font-size: 10px; color: var(--muted); margin-bottom: 6px; }
.rhythm-dial-center strong { font: 400 37px/1.12 var(--serif); letter-spacing: -.025em; }
.rhythm-dial-center > strong + span { color: var(--muted); font-size: 10px; }
.rhythm-dial-center b { margin-top: 9px; font: 500 12px var(--sans); }
#hour-share { font-size: 9px; color: var(--accent); margin-top: 4px; }
.rhythm-hour-sector { cursor: pointer; outline: none; }
.rhythm-hour-sector[aria-disabled=true] { cursor: default; }
.rhythm-hour-hit { fill: transparent; }
.rhythm-hour-sector:hover .rhythm-hour-hit { fill: #9b5b450b; }
.rhythm-hour-sector:focus-visible .rhythm-hour-hit { fill: #52706618; stroke: var(--viewer); stroke-width: 1; }
.rhythm-scopes button:focus-visible, .rhythm-view-toggle button:focus-visible, #rhythm-member:focus-visible, .rhythm-hour-bars button:focus-visible { outline: 2px solid var(--viewer); outline-offset: 3px; }
.rhythm-wheel-hint { margin: 0; text-align: center; font: 12px/1.6 var(--serif); color: var(--muted); }
.rhythm-week-row { display: grid; grid-template-columns: 35px 1fr 58px; gap: 12px; align-items: center; min-height: 39px; }
#rhythm-week-rows { margin-top: 20px; }
.rhythm-week-row > span { font-size: 11px; color: var(--muted); }
.rhythm-week-row strong { font: 400 13px var(--serif); text-align: right; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.rhythm-week-track { height: 6px; background: #e5ded2; overflow: hidden; }
.rhythm-week-track i { height: 100%; display: block; background: #c9a28f; }
.rhythm-week-row.peak .rhythm-week-track i { background: var(--accent); }
.rhythm-week-row.peak > span, .rhythm-week-row.peak strong { color: var(--accent); }
.rhythm-week-conclusion { padding-top: 14px; margin: 16px 0 0; border-top: 1px solid var(--rule); color: var(--muted); font: 14px/1.6 var(--serif); }
.rhythm-week-conclusion::before { content: "↗"; color: var(--accent); font-size: 20px; margin-right: 10px; }
.rhythm-footer { display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--rule); margin-top: 27px; padding-top: 14px; color: var(--muted); font-size: 10px; }
.rhythm-footer > span:last-child { font: italic 21px var(--serif); }
.rhythm-footer i { font: 10px var(--sans); margin-left: 16px; color: var(--accent); }
.rhythm-bar-wrap { width: min(100%, 332px); aspect-ratio: 1; margin: 8px auto 0; display: flex; flex-direction: column; justify-content: center; padding-top: 15px; }
.rhythm-hour-bars { display: grid; grid-template-columns: repeat(24, minmax(0, 1fr)); gap: 4px; height: 172px; align-items: end; border-bottom: 1px solid var(--rule); background: repeating-linear-gradient(to top, transparent 0 42px, #d2cabd66 42px 43px); }
.rhythm-hour-bars button { min-width: 0; width: 100%; height: var(--height); min-height: 3px; border: 0; border-radius: 2px 2px 0 0; padding: 0; background: #d0ab98; cursor: pointer; }
.rhythm-hour-bars button[aria-pressed=true] { background: var(--accent); }
.rhythm-bar-axis { display: flex; justify-content: space-between; padding-top: 9px; color: var(--muted); font-size: 9px; }
.rhythm-bar-readout { text-align: center; margin-top: 26px; font: 14px var(--serif); color: var(--accent); }
@media (max-width: 760px) {
  #overview { padding: 25px 24px 22px; }
  #overview .chapter-header { gap: 15px; }
  #overview .chapter-header h2 { font-size: 36px; }
  #overview .chapter-intro { font-size: 14px; margin: 17px 0 20px; }
  .rhythm-paper-meta { margin-bottom: 23px; font-size: 9px; }
  .rhythm-summary, .rhythm-summary.is-group { grid-template-columns: 1.3fr 1fr 1fr; padding: 23px 0; }
  .rhythm-stat { padding-left: 13px; }
  .rhythm-stat-primary { padding-left: 0; }
  .rhythm-stat > span { font-size: 9px; letter-spacing: 0; }
  .rhythm-stat strong { font-size: 24px; }
  .rhythm-stat-primary strong { font-size: 36px; }
  .rhythm-stat p { gap: 5px; }
  .rhythm-stat p > span { font-size: 9px; }
  .rhythm-summary.is-group .rhythm-participants { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--rule); padding: 13px 0 0; margin-top: 15px; display: flex; align-items: baseline; gap: 14px; }
  .rhythm-summary.is-group .rhythm-participants p { margin: 0; }
  .rhythm-participants strong { font-size: 20px; }
  .rhythm-toolbar { gap: 10px; }
  .rhythm-toolbar > h3 { font-size: 16px; flex-shrink: 0; }
  .rhythm-toolbar > h3::before { width: 12px; margin-right: 8px; }
  .rhythm-scopes { min-width: 0; }
  .rhythm-scopes button { max-width: 105px; font-size: 10px; padding: 4px 8px; }
  .rhythm-charts { grid-template-columns: 1fr; gap: 30px; }
  .rhythm-hour-section { padding: 0 0 25px; border-right: 0; border-bottom: 1px solid var(--rule); }
  .rhythm-view-toggle button { min-width: 58px; min-height: 42px; padding: 7px 10px; }
  .rhythm-dial-wrap { width: min(100%, 320px); }
  .rhythm-bar-wrap { width: min(100%, 320px); }
  #rhythm-week-rows { margin-top: 12px; }
  .rhythm-week-row { min-height: 37px; }
}
@media print {
  #overview { padding: 24px; }
  .rhythm-scopes, #rhythm-member, .rhythm-view-toggle, .rhythm-wheel-hint { display: none !important; }
  .rhythm-charts { grid-template-columns: 1fr 1fr; gap: 30px; break-inside: avoid; }
  .rhythm-hour-section { padding: 0 22px 0 0; border-right: 1px solid var(--rule); border-bottom: 0; }
  .rhythm-summary { grid-template-columns: 1.5fr 1fr 1fr; }
  .rhythm-summary.is-group { grid-template-columns: 1.5fr 1fr 1fr 1fr; }
  .rhythm-summary.is-group .rhythm-participants { grid-column: auto; border-top: 0; border-left: 1px solid var(--rule); padding: 0 0 0 20px; margin: 0; display: block; }
}
"""

ECHO_RHYTHM_APP_JS = r"""
(function () {
  "use strict";
  var data = window.ECHO_DATA || {};
  var root = document.getElementById("overview");
  var dial = document.getElementById("hour-dial");
  var bars = document.getElementById("hour-bars-preview");
  if (!root || !dial || !bars) return;
  var days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  var kind = (data.conversation || {}).kind;
  var members = (data.members || []).filter(function (m) { return typeof m.speaker_key === "string" && m.speaker_key; });
  var state = { scope: "", view: "dial", hour: null };
  var wheelAmount = 0, lastWheelAt = 0;
  function node(id) { return document.getElementById(id); }
  function text(id, value) { node(id).textContent = value; }
  function number(value) { return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function buckets(points, count, indexOf, missing) {
    var result = Array(count).fill(missing === undefined ? 0 : missing);
    (points || []).forEach(function (point) {
      var index = indexOf(point.label), value = Number(point.value);
      if (index >= 0 && index < count && Number.isFinite(value) && value >= 0) result[index] = value;
    });
    return result;
  }
  function current() {
    var member = members.find(function (m) { return m.speaker_key === state.scope; });
    var activity = member ? member.activity || {} : data.activity || {};
    return { hours: buckets(activity.hourly, 24, function (label) { return parseInt(label, 10); }),
      week: buckets(activity.weekday_daily_average, 7, function (label) { return days.indexOf(label); }, null),
      label: member ? labelFor(member) : "整体" };
  }
  function peak(values) { var max = Math.max.apply(null, values); return max > 0 ? values.indexOf(max) : null; }
  function hourRange(hour) { return String(hour).padStart(2, "0") + ":00—" + String(hour + 1).padStart(2, "0") + ":00"; }
  function point(radius, hour) { var a = hour * Math.PI / 12 - Math.PI / 2; return [170 + radius * Math.cos(a), 170 + radius * Math.sin(a)]; }
  function svg(name, attributes) {
    var item = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attributes).forEach(function (key) { item.setAttribute(key, attributes[key]); });
    return item;
  }
  function wedge(hour) {
    var a = point(145, hour - .47), b = point(145, hour + .47), c = point(77, hour + .47), d = point(77, hour - .47);
    return "M" + a.join(",") + "A145,145 0 0 1 " + b.join(",") + "L" + c.join(",") + "A77,77 0 0 0 " + d.join(",") + "Z";
  }
  function selectHour(hour, focus) {
    if (state.hour === null) return;
    state.hour = (hour + 24) % 24;
    render();
    if (focus) (state.view === "dial" ? dial : bars).querySelector('[data-hour="' + state.hour + '"]').focus({preventScroll: true});
  }
  function renderHours(values) {
    var max = Math.max.apply(null, values), enabled = max > 0;
    dial.replaceChildren(svg("circle", { cx: 170, cy: 170, r: 83, fill: "none", stroke: "#d2cabd", "stroke-width": .6 }));
    bars.replaceChildren();
    values.forEach(function (value, hour) {
      var tickA = point(137, hour), tickB = point(hour % 4 === 0 ? 144 : 141, hour);
      dial.appendChild(svg("line", { x1: tickA[0], y1: tickA[1], x2: tickB[0], y2: tickB[1], stroke: "#b2a898", "stroke-width": hour % 4 === 0 ? 1.2 : .7 }));
      if (hour % 4 === 0) {
        var p = point(157, hour), label = svg("text", { x: p[0], y: p[1] + 3, "text-anchor": "middle", fill: "#716b61", "font-size": 10, "font-family": "Microsoft YaHei, sans-serif" });
        label.textContent = String(hour).padStart(2, "0"); dial.appendChild(label);
      }
      var selected = hour === state.hour;
      var group = svg("g", { "class": "rhythm-hour-sector", "role": "button", "tabindex": enabled ? 0 : -1, "data-hour": hour,
        "aria-pressed": selected, "aria-disabled": !enabled, "aria-label": hourRange(hour) + "，" + number(value) + "条" });
      group.appendChild(svg("path", { "class": "rhythm-hour-hit", d: wedge(hour) }));
      var a = point(88, hour), b = point(90 + (max ? 39 * value / max : 0), hour);
      group.appendChild(svg("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: selected ? "#9b5b45" : "#d3af9c", "stroke-width": selected ? 8 : 6, "stroke-linecap": "round", "pointer-events": "none" }));
      group.addEventListener("click", function () { selectHour(hour, true); });
      group.addEventListener("keydown", function (event) {
        if (enabled && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); selectHour(hour, true); }
      });
      dial.appendChild(group);
      var bar = document.createElement("button");
      bar.type = "button"; bar.dataset.hour = hour; bar.disabled = !enabled;
      bar.style.setProperty("--height", (max ? value / max * 100 : 0) + "%");
      bar.setAttribute("aria-label", hourRange(hour) + "，" + number(value) + "条");
      bar.setAttribute("aria-pressed", selected);
      bar.addEventListener("click", function () { selectHour(hour, true); });
      bars.appendChild(bar);
    });
    if (state.hour !== null) { var marker = point(148, state.hour); dial.appendChild(svg("circle", { cx: marker[0], cy: marker[1], r: 2.7, fill: "#9b5b45", "pointer-events": "none" })); }
  }
  function render() {
    var selected = current(), hours = selected.hours, hour = state.hour;
    var total = hours.reduce(function (a, b) { return a + b; }, 0);
    text("rhythm-scope-label", selected.label + " · 消息分布");
    text("hour-context", hour !== null && hour === peak(hours) ? "消息最多的小时" : "");
    text("hour-count", hour === null ? "—" : number(hours[hour]));
    text("hour-range", hour === null ? "暂无有效时间" : hourRange(hour));
    var share = hour === null ? "" : "占当前有效时间消息 " + (hours[hour] / total * 100).toFixed(1) + "%";
    text("hour-share", share);
    text("rhythm-bar-readout", hour === null ? "暂无有效时间" : hourRange(hour) + " · " + number(hours[hour]) + " 条 · " + share);
    renderHours(hours);
    node("dial-wrap").hidden = state.view !== "dial"; node("bar-wrap").hidden = state.view !== "bars";
    var rows = node("rhythm-week-rows"), weekPeak = peak(selected.week), max = Math.max.apply(null, selected.week);
    rows.replaceChildren();
    selected.week.forEach(function (value, day) {
      var row = document.createElement("div"); row.className = "rhythm-week-row" + (day === weekPeak ? " peak" : "");
      var label = document.createElement("span"); label.textContent = days[day];
      var track = document.createElement("div"); track.className = "rhythm-week-track";
      var fill = document.createElement("i"); fill.style.width = (max ? value / max * 100 : 0) + "%"; track.appendChild(fill);
      var count = document.createElement("strong"); count.textContent = value === null ? "—" : number(value.toFixed(1));
      row.append(label, track, count); rows.appendChild(row);
    });
    text("rhythm-week-conclusion", weekPeak === null
      ? (selected.week.some(function (value) { return value !== null; }) ? "这段记录里，暂无可统计的消息。" : "暂无可计算日均的日期范围。")
      : "平均来看，" + days[weekPeak] + "聊得最多。");
    root.querySelectorAll("[data-rhythm-member]").forEach(function (button) { button.setAttribute("aria-pressed", button.dataset.rhythmMember === state.scope); });
    root.querySelectorAll("[data-hour-view]").forEach(function (button) { button.setAttribute("aria-pressed", button.dataset.hourView === state.view); });
  }
  function wheel(event) {
    if (state.hour === null || event.ctrlKey || event.metaKey || event.altKey || !event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    if (!event.currentTarget.contains(document.activeElement)) return;
    event.preventDefault();
    var now = performance.now();
    if (now - lastWheelAt > 180 || Math.sign(wheelAmount) !== Math.sign(event.deltaY)) wheelAmount = 0;
    lastWheelAt = now;
    wheelAmount += event.deltaY * (event.deltaMode === 1 ? 18 : event.deltaMode === 2 ? 120 : 1);
    if (Math.abs(wheelAmount) >= 48) { selectHour(state.hour + (wheelAmount > 0 ? 1 : -1), true); wheelAmount = 0; }
  }
  var viewerKnown = kind === "private" && members.length === 2 && members.filter(function (m) { return m.is_viewer === true; }).length === 1;
  function labelFor(member) { return viewerKnown ? (member.is_viewer ? "你" : "TA") : member.display_name || "未命名成员"; }
  function changeScope(key) { state.scope = key; state.hour = peak(current().hours); wheelAmount = 0; render(); }
  var select = node("rhythm-member"), scopes = node("rhythm-private-scopes");
  [{ speaker_key: "", display_name: kind === "group" ? "全群" : "整体" }].concat(members).forEach(function (member, index) {
    var label = index ? labelFor(member) : member.display_name;
    var option = document.createElement("option"); option.value = member.speaker_key; option.textContent = label; select.appendChild(option);
    if (kind === "private" && members.length === 2) {
      var button = document.createElement("button"); button.type = "button"; button.dataset.rhythmMember = member.speaker_key; button.textContent = label; button.title = label;
      button.addEventListener("click", function () { select.value = member.speaker_key; changeScope(member.speaker_key); }); scopes.appendChild(button);
    }
  });
  scopes.hidden = kind !== "private" || members.length !== 2;
  select.hidden = kind !== "group" || !members.length;
  select.addEventListener("change", function () { changeScope(select.value); });
  node("rhythm-summary").classList.toggle("is-group", kind !== "private");
  node("rhythm-participants").hidden = kind === "private";
  text("rhythm-conversation-name", (data.conversation || {}).name || "");
  var calendarDays = (data.activity || {}).calendar_day_count;
  var periodLabel = "";
  if (Number.isInteger(calendarDays) && calendarDays > 0) {
    periodLabel = " · 记录跨度：" + (calendarDays < 7 ? "不足 1 周" : "约 " + Math.round(calendarDays / 7) + " 周");
  }
  text("rhythm-week-note", "周一至周日 · 平均每天的消息数" + periodLabel);
  root.querySelectorAll("[data-hour-view]").forEach(function (button) { button.addEventListener("click", function () { state.view = button.dataset.hourView; render(); }); });
  dial.addEventListener("wheel", wheel, { passive: false }); bars.addEventListener("wheel", wheel, { passive: false });
  state.hour = peak(current().hours); render();
})();
"""
