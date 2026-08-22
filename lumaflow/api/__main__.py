# LumaFlow v1.0 (2026-08-07)
# Lance le serveur uvicorn de l'API REST en local (127.0.0.1:8000).
"""Thin launcher for the LumaFlow REST API -- Phase 1 of the PySide6 -> Web
migration plan (2026-07-20). Local-only server (the plan's deployment
decision: no auth, no remote binding), consumed by the React frontend during
Phase 2.
"""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("lumaflow.api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
