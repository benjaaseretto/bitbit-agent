async function waitForIce(pc, timeoutMs = 1800) {
  if (pc.iceGatheringState === "complete") return;
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    const check = () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", check);
  });
}

export async function startCall({ flowKey, onMessage, onTrack, onState }) {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  const dc = pc.createDataChannel("pipecat", { ordered: true });
  let pingTimer = 0;

  dc.addEventListener("open", () => {
    pingTimer = window.setInterval(() => {
      if (dc.readyState === "open") dc.send("ping");
    }, 4000);
  });
  dc.addEventListener("message", (event) => {
    if (typeof event.data !== "string" || event.data.startsWith("ping")) return;
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      /* ignore non-JSON control frames */
    }
  });

  pc.addEventListener("track", (event) => {
    onTrack(event.streams[0] || new MediaStream([event.track]));
  });
  pc.addEventListener("connectionstatechange", () => {
    onState(pc.connectionState);
  });

  const local = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
    video: false,
  });
  for (const track of local.getTracks()) pc.addTrack(track, local);

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitForIce(pc);

  const response = await fetch("/api/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
      request_data: { flow_key: flowKey },
    }),
  });
  if (!response.ok) {
    local.getTracks().forEach((track) => track.stop());
    pc.close();
    throw new Error(`Offer failed (${response.status})`);
  }
  const answer = await response.json();
  await pc.setRemoteDescription(answer);

  return {
    pc,
    dc,
    local,
    pcId: answer.pc_id || "",
    async sendText(text) {
      if (dc.readyState !== "open") return;
      dc.send(JSON.stringify({ type: "user_text", text }));
    },
    async stats() {
      const report = await pc.getStats();
      let rtt = null;
      report.forEach((item) => {
        if (item.type === "candidate-pair" && item.state === "succeeded" && item.currentRoundTripTime != null) {
          rtt = Math.round(item.currentRoundTripTime * 1000);
        }
      });
      return { rtt };
    },
    hangup() {
      window.clearInterval(pingTimer);
      local.getTracks().forEach((track) => track.stop());
      pc.close();
    },
  };
}
