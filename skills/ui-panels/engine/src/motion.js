// Моушн-библиотека (2026-10-17): блоки по мотивам разобранных референсов автора
// (youtube/Ресерч/2026-10-17-моушн-разбор/*.md, сводка — references/motion-library.md).
// Правила движка те же: никаких CSS transition/animation и filter: blur — всё движение GSAP-твинами или drive(t).
(function () {
  const K = window.UI.kit, B = window.UI.blocks;
  const { el, sv, esc, setStyle, setText, rgb, mix, clamp01, easeOut, enter, blurIn, rng } = K;
  const T = () => K.tl();
  const drive = (fn) => K.drive(fn);
  const smooth = (p) => { p = clamp01(p); return p * p * (3 - 2 * p); };
  const lerp = (a, b, p) => a + (b - a) * p;
  // ключи [{at, ...числа}] → значения в момент t (smoothstep между соседними ключами, dur — длительность перехода)
  function keyed(keys, t, dur = 0.6) {
    let cur = { ...keys[0] };
    for (let i = 1; i < keys.length; i++) {
      const k = keys[i]; if (t < k.at) break;
      const p = smooth((t - k.at) / (k.dur ?? dur)), prev = { ...cur };
      for (const n in k) if (n !== "at" && n !== "dur" && typeof k[n] === "number") cur[n] = lerp(prev[n] ?? k[n], k[n], p);
    }
    return cur;
  }

  // ---------- буквы и слова ----------
  // letters: каждая буква — span; mode: drop (падает с наклоном, back.out), type (печать), grey (серая → цвет), pop.
  function letters(node, text, at, o = {}) {
    node.innerHTML = "";
    const chars = [...text], spans = chars.map((c) => { const s = el("span", "ch", c === " " ? "&nbsp;" : esc(c)); s.style.display = "inline-block"; node.appendChild(s); return s; });
    let order = spans.map((_, i) => i);
    if (o.order === "random") { const r = rng(o.seed || 7); order = order.map((i) => [r(), i]).sort((a, b) => a[0] - b[0]).map((x) => x[1]); }
    const st = o.stagger ?? (o.mode === "type" ? 0.03 : 0.045);
    order.forEach((idx, k) => {
      const s = spans[idx], t0 = at + k * st;
      if (o.mode === "type") { gsap.set(s, { opacity: 0 }); T().set(s, { opacity: 1 }, t0); }
      else if (o.mode === "grey") { gsap.set(s, { opacity: 0, color: "#9a9a9a", y: 10 }); T().to(s, { opacity: 1, y: 0, duration: 0.12, ease: "power2.out" }, t0); T().to(s, { color: o.color || "", duration: 0.25 }, t0 + 0.1); }
      else if (o.mode === "pop") { gsap.set(s, { opacity: 0, scale: 0.2 }); T().to(s, { opacity: 1, scale: 1, duration: 0.22, ease: "back.out(2.6)" }, t0); }
      else { gsap.set(s, { opacity: 0, y: "-0.32em", rotation: -14, scale: 1.25 }); T().to(s, { opacity: 1, y: 0, rotation: 0, scale: 1, duration: 0.16, ease: "back.out(2.2)" }, t0); }
    });
    return spans;
  }

  // ---------------- kinetic: фраза по словам, акцент гигантский ----------------
  // lines: [{text: "обычные *АКЦЕНТ* _курсив_", at, word_at: [..], size, dx, font: sans|wide|script|narrow, weight, color}]
  // *слово* — акцент (жирный, ×acc_scale, цвет accent, по буквам «падают»); _слово_ — рукописный вводный.
  // grow: "up" — новая строка появляется снизу и выталкивает стопку вверх. lead — слово появляется раньше речи.
  B.kinetic = (b, P) => {
    const root = el("div", "blk b-kinetic" + (b.glow ? " glow" : "")); const size = b.size || 74, lead = b.lead ?? 0.12;
    root.style.setProperty("--acc", b.accent || "var(--accent)");
    if (b.align) root.style.alignItems = b.align === "left" ? "flex-start" : b.align === "right" ? "flex-end" : "center";
    const lines = (b.lines || []).map((L) => typeof L === "string" ? { text: L } : L);
    const lineNodes = [];
    lines.forEach((L, li) => {
      const ln = el("div", "kl"); ln.style.fontSize = (L.size || size) + "px";
      if (L.dx) ln.style.marginLeft = L.dx + "px";
      if (L.font) ln.style.fontFamily = `var(--${L.font})`;
      if (L.weight) ln.style.fontWeight = L.weight;
      if (L.color) ln.style.color = L.color;
      root.appendChild(ln); lineNodes.push(ln);
      const toks = String(L.text).split(/\s+/).filter(Boolean);
      const lat = L.at ?? b.at + li * 0.5;
      toks.forEach((w, wi) => {
        const acc = /^\*.*\*$/.test(w), scr = /^_.*_$/.test(w), word = acc || scr ? w.slice(1, -1) : w;
        const sp = el("span", "kw" + (acc ? " acc" : "") + (scr ? " scr" : ""));
        if (acc) sp.style.fontSize = ((L.size || size) * (b.acc_scale || 1.8)) + "px";
        ln.appendChild(sp); ln.appendChild(document.createTextNode(" "));
        const wat = (L.word_at && L.word_at[wi] != null ? L.word_at[wi] : lat + wi * (b.stagger ?? 0.12)) - lead;
        if (acc && b.acc_anim !== "blur") { gsap.set(sp, { opacity: 1 }); letters(sp, word, wat, { mode: b.acc_anim || "drop", color: b.accent }); }
        else { sp.textContent = word; blurIn(sp, wat, 0.16, acc ? 26 : 18); }
      });
    });
    if (b.grow === "up") {           // стопка растёт снизу: контейнер сдвигается вверх на высоту ещё не появившихся строк
      const starts = lines.map((L, li) => (L.at ?? b.at + li * 0.5) - lead);
      drive((t) => {
        if (!root.isConnected) return;
        let hidden = 0; lineNodes.forEach((n, i) => { if (t < starts[i]) hidden += n.offsetHeight; });
        setStyle(root, "transform", `translateY(${(hidden / 2).toFixed(1)}px)`);
      });
    }
    return root;
  };

  // ---------------- notbut: «не X — а Y» ----------------
  B.notbut = (b) => {
    const root = el("div", "blk b-notbut");
    const x = el("div", "nx", esc(b.not)), y = el("div", "ny", esc(b.but));
    const fit = (txt, sz, k) => Math.min(sz, Math.floor(940 / Math.max(1, [...txt].length * k)));
    x.style.fontSize = fit(b.not, b.not_size || 110, 0.52) + "px"; y.style.fontSize = fit(b.but, b.size || 150, 0.8) + "px"; y.style.whiteSpace = "nowrap";
    root.append(x, y);
    gsap.set(x, { opacity: 0 }); T().to(x, { opacity: 1, duration: 0.4, ease: "power1.out" }, b.at);
    const bat = b.but_at ?? b.at + 0.8;
    T().to(x, { opacity: 0.45, duration: 0.25 }, bat);
    gsap.set(y, { opacity: 1 }); letters(y, b.but, bat, { mode: "drop", stagger: 0.04 });
    return root;
  };

  // ---------------- cursor: курсор-рассказчик + клик-волна ----------------
  // path: [{at, x, y}] (px панели), click_at: [..], ripple: "local" | "full" (волна на весь кадр, контент приглушается)
  B.cursor = (b, P) => {
    const root = el("div", "b-cursor"); root.style.cssText = "position:absolute;left:0;top:0;width:1080px;height:1920px;pointer-events:none";
    const svg = sv("svg", { width: 1080, height: 1920, viewBox: "0 0 1080 1920" }, root);
    const rip = sv("circle", { r: 0, fill: b.ripple_fill || "rgba(255,255,255,0.35)", stroke: b.ripple_color || "#ffffff", "stroke-width": 4 }, svg);
    const g = sv("g", {}, svg);
    sv("path", { d: "M0 0 L0 46 L12 35 L21 56 L30 52 L21 32 L37 32 Z", fill: b.color || "#ffffff", stroke: "#111", "stroke-width": 2.5, "stroke-linejoin": "round" }, g);
    const path = b.path || [{ at: b.at, x: 540, y: 960 }], clicks = [].concat(b.click_at || []);
    const R = b.ripple === "full" ? 2400 : (b.ripple_r || 160);
    drive((t) => {
      let x = path[0].x, y = path[0].y, vis = t >= path[0].at - 0.05 && t < P.until;
      for (let i = 1; i < path.length; i++) {
        const a = path[i - 1], c = path[i]; if (t < c.at) break;
        const p = easeOut((t - c.at) / (c.dur || 0.3)), arc = Math.sin(Math.PI * clamp01((t - c.at) / (c.dur || 0.3))) * (c.arc ?? 60);
        const dx = c.x - a.x, dy = c.y - a.y, L = Math.hypot(dx, dy) || 1;
        x = lerp(a.x, c.x, p) - dy / L * arc; y = lerp(a.y, c.y, p) + dx / L * arc;
      }
      const jit = Math.sin(t * 9) * 1.5;
      let cs = 1, rr = 0, ro = 0;
      for (const ca of clicks) { const d = t - ca; if (d >= 0 && d < 0.12) cs = 0.86; if (d >= 0 && d < 0.75) { const q = clamp01(d / (b.ripple === "full" ? 0.36 : 0.6)); rr = R * easeOut(q); ro = (1 - clamp01(d / 0.75)) * 0.9; } }
      g.setAttribute("transform", `translate(${(x + jit).toFixed(1)} ${(y - jit).toFixed(1)}) scale(${cs})`);
      g.setAttribute("opacity", vis ? 1 : 0);
      rip.setAttribute("cx", x.toFixed(1)); rip.setAttribute("cy", y.toFixed(1)); rip.setAttribute("r", rr.toFixed(1)); rip.setAttribute("opacity", ro.toFixed(3));
    });
    return root;
  };

  // ---------------- burst: фонтан карточек из источника ----------------
  B.burst = (b, P) => {
    const root = el("div", "b-burst"); root.style.cssText = "position:absolute;left:0;top:0;width:1080px;height:1920px;pointer-events:none;overflow:hidden";
    const items = b.items || ["промпт"], n = b.count || 48, rate = b.rate || 22, life = b.life || 1.0, r = rng(b.seed || 3);
    const x0 = b.from?.x ?? 540, y0 = b.from?.y ?? 1500, col = b.color || "#25B45F";
    const parts = Array.from({ length: n }, (_, i) => {
      const c = el("div", "bcard", `<i></i><span>${esc(items[i % items.length])}</span>`);
      c.style.background = `linear-gradient(135deg, ${mix(col, "#0b1410", 0.75)}, ${col})`; c.style.boxShadow = `0 0 24px ${col}66`;
      root.appendChild(c);
      return { c, t0: b.at + i / rate, dx: (r() - 0.5) * 520, rot: (r() - 0.5) * 120, z: 0.6 + r() * 0.6, ph: r() * 6.28 };
    });
    drive((t) => {
      for (const p of parts) {
        const a = (t - p.t0) / life;
        if (a < 0 || a > 1) { setStyle(p.c, "opacity", "0"); continue; }
        const y = y0 - 2100 * Math.pow(a, 1.6), x = x0 + p.dx * a + Math.sin(p.t0 / 1.2 * 6.283 + p.ph) * 180 * a;
        setStyle(p.c, "opacity", (a < 0.1 ? a / 0.1 : a > 0.85 ? (1 - a) / 0.15 : 1).toFixed(3));
        setStyle(p.c, "transform", `translate(${(x - 172).toFixed(1)}px, ${(y - 44).toFixed(1)}px) rotate(${(p.rot * a).toFixed(1)}deg) scale(${(p.z * (0.6 + 0.4 * Math.min(1, a * 4))).toFixed(3)})`);
      }
    });
    return root;
  };

  // ---------------- widgets: экран собирается из плиток, «камера» в 3D ----------------
  // tiles: [{w:1|2, h:1|2, icon, value, label, color, at}], camera: [{at, rx, ry, s}], cell 225, gap 32
  B.widgets = (b) => {
    const root = el("div", "blk b-widgets"); const cols = b.cols || 4, gap = b.gap || 28, cell = b.cell || Math.floor((900 - gap * (cols - 1)) / cols);
    const grid = el("div", "wgrid"); grid.style.gridTemplateColumns = `repeat(${cols}, ${cell}px)`; grid.style.gridAutoRows = cell + "px"; grid.style.gap = gap + "px";
    root.appendChild(grid);
    (b.tiles || []).forEach((tl_, i) => {
      const n = el("div", "wtile slab", `${tl_.icon ? `<div class="wi">${esc(tl_.icon)}</div>` : ""}${tl_.value != null ? `<div class="wv">${esc(tl_.value)}</div>` : ""}${tl_.label ? `<div class="wl">${esc(tl_.label)}</div>` : ""}`);
      n.style.gridColumn = `span ${tl_.w || 1}`; n.style.gridRow = `span ${tl_.h || 1}`;
      if (tl_.color) n.style.setProperty("--wc", tl_.color);
      grid.appendChild(n);
      const at = tl_.at ?? b.at + i * (b.beat ?? 0.186);
      gsap.set(n, { scale: 0.04, opacity: 0 });
      T().to(n, { opacity: 1, duration: 0.05 }, at); T().to(n, { scale: 1.04, duration: 0.2, ease: "expo.out" }, at); T().to(n, { scale: 1, duration: 0.12, ease: "power2.out" }, at + 0.2);
      if (b.idle !== false) drive((t) => { if (t > at + 0.35) setStyle(n, "translate", `0 ${(Math.sin((t + i) * 1.7) * 3).toFixed(2)}px`); });
    });
    // по умолчанию — только наезд 1.08 → 1: скосом (вместо 3D) плитки выезжали криво и за край кадра (автор, 2026-10-18:
    // «таблички как-то криво появляются за экраном»); доворот rx/ry — только если задан camera явно
    const cam = b.camera || [{ at: b.at, rx: 0, ry: 0, s: 1.08 }, { at: b.at + 0.2, rx: 0, ry: 0, s: 1, dur: 1.6 }];
    // «камера» без 3D: наклон по X → сжатие по высоте + сдвиг, поворот по Y → сжатие по ширине + скос. Настоящая
    // perspective у контейнера с анимированными плитками выключает быстрый захват HyperFrames (JPEG-скриншоты, медленно)
    drive((t) => { const c = keyed(cam, t, 1), rx = c.rx * Math.PI / 180, ry = c.ry * Math.PI / 180;
      setStyle(grid, "transform", `scale(${c.s.toFixed(3)}) skewY(${(c.ry * 0.45).toFixed(2)}deg) skewX(${(-c.rx * 0.35).toFixed(2)}deg) scale(${Math.cos(ry).toFixed(3)}, ${Math.cos(rx).toFixed(3)})`); });
    return root;
  };

  // ---------------- calendar ----------------
  // mode "fill": дни по шагам steps [{at, done:N}], today, mark; mode "run": метка бежит по дням с ускорением, в конце зеленеет
  B.calendar = (b) => {
    const root = el("div", "blk b-cal" + (b.tilt === false ? "" : " tilt")); const days = b.days || 30, off = b.offset || 2;
    if (b.title) root.appendChild(el("div", "ctitle", esc(b.title)));
    const grid = el("div", "cgrid"); root.appendChild(grid);
    ["пн", "вт", "ср", "чт", "пт", "сб", "вс"].forEach((d) => grid.appendChild(el("div", "cdow", d)));
    for (let i = 0; i < off; i++) grid.appendChild(el("div", "cday empty"));
    const cells = Array.from({ length: days }, (_, i) => { const c = el("div", "cday", String(i + 1)); grid.appendChild(c); gsap.set(c, { scale: 0, opacity: 0 }); T().to(c, { scale: 1, opacity: 1, duration: 0.22, ease: "back.out(2)" }, b.at + i * 0.025); return c; });
    const mark = el("div", "cmark"); grid.appendChild(mark);
    drive((t) => {
      if (b.mode === "run") {
        const t0 = b.run_at ?? b.at + 0.9, end = b.run_to ?? days; let k = 0, tt = t0, stp = 0.15;
        while (k < end - 1 && t >= tt + stp) { tt += stp; k++; stp = Math.max(0.05, stp * 0.9); }
        const c = cells[k]; setStyle(mark, "opacity", t >= t0 ? "1" : "0");
        if (c && c.offsetParent) setStyle(mark, "transform", `translate(${c.offsetLeft + c.offsetWidth / 2 - 52}px, ${c.offsetTop + c.offsetHeight / 2 - 52}px)`);
        setStyle(mark, "background", k >= end - 1 && t > tt + 0.2 ? "#1DB33A" : "#D72A29");
        cells.forEach((c2, i) => setStyle(c2, "opacity", t < b.at + i * 0.025 ? "0" : String(Math.max(0.25, 1 - Math.abs(i - k) * 0.09).toFixed(2))));
      } else {
        let done = 0; for (const s of b.steps || []) if (t >= s.at) done = s.done;
        cells.forEach((c2, i) => { c2.classList.toggle("done", i < done); c2.classList.toggle("today", b.today === i + 1); });
        setStyle(mark, "opacity", "0");
      }
    });
    return root;
  };

  // ---------------- stack: каскад карточек и поглощение в заголовок ----------------
  B.stack = (b) => {
    const root = el("div", "blk b-stack"); const head = el("div", "shead", esc(b.title || "")); root.appendChild(head);
    const list = el("div", "slist"); root.appendChild(list);
    const cards = (b.cards || []).map((c, i) => {
      const n = el("div", "scard", `<div class="sic" style="background:${c.color || K.PALETTE[i % 7]}">${esc(c.icon || "")}</div><div class="stx">${esc(c.text)}</div>`);
      list.appendChild(n); const at = c.at ?? b.at + 0.3 + i * 0.28;
      gsap.set(n, { opacity: 0, scale: 0.34, y: 520 }); T().to(n, { opacity: 1, scale: 1, y: 0, duration: 0.4, ease: "back.out(1.4)" }, at);
      return { n, c };
    });
    gsap.set(head, { opacity: 0, y: -30 }); T().to(head, { opacity: 1, y: 0, duration: 0.35, ease: "power3.out" }, b.at);
    if (b.collapse_at != null) cards.slice().reverse().forEach(({ n, c }, k) => {
      const at = b.collapse_at + k * 0.18;
      T().to(n, { y: () => -(n.offsetTop + n.offsetHeight / 2) + 20, scale: 0.15, opacity: 0, duration: 0.13, ease: "power3.in" }, at);
      T().to(head, { backgroundColor: c.color || "#DE0F29", rotation: k % 2 ? 5 : -5, scale: 1.08, duration: 0.06 }, at + 0.12);
      T().to(head, { backgroundColor: "rgba(255,255,255,0.08)", rotation: 0, scale: 1, duration: 0.16, ease: "power2.out" }, at + 0.18);
    });
    return root;
  };

  // ---------------- profile: аватар раскрывается в капсулу ----------------
  B.profile = (b) => {
    const root = el("div", "blk b-profile"); const pill = el("div", "ppill");
    const av = el("div", "pav", b.avatar ? (/\.(png|jpe?g|webp|svg)$/i.test(b.avatar) ? `<img src="${esc(b.avatar)}">` : esc(b.avatar)) : "");
    const info = el("div", "pinfo", `<div class="pname">${esc(b.name || "")}</div><div class="psub">${esc(b.sub || "")}</div>` + (b.stars ? `<div class="pstars">${"★".repeat(b.stars).split("").map((s) => `<span>${s}</span>`).join("")}</div>` : ""));
    const btn = b.button ? el("div", "pbtn", `<span>${esc(b.button)}</span>`) : null;
    pill.append(av, info); if (btn) pill.appendChild(btn); root.appendChild(pill);
    const at = b.at, W1 = b.width || 800;
    gsap.set(pill, { width: 142, opacity: 0, scale: 0.4 }); gsap.set([info, btn].filter(Boolean), { opacity: 0 });
    T().to(pill, { opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)" }, at);
    T().to(pill, { width: W1 + 60, duration: 0.3, ease: "power3.out" }, at + 0.3); T().to(pill, { width: W1, duration: 0.25, ease: "power2.inOut" }, at + 0.6);
    T().to(info, { opacity: 1, duration: 0.2 }, at + 0.5);
    root.querySelectorAll(".pstars span").forEach((s, i) => { gsap.set(s, { opacity: 0, scale: 0 }); T().to(s, { opacity: 1, scale: 1, duration: 0.2, ease: "back.out(3)" }, at + 0.7 + i * 0.05); });
    if (btn) { T().to(btn, { opacity: 1, duration: 0.15 }, at + 0.8); gsap.set(btn.firstChild, { opacity: 0 }); T().to(btn.firstChild, { opacity: 1, duration: 0.2 }, at + 1.0); }
    drive((t) => { const tau = t - at - 0.55; setStyle(pill, "rotate", tau > 0 ? (2.5 * Math.exp(-4 * tau) * Math.cos(6.283 * 2.2 * tau)).toFixed(2) + "deg" : "0deg"); });
    return root;
  };

  // ---------------- board: детективная доска, красная нить, камера от листа к листу ----------------
  // cards: [{title, text, at}] — камера переезжает к листу в его at; overview_at — отъезд на общий план
  B.board = (b) => {
    const root = el("div", "blk b-board"); const VW = 960, VH = b.height || 1080;
    root.style.width = VW + "px"; root.style.height = VH + "px";
    const world = el("div", "bworld"); root.appendChild(world);
    const svg = sv("svg", { width: 2400, height: 3000, viewBox: "0 0 2400 3000", style: "position:absolute;left:0;top:0;overflow:visible" }, world);
    const r = rng(b.seed || 5), cards = b.cards || [];
    const pos = cards.map((_, i) => ({ x: 300 + (i % 2) * 760 + (r() - 0.5) * 120, y: 300 + i * 520 + (r() - 0.5) * 80, rot: (r() - 0.5) * 10 }));
    cards.forEach((c, i) => {
      const n = el("div", "bnote", `<i class="tape a"></i><i class="tape b"></i><div class="bt">${esc(c.title || "")}</div><div class="bx">${esc(c.text || "")}</div>`);
      n.style.left = pos[i].x - 210 + "px"; n.style.top = pos[i].y - 260 + "px"; n.style.rotate = pos[i].rot + "deg"; world.appendChild(n);
    });
    const thr = [];
    for (let i = 1; i < pos.length; i++) {
      const a = pos[i - 1], c = pos[i], mx = (a.x + c.x) / 2, my = Math.max(a.y, c.y) + 120;
      const L = K.qlen(a.x, a.y - 200, mx, my, c.x, c.y - 200);
      thr.push({ p: sv("path", { d: `M${a.x} ${a.y - 200} Q${mx} ${my} ${c.x} ${c.y - 200}`, fill: "none", stroke: b.thread || "#C3001C", "stroke-width": 4, "stroke-dasharray": `${L} ${L}`, "stroke-dashoffset": L }, svg), L, at: cards[i].at ?? b.at + i * 1.2 });
    }
    pos.forEach((p) => { sv("circle", { cx: p.x, cy: p.y - 200, r: 9, fill: "#e8e8e8", stroke: "#555", "stroke-width": 2 }, svg); });
    const keys = cards.map((c, i) => ({ at: c.at ?? b.at + i * 1.2, x: pos[i].x, y: pos[i].y, s: b.zoom || 1.15 }));
    if (b.overview_at != null && pos.length) {
      const x0 = Math.min(...pos.map((q) => q.x)) - 260, x1 = Math.max(...pos.map((q) => q.x)) + 260, y0 = Math.min(...pos.map((q) => q.y)) - 300, y1 = Math.max(...pos.map((q) => q.y)) + 300;
      keys.push({ at: b.overview_at, x: (x0 + x1) / 2, y: (y0 + y1) / 2, s: Math.min(VW / (x1 - x0), VH / (y1 - y0)) });
    }
    drive((t) => {
      const c = keyed(keys, t, 0.5);
      const last = keys.filter((k) => t >= k.at).pop(); const push = last ? 1 + 0.035 * clamp01((t - last.at - 0.5) / 2.5) : 1;   // лист не «висит»: медленный наезд
      const sc = c.s * push;
      setStyle(world, "transform", `translate(${(VW / 2 - c.x * sc).toFixed(1)}px, ${(VH / 2 - c.y * sc).toFixed(1)}px) scale(${sc.toFixed(3)})`);
      for (const h of thr) h.p.setAttribute("stroke-dashoffset", (h.L * (1 - smooth((t - h.at + 0.5) / 0.5))).toFixed(1));
    });
    world.style.transformOrigin = "0 0";
    return root;
  };

  // ---------------- carousel: cover-flow карточек/картинок ----------------
  // items: [{src | text, label}], steps: [{at, i}] — какой элемент в центре
  B.carousel = (b) => {
    const root = el("div", "blk b-carousel"); const w = b.card_w || 620, h = b.card_h || 800; root.style.height = h + 60 + "px";
    const nodes = (b.items || []).map((it) => {
      const n = el("div", "ccard", it.src ? `<img src="${esc(it.src)}">` : `<div class="ctext">${esc(it.text || "")}</div>`);
      n.style.width = w + "px"; n.style.height = h + "px"; if (it.color) n.style.background = it.color;
      if (it.label) n.appendChild(el("div", "clabel", esc(it.label)));
      root.appendChild(n); return n;
    });
    const steps = b.steps || nodes.map((_, i) => ({ at: b.at + i * 0.8, i }));
    enter(root, b.at);
    drive((t) => {
      let cur = steps[0].i, prev = cur, p = 1;
      for (const s of steps) { if (t < s.at) break; prev = cur; cur = s.i; p = clamp01((t - s.at) / 0.32); }
      const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2, pos = lerp(prev, cur, e);
      nodes.forEach((n, i) => {
        const d = i - pos, ad = Math.abs(d);
        setStyle(n, "transform", `translate(-50%, 0) translateX(${(d * (b.spread || 495)).toFixed(1)}px) scale(${(1 - Math.min(ad, 2) * 0.07).toFixed(3)}) skewY(${(d * 2.5).toFixed(2)}deg)`);
        setStyle(n, "zIndex", String(100 - Math.round(ad * 10))); setStyle(n, "opacity", ad > 2.2 ? "0" : "1");
        setStyle(n, "--dim", Math.min(0.62, ad * 0.38).toFixed(3));
      });
    });
    return root;
  };

  // ---------------- chart: неоновая линия со свечением без фильтров ----------------
  // points: [числа], draw_at, dur, color, label (подпись у конца), area: заливка под линией
  B.chart = (b) => {
    const root = el("div", "blk b-chart"); const W = b.width || 900, H = b.height || 520, pts = b.points || [3, 5, 4, 8, 7, 12];
    root.style.width = W + "px"; root.style.height = H + "px";
    const svg = sv("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` }, root);
    const mn = Math.min(...pts), mx = Math.max(...pts), xy = pts.map((v, i) => [30 + i * (W - 60) / (pts.length - 1), H - 40 - (v - mn) / (mx - mn || 1) * (H - 120)]);
    const d = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    for (let i = 0; i < 5; i++) sv("line", { x1: 0, x2: W, y1: 40 + i * (H - 80) / 4, y2: 40 + i * (H - 80) / 4, stroke: "rgba(255,255,255,0.07)", "stroke-width": 2 }, svg);
    let L = 0; for (let i = 1; i < xy.length; i++) L += Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]);
    const col = b.color || "#37E87C";
    const lines = [[34, 0.12], [16, 0.25], [6, 1]].map(([w, o]) => sv("path", { d, fill: "none", stroke: col, "stroke-width": w, "stroke-opacity": o, "stroke-linecap": "round", "stroke-linejoin": "round", "stroke-dasharray": `${L} ${L}`, "stroke-dashoffset": L }, svg));
    const dot = sv("circle", { r: 13, fill: "#fff", stroke: col, "stroke-width": 6, opacity: 0 }, svg);
    const lab = b.label ? el("div", "chlabel", esc(b.label)) : null; if (lab) { lab.style.color = col; root.appendChild(lab); }
    const at = b.draw_at ?? b.at + 0.2, dur = b.dur || 0.7;
    enter(root, b.at);
    drive((t) => {
      const p = easeOut((t - at) / dur);
      lines.forEach((l) => l.setAttribute("stroke-dashoffset", (L * (1 - p)).toFixed(1)));
      let rem = L * p, x = xy[0][0], y = xy[0][1];
      for (let i = 1; i < xy.length; i++) { const sl = Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]); if (rem <= sl) { const q = rem / sl; x = lerp(xy[i - 1][0], xy[i][0], q); y = lerp(xy[i - 1][1], xy[i][1], q); break; } rem -= sl; x = xy[i][0]; y = xy[i][1]; }
      dot.setAttribute("cx", x.toFixed(1)); dot.setAttribute("cy", y.toFixed(1)); dot.setAttribute("opacity", t >= at ? 1 : 0);
      if (lab) { const lw = lab.offsetWidth || 240; setStyle(lab, "transform", `translate(${Math.min(x - 40, W - lw - 10).toFixed(0)}px, ${Math.max(0, y - 110).toFixed(0)}px)`); setStyle(lab, "opacity", p >= 0.98 ? "1" : "0"); }
    });
    return root;
  };

  // ---------------- chapter: номер главы хромом + S-кривая ----------------
  B.chapter = (b) => {
    const root = el("div", "blk b-chapter"); const num = el("div", "chnum", esc(b.text || "#1")); num.style.fontSize = (b.size || 220) + "px";
    const svg = sv("svg", { width: 760, height: 200, viewBox: "0 0 760 200", class: "chcurve" }, root);
    const path = sv("path", { d: "M10 150 C 200 10, 380 190, 560 60 S 740 40, 750 20", fill: "none", stroke: "#fff", "stroke-width": 6, "stroke-linecap": "round" }, svg);
    root.appendChild(num); if (b.label) root.appendChild(el("div", "chlab", esc(b.label)));
    const L = 900; path.setAttribute("stroke-dasharray", `${L} ${L}`);
    gsap.set(num, { x: 420, opacity: 0, skewX: -12 }); T().to(num, { x: 0, opacity: 1, skewX: 0, duration: 0.45, ease: "expo.out" }, b.at);
    drive((t) => path.setAttribute("stroke-dashoffset", (L * (1 - easeOut((t - b.at) / 0.6))).toFixed(1)));
    return root;
  };

  // ---------------- phone: мокап телефона, скриншот собирается кусками, тап с волной ----------------
  B.phone = (b) => {
    const root = el("div", "blk b-phone"); const W = b.width || 470, H = Math.round(W * 2.04); root.style.width = W + "px"; root.style.height = H + "px";
    const scr = el("div", "pscr"); root.appendChild(scr);
    const rows = b.pieces || 6;
    for (let i = 0; i < rows; i++) {
      const pc = el("div", "ppiece"); pc.style.top = (i * 100 / rows) + "%"; pc.style.height = (100 / rows + 0.4) + "%";
      pc.style.backgroundImage = `url("${b.src}")`; pc.style.backgroundSize = `100% ${rows * 100}%`; pc.style.backgroundPosition = `0 ${(i / (rows - 1)) * 100}%`;
      scr.appendChild(pc); gsap.set(pc, { opacity: 0, y: 40, scale: 0.96 }); T().to(pc, { opacity: 1, y: 0, scale: 1, duration: 0.3, ease: "power3.out" }, b.at + 0.25 + i * 0.08);
    }
    const tap = el("div", "ptap"); scr.appendChild(tap);
    enter(root, b.at);
    if (b.tap_at != null) {
      tap.style.left = (b.tap?.x ?? 50) + "%"; tap.style.top = (b.tap?.y ?? 60) + "%";
      gsap.set(tap, { scale: 0, opacity: 0.55 }); T().to(tap, { scale: 6, opacity: 0, duration: 0.75, ease: "power2.out" }, b.tap_at);
      T().to(root, { scale: 0.97, duration: 0.08 }, b.tap_at); T().to(root, { scale: 1, duration: 0.25, ease: "back.out(2)" }, b.tap_at + 0.08);
    }
    if (b.zoom_at != null) T().to(root, { scale: b.zoom || 1.6, duration: 0.18, ease: "power4.out" }, b.zoom_at);
    return root;
  };

  // ---------------- timeline3d: наклонённый «планшет» с дорожками и плейхедом ----------------
  // clips: [{track, from, to, text, color, at}] (from/to — доли 0..1 ширины), playhead: [at0, at1]
  B.timeline3d = (b) => {
    const root = el("div", "blk b-tl3d"); const pad = el("div", "tlpad"); root.appendChild(pad);
    const tracks = b.tracks || 3;
    for (let i = 0; i < tracks; i++) pad.appendChild(el("div", "tltrack")).style.top = (40 + i * 110) + "px";
    (b.clips || []).forEach((c, i) => {
      const n = el("div", "tlclip", esc(c.text || "")); n.style.background = c.color || K.PALETTE[i % 7];
      n.style.left = (40 + c.from * 920) + "px"; n.style.width = ((c.to - c.from) * 920) + "px"; n.style.top = (48 + (c.track || 0) * 110) + "px";
      pad.appendChild(n); const at = c.at ?? b.at + 0.3 + i * 0.25;
      gsap.set(n, { scaleX: 0, transformOrigin: "0 50%" }); T().to(n, { scaleX: 1, duration: 0.3, ease: "power3.out" }, at);
    });
    const ph = el("div", "tlhead"); pad.appendChild(ph); const tc = el("div", "tltc"); root.appendChild(tc);
    const [p0, p1] = b.playhead || [b.at, b.at + 3];
    enter(root, b.at);
    drive((t) => { const p = clamp01((t - p0) / (p1 - p0)); setStyle(ph, "left", (40 + p * 920).toFixed(1) + "px"); const s = p * (b.length || 58); setText(tc, `00:${String(Math.floor(s)).padStart(2, "0")}:${String(Math.floor((s % 1) * 60)).padStart(2, "0")}`); });
    return root;
  };

  // ---------------- chainrun: окно программы закрывается, команда набирается, цепочка плагинов загорается ----------------
  // window, window_at, close_at — окно (оранжевая шапка, ряды-слоты) с красным крестом и схлопыванием; cmd, cmd_at — команда
  // печатается в терминальной карточке; plugins: [названия], plugins_at, stagger — пилюли с номером слота и галочкой; done, done_at
  B.chainrun = (b) => {
    const root = el("div", "blk b-chainrun");
    const code = el("div", "crcode", `<span class="crp">$</span> <span class="crt"></span><i class="crcur"></i>`); root.appendChild(code);
    const list = el("div", "crlist"); root.appendChild(list);
    const pills = (b.plugins || []).map((nm, i) => { const n = el("div", "crpl", `<b>${String(i + 1).padStart(2, "0")}</b><span>${esc(nm)}</span><em>✓</em>`); list.appendChild(n); return n; });
    const done = b.done ? el("div", "crdone", esc(b.done)) : null; if (done) root.appendChild(done);
    const win = b.window ? el("div", "crwin", `<div class="crbar"><i></i><i></i><i></i><span>${esc(b.window)}</span></div>` +
      Array.from({ length: 5 }, () => `<div class="crrow"><u></u><u></u></div>`).join("") + `<svg class="crx" viewBox="0 0 100 100"><path d="M12 12 L88 88"/><path d="M88 12 L12 88"/></svg>`) : null;
    if (win) root.appendChild(win);
    const tl = T();
    if (win) {
      gsap.set(win, { opacity: 0, scale: 0.15 }); tl.to(win, { opacity: 1, scale: 1.04, duration: 0.25, ease: "power3.out" }, b.window_at ?? b.at);
      tl.to(win, { scale: 1, duration: 0.2 }, (b.window_at ?? b.at) + 0.25);
      const xs = win.querySelectorAll(".crx path"); gsap.set(xs, { strokeDasharray: 120, strokeDashoffset: 120 });
      const ca = b.close_at ?? (b.window_at ?? b.at) + 0.6;
      tl.to(xs, { strokeDashoffset: 0, duration: 0.14, stagger: 0.08, ease: "power2.out" }, ca);
      tl.to(win, { scale: 1.06, duration: 0.08 }, ca + 0.3); tl.to(win, { scale: 0, opacity: 0, rotation: -8, duration: 0.22, ease: "expo.in" }, ca + 0.38);
    }
    const ct = code.querySelector(".crt"), cur = code.querySelector(".crcur"), cmd = b.cmd || "", cat = b.cmd_at ?? b.at + 1;
    gsap.set(code, { opacity: 0, y: 30 }); tl.to(code, { opacity: 1, y: 0, duration: 0.25, ease: "power3.out" }, cat - 0.25);
    drive((t) => { const n = Math.max(0, Math.min(cmd.length, Math.floor((t - cat) / (b.type_speed || 0.035)))); setText(ct, cmd.slice(0, n));
      setStyle(cur, "opacity", t < cat - 0.25 ? "0" : (n >= cmd.length && Math.floor(t * 2.5) % 2) ? "0" : "1"); });
    const pat = b.plugins_at ?? cat + cmd.length * 0.035 + 0.3, st = b.stagger ?? 0.11;
    pills.forEach((n, i) => {
      gsap.set(n, { opacity: 0, x: -60 }); tl.to(n, { opacity: 1, x: 0, duration: 0.2, ease: "back.out(1.6)" }, pat + i * st);
      const em = n.querySelector("em"); gsap.set(em, { scale: 0, opacity: 0 }); tl.to(em, { scale: 1, opacity: 1, duration: 0.18, ease: "back.out(3)" }, pat + i * st + 0.12);
      const on_ = pat + i * st + 0.12; drive((t) => K.setClass(n, "on", t >= on_));     // GSAP 3 не твинит className
    });
    if (done) { gsap.set(done, { opacity: 0, y: 16 }); tl.to(done, { opacity: 1, y: 0, duration: 0.25, ease: "power3.out" }, b.done_at ?? pat + pills.length * st + 0.15); }
    return root;
  };

  // ---------------- panel-level: фоновое гигантское слово и декор ----------------
  // panels.json у панели: "ghost": "текст" (огромный курсив на фоне, дрейф), "decor": {"kind": "cross"|"spark"|"dot", "n": 6, "color"}
  window.UI.panelExtras = (sec, p) => {
    if (p.ghost) {
      const g = el("div", "ghost", esc(p.ghost)); sec.insertBefore(g, sec.firstChild);
      drive((t) => setStyle(g, "transform", `translateX(${(-15 * (t - p.at)).toFixed(1)}px)`));
    }
    if (p.decor) {
      const d = p.decor, r = rng(d.seed || 11), n = d.n || 6;
      for (let i = 0; i < n; i++) {
        const s = el("div", "decor " + (d.kind || "cross")); s.style.left = (r() * 1000) + "px"; s.style.top = (80 + r() * 1700) + "px";
        const sz = 40 + r() * 90; s.style.width = s.style.height = sz + "px"; if (d.color) s.style.setProperty("--dc", d.color);
        sec.insertBefore(s, sec.children[1] || null); const sp = (r() - 0.5) * 12, ph = r() * 6;
        drive((t) => setStyle(s, "transform", `translateY(${(Math.sin(t * 0.8 + ph) * 14).toFixed(1)}px) rotate(${(sp * t * 3).toFixed(1)}deg)`));
      }
    }
    if (p.theme === "violet" || p.theme === "aurora") drive((t) => {
      setStyle(sec, "backgroundPosition", `${(50 + 18 * Math.sin(t * 0.57)).toFixed(1)}% ${(30 + 12 * Math.cos(t * 0.43)).toFixed(1)}%, ${(50 - 20 * Math.cos(t * 0.5)).toFixed(1)}% ${(75 + 10 * Math.sin(t * 0.6)).toFixed(1)}%, 0 0`);
    });
  };
})();
