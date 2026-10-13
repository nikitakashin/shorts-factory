// UI-панели для шортсов: блоки-имитации интерфейсов (терминал Claude Code, карточка README,
// счётчик, сравнение, сетка с тумблерами, граф, пайплайн…) на одном GSAP-таймлайне.
// Вход — window.PANELS (его пишет scripts/panels.py): { total, panels: [{ at, until, mode, theme, blocks: [...] }] },
// все времена уже в секундах. Каждый кадр — чистая функция времени: появления — GSAP-твины, а всё,
// что зависит от t (цифры, набор текста, тумблеры, проценты), — «драйверы», которые зовутся из onUpdate таймлайна.
(function () {
  const B = {};
  let tl, drivers;
  const drive = (fn) => drivers.push(fn);
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const easeOut = (p) => 1 - Math.pow(1 - clamp01(p), 3);
  const C = { green: "#2fd36b", red: "#ff4d3d", orange: "#d97757", blue: "#2f7cf6", yellow: "#f2c14e", off: "#3a4250", offLight: "#cfd3da" };
  const PALETTE = ["#4f8cff", "#f2c14e", "#2fd36b", "#ff8a3d", "#ff5fa2", "#a77bff", "#35d0e0"];

  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  function el(tag, cls, html) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  const SVGNS = "http://www.w3.org/2000/svg";
  function sv(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function setText(n, s) { if (n._t !== s) { n._t = s; n.textContent = s; } }
  function setHTML(n, s) { if (n._h !== s) { n._h = s; n.innerHTML = s; } }
  function setStyle(n, k, v) { const key = "_s_" + k; if (n[key] !== v) { n[key] = v; n.style[k] = v; } }
  function setClass(n, cls, on) { if (n.classList.contains(cls) !== !!on) n.classList.toggle(cls, !!on); }
  function rgb(h) { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((c) => c + c).join(""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); }
  // смесь двух #hex-цветов, результат тоже #hex (к нему можно дописать альфу: col + "55")
  function mix(a, b, p) { const x = rgb(a), y = rgb(b); p = clamp01(p); return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * p).toString(16).padStart(2, "0")).join(""); }
  // длина квадратичной кривой Безье (getTotalLength у ещё не вставленного в DOM пути ненадёжен)
  function qlen(x0, y0, x1, y1, x2, y2) { let L = 0, px = x0, py = y0; for (let i = 1; i <= 40; i++) { const t = i / 40, u = 1 - t, x = u * u * x0 + 2 * u * t * x1 + t * t * x2, y = u * u * y0 + 2 * u * t * y1 + t * t * y2; L += Math.hypot(x - px, y - py); px = x; py = y; } return L; }
  function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  // 43268 -> "43 268"; decimals/dsep для «20.8» и «2,6»
  function fmt(v, o = {}) {
    const d = o.decimals ?? 0, neg = v < 0 && Math.abs(v) >= 0.5 * Math.pow(10, -d);
    let [i, f] = Math.abs(v).toFixed(d).split(".");
    i = i.replace(/\B(?=(\d{3})+(?!\d))/g, o.gsep ?? " ");
    return (neg ? "−" : o.plus && v > 0 ? "+" : "") + i + (f ? (o.dsep ?? ",") + f : "");
  }
  // значение по ступеням [{at, v}]: от предыдущего к новому за dur с ease-out
  function stepped(steps, t, from, dur = 0.6) {
    let v = from, k = -1, p = 1;
    for (let i = 0; i < steps.length; i++) {
      const s = steps[i];
      if (t < s.at) break;
      p = (t - s.at) / dur; v = p >= 1 ? s.v : v + (s.v - v) * easeOut(p); k = i;
    }
    return { v, k, p: clamp01(p) };
  }
  function enter(node, at, o = {}) {
    gsap.set(node, { opacity: 0, y: o.y ?? 34, scale: o.s ?? 0.965 });
    tl.to(node, { opacity: 1, y: 0, scale: 1, duration: o.dur ?? 0.42, ease: o.ease ?? "back.out(1.5)" }, at);
  }
  function fadeUp(nodes, at, stagger = 0.06, y = 16) {
    nodes = [].concat(nodes).filter(Boolean);
    if (!nodes.length) return;
    gsap.set(nodes, { opacity: 0, y });
    tl.to(nodes, { opacity: 1, y: 0, duration: 0.32, ease: "power3.out", stagger }, at);
  }
  const full = (P) => P.mode === "full";

  // ---------------- title ----------------
  B.title = (b, P) => {
    const size = b.size || (full(P) ? 104 : 88);
    const root = el("div", "blk b-title" + (b.inline ? " inline" : ""));
    const pre = b.pre ? el("div", "pre", esc(b.pre)) : null;
    if (pre) { pre.style.fontSize = (b.pre_size || (b.inline ? size : Math.round(size * 0.74))) + "px"; root.appendChild(pre); }
    const main = el("div", "main" + (b.color ? " hl" : ""), esc(b.text));
    main.style.fontSize = size + "px";
    if (b.color) main.style.setProperty("--hl", b.color);
    root.appendChild(main);
    let sel = null;
    if (b.select !== false) { sel = el("div", "sel", "<i></i><i></i><i></i><i></i>"); main.prepend(sel); }
    const sub = b.sub ? el("div", "sub", esc(b.sub)) : null;
    if (sub) { sub.style.fontSize = (b.sub_size || 26) + "px"; root.appendChild(sub); }
    const at = b.at;
    if (pre) { gsap.set(pre, { opacity: 0, y: 22 }); tl.to(pre, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, at); }
    gsap.set(main, { opacity: 0, y: 30, scale: 0.94 });
    tl.to(main, { opacity: 1, y: 0, scale: 1, duration: 0.4, ease: "back.out(1.7)" }, at + (pre ? 0.12 : 0));
    if (sel) {
      const st = b.select_at ?? at + (pre ? 0.42 : 0.3);
      gsap.set(sel, { opacity: 0, scale: 1.08 }); gsap.set(sel.children, { scale: 0 });
      tl.to(sel, { opacity: 1, scale: 1, duration: 0.2, ease: "power2.out" }, st);
      tl.to(sel.children, { scale: 1, duration: 0.18, ease: "back.out(3)", stagger: 0.03 }, st + 0.06);
    }
    if (sub) fadeUp(sub, at + 0.3);
    return root;
  };

  // ---------------- text ----------------
  B.text = (b) => {
    const root = el("div", "blk b-text", esc(b.text).replace(/\n/g, "<br>"));
    root.style.fontSize = (b.size || 46) + "px";
    if (b.color) root.style.color = b.color;
    if (b.weight) root.style.fontWeight = b.weight;
    if (b.width) root.style.width = b.width + "px";
    enter(root, b.at);
    return root;
  };

  // ---------------- readme ----------------
  B.readme = (b) => {
    const root = el("div", "blk card b-readme");
    if (b.width) root.style.width = b.width + "px";
    const tabs = (b.tabs || ["README", "MIT license"]).map((t, i) => `<span class="${i ? "" : "on"}">${esc(t)}</span>`).join("");
    root.appendChild(el("div", "tabs", tabs + '<span class="menu">≡</span>'));
    let hero = null;
    if (b.image || b.hero_text || b.emoji) {
      hero = el("div", "hero" + (b.cover ? " cover" : ""));
      hero.style.height = (b.hero_h || 300) + "px";
      if (b.hero_bg) hero.style.background = b.hero_bg;
      if (b.image) hero.innerHTML = `<img src="${esc(b.image)}">`;
      else if (b.emoji) hero.innerHTML = `<div class="emoji">${esc(b.emoji)}</div>`;
      else { hero.innerHTML = `<div class="htext">${esc(b.hero_text)}</div>`; if (b.hero_color) hero.firstChild.style.color = b.hero_color; if (b.hero_size) hero.firstChild.style.fontSize = b.hero_size + "px"; }
      root.appendChild(hero);
    }
    const pills = b.pills ? el("div", "pills", b.pills.map((p) => `<span class="pill" style="background:${p.color || PALETTE[0]}">${esc(p.text)}</span>`).join("")) : null;
    if (pills) root.appendChild(pills);
    const name = b.name ? el("div", "name", esc(b.name)) : null;
    const tag = b.tagline ? el("div", "tagline", esc(b.tagline)) : null;
    const badge = b.badge ? el("div", "badge", `<span style="font-size:22px">🏆</span><div><small>${esc(b.badge_kicker || "GitHub trending")}</small>${esc(b.badge)}</div>`) : null;
    [name, tag, badge].forEach((n) => n && root.appendChild(n));
    root.appendChild(el("div", "foot"));
    enter(root, b.at);
    fadeUp([hero, pills, name, tag, badge], b.at + 0.16, 0.07);
    return root;
  };

  // ---------------- counter ----------------
  // steps: [{at, value, color?, bar?}] — цифра едет от предыдущего значения, цвет и полоса вслед за ней
  B.counter = (b, P) => {
    const root = el("div", "blk b-counter");
    const num = el("div", "num");
    num.style.fontSize = (b.size || (full(P) ? 250 : 220)) + "px";
    root.appendChild(num);
    const lbl = b.label ? el("div", "lbl", esc(b.label)) : null;
    const bar = b.bar === false ? null : el("div", "bar", "<i></i>");
    if (lbl) root.appendChild(lbl);
    if (bar) root.appendChild(bar);
    const steps = (b.steps || [{ at: b.at, value: b.value }]).map((s) => ({ ...s, at: s.at ?? b.at, v: s.value }));
    const n = steps.length, vals = steps.map((s) => s.v), max = Math.max(...vals.map(Math.abs), 1e-9);
    const pct = (b.suffix || "").trim() === "%";
    const barOf = (s) => s.bar ?? (pct ? (s.v < 0 ? 1 + s.v / 100 : s.v / 100) : Math.abs(s.v) / max);
    const tone = b.tone || "good";
    const colorOf = (s, i) => s.color || (tone === "bad" ? mix(C.green, C.red, n > 1 ? i / (n - 1) : 1) : tone === "good" ? mix(C.red, C.green, n > 1 ? i / (n - 1) : 1) : tone === "red" ? C.red : tone === "green" ? C.green : tone);
    const cols = steps.map(colorOf), bars = steps.map(barOf);
    const dur = b.dur ?? 0.6, from = b.from ?? (n > 1 ? steps[0].v : 0);
    drive((t) => {
      const r = stepped(steps, t, from, dur);
      const k = Math.max(0, r.k);
      const col = r.k <= 0 ? cols[0] : mix(cols[r.k - 1], cols[k], easeOut(r.p));
      const whole = b.trim !== false && Math.abs(r.v - Math.round(r.v)) < 1e-6;   // «26», а не «26.0»
      setText(num, (b.prefix || "") + fmt(r.v, whole ? { ...b, decimals: 0 } : b) + (b.suffix || ""));
      setStyle(num, "color", col);
      setStyle(num, "textShadow", `0 0 60px ${col}55`);
      const pop = r.k >= 0 && r.p < 1 ? 1 + 0.07 * (1 - easeOut(r.p * 1.4)) : 1;
      setStyle(num, "transform", `scale(${pop.toFixed(4)})`);
      if (bar) {
        const prevB = r.k > 0 ? bars[r.k - 1] : (n > 1 ? bars[0] : 0);
        const bw = r.k < 0 ? 0 : prevB + (bars[k] - prevB) * easeOut(r.p);
        setStyle(bar.firstChild, "width", (clamp01(bw) * 100).toFixed(2) + "%");
        setStyle(bar.firstChild, "background", `linear-gradient(90deg, ${cols[k]}, ${cols[k]}cc)`);
      }
    });
    enter(root, b.at, { y: 20 });
    return root;
  };

  // ---------------- terminal ----------------
  const CRAB = ["..XXXXXXXXX..", "..X.XXXXX.X..", "XXXXXXXXXXXXX", "XXXXXXXXXXXXX", "..XXXXXXXXX..", "..X.X...X.X.."];
  function crabSVG(color = C.orange) {
    let r = "";
    CRAB.forEach((row, y) => [...row].forEach((c, x) => { if (c === "X") r += `<rect x="${x * 4}" y="${y * 4}" width="4.2" height="4.2"/>`; }));
    return `<svg viewBox="0 0 52 24" fill="${color}">${r}</svg>`;
  }
  const SPIN = ["✻", "✶", "✳", "✢", "·", "✢", "✳", "✶"];
  B.terminal = (b, P) => {
    const root = el("div", "blk b-term");
    if (b.width) root.style.width = b.width + "px";
    if (b.font) root.style.fontSize = b.font + "px";
    root.appendChild(el("div", "tbar", `<i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><div class="ttl">${esc(b.title || "claude-code — zsh")}</div>`));
    const body = el("div", "tbody");
    root.appendChild(body);
    if (b.app !== false) {
      const logo = b.logo === "none" ? "" : b.logo ? `<img src="${esc(b.logo)}" style="width:40px;height:40px;object-fit:contain">` : crabSVG();
      body.appendChild(el("div", "thead", `${logo}<div><div class="app">${esc(b.app || "Claude Code")}</div><div class="sub">${esc(b.sub || "opus · ~/app")}</div></div>`));
    }
    // prompt: печатается по буквам, может быть зачёркнут
    if (b.prompt) {
      const p = typeof b.prompt === "string" ? { text: b.prompt } : b.prompt;
      const pat = p.at ?? b.at + 0.25, pdur = p.type ?? Math.min(1.2, 0.035 * p.text.length);
      const row = el("div", "prompt", `<b>›</b> <span class="txt"></span><span class="cur"></span>`);
      body.appendChild(row);
      const txt = row.querySelector(".txt"), cur = row.querySelector(".cur");
      drive((t) => {
        const k = pdur <= 0 ? (t >= pat ? p.text.length : 0) : Math.round(clamp01((t - pat) / pdur) * p.text.length);
        setText(txt, p.text.slice(0, k));
        const typing = t >= pat && k < p.text.length, done = k >= p.text.length;
        const blink = Math.floor(t * 2.4) % 2 === 0;
        setStyle(cur, "opacity", p.strike_at != null && t >= p.strike_at ? "0" : typing || (done && blink) || t < pat ? "1" : "0");
        setClass(row, "strike", p.strike_at != null && t >= p.strike_at);
      });
    }
    // строки tool calls
    // окно на rows строк: новая строка вытесняет старые целиком (tool + └ вывод), как прокрутка терминала
    const lines = el("div", "lines");
    const rows = b.rows || (full(P) ? 11 : 7);
    body.appendChild(lines);
    const shown = [];
    (b.lines || []).forEach((L, i) => {
      const at = L.at ?? b.at + 0.6 + i * 0.5;
      let html;
      if (L.text != null) html = `${L.dot === false ? "" : '<span class="d">● </span>'}${esc(L.text)}`;
      else html = `<span class="d">● </span><b>${esc(L.tool || "Read")}</b>(${esc(L.arg || "")})`;
      if (L.out) html += `<span class="o">└ ${esc(L.out)}</span>`;
      const kind = L.kind || (L.text != null && L.color === "green" ? "ok-text" : L.text != null && L.color === "red" ? "err-text" : "");
      const ln = el("div", "ln " + kind, html);
      lines.appendChild(ln);
      gsap.set(ln, { display: "none", opacity: 0, x: -10 });
      tl.set(ln, { display: "block" }, at);
      tl.to(ln, { opacity: 1, x: 0, duration: 0.22, ease: "power2.out" }, at);
      shown.push({ ln, h: L.out ? 2 : 1 });
      let used = shown.reduce((a, x) => a + x.h, 0);
      while (used > rows && shown.length > 1) { const old = shown.shift(); used -= old.h; tl.set(old.ln, { display: "none" }, at); }
    });
    // статус «Работаю…» и счётчик токенов (в тысячах)
    if (b.status) {
      const s = b.status, sat = s.at ?? b.at + 0.5;
      const st = el("div", "status", `<span><span class="spn"></span> ${esc(s.text || "Работаю…")} <span style="color:#6b7482">${esc(s.hint || "(esc — прервать)")}</span></span><span class="tok"></span>`);
      body.appendChild(st);
      gsap.set(st, { display: "none" });
      tl.set(st, { display: "flex" }, sat);
      const spn = st.querySelector(".spn"), tok = st.querySelector(".tok");
      const steps = (s.tokens || []).map((x) => ({ at: x.at, v: x.v }));
      drive((t) => {
        setText(spn, SPIN[Math.floor(t * 8) % SPIN.length]);
        if (steps.length) { const v = stepped(steps, t, 0, s.ramp ?? 0.5).v; setText(tok, `↑ ${fmt(v, { decimals: 1 })} тыс. токенов`); }
      });
    }
    // лимит сессии: сегментная полоса, жёлтая → красная, рамка терминала краснеет на 100 %
    if (b.limit) {
      const L = b.limit, N = L.ticks || 36;
      const box = el("div", "limit", `<div class="lr"><span>${esc(L.label || "Лимит сессии")}</span><span class="lp"></span></div><div class="ticks">${"<i></i>".repeat(N)}</div>`);
      body.appendChild(box);
      const lp = box.querySelector(".lp"), ticks = [...box.querySelectorAll(".ticks i")];
      const steps = (L.steps || []).map((x) => ({ at: x.at, v: x.v }));
      const warn = L.warn ?? 95;
      drive((t) => {
        const v = stepped(steps, t, L.from ?? 0, L.ramp ?? 0.7).v;
        const red = v >= warn, col = red ? C.red : C.yellow;
        const k = Math.round((v / 100) * N);
        ticks.forEach((tk, i) => setStyle(tk, "background", i < k ? col : "rgba(255,255,255,0.08)"));
        setText(lp, `${Math.round(v)}% ${L.unit || "использовано"}`);
        setStyle(lp, "color", red ? C.red : C.yellow);
        setClass(root, "alert", red);
      });
    }
    enter(root, b.at);
    return root;
  };

  // ---------------- compare ----------------
  B.compare = (b) => {
    const root = el("div", "blk b-compare");
    const col = el("div", "cmp-col");
    root.appendChild(col);
    const rows = b.rows || [];
    const maxV = Math.max(...rows.map((r) => r.value || 0), 1);
    rows.forEach((r, i) => {
      const at = r.at ?? b.at + i * 0.5;
      const good = (r.tone || (i ? "good" : "bad")) === "good", c = r.color || (good ? C.green : C.red);
      const card = el("div", "card cmp", `<div class="l">${esc(r.label || "")}</div><div class="p"><b>›</b> ${esc(r.prompt || "")}</div><div class="v"><span class="vv" style="color:${c}"></span>${r.extra ? `<span class="x">${esc(r.extra)}</span>` : ""}</div><div class="bar"><i style="background:${c}"></i></div>`);
      col.appendChild(card);
      enter(card, at, { y: 20 });
      const vv = card.querySelector(".vv"), bi = card.querySelector(".bar i");
      const w = r.bar ?? r.value / maxV;
      drive((t) => {
        const p = easeOut((t - at - 0.1) / (r.dur ?? 0.8));
        setText(vv, fmt((r.value || 0) * p) + (r.unit ? " " + r.unit : ""));
        setStyle(bi, "width", (w * p * 100).toFixed(2) + "%");
      });
    });
    if (b.checklist) {
      const ckl = b.checklist, items = ckl.items || [];
      const box = el("div", "check");
      root.appendChild(box);
      const nodes = items.map((it, i) => { const n = el("div", "ck", `<i>${i + 1}</i><span>${esc(typeof it === "string" ? it : it.text)}</span>`); box.appendChild(n); return n; });
      fadeUp(nodes, ckl.show_at ?? b.at + 0.2, 0.04, 10);
      const t0 = ckl.at ?? b.at + 0.8, stp = ckl.step ?? 0.22;
      drive((t) => nodes.forEach((n, i) => {
        const at = typeof items[i] === "object" && items[i].at != null ? items[i].at : t0 + i * stp;
        setClass(n, "on", t >= at);
        setHTML(n.firstChild, t >= at ? "✓" : String(i + 1));
      }));
    }
    return root;
  };

  // ---------------- table ----------------
  // cols: [..], rows: [{cells: [...], at?, hl_at?, tone?: "bad"|"good"}], col_w: ["1.6fr","1fr",..], accent_col, font, width
  // Строки проявляются по своим at (по словам), строка с hl_at в этот момент подсвечивается (tone: bad — красным).
  B.table = (b, P) => {
    const root = el("div", "blk card b-table");
    if (b.width) root.style.width = b.width + "px";
    if (b.title) root.appendChild(el("div", "tt", esc(b.title)));
    const grid = el("div", "tg");
    grid.style.gridTemplateColumns = (b.col_w || b.cols.map(() => "1fr")).join(" ");
    root.appendChild(grid);
    b.cols.forEach((c) => grid.appendChild(el("div", "th", esc(c))));
    const font = b.font || 30;
    (b.rows || []).forEach((r, i) => {
      const at = r.at ?? b.at + 0.12 * (i + 1);
      const cells = r.cells.map((c, j) => {
        const d = el("div", "td" + (b.accent_col === j ? " acc" : ""), esc(String(c)));
        d.style.fontSize = font + "px";
        grid.appendChild(d);
        return d;
      });
      const hlc = r.tone === "good" ? "rgba(47,211,107,0.16)" : "rgba(255,77,61,0.16)";
      drive((t) => {
        const p = Math.max(0, Math.min(1, (t - at) / 0.25));
        const h = r.hl_at != null && t >= r.hl_at ? Math.min(1, (t - r.hl_at) / 0.2) : 0;
        for (const d of cells) {
          setStyle(d, "opacity", p.toFixed(3));
          setStyle(d, "transform", p < 1 ? `translateY(${(12 * (1 - p)).toFixed(1)}px)` : "none");
          setStyle(d, "background", h ? hlc.replace(/0\.16\)/, (0.16 * h).toFixed(3) + ")") : "transparent");
        }
      });
    });
    enter(root, b.at, { y: 20 });
    return root;
  };

  // ---------------- grid ----------------
  // items: [{name, note}], steps: [{at, names: [...] | "*", state: on|fail|off, note, stagger}]
  B.grid = (b, P) => {
    const root = el("div", "blk b-grid");
    if (b.title || b.subtitle) root.appendChild(el("div", "gh", `${b.icon ? `<span style="font-size:30px">${esc(b.icon)}</span>` : ""}<div><div class="t">${esc(b.title || "")}</div><div class="s">${esc(b.subtitle || "")}</div></div>`));
    const cells = el("div", "cells");
    const cols = b.cols || 4;
    cells.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
    root.appendChild(cells);
    const light = (P.theme || "dark") === "light";
    const items = (b.items || []).map((it) => (typeof it === "string" ? { name: it } : it));
    const ev = items.map(() => []);
    (b.steps || []).forEach((s) => {
      const names = s.names === "*" ? items.map((x) => x.name) : [].concat(s.names ?? s.name);
      names.forEach((nm, j) => {
        const i = items.findIndex((x) => x.name === nm);
        if (i < 0) throw new Error(`grid: нет элемента «${nm}»`);
        ev[i].push({ at: s.at + j * (s.stagger ?? 0), state: s.state || "on", note: s.note });
      });
    });
    ev.forEach((e) => e.sort((a, c) => a.at - c.at));
    const nodes = items.map((it, i) => {
      const n = el("div", "card cell", `<div class="n">${esc(it.name)}</div><div class="r"><span class="st"></span><span class="sw"><i></i></span></div>`);
      if (b.cell_font) n.firstChild.style.fontSize = b.cell_font + "px";
      cells.appendChild(n);
      const st = n.querySelector(".st"), sw = n.querySelector(".sw"), kn = sw.firstChild;
      const offC = light ? C.offLight : C.off;
      drive((t) => {
        let cur = { state: it.state || "off", note: it.note ?? "", at: -1 };
        for (const e of ev[i]) if (t >= e.at) cur = { state: e.state, note: e.note ?? (e.state === "on" ? b.on_note ?? "подключён" : e.state === "fail" ? b.fail_note ?? "недоступно" : it.note ?? ""), at: e.at };
        const p = cur.at < 0 ? 1 : easeOut((t - cur.at) / 0.2);
        const on = cur.state === "on", fail = cur.state === "fail";
        setClass(n, "on", on); setClass(n, "fail", fail);
        setText(st, cur.note);
        setStyle(kn, "left", (3 + (on ? 20 * p : 0)).toFixed(2) + "px");
        setStyle(sw, "background", on ? mix(offC, C.green, p) : fail ? mix(offC, C.red, p) : offC);
        setStyle(n, "transform", cur.at >= 0 && p < 1 ? `scale(${(1 + 0.05 * (1 - p)).toFixed(4)})` : "none");
      });
      return n;
    });
    enter(root, b.at, { y: 20 });
    gsap.set(nodes, { opacity: 0, scale: 0.9 });
    tl.to(nodes, { opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)", stagger: b.pop_stagger ?? 0.025 }, b.at + 0.1);
    return root;
  };

  // ---------------- toggle ----------------
  B.toggle = (b, P) => {
    const root = el("div", "blk b-toggle", `<div class="t">${esc(b.label || "включается сам")}</div><div class="bsw"><i></i></div>`);
    if (b.size) root.firstChild.style.fontSize = b.size + "px";
    const sw = root.querySelector(".bsw"), kn = sw.firstChild;
    const offC = (P.theme || "dark") === "light" ? C.offLight : C.off;
    const on = b.on_at ?? b.at + 0.6;
    drive((t) => {
      const p = easeOut((t - on) / 0.22);
      setStyle(kn, "left", (6 + 54 * p).toFixed(2) + "px");
      setStyle(sw, "background", mix(offC, b.color || C.green, p));
    });
    enter(root, b.at);
    return root;
  };

  // ---------------- install ----------------
  const BRAILLE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
  B.install = (b) => {
    const root = el("div", "blk b-install");
    if (b.title) root.appendChild(el("div", "h", esc(b.title)));
    const items = (b.items || []).map((x) => (typeof x === "string" ? { name: x } : x));
    const nodes = items.map((it, i) => {
      const n = el("div", "card it", `<div class="r"><span class="sp"></span><span class="nm${it.blur ?? b.blur ? " blur" : ""}">${esc(it.name)}</span><span class="pc"></span></div><div class="pb"><i></i></div>`);
      root.appendChild(n);
      const sp = n.querySelector(".sp"), pc = n.querySelector(".pc"), pb = n.querySelector(".pb i");
      const at = it.at ?? b.at + 0.15 + i * (b.stagger ?? 0.25), dur = it.dur ?? b.dur ?? 3, target = it.target ?? b.target ?? 100;
      drive((t) => {
        const v = target * clamp01((t - at) / dur) ** 0.8;
        const done = v >= 99.5;
        setText(sp, done ? "✓" : BRAILLE[Math.floor(t * 12) % BRAILLE.length]);
        setStyle(sp, "color", done ? C.green : C.blue);
        setText(pc, done ? b.done_text || "установлен" : `${b.verb || "установка…"} ${Math.floor(v)}%`);
        setStyle(pc, "color", done ? C.green : "");
        setStyle(pb, "width", v.toFixed(2) + "%");
        setStyle(pb, "background", done ? C.green : C.blue);
      });
      return n;
    });
    enter(root, b.at, { y: 16 });
    fadeUp(nodes, b.at + 0.1, b.stagger ?? 0.25, 12);
    return root;
  };

  // ---------------- pipeline ----------------
  B.pipeline = (b) => {
    const root = el("div", "blk b-pipe");
    const stages = b.stages || [];
    root.style.gridTemplateColumns = `repeat(${stages.length}, 1fr)`;
    const lit = {};
    (b.steps || []).forEach((s) => [].concat(s.stage ?? s.stages).forEach((nm) => (lit[nm] = Math.min(lit[nm] ?? 1e9, s.at))));
    const cols = stages.map((s, i) => {
      const c = el("div", "stg", `<div class="card hd"><b>${esc(s.name)}</b><span>${esc(s.cmd || "")}</span></div><div class="chips">${(s.skills || []).map((k) => `<div class="chip">${esc(k)}</div>`).join("")}</div>`);
      root.appendChild(c);
      const hd = c.firstChild, chips = [...c.querySelectorAll(".chip")], color = s.color || PALETTE[i % PALETTE.length];
      const la = lit[s.name];
      drive((t) => {
        const on = la != null && t >= la, p = on ? easeOut((t - la) / 0.25) : 0;
        setStyle(hd, "background", on ? color : "");
        setStyle(hd, "borderColor", on ? color : "");
        setStyle(hd, "color", on ? "#fff" : "");
        setStyle(hd.lastChild, "color", on ? "rgba(255,255,255,0.8)" : "");
        setStyle(hd, "transform", on && p < 1 ? `scale(${(1 + 0.1 * (1 - p)).toFixed(4)})` : "none");
        chips.forEach((ch) => setStyle(ch, "borderColor", on ? color + "99" : ""));
      });
      return c;
    });
    gsap.set(cols, { opacity: 0, y: -24 });
    tl.to(cols, { opacity: 1, y: 0, duration: 0.32, ease: "back.out(1.6)", stagger: 0.06 }, b.at);
    return root;
  };

  // ---------------- graph ----------------
  // кластеры узлов растут по ступеням [{at, nodes, edges, fill}]; рёбра дорисовываются, когда видны оба конца
  B.graph = (b, P) => {
    const W = b.w || 900, H = b.h || (full(P) ? 720 : 560);
    const root = el("div", "blk b-graph");
    const svg = sv("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` });
    root.appendChild(svg);
    const R = rng(b.seed || 7), K = b.clusters || 6, N = b.nodes || 72;
    const centers = [];
    for (let k = 0; k < K; k++) {
      const a = (k / K) * Math.PI * 2 + R() * 0.6, rr = 0.3 + R() * 0.12;
      centers.push([W / 2 + Math.cos(a) * W * rr, H / 2 + Math.sin(a) * H * (rr + 0.04)]);
    }
    const nodes = [];
    for (let i = 0; i < N; i++) {
      const k = i % K, [cx, cy] = centers[k];
      const a = R() * Math.PI * 2, d = Math.sqrt(R()) * Math.min(W, H) * 0.17;
      nodes.push({ k, x: Math.max(12, Math.min(W - 12, cx + Math.cos(a) * d)), y: Math.max(12, Math.min(H - 12, cy + Math.sin(a) * d)), r: 4 + R() * 4 });
    }
    // порядок появления: по кластерам, внутри — по удалённости от центра кластера
    const order = nodes.map((n, i) => i).sort((a, c) => nodes[a].k - nodes[c].k || Math.hypot(nodes[a].x - centers[nodes[a].k][0], nodes[a].y - centers[nodes[a].k][1]) - Math.hypot(nodes[c].x - centers[nodes[c].k][0], nodes[c].y - centers[nodes[c].k][1]));
    const edges = [];
    nodes.forEach((n, i) => {
      const near = nodes.map((m, j) => [j, Math.hypot(m.x - n.x, m.y - n.y), m.k]).filter((x) => x[0] !== i && x[2] === n.k).sort((a, c) => a[1] - c[1]).slice(0, 2);
      near.forEach(([j]) => i < j && edges.push([i, j]));
    });
    for (let k = 0; k < K; k++) { const a = nodes.findIndex((n) => n.k === k), c = nodes.findIndex((n) => n.k === (k + 1) % K); edges.push([a, c]); }
    const steps = (b.steps || [{ at: b.at, fill: 1 }]).map((s, i, arr) => ({ ...s, fill: s.fill ?? (arr.length > 1 ? 0.25 + (0.75 * i) / (arr.length - 1) : 1) }));
    const spread = b.spread ?? 1.1;
    const tShow = new Array(N);
    let done = 0;
    steps.forEach((s) => {
      const upto = Math.round(s.fill * N), cnt = Math.max(1, upto - done);
      for (let q = done; q < upto; q++) tShow[order[q]] = s.at + ((q - done) / cnt) * spread;
      done = Math.max(done, upto);
    });
    const ge = sv("g", {}, svg), gn = sv("g", {}, svg);
    edges.forEach(([i, j]) => {
      if (tShow[i] == null || tShow[j] == null) return;
      const a = nodes[i], c = nodes[j], L = Math.hypot(a.x - c.x, a.y - c.y);
      const ln = sv("line", { x1: a.x, y1: a.y, x2: c.x, y2: c.y, stroke: PALETTE[a.k % PALETTE.length], "stroke-width": 1.6, "stroke-opacity": a.k === c.k ? 0.6 : 0.25, "stroke-dasharray": `${L} ${L}`, "stroke-dashoffset": L }, ge);
      gsap.set(ln, { opacity: 0 });
      const at = Math.max(tShow[i], tShow[j]) + 0.05;
      tl.set(ln, { opacity: 1 }, at);
      tl.to(ln, { attr: { "stroke-dashoffset": 0 }, duration: 0.3, ease: "power2.out" }, at);
    });
    nodes.forEach((n, i) => {
      if (tShow[i] == null) return;
      const col = PALETTE[n.k % PALETTE.length];
      const halo = sv("circle", { cx: n.x, cy: n.y, r: 0, fill: col, "fill-opacity": 0.18 }, gn);
      const dot = sv("circle", { cx: n.x, cy: n.y, r: 0, fill: col }, gn);
      tl.to(halo, { attr: { r: n.r * 2.6 }, duration: 0.35, ease: "back.out(2)" }, tShow[i]);
      tl.to(dot, { attr: { r: n.r }, duration: 0.3, ease: "back.out(3)" }, tShow[i]);
    });
    if (b.steps && b.steps.some((s) => s.nodes != null)) {
      const cnt = el("div", "cnt");
      root.appendChild(cnt);
      const sn = steps.map((s) => ({ at: s.at, v: s.nodes || 0 })), se = steps.map((s) => ({ at: s.at, v: s.edges || 0 }));
      const [ln, le] = b.labels || ["узлов", "рёбер"];
      drive((t) => setHTML(cnt, `<b>${fmt(stepped(sn, t, 0, spread).v)}</b> ${esc(ln)} · <b>${fmt(stepped(se, t, 0, spread).v)}</b> ${esc(le)}`));
      fadeUp(cnt, steps[0].at);
    }
    gsap.set(root, { opacity: 0 });
    tl.to(root, { opacity: 1, duration: 0.2 }, b.at);
    return root;
  };

  // ---------------- hub ----------------
  // центр (искра Claude или текст) и ветки к узлам-плашкам по эллипсу
  B.hub = (b, P) => {
    const W = b.w || 940, H = b.h || (full(P) ? 760 : 600), cx = W / 2, cy = H / 2;
    const root = el("div", "blk b-hub");
    const svg = sv("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` });
    root.appendChild(svg);
    const branches = sv("g", {}, svg), centerG = sv("g", { transform: `translate(${cx} ${cy})` }, svg), inner = sv("g", {}, centerG);
    const col = b.color || C.orange;
    if (!b.center || b.center === "claude") {
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2 + 0.13, L = i % 2 ? 46 : 62;
        sv("line", { x1: Math.cos(a) * 12, y1: Math.sin(a) * 12, x2: Math.cos(a) * L, y2: Math.sin(a) * L, stroke: col, "stroke-width": 11, "stroke-linecap": "round" }, inner);
      }
    } else {
      const w = String(b.center).length * 20 + 50;
      sv("rect", { x: -w / 2, y: -34, width: w, height: 68, rx: 18, fill: col }, inner);
      const tx = sv("text", { x: 0, y: 11, "text-anchor": "middle", fill: "#fff", style: "font:800 30px Inter,sans-serif" }, inner);
      tx.textContent = b.center;
    }
    gsap.set(inner, { scale: 0, rotation: -60, svgOrigin: "0 0" });
    tl.to(inner, { scale: 1, rotation: 0, duration: 0.5, ease: "back.out(1.8)", svgOrigin: "0 0" }, b.at);
    const items = (b.nodes || []).map((x) => (typeof x === "string" ? { label: x } : x));
    const n = items.length, rx = b.rx || W / 2 - 110, ry = b.ry || H / 2 - 50;
    items.forEach((it, i) => {
      const a = -Math.PI / 2 + (i / n) * Math.PI * 2 + (b.rot || 0);
      const x = cx + Math.cos(a) * rx, y = cy + Math.sin(a) * ry;
      const x0 = cx + Math.cos(a) * 78, y0 = cy + Math.sin(a) * 78;
      const mx = (x0 + x) / 2 - Math.sin(a) * 40 * (i % 2 ? 1 : -1), my = (y0 + y) / 2 + Math.cos(a) * 40 * (i % 2 ? 1 : -1);
      const d = `M${x0.toFixed(1)} ${y0.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)}`;
      const path = sv("path", { d, fill: "none", stroke: col, "stroke-width": 3, "stroke-linecap": "round", "stroke-opacity": 0.75 }, branches);
      const L = qlen(x0, y0, mx, my, x, y);
      path.setAttribute("stroke-dasharray", `${L} ${L}`); path.setAttribute("stroke-dashoffset", L);
      // веточка с точкой на середине
      const tx = (x0 + 2 * mx + x) / 4, ty = (y0 + 2 * my + y) / 4, ta = a + (i % 2 ? 0.9 : -0.9);
      const twig = sv("path", { d: `M${tx.toFixed(1)} ${ty.toFixed(1)} l${(Math.cos(ta) * 34).toFixed(1)} ${(Math.sin(ta) * 34).toFixed(1)}`, fill: "none", stroke: col, "stroke-width": 2.5, "stroke-linecap": "round", "stroke-opacity": 0.6 }, branches);
      const tip = sv("circle", { cx: tx + Math.cos(ta) * 34, cy: ty + Math.sin(ta) * 34, r: 0, fill: "#fff" }, branches);
      const bt = it.at ?? b.at + 0.3 + i * (b.stagger ?? 0.12);
      gsap.set([path, twig], { opacity: 0 });
      tl.set(path, { opacity: 1 }, bt);
      tl.to(path, { attr: { "stroke-dashoffset": 0 }, duration: 0.4, ease: "power2.out" }, bt);
      tl.set(twig, { opacity: 1 }, bt + 0.2);
      tl.to(tip, { attr: { r: 5 }, duration: 0.2, ease: "back.out(3)" }, bt + 0.25);
      // плашка-узел
      const g = sv("g", { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})` }, svg), gi = sv("g", { class: "hub-node" }, g);
      const label = it.label || "", hasIcon = !!it.icon;
      const w = Math.max(64, label.length * 11.5 + (hasIcon ? 66 : 34)), h = 50;
      if (label) sv("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 13 }, gi);
      if (hasIcon) {
        const s = label ? 30 : 56;
        sv("image", { href: it.icon, x: label ? -w / 2 + 14 : -s / 2, y: -s / 2, width: s, height: s }, gi);
      }
      if (label) { const tt = sv("text", { x: hasIcon ? -w / 2 + 52 : 0, y: 7, "text-anchor": hasIcon ? "start" : "middle" }, gi); tt.textContent = label; if (it.color) tt.setAttribute("fill", it.color); }
      gsap.set(gi, { scale: 0, svgOrigin: "0 0" });
      tl.to(gi, { scale: 1, duration: 0.3, ease: "back.out(2.2)", svgOrigin: "0 0" }, bt + 0.32);
    });
    return root;
  };

  // ---------------- image ----------------
  B.image = (b) => {
    const root = el("div", "blk");
    const box = el("div", "b-image" + (b.card === false ? "" : " card"), `<img src="${esc(b.src)}">`);
    box.style.width = (b.width || 860) + "px";
    if (b.height) box.style.height = b.height + "px";
    if (b.radius != null) box.style.borderRadius = b.radius + "px";
    if (b.fit) box.firstChild.style.objectFit = b.fit;
    root.appendChild(box);
    if (b.caption) root.appendChild(el("div", "cap", esc(b.caption)));
    enter(root, b.at);
    return root;
  };

  // ---------------- сборка ----------------
  window.UI = {
    blocks: B,
    build(P) {
      const host = document.getElementById("root");
      if (P.canvas === "landscape") document.documentElement.classList.add("landscape");
      drivers = [];
      tl = gsap.timeline({ paused: true, onUpdate: () => update(tl.time()) });
      const update = (t) => { for (const f of drivers) f(t); };
      tl.to({ p: 0 }, { p: 1, duration: P.total, ease: "none" }, 0);
      (P.panels || []).forEach((p) => {
        const mode = p.mode || "split";
        const sec = el("section", `panel ${p.theme || "dark"} ${mode}`);
        const area = el("div", "area");
        if (p.gap != null) area.style.gap = p.gap + "px";
        if (p.align === "top") area.style.justifyContent = "flex-start";
        if (p.scale) { area.style.transform = `scale(${p.scale})`; area.style.transformOrigin = "50% 50%"; }
        sec.appendChild(area);
        host.appendChild(sec);
        if (p.at < 1 / 120) gsap.set(sec, { visibility: "visible" }); else { gsap.set(sec, { visibility: "hidden" }); tl.set(sec, { visibility: "visible" }, p.at); }
        if (p.until < P.total) tl.set(sec, { visibility: "hidden" }, p.until);
        (p.blocks || []).forEach((b, i) => {
          const fn = B[b.type];
          if (!fn) throw new Error(`неизвестный блок «${b.type}»`);
          const node = fn({ ...b, at: b.at ?? p.at + i * 0.15 }, { ...p, mode });
          if (b.style) Object.assign(node.style, b.style);
          area.appendChild(node);
        });
      });
      window.__total = P.total;
      update(0);
      return tl;
    },
  };
})();
