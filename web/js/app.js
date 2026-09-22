import { mountGlobe } from "./globe.js";
import { mountVoice } from "./voice.js";
import { startCall } from "./webrtc.js?v=20260922b";
import { createHud } from "./hud.js";

const lobby = document.getElementById("lobby");
const hudEl = document.getElementById("hud");
const flowSelect = document.getElementById("flow-select");
const connectBtn = document.getElementById("connect-btn");
const startBtn = document.getElementById("start-btn");
const hangupBtn = document.getElementById("hangup-btn");
const shutdownBtn = document.getElementById("shutdown-btn");
const shutdownHudBtn = document.getElementById("shutdown-hud-btn");
const lobbyStatus = document.getElementById("lobby-status");
const remoteAudio = document.getElementById("remote-audio");
const globeHost = document.getElementById("globe-host");
const voiceHost = document.getElementById("voice-host");

const hud = createHud({
  sessionId: document.getElementById("session-id"),
  convStatus: document.getElementById("conv-status"),
  flow: document.getElementById("m-flow"),
  phase: document.getElementById("m-phase"),
  rtt: document.getElementById("m-rtt"),
  infer: document.getElementById("m-infer"),
  total: document.getElementById("m-total"),
  prompt: document.getElementById("m-prompt"),
  completion: document.getElementById("m-completion"),
  tokens: document.getElementById("m-tokens"),
  userLog: document.getElementById("user-log"),
  botLog: document.getElementById("bot-log"),
  pillUser: document.getElementById("pill-user"),
  pillBot: document.getElementById("pill-bot"),
  live: document.getElementById("hud-live"),
  chartLatency: document.getElementById("chart-latency"),
  chartTokens: document.getElementById("chart-tokens"),
});

let globe;
let voice;
let call;
let statsTimer = 0;
let botRunning = false;

try {
  globe = mountGlobe(globeHost, { ambient: false });
} catch (error) {
  lobbyStatus.textContent = "El globo 3D no pudo cargar; el enlace de voz sigue disponible.";
}

function setBotUi(running) {
  botRunning = Boolean(running);
  if (startBtn) startBtn.disabled = botRunning;
  if (shutdownBtn) shutdownBtn.disabled = !botRunning;
  if (shutdownHudBtn) shutdownHudBtn.disabled = !botRunning;
  connectBtn.disabled = !botRunning;
}

async function fetchStatus() {
  const response = await fetch("/api/studio/status");
  if (!response.ok) throw new Error("status");
  return response.json();
}

async function refreshBotStatus() {
  try {
    const status = await fetchStatus();
    setBotUi(status.running);
    if (!status.running) {
      lobbyStatus.textContent = "Bot apagado. Tocá Encender bot.";
    } else if (!call) {
      lobbyStatus.textContent = "Bot encendido. Listo para conectar.";
    }
    return status;
  } catch {
    setBotUi(false);
    lobbyStatus.textContent = "No hay supervisor. Corré scripts/run_local.py.";
    return { running: false };
  }
}

async function loadFlows() {
  try {
    const response = await fetch("/api/studio/config");
    if (!response.ok) throw new Error("config");
    const data = await response.json();
    const flows = data.flows || [];
    flowSelect.replaceChildren();
    for (const flow of flows) {
      const option = document.createElement("option");
      option.value = flow.flow_key;
      option.textContent = flow.visible_name;
      flowSelect.appendChild(option);
    }
    if (data.default_flow_key) {
      flowSelect.value = data.default_flow_key;
    } else {
      const saved = localStorage.getItem("bitbit.flow_key");
      if (saved && [...flowSelect.options].some((opt) => opt.value === saved)) {
        flowSelect.value = saved;
      }
    }
    setBotUi(data.running);
  } catch {
    const option = document.createElement("option");
    option.value = "clinica_vida_flow";
    option.textContent = "clinica_vida_flow";
    flowSelect.appendChild(option);
    setBotUi(false);
  }
}

function enterHud() {
  document.getElementById("user-log").replaceChildren();
  document.getElementById("bot-log").replaceChildren();
  lobby.classList.add("is-hidden");
  hudEl.classList.remove("is-hidden");
  document.body.classList.add("is-live");
  globe?.setAmbient(true);
}

