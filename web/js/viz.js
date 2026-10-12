/**
 * Panel de visualizaciones del Studio (Datos en vivo).
 *
 * Renderiza specs tipadas que llegan por el data channel:
 *   { type: "visualization", message, visualization: {...} }
 *
 * Seguridad:
 * - Whitelist de chart_type (line | bar | ring | table | kpi).
 * - Todo texto entra por textContent; NUNCA innerHTML ni eval: un campo
 *   malicioso del modelo no puede ejecutar código en el frontend.
 * - SVG construido con createElementNS; tooltips con <title> nativo.
 * - Update in-place por id estable: una pregunta de seguimiento reemplaza
 *   el contenido del mismo panel sin perder el historial de la conversación.
 */

const ALLOWED_CHARTS = new Set(["line", "bar", "ring", "table", "kpi"]);
const NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, String(value));
  }
  if (text != null) node.textContent = text;
  return node;
}

function svgEl(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, String(value));
  }
  if (text != null) node.textContent = text;
  return node;
}

function fmtNumber(value) {
  return Number(value).toLocaleString("es-MX", { maximumFractionDigits: 0 });
}

function fmtMoney(value) {
  return `$${fmtNumber(value)}`;
}

function clearHost(panel) {
  const host = panel.querySelector("[data-viz-body]");
  if (host) host.replaceChildren();
  return host;
}

/* ---------- charts ---------- */

function renderLine(spec, host) {
  const data = spec.data || [];
  const series = spec.series || [];
  const width = 300;
  const height = 150;
  const pad = { top: 12, right: 10, bottom: 22, left: 44 };
  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "viz-svg",
    role: "img",
  });

  let min = Infinity;
  let max = -Infinity;
  for (const row of data) {
    for (const s of series) {
      const value = Number(row[s.field]);
      if (Number.isFinite(value)) {
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
    }
  }
  if (!Number.isFinite(min)) return;
  if (min === max) {
    min -= 1;
    max += 1;
  }

  const xAt = (index) =>
    pad.left +
    (index / Math.max(data.length - 1, 1)) * (width - pad.left - pad.right);
  const yAt = (value) =>
    height - pad.bottom - ((value - min) / (max - min)) * (height - pad.top - pad.bottom);

  // Grid sutil: 3 líneas horizontales con etiquetas numéricas.
  for (let i = 0; i <= 2; i += 1) {
    const value = min + ((max - min) * i) / 2;
    const y = yAt(value);
    svg.appendChild(
      svgEl("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: "viz-grid" })
    );
    svg.appendChild(
      svgEl("text", { x: pad.left - 6, y: y + 3, class: "viz-tick", "text-anchor": "end" }, fmtNumber(value))
    );
  }

  // Eje X: primera y última fecha.
  if (data.length) {
    svg.appendChild(
      svgEl("text", { x: pad.left, y: height - 6, class: "viz-tick" }, String(data[0].date).slice(5))
    );
    svg.appendChild(
      svgEl(
        "text",
        { x: width - pad.right, y: height - 6, class: "viz-tick", "text-anchor": "end" },
        String(data[data.length - 1].date).slice(5)
      )
    );
  }

  const palette = ["#6c5ce7", "#00b894", "#0984e3"];
  series.forEach((s, seriesIndex) => {
    const points = data
      .map((row, index) => {
        const value = Number(row[s.field]);
        if (!Number.isFinite(value)) return null;
        return `${xAt(index)},${yAt(value)}`;
      })
      .filter(Boolean)
      .join(" ");
    const polyline = svgEl("polyline", {
      points,
      fill: "none",
      stroke: palette[seriesIndex % palette.length],
      "stroke-width": "1.6",
      "stroke-linejoin": "round",
    });
    svg.appendChild(polyline);

    // Un nodo por punto con tooltip nativo (un detalle por nodo, editable).
    data.forEach((row, index) => {
      const value = Number(row[s.field]);
      if (!Number.isFinite(value)) return;
      const dot = svgEl("circle", {
        cx: xAt(index),
        cy: yAt(value),
        r: "2.2",
        class: "viz-dot",
      });
      const tip = svgEl("title", {}, `${s.label}: ${fmtMoney(value)} · ${row.date}`);
      dot.appendChild(tip);
      svg.appendChild(dot);
    });
  });

  host.appendChild(svg);
  const legend = el("div", { class: "viz-legend" });
  series.forEach((s, i) => {
    const item = el("span", { class: "viz-legend-item" });
    const swatch = el("span", { class: "viz-swatch", style: `background:${palette[i % palette.length]}` });
    item.appendChild(swatch);
    item.appendChild(el("span", {}, s.label));
    legend.appendChild(item);
  });
  host.appendChild(legend);
}

function renderBar(spec, host) {
  const labels = spec.labels || [];
  const values = spec.values || [];
  const width = 300;
  const height = 150;
  const pad = { top: 12, right: 10, bottom: 26, left: 48 };
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "viz-svg", role: "img" });
  const max = Math.max(...values.map(Number), 1);
  const slot = (width - pad.left - pad.right) / Math.max(values.length, 1);
  const barWidth = Math.min(slot * 0.55, 64);

  values.forEach((value, index) => {
    const h = ((Number(value) / max) * (height - pad.top - pad.bottom)) || 0;
    const x = pad.left + index * slot + (slot - barWidth) / 2;
    const y = height - pad.bottom - h;
    const rect = svgEl("rect", { x, y, width: barWidth, height: Math.max(h, 1), class: "viz-bar" });
    rect.appendChild(svgEl("title", {}, `${labels[index] || ""}: ${fmtMoney(value)}`));
    svg.appendChild(rect);
    svg.appendChild(
      svgEl(
        "text",
        { x: x + barWidth / 2, y: height - 8, class: "viz-tick", "text-anchor": "middle" },
        labels[index] || ""
      )
    );
  });

  [0, max / 2, max].forEach((value) => {
    const y = height - pad.bottom - (value / max) * (height - pad.top - pad.bottom);
    svg.appendChild(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: "viz-grid" }));
    svg.appendChild(
      svgEl("text", { x: pad.left - 6, y: y + 3, class: "viz-tick", "text-anchor": "end" }, fmtNumber(value))
    );
  });

  host.appendChild(svg);
}

