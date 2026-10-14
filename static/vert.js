// VERT (AGPL-3.0, /vert/, same origin) as the "Navigateur" mode of Convertir: Atelier's look injected into the iframe.
(() => {
  const $row = $("#cv-mode-row"), $hint = $("#cv-mode-hint"), $atelier = $("#cv-atelier"), $frame = $("#vt-frame");
  const HINTS = {
    atelier: "Tous formats, vidéo et e-books compris. Résultats dans le dossier Atelier › convert.",
    vert: "Images, audio, documents : converti dans le navigateur, téléchargement direct.",
  };
  const VARS = {
    "--bg": "--bg", "--bg-panel": "--surface", "--bg-panel-highlight": "--surface-2", "--bg-button": "--surface-2",
    "--bg-input": "--surface-2", "--bg-separator": "--line", "--fg": "--fg", "--fg-muted": "--dim", "--fg-accent": "--accent-text",
    "--fg-failure": "--bad", "--accent": "--accent-btn", "--accent-alt": "--accent-btn-h", "--accent-pink": "--accent-btn",
    "--accent-purple": "--accent-btn", "--accent-blue": "--accent-btn", "--accent-green": "--accent-btn", "--bg-badge": "--accent-btn",
    "--shadow-panel": "--shadow", "--font-body": "--font", "--font-display": "--font", "--a-radius": "--radius", "--a-line": "--line", "--a-soft": "--accent-soft",
  };
  const DZ = ".auto-rows-\\[240px\\]";
  const SKIN = `
html{font-size:15px;overflow:hidden}
html,body{background:transparent!important;height:auto!important}
body{overflow:visible!important;font:15px/1.5 var(--font-body)!important;-webkit-font-smoothing:antialiased}
.min-h-screen{min-height:0!important;height:auto!important;overflow:visible!important}
.min-h-screen>div:has(>.p-8),.min-h-screen>div:has(>footer),.\\-z-40{display:none!important}
.pb-32,.\\-mt-4{padding-bottom:0!important;margin-top:0!important}
.max-w-6xl,.max-w-\\[778px\\]{max-width:none!important;padding-left:0!important;padding-right:0!important;width:100%!important}
.gap-8{gap:16px!important;padding-left:0!important;padding-right:0!important}
h1,h2,h3,.font-display{font-family:var(--font-body)!important}
h2{font-size:14px!important;font-weight:600!important}
.text-xl,.text-2xl{font-size:15px!important}
.bg-panel{border:1px solid var(--a-line);border-radius:var(--a-radius)!important;box-shadow:var(--shadow-panel)!important}
.rounded-xl,.rounded-2xl,.rounded-2\\.5xl,.rounded-3xl,.rounded-full{border-radius:var(--a-radius)!important}
button{transform:none!important}
.bg-accent,.bg-accent *{color:#fff!important}
svg.lucide{width:18px;height:18px}
.btn,.bg-button{border-radius:var(--a-radius)!important;height:auto!important;padding:8px 16px!important;gap:8px!important;border:1px solid var(--a-line)!important;background:var(--bg-button)!important;color:var(--fg)!important;font-weight:500;white-space:nowrap;max-width:none!important;transition:border-color .15s,background .15s,opacity .15s!important}
.btn:hover,.bg-button:hover{border-color:var(--accent)!important}
.btn.p-4,.btn.w-14{width:auto!important;padding:8px!important}
.btn.highlight,.btn.bg-accent-blue,.btn.bg-accent-purple,.btn.bg-accent-green,.btn.bg-accent-pink{background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important}
.btn.highlight:hover{background:var(--accent-alt)!important}
.gap-8>div:not(.grid)>.bg-panel{background:none!important;border:0!important;box-shadow:none!important;padding:0!important}
.gap-8>div:not(.grid) p.text-xl{font-size:13px!important;color:var(--fg-muted)}
.gap-8>${DZ}{order:-1}
${DZ}{grid-auto-rows:minmax(150px,auto)!important}
${DZ}>button>.bg-panel{gap:4px;padding:24px!important;color:var(--fg-muted)}
${DZ}>button:hover>.bg-panel{border-color:var(--accent)!important}
${DZ}>button .w-16{width:26px!important;height:26px!important;padding:0!important;background:none!important}
${DZ}>button svg{color:var(--fg-muted)!important}
${DZ}>button h2{color:var(--fg);font-size:15px!important;font-weight:500!important;margin-top:4px!important}
`;
  let mode = store.get("cv.mode", "atelier");

  function doc() {
    try { return $frame.contentDocument?.documentElement ? $frame.contentDocument : null; } catch { return null; }
  }

  function paint() {
    const d = doc();
    if (!d) return;
    const cs = getComputedStyle(document.documentElement), root = d.documentElement, dark = effectiveTheme() === "dark";
    for (const [k, v] of Object.entries(VARS)) root.style.setProperty(k, cs.getPropertyValue(v).trim());
    root.style.setProperty("--fg-on-accent", "#fff");
    root.style.setProperty("--fg-on-badge", "#fff");
    root.style.colorScheme = dark ? "dark" : "light";
    root.classList.toggle("dark", dark);
    root.classList.toggle("light", !dark);
  }

  function fit() {  // content height, plus open popups (format pickers) that overflow it
    const d = doc();
    if (!d?.body) return;
    let h = d.body.scrollHeight;
    for (const e of d.body.querySelectorAll(".absolute")) h = Math.max(h, e.getBoundingClientRect().bottom + 16);
    $frame.style.height = `${Math.max(420, Math.ceil(h))}px`;
  }

  function skin() {
    const d = doc();
    if (!d || d.getElementById("atelier-skin")) return;
    const s = d.createElement("style");
    s.id = "atelier-skin";
    s.textContent = SKIN;
    d.head.append(s);
    paint();
    let raf = 0;
    const later = () => raf || (raf = requestAnimationFrame(() => ((raf = 0), fit())));
    new ResizeObserver(later).observe(d.body);
    new MutationObserver(later).observe(d.body, {childList: true, subtree: true});
    d.addEventListener("transitionend", later);
    fit();
    $frame.style.visibility = "";
  }

  function load() {
    if ($frame.getAttribute("src")) return;
    try {
      localStorage.setItem("PARAGLIDE_LOCALE", i18n.lang);
      localStorage.removeItem("locale");
    } catch {}
    $frame.style.visibility = "hidden";
    $frame.addEventListener("load", skin);
    $frame.src = "/vert/convert/";
  }

  function show() {
    const v = mode === "vert" && !$row.hidden;
    $atelier.hidden = v;
    $frame.hidden = !v;
    $hint.textContent = HINTS[v ? "vert" : "atelier"];
    if (v) load();
  }

  ui.segmented($("#cv-mode"), [["atelier", "Atelier", "server"], ["vert", "Navigateur", "download"]], mode, (m) => {
    mode = m;
    store.set("cv.mode", m);
    show();
  });

  async function probe() {
    let ok = false;
    try {
      const r = await fetch("/vert/", {method: "HEAD"});
      ok = r.ok && (r.headers.get("content-type") || "").includes("html");
    } catch {}
    $row.hidden = !ok;
    show();
  }

  new MutationObserver(paint).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", paint);
  bus.addEventListener("tab:convertir", probe);
  probe();
})();
