/** Laboratorio de voz: presets Qwen + clonación con micrófono (WAV). */

function encodeWav(samples, sampleRate) {
  const numChannels = 1;
  const bitsPerSample = 16;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  const writeStr = (offset, str) => {
    for (let i = 0; i < str.length; i += 1) view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function mergeChannels(buffers, length) {
  const result = new Float32Array(length);
  let offset = 0;
  for (const chunk of buffers) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function labelForActive(active, clones = []) {
  if (!active) return "—";
  if (active.mode === "clone" && active.clone_id) {
    const clone = clones.find((item) => item.id === active.clone_id);
    const name = clone?.name || active.clone_id;
    return `${name}`;
  }
  return `preset ${active.preset_id || "Serena"}`;
}

export function mountVoiceLab(root, { onStatus } = {}) {
  const els = {
    status: root.querySelector("[data-voice-status]"),
    toggle: root.querySelector("#voice-clone-toggle"),
    cloneCount: root.querySelector("[data-clone-count]"),
    presetSelect: root.querySelector("#voice-preset"),
    activatePreset: root.querySelector("#voice-activate-preset"),
    clonePanel: root.querySelector("[data-clone-panel]"),
    name: root.querySelector("#voice-name"),
    transcript: root.querySelector("#voice-transcript"),
    recordBtn: root.querySelector("#voice-record"),
    stopBtn: root.querySelector("#voice-stop"),
    playBtn: root.querySelector("#voice-play"),
    saveBtn: root.querySelector("#voice-save"),
    meter: root.querySelector("#voice-meter"),
    timer: root.querySelector("#voice-timer"),
    clones: root.querySelector("#voice-clones"),
    activeLabel: root.querySelector("#voice-active"),
    hint: root.querySelector("#voice-hint"),
  };

  let state = {
    payload: null,
    selection: null,
    expanded: false,
    locked: false,
    recording: false,
    startedAt: 0,
    timerId: 0,
    stream: null,
    context: null,
    processor: null,
    source: null,
    chunks: [],
    length: 0,
    sampleRate: 48000,
    blob: null,
    objectUrl: null,
    previewAudio: null,
    selecting: false,
  };

  const setStatus = (text) => {
    if (els.status) els.status.textContent = text;
    onStatus?.(text);
  };

  const stopPreview = () => {
    if (!state.previewAudio) return;
    state.previewAudio.pause();
    state.previewAudio = null;
  };

  const playUrl = (url, label) => {
    stopPreview();
    const audio = new Audio(url);
    state.previewAudio = audio;
    setStatus(`Reproduciendo ${label}…`);
    audio.play().catch(() => setStatus(`No se pudo reproducir ${label}`));
    audio.onended = () => {
      if (state.previewAudio === audio) state.previewAudio = null;
      setStatus("Listo.");
    };
  };

  const setExpanded = (open) => {
    state.expanded = Boolean(open);
    if (els.toggle) els.toggle.setAttribute("aria-expanded", state.expanded ? "true" : "false");
    if (els.clonePanel) {
      els.clonePanel.hidden = !state.expanded;
      els.clonePanel.classList.toggle("is-collapsed", !state.expanded);
    }
  };

  const renderActive = (active, clones = []) => {
    state.selection = active || null;
    if (!els.activeLabel) return;
    const label = labelForActive(active, clones);
    els.activeLabel.textContent =
      active?.mode === "clone" ? `Tu voz: ${label}` : `Para la llamada: ${label}`;
    els.activeLabel.classList.toggle("is-mine", active?.mode === "clone");
    const presetPanel = root.querySelector("[data-preset-panel]");
    presetPanel?.classList.toggle("is-dimmed", active?.mode === "clone");
  };

  const renderCloneCount = (clones) => {
    if (!els.cloneCount) return;
    const n = clones?.length || 0;
    els.cloneCount.textContent = n === 1 ? "1 guardada" : `${n} guardadas`;
  };

  const renderClones = (clones, active) => {
    if (!els.clones) return;
    els.clones.replaceChildren();
    if (!clones?.length) {
      const empty = document.createElement("p");
      empty.className = "voice-empty";
      empty.textContent = "Todavía no hay voces tuyas. Grabá una abajo.";
      els.clones.appendChild(empty);
      return;
    }
    for (const clone of clones) {
      const row = document.createElement("div");
      const isActive = active?.mode === "clone" && active?.clone_id === clone.id;
      row.className = `voice-clone-row${isActive ? " is-active" : ""}`;
      row.innerHTML = `
        <button type="button" class="voice-clone-select" data-select="${escapeHtml(clone.id)}" aria-pressed="${isActive ? "true" : "false"}">
          <strong>${escapeHtml(clone.name)}</strong>
          <span>${clone.duration_s ? `${clone.duration_s}s` : "—"} · ${escapeHtml(clone.id)}</span>
        </button>
        <div class="voice-clone-actions">
          <button type="button" data-play="${escapeHtml(clone.id)}">probar</button>
          <button type="button" data-select="${escapeHtml(clone.id)}" ${isActive ? "disabled" : ""}>
            ${isActive ? "elegida" : "elegir"}
          </button>
        </div>
      `;
      els.clones.appendChild(row);
    }
  };

  const renderPresets = (presets, active) => {
    if (!els.presetSelect) return;
    els.presetSelect.replaceChildren();
    for (const preset of presets || []) {
      const option = document.createElement("option");
      option.value = preset.id;
      option.textContent = `${preset.id}${preset.recommended ? " · recomendada" : ""}`;
      els.presetSelect.appendChild(option);
    }
    if (active?.mode === "preset" && active?.preset_id) {
      els.presetSelect.value = active.preset_id;
    } else if (presets?.length) {
      // Clone activo: no fingir que un preset está elegido.
      els.presetSelect.selectedIndex = -1;
    }
  };

  async function refresh() {
    const response = await fetch("/api/studio/voices");
    if (!response.ok) throw new Error("No se pudieron cargar las voces");
    const data = await response.json();
    state.payload = data;
    if (els.hint && data.reference_hint && els.transcript && !els.transcript.value) {
      els.transcript.value = data.reference_hint;
      els.hint.textContent = data.reference_hint;
    }
    renderPresets(data.presets, data.active);
    renderClones(data.clones, data.active);
    renderCloneCount(data.clones);
    renderActive(data.active, data.clones);
    return data;
  }

  function selectionPayload() {
    if (state.selection?.mode === "clone" && state.selection.clone_id) {
      return {
        engine: "qwen-mlx",
        mode: "clone",
        clone_id: state.selection.clone_id,
      };
    }
    return {
      engine: "qwen-mlx",
      mode: "preset",
      preset_id: els.presetSelect?.value || state.selection?.preset_id || "Serena",
    };
  }

  async function selectVoice(payload, { quiet = false } = {}) {
    if (state.locked || document.body.classList.contains("is-live")) {
      setStatus("Durante la llamada la voz queda fija. Cortá el enlace para cambiarla.");
      return null;
    }
    if (state.selecting) return null;
    state.selecting = true;
    if (!quiet) setStatus("Guardando voz elegida…");
    try {
      const response = await fetch("/api/studio/voices/activate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || "No se pudo elegir la voz");
      }
      await refresh();
      if (!quiet) {
        const clones = state.payload?.clones || [];
        setStatus(
          data.active?.mode === "clone"
            ? `«${labelForActive(data.active, clones)}» elegida. Iniciá la llamada.`
            : `Preset ${labelForActive(data.active, clones)} listo. Iniciá la llamada.`
        );
      }
      return data;
    } finally {
      state.selecting = false;
    }
  }

  async function selectPreset() {
    const preset_id = els.presetSelect?.value;
    if (!preset_id) {
      setStatus("Elegí un preset de la lista.");
      return null;
    }
    return selectVoice({ engine: "qwen-mlx", mode: "preset", preset_id });
  }

  async function selectClone(cloneId) {
    return selectVoice({ engine: "qwen-mlx", mode: "clone", clone_id: cloneId });
  }

  /** Guarda la selección actual y aplica la voz al bot antes de WebRTC. */
  async function prepareForCall({ onProgress } = {}) {
    const payload = selectionPayload();
    onProgress?.("Guardando voz elegida…");
    const activate = await fetch("/api/studio/voices/activate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const activateData = await activate.json().catch(() => ({}));
    if (!activate.ok || activateData.ok === false) {
      throw new Error(activateData.error || "No se pudo guardar la voz");
    }
    await refresh();

    onProgress?.(`Aplicando ${labelForActive(activateData.active)} al bot…`);
    const ensure = await fetch("/api/studio/voices/ensure", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    const ensureData = await ensure.json().catch(() => ({}));
    if (!ensure.ok || ensureData.ok === false) {
      throw new Error(ensureData.error || "No se pudo aplicar la voz al bot");
    }

    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      const statusRes = await fetch("/api/studio/status");
      const status = await statusRes.json().catch(() => ({}));
      if (status.ready) {
        onProgress?.(`Voz ${labelForActive(ensureData.active)} lista.`);
        return { active: ensureData.active, status };
      }
      onProgress?.(
        status.starting
          ? "Cargando modelos (puede tardar)…"
          : "Esperando que el bot quede listo…"
      );
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    throw new Error("El bot no quedó listo a tiempo con la voz elegida");
  }

  function clearCapture() {
    window.clearInterval(state.timerId);
    state.processor?.disconnect();
    state.source?.disconnect();
    state.context?.close().catch(() => {});
    state.stream?.getTracks().forEach((track) => track.stop());
    state.processor = null;
    state.source = null;
    state.context = null;
    state.stream = null;
    state.recording = false;
    if (els.recordBtn) els.recordBtn.disabled = false;
    if (els.stopBtn) els.stopBtn.disabled = true;
    if (els.meter) els.meter.style.setProperty("--level", "0%");
  }

  async function startRecording() {
    if (state.recording) return;
    setStatus("Pedí permiso de micrófono…");
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        channelCount: 1,
      },
    });
    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    state.chunks = [];
    state.length = 0;
    state.sampleRate = context.sampleRate;
    state.blob = null;
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = null;
    if (els.playBtn) els.playBtn.disabled = true;
    if (els.saveBtn) els.saveBtn.disabled = true;

    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      state.chunks.push(new Float32Array(input));
      state.length += input.length;
      let sum = 0;
      for (let i = 0; i < input.length; i += 1) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);
      const level = Math.min(100, Math.round(rms * 280));
      if (els.meter) els.meter.style.setProperty("--level", `${level}%`);
    };

    source.connect(processor);
    processor.connect(context.destination);
    state.stream = stream;
    state.context = context;
    state.source = source;
    state.processor = processor;
    state.recording = true;
    state.startedAt = performance.now();
    if (els.recordBtn) els.recordBtn.disabled = true;
    if (els.stopBtn) els.stopBtn.disabled = false;
    state.timerId = window.setInterval(() => {
      const secs = Math.floor((performance.now() - state.startedAt) / 1000);
      if (els.timer) els.timer.textContent = `${secs}s`;
      if (secs >= 25) stopRecording();
    }, 200);
    setStatus("Grabando… leé la transcripción en voz clara (8–20 s).");
  }

  function stopRecording() {
    if (!state.recording) return;
    const samples = mergeChannels(state.chunks, state.length);
    clearCapture();
    if (samples.length < state.sampleRate * 2) {
      setStatus("Muy corto. Grabá al menos 2 segundos.");
      return;
    }
    state.blob = encodeWav(samples, state.sampleRate);
    state.objectUrl = URL.createObjectURL(state.blob);
    if (els.playBtn) els.playBtn.disabled = false;
    if (els.saveBtn) els.saveBtn.disabled = false;
    const secs = (samples.length / state.sampleRate).toFixed(1);
    if (els.timer) els.timer.textContent = `${secs}s`;
    setStatus(`Listo (${secs}s). Probá la toma y guardá para clonar.`);
  }

  async function saveClone() {
    if (!state.blob) {
      setStatus("Primero grabá un audio.");
      return;
    }
    const name = els.name?.value?.trim() || "mi-voz";
    const reference_text = els.transcript?.value?.trim() || "";
    const form = new FormData();
    form.append("name", name);
    form.append("reference_text", reference_text);
    form.append("activate", "1");
    form.append("audio", state.blob, `${name}.wav`);
    setStatus("Guardando clone…");
    if (els.saveBtn) els.saveBtn.disabled = true;
    try {
      const response = await fetch("/api/studio/voices/clone", {
        method: "POST",
        body: form,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || "No se pudo guardar");
      }
      await refresh();
      setExpanded(true);
      const label = data.clone?.name || name;
      setStatus(
        `Voz «${label}» elegida. Iniciá la llamada para oírla.`
      );
    } finally {
      if (els.saveBtn) els.saveBtn.disabled = !state.blob;
    }
  }

  els.toggle?.addEventListener("click", () => {
    setExpanded(!state.expanded);
  });
  els.activatePreset?.addEventListener("click", () => {
    selectPreset().catch((error) => setStatus(error.message || "Error"));
  });
  // Solo el botón aplica preset; el change del select no pisa tu clone por accidente.
  els.recordBtn?.addEventListener("click", () => {
    startRecording().catch((error) => setStatus(error.message || "Sin micrófono"));
  });
  els.stopBtn?.addEventListener("click", stopRecording);
  els.playBtn?.addEventListener("click", () => {
    if (!state.objectUrl) return;
    playUrl(state.objectUrl, "la toma");
  });
  els.saveBtn?.addEventListener("click", () => {
    saveClone().catch((error) => setStatus(error.message || "Error al guardar"));
  });
  els.clones?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const playEl = target.closest("[data-play]");
    if (playEl instanceof HTMLElement) {
      const playId = playEl.getAttribute("data-play");
      if (playId) {
        playUrl(`/api/studio/voices/clones/${encodeURIComponent(playId)}/audio`, `«${playId}»`);
      }
      return;
    }
    const selectEl = target.closest("[data-select]");
    if (selectEl instanceof HTMLElement && !selectEl.disabled) {
      const cloneId = selectEl.getAttribute("data-select");
      if (cloneId) {
        selectClone(cloneId).catch((error) => setStatus(error.message || "Error"));
      }
    }
  });

  if (els.stopBtn) els.stopBtn.disabled = true;
  if (els.playBtn) els.playBtn.disabled = true;
  if (els.saveBtn) els.saveBtn.disabled = true;
  setExpanded(false);

  return {
    refresh,
    prepareForCall,
    getSelection: () => state.selection,
    setCallLocked(locked) {
      state.locked = Boolean(locked);
      root.classList.toggle("is-call-locked", state.locked);
      if (els.activatePreset) els.activatePreset.disabled = state.locked;
      if (els.presetSelect) els.presetSelect.disabled = state.locked;
      if (els.saveBtn) els.saveBtn.disabled = state.locked || !state.blob;
      if (state.locked) {
        setStatus("Llamada en curso: voz fija. No se puede cambiar hasta cortar.");
      }
    },
    dispose: () => {
      stopPreview();
      clearCapture();
    },
  };
}