function renderRing(spec, host) {
  const labels = spec.labels || [];
  const values = spec.values || [];
  const total = values.reduce((acc, v) => acc + Number(v), 0);
  if (total <= 0) return;
  const size = 150;
  const radius = 56;
  const stroke = 22;
  const cx = size / 2;
  const cy = size / 2;
  const svg = svgEl("svg", { viewBox: `0 0 ${size} ${size}`, class: "viz-svg viz-ring", role: "img" });
  const palette = ["#6c5ce7", "#00b894", "#0984e3", "#fdcb6e", "#e17055", "#636e72"];
  let offset = 0;
  values.forEach((value, index) => {
    const fraction = Number(value) / total;
    const circle = svgEl("circle", {
      cx,
      cy,
      r: radius,
      fill: "none",
      stroke: palette[index % palette.length],
      "stroke-width": stroke,
      "stroke-dasharray": `${(fraction * 2 * Math.PI * radius).toFixed(2)} ${(2 * Math.PI * radius).toFixed(2)}`,
      "stroke-dashoffset": (-offset * 2 * Math.PI * radius).toFixed(2),
      transform: `rotate(-90 ${cx} ${cy})`,
    });
    circle.appendChild(
      svgEl("title", {}, `${labels[index] || ""}: ${fmtMoney(value)} (${Math.round(fraction * 100)}%)`)
    );
    svg.appendChild(circle);
    offset += fraction;
  });
  svg.appendChild(
    svgEl("text", { x: cx, y: cy + 4, class: "viz-ring-total", "text-anchor": "middle" }, fmtMoney(total))
  );
  host.appendChild(svg);
  const legend = el("div", { class: "viz-legend" });
  labels.forEach((label, index) => {
    const item = el("span", { class: "viz-legend-item" });
    item.appendChild(
      el("span", { class: "viz-swatch", style: `background:${palette[index % palette.length]}` })
    );
    const pct = Math.round((Number(values[index]) / total) * 100);
    item.appendChild(el("span", {}, `${label} · ${pct}%`));
    legend.appendChild(item);
  });
  host.appendChild(legend);
}

