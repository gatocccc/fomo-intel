// Odds traffic light, shared by the landing and the user dashboard.
window.Semaforo = (() => {
  const fmtX = v => "x" + Number(v).toFixed(v >= 10 ? 0 : (v < 1.1 ? 2 : 1));
  const pct = v => Math.round(v * 100) + "%";

  function render(d, box, note, selected, onPick) {
    box.innerHTML = "";
    let prelim = false;
    d.planes.forEach(p => {
      prelim = prelim || p.preliminar;
      const b = document.createElement("button");
      b.type = "button"; b.className = "plan"; b.setAttribute("aria-pressed", selected === p.plan);
      const out = p.prob_objetivo < 0.01;
      const sug = p.color === "red" && p.objetivo_sugerido ? ` · with this plan, ${fmtX(p.objetivo_sugerido)} is more realistic` : "";
      const line = out
        ? `This table is not built for that goal${p.objetivo_sugerido ? `: it aims for up to ${fmtX(p.objetivo_sugerido)} in this time` : ""}. Pick a louder table.`
        : `Lose half: ${pct(p.prob_perder_mitad)} · most likely: ${fmtX(p.mediana)}${sug}`;
      b.innerHTML = `<span class="light ${p.color}" aria-hidden="true"></span>
        <span><b></b><small></small><small class="ln"></small></span>
        <span class="pct">${out ? "Out of range" : pct(p.prob_objetivo)}<small>${out ? "for this table" : "to get there"}</small></span>`;
      b.querySelector(".ln").textContent = line;
      if (out) b.querySelector(".pct").classList.add("off");
      b.querySelector("b").textContent = p.nombre;
      b.querySelector("small").textContent = p.mercados;
      b.setAttribute("aria-label", out ? `${p.nombre}: out of range for this goal` : `${p.nombre}: ${pct(p.prob_objetivo)} to get there, ${p.color} light, ${pct(p.prob_perder_mitad)} to lose half`);
      b.onclick = () => onPick && onPick(p.plan);
      box.appendChild(b);
    });
    const n = d.planes.map(p => p.ops_reales).reduce((a, b) => a + b, 0);
    note.textContent = prelim
      ? `Preliminary estimate: ${n} real trades so far plus starting assumptions. It recalculates itself as the bot trades.`
      : `Based on ${n} real trades.`;
  }

  function mount({goal, days, goalOut, daysOut, box, note, selected = "", onPick, onChange}) {
    let t, seq = 0, last = null, sel = selected;
    const pick = plan => { sel = plan; if (last) render(last, box, note, sel, pick); onPick && onPick(plan); };
    const update = () => {
      const o = +goal.value, d = +days.value;
      if (goalOut) goalOut.textContent = fmtX(o);
      if (daysOut) daysOut.textContent = d + " days";
      onChange && onChange(o, d);
      clearTimeout(t);
      const id = ++seq;
      t = setTimeout(() => fetch(`/api/semaforo?objetivo=${o}&dias=${d}`).then(r => r.json())
        .then(x => { if (id !== seq) return; last = x; render(x, box, note, sel, pick); })
        .catch(() => note.textContent = "We could not calculate right now. Try again in a moment."), 180);
    };
    goal.addEventListener("input", update); days.addEventListener("input", update); update();
    return {refresh: update, select: pick};
  }
  return {mount, fmtX, pct};
})();
