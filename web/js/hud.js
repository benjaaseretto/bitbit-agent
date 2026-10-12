function sparkline(canvas, values, color) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!values.length) return;
  const max = Math.max(...values, 1);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * (w - 8) + 4;
    const y = h - 6 - (value / max) * (h - 14);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

const BUBBLE_MAX = 320;

function displayText(text) {
  const raw = String(text || "").replace(/\s+/g, " ").trim();
  if (raw.length <= BUBBLE_MAX) return raw;
  return `${raw.slice(0, BUBBLE_MAX).trim()}…`;
}

function appendBubble(list, text, { ai = false, streaming = false } = {}) {
  const shown = displayText(text);
  if (!shown) return;
  let item = list.querySelector("[data-stream='1']");
  if (streaming) {
    if (!item) {
      item = document.createElement("li");
      item.className = `bubble${ai ? " is-ai" : ""} is-stream`;
      item.dataset.stream = "1";
      list.appendChild(item);
    }
    item.textContent = shown;
    list.scrollTop = list.scrollHeight;
    return;
  }
  if (item) item.remove();
  const li = document.createElement("li");
  li.className = `bubble${ai ? " is-ai" : ""}`;
  li.textContent = shown;
  list.appendChild(li);
  list.scrollTop = list.scrollHeight;
}

export function createHud(els) {
  const latencySeries = [];
  const tokenSeries = [];

  const setText = (node, value) => {
    if (node) node.textContent = value;
  };

  return {
    apply(message) {
      if (!message || typeof message !== "object") return;
      if (message.type === "session") {
        setText(els.sessionId, message.session_id || "—");
        setText(els.convStatus, message.status || "ACTIVE");
        setText(els.flow, message.flow_key || "—");
        setText(els.phase, message.phase || "identity");
      }
      if (message.type === "phase") setText(els.phase, message.phase || "—");
      if (message.type === "status") {
        if (message.listening != null) {
          setText(els.pillUser, message.listening ? "ESCUCHANDO" : "SILENCIO");
        }
        if (message.generating) setText(els.pillBot, "GENERANDO");
        else if (message.speaking) setText(els.pillBot, "AUDIO ACTIVO");
        else if (message.speaking === false || message.generating === false) {
          setText(els.pillBot, "EN ESPERA");
        }
        if (message.latency_total_ms != null) {
          setText(els.total, `${message.latency_total_ms}ms`);
          latencySeries.push(message.latency_total_ms);
          if (latencySeries.length > 28) latencySeries.shift();
          sparkline(els.chartLatency, latencySeries, "#0a0a0a");
        }
        const live = [];
        if (message.listening) live.push("ESCUCHANDO…");
        if (message.generating) live.push("GENERANDO…");
        if (message.speaking) live.push("BITBIT HABLA");
        setText(els.live, live.join("  ·  ") || "ENLACE ACTIVO");
      }
      if (message.type === "transcript") {
        if (message.role === "user") {
          appendBubble(els.userLog, message.text, { streaming: Boolean(message.streaming) });
        } else {
          appendBubble(els.botLog, message.text, {
            ai: true,
            streaming: Boolean(message.streaming),
          });
        }
      }
      if (message.type === "metrics") {
        setText(els.prompt, String(message.tokens_prompt ?? 0));
        setText(els.completion, String(message.tokens_completion ?? 0));
        setText(els.tokens, String(message.tokens_total ?? 0));
        if (message.latency_infer_ms != null) {
          setText(els.infer, `${message.latency_infer_ms}ms`);
          latencySeries.push(message.latency_infer_ms);
          if (latencySeries.length > 28) latencySeries.shift();
          sparkline(els.chartLatency, latencySeries, "#0a0a0a");
        }
        tokenSeries.push(Number(message.tokens_total || 0));
        if (tokenSeries.length > 28) tokenSeries.shift();
        sparkline(els.chartTokens, tokenSeries, "#6b6b6b");
      }
    },
    setRtt(ms) {
      setText(els.rtt, ms == null ? "—" : `${ms}ms`);
    },
    seedPreview() {
      this.apply({
        type: "session",
        session_id: "A1B2C3D4",
        status: "ACTIVE",
        flow_key: "clinica_vida_flow",
        phase: "identity",
      });
      this.apply({
        type: "transcript",
        role: "user",
        text: "Quiero probar el agente conversacional bitbit en tiempo real.",
      });
      this.apply({
        type: "transcript",
        role: "bitbit",
        text: "Hola, soy bitbit. Estoy en el enlace. Decime con quién hablo y seguimos.",
      });
      this.apply({
        type: "metrics",
        tokens_prompt: 289,
        tokens_completion: 412,
        tokens_total: 701,
        latency_infer_ms: 145,
      });
      this.apply({ type: "status", listening: true, latency_total_ms: 173 });
    },
  };
}
