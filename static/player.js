// Lecteur intégré: <video>/<audio> de la vue + barre maison. Le serveur prépare un mp4/m4a si le format n'est pas sûr.
// Garde anti-crash: si la page a rechargé pendant une lecture, on bascule en lecteur externe (mpv) pour la session.
(() => {
  const KEY = "atelierMediaTry", SAFE = "atelierMediaSafe";
  const ss = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch {} },
    del: (k) => { try { sessionStorage.removeItem(k); } catch {} },
  };
  const t0 = Number(ss.get(KEY) || 0);
  if (t0 && Date.now() - t0 < 60000) {
    ss.set(SAFE, "1");
    ss.del(KEY);
  }
  const client = () => (/Chrome\//.test(navigator.userAgent) ? "chromium" : "webkitgtk");
  const fmt = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, "0"), x = String(s % 60).padStart(2, "0");
    return (h ? `${h}:` : "") + `${m}:${x}`;
  };
  const err = async (r) => ui.toast((await r.json().catch(() => ({}))).detail || "Lecture impossible", "bad");

  async function openExternal(j, sub = "") {
    const r = await post("/api/player/mpv", {id: j.id, sub});
    if (!r.ok) err(r);
  }

  window.openPlayer = async function (j) {
    const c = client();
    let info;
    try {
      const r = await fetch(`/api/jobs/${j.id}/media?client=${c}`);
      if (!r.ok) return err(r);
      info = await r.json();
    } catch {
      return ui.toast("Lecteur indisponible", "bad");
    }
    const box = ui.h("div", "player");
    let media = null, closed = false, offJob = null;
    const close = ui.panel({title: info.name, node: box, onClose: () => {
      closed = true;
      media?.pause();
      media?.removeAttribute("src");
      media?.load();
      offJob?.();
      ss.del(KEY);
    }});
    const msg = ui.h("p", "dim");
    box.append(msg);

    const external = ui.button("Lecteur externe (mpv)", {size: "sm", icon: "external-link", onclick: () => openExternal(j)});
    if (!info.mpv) external.hidden = true;

    if (ss.get(SAFE) === "1" && info.mpv) {
      msg.textContent = "La lecture intégrée a fait planter la vue: lecture dans une fenêtre externe. (Installer gst-plugins-good puis relancer l'application.)";
      box.append(external);
      return;
    }

    async function mount() {
      if (closed) return;
      const video = info.kind === "video";
      media = ui.h(video ? "video" : "audio", video ? "player-video" : "player-audio");
      media.preload = "metadata";
      media.playsInline = true;
      media.src = `/api/jobs/${j.id}/stream?client=${c}`;
      if (video) {
        for (const [i, s] of info.subs.entries()) {
          const tr = ui.h("track");
          tr.kind = "subtitles";
          tr.label = s.label;
          tr.src = `/api/jobs/${j.id}/subs/${s.id}.vtt`;
          if (i === 0) tr.default = true;
          media.append(tr);
        }
      }
      const play = ui.button("Lire", {size: "sm", icon: "play"});
      const seek = ui.h("input", "player-seek");
      seek.type = "range"; seek.min = 0; seek.max = 1000; seek.value = 0;
      const time = ui.h("span", "dim player-time", `0:00 / ${fmt(info.duration)}`);
      const vol = ui.h("input", "player-vol");
      vol.type = "range"; vol.min = 0; vol.max = 100; vol.value = Number(store.get("player.vol", "80"));
      media.volume = vol.value / 100;
      const speed = ui.h("select");
      ui.select(speed, [["1", "×1"], ["0.75", "×0,75"], ["1.25", "×1,25"], ["1.5", "×1,5"], ["2", "×2"]], "1");
      const bar = ui.h("div", "player-bar");
      bar.append(play, seek, time, vol, speed);
      if (video && info.subs.length) {
        const sub = ui.h("select");
        ui.select(sub, [["-1", "Sans sous-titres"], ...info.subs.map((s, i) => [String(i), s.label])], "0");
        sub.onchange = () => [...media.textTracks].forEach((t, i) => (t.mode = String(i) === sub.value ? "showing" : "disabled"));
        bar.append(sub);
      }
      if (video) bar.append(ui.button("Plein écran", {size: "sm", icon: "maximize", onclick: () => box.requestFullscreen?.()}));
      bar.append(ui.button("Télécharger", {size: "sm", icon: "download", onclick: () => (location.href = `/api/jobs/${j.id}/download`)}), external);
      msg.hidden = true;
      box.replaceChildren(...(video ? [media] : []), ...(video ? [] : [media]), bar, msg);

      const toggle = async () => {
        if (media.paused) {
          ss.set(KEY, String(Date.now()));
          try { await media.play(); } catch { ss.del(KEY); }
        } else media.pause();
      };
      play.onclick = toggle;
      media.onclick = toggle;
      media.onplaying = () => { ss.del(KEY); play.querySelector("span").textContent = "Pause"; };
      media.onpause = () => (play.querySelector("span").textContent = "Lire");
      media.onended = () => (play.querySelector("span").textContent = "Lire");
      media.ontimeupdate = () => {
        const d = media.duration || info.duration || 0;
        if (d && !seek.matches(":active")) seek.value = Math.round((media.currentTime / d) * 1000);
        time.textContent = `${fmt(media.currentTime)} / ${fmt(d)}`;
      };
      seek.oninput = () => {
        const d = media.duration || info.duration || 0;
        if (d) media.currentTime = (seek.value / 1000) * d;
      };
      vol.oninput = () => { media.volume = vol.value / 100; store.set("player.vol", vol.value); };
      speed.onchange = () => (media.playbackRate = Number(speed.value));
      media.onerror = () => {
        ss.del(KEY);
        msg.hidden = false;
        msg.textContent = "Lecture impossible dans l'application.";
        if (info.mpv) external.hidden = false;
      };
      box.onkeydown = (e) => {
        if (e.target.tagName === "SELECT") return;
        if (e.key === " ") { e.preventDefault(); toggle(); }
        else if (e.key === "ArrowRight") media.currentTime += 5;
        else if (e.key === "ArrowLeft") media.currentTime -= 5;
        else if (e.key === "m") media.muted = !media.muted;
      };
      box.tabIndex = 0;
      box.focus();
    }

    if (!info.needs_prepare) return mount();
    msg.textContent = "Préparation de la lecture (conversion H.264/AAC, mise en cache)…";
    const r = await post(`/api/jobs/${j.id}/prepare?client=${c}`);
    if (!r.ok) return err(r);
    const d = await r.json();
    if (d.ready) return mount();
    const bar = ui.progress(0);
    box.append(bar.el, external);
    const on = (e) => {
      const q = e.detail;
      if (q.id !== d.job) return;
      if (q.status === "running" || q.status === "queued") bar.set?.(q.progress || 0);
      else if (q.status === "done") { offJob(); mount(); }
      else { offJob(); msg.textContent = `Préparation échouée: ${q.error || q.status}`; }
    };
    offJob = () => bus.removeEventListener("job", on);
    bus.addEventListener("job", on);
  };
})();
