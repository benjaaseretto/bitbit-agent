"""Local WebRTC/STT smoke test using a synthetic WAV, never the microphone.

The configured LLM may use its normal API after the synthetic user turn.
"""
import asyncio
import argparse
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]


class SyntheticInput(AudioStreamTrack):
    def __init__(self, path):
        super().__init__()
        with wave.open(str(path)) as wav:
            assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
            rate = wav.getframerate()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        import math
        divisor = math.gcd(rate, 8000)
        self.pcm = resample_poly(samples.astype(float), 8000 // divisor, rate // divisor).astype("<i2").tobytes()
        self.position = 0
        self.enabled = False

    async def recv(self):
        frame = await super().recv()  # paced 8 kHz mono, 20 ms frames
        if self.enabled:
            n = frame.samples * 2
            chunk = self.pcm[self.position:self.position + n]
            self.position += len(chunk)
            frame.planes[0].update(chunk.ljust(n, b"\0"))
        return frame


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--opening-only", action="store_true",
                        help="Receive the scripted opening with silent input; never trigger the LLM.")
    args = parser.parse_args()
    pc = RTCPeerConnection()
    source = AudioStreamTrack() if args.opening_only else SyntheticInput(ROOT / "reports" / "synthetic-user.wav")
    pc.addTrack(source)
    dc = pc.createDataChannel("pipecat")
    stopped = asyncio.Queue()
    spoken = False
    transcripts = 0
    reader = None
    frames = 0
    peak = 0
    response_delay = None
    user_end = None

    @dc.on("message")
    def message(raw):
        nonlocal spoken, transcripts, response_delay
        try:
            item = json.loads(raw)
        except (ValueError, TypeError):
            return
        if item.get("type") == "transcript" and item.get("role") == "user":
            transcripts += 1
        if item.get("speaking") is True:
            spoken = True
            if user_end is not None and response_delay is None:
                response_delay = round((time.monotonic() - user_end) * 1000)
        elif item.get("speaking") is False and spoken:
            spoken = False
            stopped.put_nowait(True)

    @pc.on("track")
    def track_received(track):
        nonlocal reader
        async def receive():
            nonlocal frames, peak
            while True:
                frame = await track.recv()
                peak = max(peak, int(np.abs(frame.to_ndarray().astype("int32")).max()))
                frames += 1
        reader = asyncio.create_task(receive())

    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        async with httpx.AsyncClient() as client:
            response = await client.post("http://127.0.0.1:7860/api/offer", json={
                "sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
                "request_data": {"flow_key": "clinica_vida_flow", "name": "Prueba de audio"},
            }, timeout=20)
            response.raise_for_status()
            answer = response.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
        await asyncio.wait_for(stopped.get(), timeout=45)
        if not args.opening_only:
            await asyncio.sleep(0.3)
            source.enabled = True
            user_end = time.monotonic() + len(source.pcm) / 16000
            await asyncio.wait_for(stopped.get(), timeout=45)
        stats = await pc.getStats()
        inbound = [{"packets_received": s.packetsReceived, "packets_lost": s.packetsLost,
                    "jitter": s.jitter} for s in stats.values() if s.type == "inbound-rtp"]
        result = {"opening_only": args.opening_only, "audio_frames": frames, "peak": peak, "user_transcripts": transcripts,
                  "user_end_to_bot_ms": response_delay, "inbound_rtp": inbound}
        print(json.dumps(result), flush=True)
        (ROOT / "reports" / "call-audit.json").write_text(json.dumps(result, indent=2))
        assert frames and peak
        if not args.opening_only:
            assert transcripts and response_delay is not None
    finally:
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await pc.close()


if __name__ == "__main__":
    asyncio.run(main())
