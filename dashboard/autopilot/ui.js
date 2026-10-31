// Lloyd's Tavern app UI, shared by /app/ and /book/: odometer, scrubbable hero chart, bottom sheets, toast,
// token avatars, journal icons, pull-to-refresh. Needs lloyd.js (window.Lloyd) first. No dependencies.
window.UI = (() => {
  const L = window.Lloyd;
  const $ = s => document.querySelector(s), $$ = s => Array.from(document.querySelectorAll(s));
  const buzz = ms => { try { navigator.vibrate && navigator.vibrate(ms); } catch (_) {} };
  const store = {get: k => { try { return localStorage.getItem(k); } catch (_) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} }};

  // ---------- toast ----------
  let tT;
  function toast(msg, kind = "") {
    let t = $("#toast"); if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = msg; t.className = "toast on " + kind; clearTimeout(tT); tT = setTimeout(() => t.className = "toast " + kind, 3200);
  }

  // ---------- bottom sheets: <section class="sheet" id=…> + one .scrim ----------
  let open = null;
  function sheet(id) {
    close(); open = $(id); if (!open) return;
    let sc = $("#scrim"); if (!sc) { sc = document.createElement("div"); sc.id = "scrim"; sc.className = "scrim"; document.body.appendChild(sc); sc.onclick = () => close(); }
    sc.classList.add("on"); open.classList.add("on"); document.body.style.overflow = "hidden"; buzz(8);
    setTimeout(() => { const f = open && open.querySelector("input[type=text]"); if (f && !f.value) f.focus(); }, 380);
  }
  function close() { if (!open) return; open.classList.remove("on"); open.style.transform = ""; open = null; const sc = $("#scrim"); if (sc) sc.classList.remove("on"); document.body.style.overflow = ""; }
  const isOpen = () => !!open;
  function wireSheets() {
    const sc = $("#scrim"); if (sc) sc.onclick = () => close();
    $$("[data-close]").forEach(b => b.onclick = () => close());
    document.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
    $$(".sheet").forEach(sh => {   // swipe down to close
      let y0 = null, dy = 0;
      sh.addEventListener("touchstart", e => { if (sh.scrollTop > 0) return; y0 = e.touches[0].clientY; dy = 0; sh.style.transition = "none"; }, {passive: true});
      sh.addEventListener("touchmove", e => { if (y0 == null) return; dy = Math.max(0, e.touches[0].clientY - y0); sh.style.transform = `translateY(${dy}px)`; }, {passive: true});
      sh.addEventListener("touchend", () => { if (y0 == null) return; sh.style.transition = ""; y0 = null; if (dy > 110) close(); else sh.style.transform = ""; });
    });
    document.addEventListener("click", async e => {   // [data-copy="#selector"]
      const b = e.target.closest("[data-copy]"); if (!b) return;
      const txt = ($(b.dataset.copy) || {}).textContent || "";
      try { await navigator.clipboard.writeText(txt.trim()); toast("Copied", "ok"); buzz(12); } catch (_) { toast("Long-press to copy it"); }
    });
  }

  // ---------- odometer: each digit rolls into place. odo(el, "$1,234.56") or odo(el, "+65.2%") ----------
  function odo(el, text, masked) {
    el.classList.remove("sk");
    if (masked) { el.innerHTML = `<span class="mask">$••••••</span>`; el.dataset.v = ""; return; }
    const m = /^(.*?)(\.\d+)?(%?)$/.exec(text), whole = m[1], cents = m[2] ? m[2].slice(1) : null, tail = m[3];
    const shape = whole.replace(/\d/g, "0") + "|" + (cents || "").length + tail;
    if (el.dataset.shape !== shape || !el.querySelector(".odo")) {
      el.innerHTML = `<span class="odo">${[...whole].map(ch => /\d/.test(ch) ? `<span class="d"><span>${"0123456789".split("").map(n => `<i>${n}</i>`).join("")}</span></span>` : `<span>${ch}</span>`).join("")}</span>${cents != null ? `<span class="c">.${cents}${tail}</span>` : tail ? `<span class="c">${tail}</span>` : ""}`;
      el.querySelectorAll(".d > span").forEach(c => { c.style.transition = "none"; c.style.transform = "translateY(0)"; });
      void el.offsetWidth; el.querySelectorAll(".d > span").forEach(c => c.style.transition = "");
      el.dataset.shape = shape;
    }
    const ds = [...whole].filter(ch => /\d/.test(ch));
    el.querySelectorAll(".d > span").forEach((c, i) => c.style.transform = `translateY(-${ds[i]}em)`);
    const c = el.querySelector(".c"); if (c) c.textContent = (cents != null ? "." + cents : "") + tail;
    el.dataset.v = text;
  }
  function flash(el, delta) { if (!delta || Math.abs(delta) < 1e-9) return; el.classList.remove("flash-up", "flash-dn"); void el.offsetWidth; el.classList.add(delta > 0 ? "flash-up" : "flash-dn"); setTimeout(() => el.classList.remove("flash-up", "flash-dn"), 1400); }

  const ARROW_UP = `<svg viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg>`, ARROW_DN = `<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>`;
  // chip(pct, extra) -> "+4.62% · +$43.43" pill
  function chip(pct, extra) {
    const up = pct >= 0;
    return `<span class="chip ${up ? "up" : "dn"}">${up ? ARROW_UP : ARROW_DN}${L.signed(pct, pct !== 0 && Math.abs(pct) < 10 ? 2 : 1)}${extra ? ` · ${extra}` : ""}</span>`;
  }

  // ---------- hero chart: draw(svg, wrap, pts, compare, key) -> geometry; scrub(wrap, getGeo, onPoint, onEnd) ----------
  function draw(svg, wrap, pts, compare, key) {
    const W = Math.max(300, wrap.clientWidth), H = svg.clientHeight || 210, pt = 18, pb = 14;
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
    const all = pts.concat(compare || []);
    let lo = Math.min(0, ...all.map(p => p[1])), hi = Math.max(0, ...all.map(p => p[1]));
    const pad = (hi - lo || 2) * .12; lo -= pad; hi += pad;
    const X = t => (t - t0) / ((t1 - t0) || 1) * (W - 18) + 4, Y = v => pt + (1 - (v - lo) / (hi - lo)) * (H - pt - pb);
    const up = pts[pts.length - 1][1] >= pts[0][1], col = up ? "#FFC226" : "#FF8A80";
    const path = ps => ps.map((p, k) => (k ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
    const d = path(pts), last = pts[pts.length - 1], y0 = Y(pts[0][1]);
    let g = `<defs><linearGradient id="hg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".38"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>`;
    g += `<line x1="0" x2="${W}" y1="${y0.toFixed(1)}" y2="${y0.toFixed(1)}" stroke="rgba(255,253,247,.35)" stroke-width="1.5" stroke-dasharray="3 6"/>`;
    g += `<path d="${d} L${X(last[0]).toFixed(1)} ${H} L${X(t0).toFixed(1)} ${H} Z" fill="url(#hg)"/>`;
    if (compare && compare.length > 1) g += `<path d="${path(compare)}" fill="none" stroke="#F6EEDC" stroke-opacity=".75" stroke-width="2.2" stroke-dasharray="6 6" stroke-linecap="round"/>`;
    g += `<path d="${d}" fill="none" stroke="#1A1814" stroke-width="7" stroke-linejoin="round" stroke-linecap="round" opacity=".55" transform="translate(0 3)"/>`;
    g += `<path class="hline" d="${d}" fill="none" stroke="${col}" stroke-width="3.6" stroke-linejoin="round" stroke-linecap="round"/>`;
    g += `<circle class="enddot" cx="${X(last[0]).toFixed(1)}" cy="${Y(last[1]).toFixed(1)}" r="9" fill="${col}"/><circle cx="${X(last[0]).toFixed(1)}" cy="${Y(last[1]).toFixed(1)}" r="5.5" fill="${col}" stroke="#1A1814" stroke-width="2.5"/>`;
    g += `<g class="hx" style="display:none"><line class="hxl" y1="0" y2="${H}" stroke="#FFFDF7" stroke-width="1.5" stroke-dasharray="2 4"/><circle class="hxc" r="7" fill="${col}" stroke="#1A1814" stroke-width="3"/></g>`;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("preserveAspectRatio", "none"); svg.innerHTML = g;
    const ln = svg.querySelector(".hline");
    if (svg.dataset.key !== key && ln.getTotalLength) { const n = ln.getTotalLength(); ln.style.strokeDasharray = n; ln.style.strokeDashoffset = n; ln.getBoundingClientRect(); ln.style.transition = "stroke-dashoffset 1.1s cubic-bezier(.25,.8,.25,1)"; ln.style.strokeDashoffset = 0; setTimeout(() => { ln.style.strokeDasharray = ""; }, 1200); }
    svg.dataset.key = key;
    return {pts, X, Y, W, t0, t1, svg};
  }
  function scrub(wrap, getGeo, onPoint, onEnd) {
    let lastI = -1, active = false;
    const at = e => {
      const G = getGeo(); if (!G || !G.X) return;
      const r = wrap.getBoundingClientRect(), x = ((e.touches ? e.touches[0].clientX : e.clientX) - r.left) / r.width * G.W;
      let best = 0, bd = Infinity; G.pts.forEach((p, i) => { const dd = Math.abs(G.X(p[0]) - x); if (dd < bd) { bd = dd; best = i; } });
      const p = G.pts[best], g = G.svg.querySelector(".hx"); if (!g) return;
      g.style.display = ""; const l = g.querySelector(".hxl"), c = g.querySelector(".hxc");
      l.setAttribute("x1", G.X(p[0])); l.setAttribute("x2", G.X(p[0])); c.setAttribute("cx", G.X(p[0])); c.setAttribute("cy", G.Y(p[1]));
      if (best !== lastI) { lastI = best; if (active) buzz(3); onPoint(p, best); }
    };
    const end = () => { active = false; lastI = -1; const G = getGeo(); const g = G && G.svg.querySelector(".hx"); if (g) g.style.display = "none"; onEnd(); };
    wrap.addEventListener("pointerdown", e => { active = true; at(e); });
    wrap.addEventListener("pointermove", e => { if (active || e.pointerType === "mouse") at(e); });
    wrap.addEventListener("pointerup", end); wrap.addEventListener("pointerleave", end); wrap.addEventListener("pointercancel", end);
    let sx = 0, sy = 0, lock = null;   // horizontal drag scrubs, vertical scrolls
    wrap.addEventListener("touchstart", e => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; lock = null; active = true; at(e); }, {passive: true});
    wrap.addEventListener("touchmove", e => { const dx = Math.abs(e.touches[0].clientX - sx), dy = Math.abs(e.touches[0].clientY - sy); if (lock == null && (dx > 6 || dy > 6)) lock = dx > dy ? "x" : "y"; if (lock === "y") { end(); return; } if (lock === "x") e.preventDefault(); at(e); }, {passive: false});
    wrap.addEventListener("touchend", end);
  }
  // keeps points from `hours` back (0 = all), rebased to 0% at the start of the window
  function window_(series, hours) {
    if (!series || series.length < 2) return null;
    const t1 = series[series.length - 1][0], t0 = hours ? t1 - hours * 3600 : -Infinity;
    let pts = series.filter(p => p[0] >= t0); if (pts.length < 2) pts = series.slice(-2);
    const base = pts[0][1];
    return pts.map(p => [p[0], ((1 + p[1] / 100) / (1 + base / 100) - 1) * 100]);
  }

  // ---------- tokens ----------
  const AV = ["#FFC226", "#FFAE79", "#B9A6F2", "#8FC7F2", "#8FDF9A", "#5BC8BD", "#F6EEDC"];
  const avColor = s => { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return AV[h % AV.length]; };
  const parsePerp = t => { const m = /^(\w+)\s+(short|long)\s+([\d.]+)x$/i.exec(t || ""); return m ? {coin: m[1], side: m[2].toLowerCase(), lev: m[3]} : null; };
  function avatar(sym, perp) {
    const base = perp ? perp.coin : String(sym || "?"), short = perp ? perp.side === "short" : false;
    const ini = base.replace(/[^A-Za-z0-9$]/g, "").slice(0, base.length <= 4 ? 4 : 3) || "?";
    const fs = ini.length >= 4 ? 11 : ini.length === 3 ? 13 : 16;
    return `<span class="av" style="background:${avColor(base)};font-size:${fs}px">${L.esc(ini)}${perp ? `<span class="bdg ${short ? "" : "long"}">${short ? ARROW_DN : ARROW_UP}</span>` : ""}</span>`;
  }
  const changeCls = ch => ch == null || Math.abs(ch) < .05 ? "fl" : ch > 0 ? "up" : "dn";

  // ---------- journal ----------
  const IC = {
    short: `<path d="M3 7l7 7 4-4 7 7M21 11v6h-6"/>`, long: `<path d="M3 17l7-7 4 4 7-7M21 13V7h-6"/>`, buy: `<path d="M12 5v14M5 12h14"/>`, sell: `<path d="M5 12h14"/>`,
    close: `<path d="M5 12l5 5L20 7"/>`, dep: `<path d="M12 5v14M6 13l6 6 6-6"/>`, wd: `<path d="M12 19V5M6 11l6-6 6 6"/>`, tip: `<path d="M5 8h11v9a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3zM16 10h2a2 2 0 0 1 0 4h-2M8 3v2M11 3v2"/>`,
    warn: `<path d="M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>`,
    eye: `<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>`,
  };
  // a stool's journal line -> {k, title, text}
  function classify(j) {
    const t = j.title || "", x = j.text || "", sym = (/^([A-Za-z0-9$._-]{1,14}):/.exec(x) || [])[1];
    if (/Deposit received/i.test(t)) return {k: "dep", title: "Money in", text: x};
    if (/^Withdrawn/i.test(t)) return {k: "wd", title: "Sent to your wallet", text: x};
    if (/round|tip/i.test(t) && !/skip|did not/i.test(t)) return {k: "tip", title: "You bought the lab a round", text: x};
    if (/error|could not|failed|skipped|did not|stopped|too small|do not count/i.test(t)) return {k: "warn", title: t, text: x};
    if (/opened a short/i.test(x)) return {k: "short", title: `Shorted ${sym || ""}`.trim(), text: x.replace(/^[^:]+:\s*/, "")};
    if (/opened a long/i.test(x)) return {k: "long", title: `Went long ${sym || ""}`.trim(), text: x.replace(/^[^:]+:\s*/, "")};
    if (/closed the/i.test(x)) return {k: "close", title: `Closed ${sym || "a perp"}`, text: x.replace(/^[^:]+:\s*/, "")};
    if (sym && /sold|sell/i.test(x)) return {k: "sell", title: `Sold ${sym}`, text: x.replace(/^[^:]+:\s*/, "")};
    if (sym && /bought|buy|copying/i.test(x)) return {k: "buy", title: `Bought ${sym}`, text: x.replace(/^[^:]+:\s*/, "")};
    if (/parked|USDC/i.test(x) && sym) return {k: "sell", title: "Parked in cash", text: x};
    return {k: "lloyd", title: t || "Lloyd", text: x};
  }
  // the book's journal line (brain notes, trades, reviews) -> {k, title, text}
  function classifyBook(j) {
    const t = j.title || "", x = j.text || "", both = t + " " + x;
    const clean = t.replace(/^Automatic brain:\s*/i, "").replace(/^\w/, c => c.toUpperCase());
    if (/\bshort\b/i.test(t) && /open|opened|touched/i.test(both)) return {k: "short", title: clean, text: x};
    if (/\blong\b/i.test(t) && /open|opened/i.test(both)) return {k: "long", title: clean, text: x};
    if (/^(bought|buy)\b/i.test(t) || /\bbought\b/i.test(t)) return {k: "buy", title: clean, text: x};
    if (/^(sold|sell)\b/i.test(t) || /\bsold\b|\bclosed\b|took profit/i.test(t)) return {k: "sell", title: clean, text: x};
    if (/error|fail|could not|risk alert|stop/i.test(t)) return {k: "warn", title: clean, text: x};
    if (/status|watch|review|scan/i.test(t)) return {k: "eye", title: clean, text: x};
    return {k: "lloyd", title: clean || "Lloyd", text: x};
  }
  function dayLabel(ts) {
    const d = new Date(ts * 1000), n = new Date(), k = x => x.toDateString();
    if (k(d) === k(n)) return "Today"; const y = new Date(n); y.setDate(n.getDate() - 1); if (k(d) === k(y)) return "Yesterday";
    return d.toLocaleDateString("en-US", {weekday: "long", month: "short", day: "numeric"});
  }
  // renders a grouped activity list into <ul class="feedx">
  function feed(ul, items, classifier, limit) {
    const open = new Set($$("#" + ul.id + " .it.open").map(li => li.dataset.ts));
    let cur = "", h = "";
    (limit ? items.slice(0, limit) : items).forEach(j => {
      const dl = dayLabel(j.ts); if (dl !== cur) { cur = dl; h += `<li class="day">${dl}</li>`; }
      const c = classifier(j), tm = new Date(j.ts * 1000).toLocaleTimeString("en-US", {hour: "numeric", minute: "2-digit"});
      const ic = c.k === "lloyd" ? `<img src="/assets/lloyd-head.png?v=2" alt="">` : `<svg viewBox="0 0 24 24">${IC[c.k]}</svg>`;
      h += `<li class="it k-${c.k}${open.has(String(j.ts)) ? " open" : ""}" data-ts="${j.ts}"><span class="ic">${ic}</span><div class="tx"><b><span>${L.esc(c.title)}</span><time>${tm}</time></b><p>${L.esc(c.text)}</p></div></li>`;
    });
    ul.innerHTML = h;
    ul.querySelectorAll(".it").forEach(li => li.onclick = () => li.classList.toggle("open"));
  }

  // ---------- page chrome ----------
  function chrome(refresh) {
    window.addEventListener("scroll", () => { const tb = $(".tb"); if (tb) tb.classList.toggle("solid", scrollY > 12); }, {passive: true});
    const p = $("#ptr"); if (!p || !refresh) return;
    let y0 = null, dy = 0, busy = false;   // pull to refresh
    addEventListener("touchstart", e => { if (scrollY > 0 || open || busy || e.target.closest(".hc")) return; y0 = e.touches[0].clientY; dy = 0; }, {passive: true});
    addEventListener("touchmove", e => { if (y0 == null) return; dy = Math.min(120, Math.max(0, e.touches[0].clientY - y0)); p.style.transition = "none"; p.style.transform = `translate(-50%, ${dy - 60}px) rotate(${dy * 3}deg)`; }, {passive: true});
    addEventListener("touchend", async () => {
      if (y0 == null) return; y0 = null; p.style.transition = "";
      if (dy > 75 && !busy) { busy = true; buzz(10); p.style.transform = "translate(-50%, 30px)"; p.classList.add("spin"); await refresh(); await new Promise(r => setTimeout(r, 400)); p.classList.remove("spin"); busy = false; }
      p.style.transform = "";
    });
  }

  return {$, $$, buzz, store, toast, sheet, close, isOpen, wireSheets, odo, flash, chip, ARROW_UP, ARROW_DN, draw, scrub, window: window_, avatar, avColor, parsePerp, changeCls, IC, classify, classifyBook, dayLabel, feed, chrome};
})();
