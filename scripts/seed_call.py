"""Siembra o imprime el payload de prueba (TEST_* / Redis opcional)."""
from __future__ import annotations

import json
import sys

from app.pipecat_runtime.config import load_config_env
from app.utils.call_metadata import load_call_metadata, redis_key, seed_redis_body


def main() -> int:
    load_config_env()
    payload = load_call_metadata()
    if "--redis" in sys.argv:
        try:
            key = seed_redis_body()
        except Exception as exc:
            print(f"Redis no sembrado: {exc}", file=sys.stderr)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1
        print(f"Seeded Redis key: {key}")
        return 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"# redis key (si TEST_REDIS_URL): {redis_key()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
