from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures import build_all

ROOT = Path(__file__).resolve().parents[2]


def _gui_available() -> str | None:
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return "no display (run under a desktop session or xvfb-run)"
    try:
        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # noqa: F401
    except (ImportError, ValueError) as exc:
        return f"WebKitGTK 6.0 not available: {exc}"
    return None


@pytest.fixture(scope="session")
def books(tmp_path_factory) -> dict[str, Path]:
    return build_all(tmp_path_factory.mktemp("books"))


@pytest.fixture
def run_app(tmp_path):
    """Runs one driver scenario against a fresh, isolated app profile and returns its JSON."""
    reason = _gui_available()
    if reason:
        pytest.skip(reason)

    def run(scenario: str, *paths: Path, settings: dict | None = None) -> dict:
        xdg = {name: tmp_path / name for name in ("config", "data", "cache")}
        for d in xdg.values():
            d.mkdir(exist_ok=True)
        if settings:
            cfg = xdg["config"] / "ebookread"
            cfg.mkdir(exist_ok=True)
            (cfg / "settings.json").write_text(json.dumps(settings))
        out = tmp_path / f"{scenario}.json"
        env = {
            **os.environ,
            "XDG_CONFIG_HOME": str(xdg["config"]),
            "XDG_DATA_HOME": str(xdg["data"]),
            "XDG_CACHE_HOME": str(xdg["cache"]),
        }
        proc = subprocess.run(
            [sys.executable, "-m", "tests.integration.driver", scenario, str(out), *map(str, paths)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
        )
        assert out.exists(), f"driver produced no result\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        result = json.loads(out.read_text())
        assert "driver_error" not in result, result["driver_error"]
        return result

    return run
