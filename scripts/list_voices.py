#!/usr/bin/env python3
"""Lista voces TTS disponibles y aplica un preset opcional.

Uso:
  python scripts/list_voices.py
  python scripts/list_voices.py --set Serena
  python scripts/list_voices.py --engine kokoro
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "presets" / "voices.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Listado de voces TTS legales")
    parser.add_argument(
        "--engine",
        choices=("qwen", "kokoro", "all"),
        default="all",
        help="Motor a listar",
    )
    parser.add_argument(
        "--set",
        metavar="VOICE_ID",
        help="Escribe QWEN_TTS_VOICE o KOKORO_VOICE en .env.mac (crea si no existe)",
    )
    parser.add_argument(
        "--recommended",
        action="store_true",
        help="Solo voces recommended=true",
    )
    args = parser.parse_args()

    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    sections = []
    if args.engine in ("qwen", "all"):
        sections.append(("Qwen CustomVoice (Mac)", "qwen_custom_voice", "QWEN_TTS_VOICE"))
    if args.engine in ("kokoro", "all"):
        sections.append(("Kokoro ES (bot)", "kokoro_es", "KOKORO_VOICE"))

    for title, key, env_name in sections:
        print(f"\n== {title} ==")
        for item in data[key]:
            if args.recommended and not item.get("recommended"):
                continue
            flag = "*" if item.get("recommended") else " "
            print(
                f"  {flag} {item['id']:<12}  gender={item.get('gender','?')}  lang={item.get('lang','?')}"
            )
        print(f"  → env: {env_name}=...")

    print("\n" + data.get("note", ""))

    if args.set:
        voice = args.set.strip()
        qwen_ids = {v["id"].lower(): v["id"] for v in data["qwen_custom_voice"]}
        kokoro_ids = {v["id"].lower(): v["id"] for v in data["kokoro_es"]}
        target = ROOT / ".env.mac"
        if not target.exists():
            target = ROOT / ".env"
        text = target.read_text(encoding="utf-8") if target.exists() else ""

        if voice.lower() in qwen_ids:
            canonical = qwen_ids[voice.lower()]
            text = _upsert_env(text, "QWEN_TTS_VOICE", canonical)
            text = _upsert_env(text, "TTS_VOICE_MODE", "preset")
            target.write_text(text, encoding="utf-8")
            print(f"\nOK: {target.name} → QWEN_TTS_VOICE={canonical}")
        elif voice.lower() in kokoro_ids:
            canonical = kokoro_ids[voice.lower()]
            text = _upsert_env(text, "KOKORO_VOICE", canonical)
            target.write_text(text, encoding="utf-8")
            print(f"\nOK: {target.name} → KOKORO_VOICE={canonical}")
        else:
            print(f"Voz desconocida: {voice}", file=sys.stderr)
            return 1
    return 0


def _upsert_env(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
