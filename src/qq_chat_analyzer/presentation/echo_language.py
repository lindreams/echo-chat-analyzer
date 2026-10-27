"""Read-only, offline original-message lookup for the language chapter."""

ECHO_LANGUAGE_CSS = r"""
#voices, #expression { min-height: 0; padding: 34px 64px 64px; }
#voices .chapter-intro { margin: 18px 0 26px; }
.language-word-button { appearance: none; border: 0; border-radius: 0; background: transparent; padding: 0; color: inherit; font: inherit; line-height: inherit; letter-spacing: inherit; cursor: pointer; text-align: inherit; overflow-wrap: anywhere; }
.language-word-button:hover { color: var(--accent); }
.language-word-button:focus-visible, #language-originals button:focus-visible { outline: 1px solid var(--viewer); outline-offset: 3px; }
@media screen { html:has(#language-originals[open]) { overflow: hidden; scrollbar-gutter: stable; } }
#language-originals { width: min(760px, calc(100% - 32px)); max-width: none; max-height: min(840px, calc(100dvh - 40px)); padding: 0; border: 1px solid var(--rule); background: var(--paper); color: var(--ink); box-shadow: 0 18px 70px #29272033; overflow: hidden; }
#language-originals:not([open]) { display: none; }
#language-originals[open] { display: flex; flex-direction: column; }
#language-originals::backdrop { background: #29272066; }
.language-original-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; padding: 26px 28px 18px; border-bottom: 1px solid var(--rule); }
.language-original-header > div { min-width: 0; }
.language-original-header h3 { margin: 0; font: 500 25px/1.5 var(--serif); overflow-wrap: anywhere; }
.language-original-header .folio { font-size: 10px; margin-bottom: 8px; }
.language-original-summary { margin: 8px 0 0; color: var(--muted); font: 12px/1.8 var(--sans); }
#language-originals button { font-family: var(--sans); }
.language-original-close { flex: 0 0 auto; padding: 5px 0; border: 0; background: none; color: var(--muted); font-size: 12px; cursor: pointer; }
.language-original-results { padding: 0 28px; overflow: auto; overscroll-behavior: contain; overflow-anchor: none; scrollbar-width: thin; min-height: 0; scroll-behavior: auto; }
.language-original-results:focus-visible { outline: 1px solid var(--viewer); outline-offset: -1px; }
.language-original-hit { padding: 20px 0; border-bottom: 1px solid var(--rule); }
.language-original-hit:last-child { border-bottom: 0; }
.language-original-row { padding: 10px 12px; min-width: 0; }
.language-original-row.is-match { background: #e9e4da; border-left: 2px solid var(--viewer); }
.language-original-meta { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 4px 16px; margin-bottom: 7px; color: var(--muted); font: 11px/1.7 var(--sans); }
.language-original-meta > span { color: var(--viewer); overflow-wrap: anywhere; }
.language-original-meta time { font-variant-numeric: tabular-nums; }
.language-original-text { margin: 0; font: 14px/1.9 var(--sans); white-space: pre-wrap; overflow-wrap: anywhere; user-select: text; }
.language-original-row.is-context .language-original-text { color: var(--muted); font-size: 13px; }
.language-context-toggle, .language-all, .language-more { border: 0; border-bottom: 1px solid var(--rule); padding: 4px 0; background: transparent; color: var(--accent); font-size: 12px; line-height: 1.6; cursor: pointer; }
.language-context-toggle { margin: 10px 0 0 12px; }
.language-original-footer { display: flex; justify-content: space-between; flex-wrap: wrap; align-items: baseline; gap: 12px; border-top: 1px solid var(--rule); padding: 16px 28px; color: var(--muted); font: 12px/1.7 var(--sans); }
.language-original-footer [hidden] { display: none !important; }
.language-original-empty { padding: 24px 0; color: var(--muted); font: 14px/1.8 var(--sans); }
@media(max-width: 720px) {
  #voices, #expression { padding: 28px 22px 54px; }
  #voices .chapter-intro, #expression .chapter-intro { margin: 17px 0 20px; }
  #language-originals { width: calc(100% - 20px); max-height: calc(100dvh - 24px); }
  .language-original-header { padding: 20px 18px 15px; gap: 12px; }
  .language-original-header h3 { font-size: 22px; }
  .language-original-results { padding: 0 16px; }
  .language-original-footer { padding: 14px 18px; }
  .language-original-meta { font-size: 10px; }
}
@media print {
  #language-originals { display: none !important; }
  .language-word-button { color: inherit; }
}
"""


