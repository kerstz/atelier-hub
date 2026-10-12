// First-launch assistant (missing essentials + one install command) and per-tab "outil manquant" notices.
const setup = (() => {
  const NEED = {
    traduire: ["ollama", "model-translate_model"],
    youtube: ["yt-dlp", "ffmpeg"],
    soustitres: ["ffmpeg", "yt-dlp", "whisper", "ollama", "model-translate_model"],
    documents: ["ollama", "model-translate_model", "pdf2zh"],
    convertir: ["ffmpeg", "ffprobe"],
    images: ["realesrgan", "rembg"],
    audio: ["demucs", "deep-filter"],
  };
  const HOWTO = {
    windows: "Ouvrir PowerShell (menu Démarrer › « PowerShell »), coller la commande, valider avec Entrée et suivre les étapes.",
    debian: "Ouvrir un terminal (Ctrl+Alt+T), coller les commandes une par une et valider avec Entrée (mot de passe demandé).",
    arch: "Ouvrir un terminal, coller les commandes une par une et valider avec Entrée (mot de passe demandé).",
  };
  let info = null, rows = [];
  let later = false;
  try {
    later = sessionStorage.getItem("setup-later") === "1";
  } catch {}
  const content = document.querySelector("main .content");
  const welcome = ui.h("div", "card setup");
  welcome.hidden = true;
  content.prepend(welcome);

  function cmdLine(text) {
    const row = ui.h("div", "cmd");
    row.append(ui.h("code", null, text));
    const c = ui.button("Copier", {size: "sm", icon: "copy"});
    ui.copy(c, () => text);
    row.append(c);
    return row;
  }

  function renderWelcome() {
    const miss = info?.missing || [];
    welcome.hidden = later || !miss.length;
    if (welcome.hidden) return;
    const head = ui.h("div", "card-head");
    head.append(ui.h("h2", null, "Bienvenue ! Encore une étape avant de commencer"));
    const ul = ui.h("ul", "setup-miss");
    miss.forEach((r) => {
      const li = ui.h("li");
      li.append(ui.icon("circle-x"), ui.h("strong", null, r.label), ui.h("span", "dim", `pour : ${r.used_by}`));
      ul.append(li);
    });
    const kids = [head, ui.h("p", null, "Ces outils gratuits sont nécessaires pour traduire, télécharger et convertir. Ils s'installent une seule fois."), ul];
    if (info.can_run) {
      kids.push(ui.h("p", "dim", "Une fenêtre va s'ouvrir : suivre ses étapes (quelques minutes), puis revenir ici et cliquer sur « Revérifier »."));
      kids.push(ui.button("Installer les outils", {variant: "primary", icon: "download", onclick: (e) => runSetup(e)}));
    } else if (info.commands.length) {
      kids.push(ui.h("p", "dim", HOWTO[info.os] || HOWTO.arch));
      info.commands.forEach((c) => kids.push(cmdLine(c)));
    }
    const bar = ui.h("div", "field-row wrap");
    bar.append(
      ui.button("Revérifier", {size: "sm", icon: "search", onclick: () => refresh(true)}),
      ui.button("Plus tard", {size: "sm", icon: "x", onclick: () => {
        later = true;
        try {
          sessionStorage.setItem("setup-later", "1");
        } catch {}
        render();
      }})
    );
    kids.push(bar);
    welcome.replaceChildren(...kids);
  }

  function renderNotices() {
    for (const [tab, ids] of Object.entries(NEED)) {
      const sec = document.getElementById(`tab-${tab}`);
      if (!sec) continue;
      let box = sec.querySelector(":scope > .notice");
      const skip = welcome.hidden ? [] : rows.filter((r) => r.essential && !r.ok).map((r) => r.id);
      const miss = rows.filter((r) => ids.includes(r.id) && !r.ok && !skip.includes(r.id));
      if (!miss.length) {
        box?.remove();
        continue;
      }
      if (!box) {
        box = ui.h("div", "notice");
        sec.querySelector(".page-head").after(box);
      }
      const title = ui.h("div", "notice-title");
      title.append(ui.icon("alert"), ui.h("strong", null, miss.length > 1 ? "Outils manquants pour cet onglet" : "Outil manquant pour cet onglet"));
      const list = miss.map((r) => ui.h("div", "notice-row", `${r.label} — pour : ${r.used_by}`));
      const cmds = info?.can_run ? [] : [...new Set(miss.map(winHint).filter(Boolean))];
      box.replaceChildren(title, ...list, ...cmds.map(cmdLine));
      if (info?.can_run && miss.some((r) => !/^(winget|lancer)/.test(r.hint || ""))) {
        const tier = miss.every((r) => STANDARD.includes(r.id)) ? "standard" : "full";
        box.append(ui.button("Installer", {size: "sm", icon: "download", onclick: (e) => runSetup(e, tier)}));
      }
    }
  }

  // Windows: anything that is not a plain winget line goes through win-setup.ps1 (no uv/zip steps by hand)
  const STANDARD = ["whisper", "pdf2zh", "ocrmypdf", "pdftotext", "tesseract", "pandoc", "soffice"];
  function winHint(r) {
    if (info?.os !== "windows" || !r.hint || /^(winget|lancer)/.test(r.hint)) return r.hint;
    return `${info.win_setup} -Tier ${STANDARD.includes(r.id) ? "standard" : "full"}`;
  }

  function render() {
    renderWelcome();
    renderNotices();
  }

  async function runSetup(e, tier = "minimal") {
    e.currentTarget.disabled = true;
    const r = await post(`/api/setup/run?tier=${tier}`);
    if (!r.ok) ui.toast((await r.json().catch(() => ({}))).detail || "Lancement impossible", "bad", 7000);
    else ui.toast("Installation lancée dans une autre fenêtre", "ok");
  }

  let busy = false;
  async function refresh(manual = false) {
    if (busy) return;
    busy = true;
    try {
      const r = await fetch("/api/setup");
      if (r.ok) {
        info = await r.json();
        rows = info.rows;
      }
    } catch {
    } finally {
      busy = false;
    }
    render();
    if (manual) ui.toast(info?.missing?.length ? "Il manque encore des outils" : "Tout est prêt", info?.missing?.length ? "bad" : "ok");
  }

  // back from a terminal / installer window: check again
  let last = 0;
  window.addEventListener("focus", () => {
    if (Date.now() - last < 5000 || !(info?.missing?.length || document.querySelector(".notice"))) return;
    last = Date.now();
    refresh();
  });
  refresh();
  return {hint: (id) => rows.find((r) => r.id === id)?.hint || "", refresh};
})();
