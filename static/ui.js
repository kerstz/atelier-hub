const ui = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const h = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  function icon(name, cls = "") {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("class", `ic ${cls}`.trim());
    s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS(NS, "use");
    u.setAttribute("href", `icons.svg#i-${name}`);
    s.append(u);
    return s;
  }

  function iconize(root = document) {
    root.querySelectorAll("i[data-i]").forEach((i) => i.replaceWith(icon(i.dataset.i, i.className)));
  }

  function button(label, {variant = "ghost", icon: ic, onclick, title, size} = {}) {
    const b = h("button", `btn ${variant}${size ? ` ${size}` : ""}`);
    b.type = "button";
    if (ic) b.append(icon(ic));
    if (label) b.append(h("span", null, label));
    if (title) b.title = b.ariaLabel = title;
    if (onclick) b.onclick = onclick;
    return b;
  }

  const card = (...kids) => {
    const c = h("div", "card");
    c.append(...kids);
    return c;
  };

  function toast(msg, kind = "info", ms = 4000) {
    const box = document.getElementById("toasts");
    const t = h("div", `toast ${kind}`);
    t.setAttribute("role", kind === "bad" ? "alert" : "status");
    t.append(icon({ok: "circle-check", bad: "circle-x", info: "info"}[kind] || "info"), h("span", null, msg));
    const close = () => t.remove();
    t.onclick = close;
    box.append(t);
    setTimeout(close, ms);
  }

  let closeModal = null;
  function modal({title, body, confirm = "Confirmer", cancel = "Annuler", danger = false}) {
    closeModal?.(false);
    return new Promise((resolve) => {
      const back = h("div", "modal-back");
      const m = h("div", "modal card");
      m.setAttribute("role", "dialog");
      m.setAttribute("aria-modal", "true");
      const acts = h("div", "actions");
      const done = (v) => {
        closeModal = null;
        back.remove();
        prev?.focus?.();
        resolve(v);
      };
      const ok = button(confirm, {variant: danger ? "danger" : "primary", onclick: () => done(true)});
      acts.append(button(cancel, {onclick: () => done(false)}), ok);
      m.append(h("h3", null, title), h("p", "dim", body), acts);
      back.append(m);
      back.onclick = (e) => e.target === back && done(false);
      const prev = document.activeElement;
      document.body.append(back);
      closeModal = done;
      ok.focus();
    });
  }

  function progress(value = 0) {
    const bar = h("div", "progress");
    bar.setAttribute("role", "progressbar");
    const fill = h("div");
    bar.append(fill);
    const set = (v) => {
      bar.classList.toggle("indet", v == null);
      fill.style.width = v == null ? "" : `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
      if (v != null) bar.setAttribute("aria-valuenow", Math.round(v * 100));
    };
    set(value);
    return {el: bar, set};
  }

  function empty(ic, title, hint) {
    const e = h("div", "empty");
    e.append(icon(ic), h("strong", null, title));
    if (hint) e.append(h("span", "dim", hint));
    return e;
  }

  function skeleton(n = 3) {
    const s = h("div", "skeleton");
    for (let i = 0; i < n; i++) s.append(h("div", "skel"));
    return s;
  }

  function copy(btn, getText) {
    const label = btn.querySelector("span");
    btn.onclick = async () => {
      const text = getText();
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const ta = h("textarea");
        ta.value = text;
        document.body.append(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      toast("Copié", "ok", 1500);
      if (label) {
        const old = label.textContent;
        label.textContent = "Copié";
        setTimeout(() => (label.textContent = old), 1200);
      }
    };
  }

  function select(sel, options, value) {
    sel.replaceChildren(...options.map(([v, t]) => new Option(t, v)));
    if (value != null) sel.value = value;
  }

  function segmented(box, options, value, onchange) {
    let cur = value;
    box.classList.add("segmented");
    box.setAttribute("role", "radiogroup");
    const render = () => {
      box.replaceChildren(
        ...options.map(([v, label, ic]) => {
          const b = h("button", cur === v ? "on" : "");
          b.type = "button";
          b.setAttribute("role", "radio");
          b.setAttribute("aria-checked", String(cur === v));
          if (ic) b.append(icon(ic));
          b.append(h("span", null, label));
          b.onclick = () => set(v);
          return b;
        })
      );
    };
    const set = (v) => {
      if (v === cur) return;
      cur = v;
      render();
      onchange?.(v);
    };
    render();
    return {get: () => cur, set};
  }

  function dropzone(el, {multiple = false, onFiles, label}) {
    const input = h("input");
    input.type = "file";
    input.hidden = true;
    input.multiple = multiple;
    el.classList.add("dropzone");
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.prepend(input);
    const visible = () => el.offsetParent !== null;
    const take = (fl) => fl.length && onFiles(multiple ? [...fl] : [fl[0]]);
    el.addEventListener("click", (e) => e.target.closest("button,a") || input.click());
    el.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.click()));
    input.onchange = () => {
      take(input.files);
      input.value = "";
    };
    ["dragenter", "dragover"].forEach((ev) =>
      el.addEventListener(ev, (e) => {
        e.preventDefault();
        el.classList.add("over");
      })
    );
    ["dragleave", "drop"].forEach((ev) => el.addEventListener(ev, () => el.classList.remove("over")));
    el.addEventListener("drop", (e) => {
      e.preventDefault();
      take(e.dataTransfer.files);
    });
    document.addEventListener("paste", (e) => {
      if (visible() && e.clipboardData?.files?.length) take(e.clipboardData.files);
    });
    if (label) el.append(h("span", "dz-label", label));
  }

  function chips(box, items, onRemove) {
    box.replaceChildren(
      ...items.map((it, i) => {
        const c = h("span", "chip");
        const x = h("button");
        x.type = "button";
        x.title = x.ariaLabel = "Retirer";
        x.append(icon("x"));
        x.onclick = () => onRemove(i);
        c.append(icon("file"), h("span", "clip", it.name), x);
        return c;
      })
    );
  }

  // Disclosure with the "Options avancées" pattern
  function disclosure(det) {
    const sum = det.querySelector("summary");
    sum.prepend(icon("chevron-down", "chev"));
  }

  const dismiss = () => (closeModal ? (closeModal(false), true) : false);

  return {dismiss, h, icon, iconize, button, card, toast, modal, progress, empty, skeleton, copy, select, segmented, dropzone, chips, disclosure};
})();
