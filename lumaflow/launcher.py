# LumaFlow v1.0 (2026-08-07)
# Point d'entree `lumaflow` : construit le frontend web si besoin, ouvre le
# navigateur et lance le serveur uvicorn FastAPI.
"""Default `lumaflow` entry point -- Phase 3 of the PySide6 -> Web migration
plan (2026-07-23): the web UI (FastAPI + React, served as a single process)
is now the sole IHM. The PySide6 desktop UI (`lumaflow --qt` escape hatch)
was removed 2026-07-29 once the web UI had seen real usage.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_DIST_DIR = _WEB_DIR / "dist"
_URL = "http://127.0.0.1:8000/"


def _ensure_built() -> None:
    if (_DIST_DIR / "index.html").exists():
        return
    print("[LumaFlow] Premier lancement : construction de l'interface web...", file=sys.stderr)
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        if not (_WEB_DIR / "node_modules").exists():
            subprocess.run([npm, "install"], cwd=_WEB_DIR, check=True)
        subprocess.run([npm, "run", "build"], cwd=_WEB_DIR, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        print(
            f"[LumaFlow] Échec de la construction de l'interface web ({error}).\n"
            f"Lancez manuellement 'npm install && npm run build' dans {_WEB_DIR}.",
            file=sys.stderr,
        )
        sys.exit(1)


def _open_browser_when_ready() -> None:
    time.sleep(1.0)
    webbrowser.open(_URL)


def run_web() -> None:
    _ensure_built()
    import uvicorn

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run("lumaflow.api.app:app", host="127.0.0.1", port=8000)


def main() -> None:
    run_web()


if __name__ == "__main__":
    main()
