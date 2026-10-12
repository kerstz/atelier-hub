// FR/EN switch, no build step. French is the source language: with lang="fr" nothing runs.
// With "en", I18N_EN / I18N_RX (i18n.en.js) are applied to text nodes and a few attributes, once at
// load and for every later DOM change (toasts, job cards, API messages). Unknown strings stay French.
const i18n = (() => {
  let lang = "fr";
  try {
    lang = localStorage.getItem("lang") || ((navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en");
  } catch {}
  if (lang !== "en") lang = "fr";
  const ATTRS = ["title", "placeholder", "aria-label"];
  const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA"]);

  function translate(s) {
    if (lang === "fr" || !s) return s;
    const core = s.trim();
    if (!core) return s;
    let out = I18N_EN[core];
    if (out === undefined) {
      for (const [re, rep] of I18N_RX) {
        if (re.test(core)) {
          out = core.replace(re, rep);
          break;
        }
      }
    }
    if (out === undefined) {
      const sep = [" · ", " — "].find((x) => core.includes(x));
      if (sep) {
        const parts = core.split(sep);
        const tp = parts.map((p) => translate(p));
        if (tp.some((p, i) => p !== parts[i])) out = tp.join(sep);
      }
    }
    if (out === undefined || out === core) return s;
    const start = s.indexOf(core);
    return s.slice(0, start) + out + s.slice(start + core.length);
  }

  function node(n) {
    if (n.nodeType === 3) {
      const v = translate(n.nodeValue);
      if (v !== n.nodeValue) n.nodeValue = v;
      return;
    }
    if (n.nodeType !== 1 || n.tagName === "SCRIPT" || n.tagName === "STYLE") return;
    for (const a of ATTRS) {
      const v = n.getAttribute(a);
      if (v) {
        const t = translate(v);
        if (t !== v) n.setAttribute(a, t);
      }
    }
    if (!SKIP.has(n.tagName)) n.childNodes.forEach(node);
  }

  function start() {
    document.documentElement.lang = lang;
    if (lang === "fr") return;
    node(document.body);
    new MutationObserver((records) => {
      for (const r of records) {
        if (r.type === "childList") r.addedNodes.forEach(node);
        else if (r.type === "characterData") node(r.target);
        else if (r.type === "attributes") node(r.target);
      }
    }).observe(document.body, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS});
  }

  function toggle() {
    try {
      localStorage.setItem("lang", lang === "en" ? "fr" : "en");
    } catch {}
    location.reload();
  }

  // language-aware field of an API object ({name, name_en, note, note_en})
  const pick = (o, k) => (lang === "en" && o[`${k}_en`]) || o[k];

  return {get lang() { return lang; }, t: translate, start, toggle, pick};
})();
function i18nTr(s) {
  return i18n.t(s);
}
