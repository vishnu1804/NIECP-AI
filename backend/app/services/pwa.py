"""PWA manifest + service-worker content helpers (spec §40, §56)."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from ..config import settings

FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "static"))


def build_manifest(theme_color: str = "#0b1220", background: str = "#0b1220") -> dict[str, Any]:
    return {
        "name": settings.app_long_name,
        "short_name": "NIECP-AI",
        "description": (
            "AI-powered industrial approval and compliance navigator: understand potential approvals, prepare "
            "documents, apply through official channels, track and stay compliant."
        ),
        "start_url": "/dashboard",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": background,
        "theme_color": theme_color,
        "categories": ["business", "government", "productivity"],
        "lang": "en-IN",
        "dir": "ltr",
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Dashboard", "url": "/dashboard"},
            {"name": "My projects", "url": "/projects"},
            {"name": "Documents", "url": "/projects"},
        ],
    }


def asset_hashes() -> dict[str, str]:
    """Best-effort hash manifest of built frontend assets for cache-busting."""
    out: dict[str, str] = {}
    dist = os.path.abspath(FRONTEND_DIST)
    if not os.path.isdir(dist):
        return out
    for root, _dirs, files in os.walk(dist):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, dist)
            if rel.startswith(("assets" + os.sep, "icons" + os.sep)) or rel in ("index.html", "manifest.webmanifest", "sw.js"):
                try:
                    with open(path, "rb") as f:
                        out[rel.replace(os.sep, "/")] = hashlib.sha256(f.read()).hexdigest()[:16]
                except OSError:
                    continue
    return out


def service_worker_version() -> str:
    hashes = asset_hashes()
    blob = json.dumps(hashes, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12] if hashes else "dev"
