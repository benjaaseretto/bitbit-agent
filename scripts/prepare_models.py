"""Descarga modelos de audio MLX (y LLM local solo si --llm)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from huggingface_hub import snapshot_download

from app.pipecat_runtime.config import RuntimeConfig, TTS_BASE

parser = argparse.ArgumentParser()
parser.add_argument("--whisper", action="store_true", help="Incluye Whisper MLX (A/B STT)")
parser.add_argument("--clone", action="store_true", help="Descarga checkpoint de clonación")
parser.add_argument(
    "--llm",
    action="store_true",
    help="También descarga el LLM MLX (solo si usás LLM_PROVIDER=mlx)",
)
args = parser.parse_args()
config = RuntimeConfig.from_env(require_llm=False)

models = [config.parakeet_model, config.tts_model, config.whisper_model]
if args.clone:
    models.append(TTS_BASE)
if args.llm or config.llm_provider == "mlx":
    models.append(config.llm_model)
# --whisper queda por compat; whisper ya se descarga siempre en perfil Mac.

for model in dict.fromkeys(models):
    print(f"Downloading {model}", flush=True)
    # Snapshot completo: Parakeet necesita tokenizer.vocab (no solo pesos).
    snapshot_download(model)
print("Models ready.")