function renderTable(spec, host) {
  const table = el("table", { class: "viz-table" });
  const thead = el("thead");
  const headRow = el("tr");
  (spec.headers || []).forEach((header) => headRow.appendChild(el("th", {}, header)));
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = el("tbody");
  (spec.rows || []).forEach((row) => {
    const tr = el("tr");
    row.forEach((cell, index) => {
      const isNumber = typeof cell === "number";
      const td = el("td", {}, isNumber ? fmtMoney(cell) : cell);
      if (isNumber) td.className = "is-number";
      if (index === row.length - 1) td.className = `${td.className} viz-status`.trim();
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}

function renderKpi(spec, host) {
  const values = spec.values || [];
  const labels = spec.labels || [];
  const wrap = el("div", { class: "viz-kpi-row" });
  labels.forEach((label, index) => {
    const card = el("div", { class: "viz-kpi" });
    card.appendChild(el("p", { class: "viz-kpi-label" }, label));
    card.appendChild(
      el("p", { class: "viz-kpi-value" }, `${spec.unit === "MXN" ? "" : ""}${fmtNumber(values[index] ?? 0)}`)
    );
    wrap.appendChild(card);
  });
  host.appendChild(wrap);
}

const RENDERERS = {
  line: renderLine,
  bar: renderBar,
  ring: renderRing,
  table: renderTable,
  kpi: renderKpi,
};

/* ---------- panel ---------- */

export function createViz(panel, { sendText } = {}) {
  if (!panel) return null;
  const placeholder = panel.querySelector("[data-viz-empty]");

  const showEmpty = (text) => {
    const empty = panel.querySelector("[data-viz-empty]");
    if (empty) {
      empty.textContent = text;
      empty.hidden = false;
    }
    const host = clearHost(panel);
    const title = panel.querySelector("[data-viz-message]");
    if (title) title.textContent = "";
  };

  return {
    apply(message) {
      if (!message || typeof message !== "object") return;

      // Estados de datos: consultando / vacío / error llegan como insight status.
      if (message.type === "insight_status") {
        if (message.state === "querying") {
          showEmpty("Consultando datos…");
        }
        return;
      }
      if (message.type !== "visualization") return;

      const spec = message.visualization;
      if (!spec || !ALLOWED_CHARTS.has(spec.chart_type)) {
        // Estado visible SIN destruir las visualizaciones ya renderizadas.
        const empty = panel.querySelector("[data-viz-empty]");
        if (empty) {
          empty.textContent = "Visualización no soportada; se ignoró el mensaje.";
          empty.hidden = false;
        }
        return;
      }
      const renderer = RENDERERS[spec.chart_type];
      if (!renderer) return;

      const empty = panel.querySelector("[data-viz-empty]");
      if (empty) empty.hidden = true;
      const messageEl = panel.querySelector("[data-viz-message]");
      if (messageEl) messageEl.textContent = String(message.message || "");

      // Update in-place: mismo id → mismo panel.
      const cssEscape = globalThis.CSS?.escape ?? ((s) => s);
      let target = panel.querySelector(`[data-viz-id="${cssEscape(spec.id)}"]`);
      if (!target) {
        target = el("div", { class: "viz-card", "data-viz-id": spec.id });
        const body = panel.querySelector("[data-viz-body]");
        if (body) body.appendChild(target);
      }
      target.replaceChildren();

      target.appendChild(el("h3", { class: "viz-title" }, spec.title || ""));
      const host = el("div", { class: "viz-host" });
      target.appendChild(host);
      try {
        renderer(spec, host);
      } catch (error) {
        host.replaceChildren();
        host.appendChild(el("p", { class: "viz-error" }, "No se pudo dibujar el gráfico."));
        return;
      }
      if (spec.unit) target.appendChild(el("p", { class: "viz-unit" }, `Unidad: ${spec.unit}`));

      // Filtros gráficos de período: reutilizan el canal de texto del agente,
      // así el contexto conversacional se mantiene (misma llamada, mismas tools).
      if (sendText && spec.id === "recovery-trend") {
        const filters = el("div", { class: "viz-filters" });
        const options = [
          ["este_mes", "Este mes"],
          ["ultima_semana", "Última semana"],
          ["mes_anterior", "Mes anterior"],
          ["ultimos_3_meses", "Últimos 3 meses"],
        ];
        for (const [period, label] of options) {
          const button = el("button", { type: "button", class: "viz-filter" }, label);
          button.addEventListener("click", () => {
            sendText(`Mostrame el recupero de ${label.toLowerCase()}`);
          });
          filters.appendChild(button);
        }
        target.appendChild(filters);
      }
    },
    reset() {
      showEmpty("Sin visualizaciones todavía.");
      const body = panel.querySelector("[data-viz-body]");
      if (body) body.replaceChildren();
    },
  };
}