function leaveHud() {
  lobby.classList.remove("is-hidden");
  hudEl.classList.add("is-hidden");
  document.body.classList.remove("is-live");
  globe?.setAmbient(false);
  voice?.dispose();
  voice = null;
}

async function connect() {
  if (!botRunning) {
    lobbyStatus.textContent = "Encendé el bot antes de iniciar el enlace.";
    return;
  }
  connectBtn.disabled = true;
  lobbyStatus.textContent = "Pidiendo micrófono y negociando WebRTC…";
  try {
    enterHud();
    voice = mountVoice(voiceHost);
    call = await startCall({
      flowKey: flowSelect.value,
      onMessage: (payload) => hud.apply(payload),
      onTrack(stream) {
        remoteAudio.srcObject = stream;
        remoteAudio.play().catch(() => {});
        voice?.attachBot(stream);
      },
      onState(state) {
        document.getElementById("conv-status").textContent =
          state === "connected" ? "ACTIVE" : state.toUpperCase();
        if (state === "failed" || state === "disconnected" || state === "closed") {
          lobbyStatus.textContent = `Enlace ${state}.`;
        }
      },
    });
    voice?.attachUser(call.local);
    hud.apply({
      type: "session",
      session_id: call.pcId.slice(0, 12) || "live",
      status: "ACTIVE",
      flow_key: flowSelect.value,
      phase: "identity",
    });
    statsTimer = window.setInterval(async () => {
      const stats = await call.stats();
      hud.setRtt(stats.rtt);
    }, 2000);
    lobbyStatus.textContent = "Enlace activo.";
  } catch (error) {
    leaveHud();
    lobbyStatus.textContent = error.message || "No se pudo abrir el enlace.";
    setBotUi(botRunning);
  }
}

function hangup() {
  window.clearInterval(statsTimer);
  call?.hangup();
  call = null;
  leaveHud();
  setBotUi(botRunning);
  lobbyStatus.textContent = botRunning
    ? "Enlace cortado. Bot sigue encendido."
    : "Enlace cortado.";
}

async function startBot() {
  if (startBtn) startBtn.disabled = true;
  lobbyStatus.textContent = "Encendiendo bot (MLX puede tardar un minuto)…";
  try {
    const response = await fetch("/api/studio/start", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `No se pudo encender (${response.status})`);
    }
    setBotUi(true);
    lobbyStatus.textContent = "Bot encendido. Listo para conectar.";
  } catch (error) {
    setBotUi(false);
    lobbyStatus.textContent = error.message || "Fallo al encender el bot.";
  }
}

async function stopBot() {
  window.clearInterval(statsTimer);
  call?.hangup();
  call = null;
  leaveHud();
  if (shutdownBtn) shutdownBtn.disabled = true;
  if (shutdownHudBtn) shutdownHudBtn.disabled = true;
  lobbyStatus.textContent = "Apagando bot…";
  try {
    await fetch("/api/studio/stop", { method: "POST" });
  } catch {
    /* ok */
  }
  setBotUi(false);
  lobbyStatus.textContent = "Bot apagado. Tocá Encender bot para volver.";
}

connectBtn.addEventListener("click", connect);
hangupBtn.addEventListener("click", hangup);
startBtn?.addEventListener("click", startBot);
shutdownBtn?.addEventListener("click", stopBot);
shutdownHudBtn?.addEventListener("click", stopBot);
flowSelect.addEventListener("change", () => {
  localStorage.setItem("bitbit.flow_key", flowSelect.value);
});
document.getElementById("text-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("text-input");
  const text = input.value.trim();
  if (!text) return;
  call?.sendText(text);
  hud.apply({ type: "transcript", role: "user", text, streaming: false });
  input.value = "";
});

const preview = new URLSearchParams(location.search).has("preview");
if (preview) {
  enterHud();
  hud.seedPreview();
  try {
    voice = mountVoice(voiceHost);
  } catch {
    /* preview still usable without WebGL */
  }
}

loadFlows().then(() => refreshBotStatus());