ECHO_LANGUAGE_APP_JS = r"""
(function () {
  "use strict";
  var data = window.ECHO_DATA;
  var sources = data && data.language_sources;
  var chapter = document.getElementById("voices");
  var dialog = document.getElementById("language-originals");
  if (!sources || !chapter || !dialog) return;
  var originals = new Map((sources.messages || []).map(function (message) { return [message.ref, message]; }));
  var terms = new Map((sources.terms || []).map(function (term) {
    return [JSON.stringify([term.member_index, term.word]), term];
  }));
  var results = dialog.querySelector(".language-original-results");
  var summary = dialog.querySelector(".language-original-summary");
  var title = document.getElementById("language-original-title");
  var progress = dialog.querySelector(".language-original-progress");
  var allButton = dialog.querySelector(".language-all");
  var moreButton = dialog.querySelector(".language-more");
  var closeButton = dialog.querySelector(".language-original-close");
  var current = null, rendered = 0, preview = true, trigger = null;
  var backdropPress = false;

  function element(tag, className, text) {
    var node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function messageRow(message, isMatch) {
    var row = element("div", "language-original-row " + (isMatch ? "is-match" : "is-context"));
    var meta = element("div", "language-original-meta");
    meta.appendChild(element("span", "", message.speaker_label));
    meta.appendChild(element("time", "", message.timestamp || "时间未知"));
    row.appendChild(meta);
    row.appendChild(element("p", "language-original-text", message.text || "［非文字消息］"));
    return row;
  }
  function hitCard(message) {
    var article = element("article", "language-original-hit");
    var lines = element("div", "language-original-lines");
    article.appendChild(lines);
    var before = message.before_refs || [], after = message.after_refs || [];
    var expanded = false;
    function draw() {
      lines.textContent = "";
      var refs = expanded ? before.concat([message.ref], after) : [message.ref];
      refs.forEach(function (ref) {
        var original = originals.get(ref);
        if (original) lines.appendChild(messageRow(original, ref === message.ref));
      });
    }
    draw();
    if (before.length || after.length) {
      var toggle = element("button", "language-context-toggle", "前后几句 ↓");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", "false");
      toggle.addEventListener("click", function () {
        var oldTop = lines.getBoundingClientRect().top;
        expanded = !expanded;
        draw();
        toggle.textContent = expanded ? "收起上下文 ↑" : "前后几句 ↓";
        toggle.setAttribute("aria-expanded", String(expanded));
        // Keep the start of the passage visible, rather than anchoring the
        // button below it and scrolling the newly revealed front context away.
        var visibleTop = Math.max(oldTop, results.getBoundingClientRect().top + 12);
        results.scrollTop += lines.getBoundingClientRect().top - visibleTop;
      });
      article.appendChild(toggle);
    }
    return article;
  }
  function appendUntil(limit) {
    var refs = current.message_refs || [];
    var end = Math.min(limit, refs.length);
    for (; rendered < end; rendered++) {
      var message = originals.get(refs[rendered]);
      if (message) results.appendChild(hitCard(message));
    }
    if (!refs.length) results.appendChild(element("p", "language-original-empty", "这份报告暂未收录这个词的原话。"));
    progress.textContent = "已显示 " + rendered + " / " + refs.length + " 条";
    allButton.hidden = !preview || rendered >= refs.length;
    moreButton.hidden = preview || rendered >= refs.length;
  }
  chapter.addEventListener("click", function (event) {
    var button = event.target.closest(".language-word-button");
    if (!button || !chapter.contains(button)) return;
    var memberIndex = button.dataset.languageMember === "all" ? null : Number(button.dataset.languageMember);
    var term = terms.get(JSON.stringify([memberIndex, button.dataset.languageWord]));
    if (!term) return;
    current = term;
    trigger = button;
    rendered = 0;
    preview = true;
    results.textContent = "";
    var member = memberIndex === null ? null : data.language_profile.members[memberIndex];
    title.textContent = term.word + " · " + (member ? member.display_name + "的原话" : "双方的原话");
    summary.textContent = "出现 " + term.occurrence_count + " 次，分布于 " + term.message_refs.length + " 条消息";
    appendUntil(3);
    results.scrollTop = 0;
    dialog.showModal();
    closeButton.focus({preventScroll: true});
  });
  allButton.addEventListener("click", function () {
    preview = false;
    appendUntil(10);
  });
  moreButton.addEventListener("click", function () { appendUntil(rendered + 10); });
  closeButton.addEventListener("click", function () { dialog.close(); });
  function outsideDialog(event) {
    var box = dialog.getBoundingClientRect();
    return event.clientX < box.left || event.clientX > box.right ||
      event.clientY < box.top || event.clientY > box.bottom;
  }
  dialog.addEventListener("pointerdown", function (event) {
    backdropPress = event.button === 0 && event.target === dialog && outsideDialog(event);
  });
  dialog.addEventListener("pointercancel", function () { backdropPress = false; });
  dialog.addEventListener("click", function (event) {
    if (backdropPress && event.target === dialog && outsideDialog(event)) dialog.close();
    backdropPress = false;
  });
  dialog.addEventListener("close", function () {
    backdropPress = false;
    if (trigger && trigger.isConnected) trigger.focus({preventScroll: true});
  });
})();
"""
