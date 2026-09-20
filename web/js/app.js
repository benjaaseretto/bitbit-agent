import { mountGlobe } from "./globe.js";
import { mountVoice } from "./voice.js";
import { startCall } from "./webrtc.js";
import { createHud } from "./hud.js";

const lobby = document.getElementById("lobby");
const hudEl = document.getElementById("hud");
const flowSelect = document.getElementById("flow-select");
const connectBtn = document.getElementById("connect-btn");
const hangupBtn = document.getElementById("hangup-btn");
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

try {
  globe = mountGlobe(globeHost, { ambient: false });
} catch (error) {
  lobbyStatus.textContent = "El globo 3D no pudo cargar; el enlace de voz sigue disponible.";
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
  } catch {
    const option = document.createElement("option");
    option.value = "clinica_vida_flow";
    option.textContent = "clinica_vida_flow";
    flowSelect.appendChild(option);
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
    connectBtn.disabled = false;
  }
}

function hangup() {
  window.clearInterval(statsTimer);
  call?.hangup();
  call = null;
  leaveHud();
  connectBtn.disabled = false;
  lobbyStatus.textContent = "Enlace cortado.";
}

connectBtn.addEventListener("click", connect);
hangupBtn.addEventListener("click", hangup);
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

loadFlows();
