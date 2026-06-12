"""Playwright visual smoke tests (``visual`` marker — never in the default suite).

Boots the canned stub backend + a real ``streamlit run`` (pointed at the stub), then
drives a headless Chromium to screenshot the money screens at 390/1280 in light and
dark across the three modes. Asserts elements render and that mobile has no horizontal
overflow — the pixel-level gaps AppTest can't see. Screenshots land in
``tests/visual/artifacts/`` for eyeball review.

Run:
    uv run playwright install chromium          # one-time
    uv run pytest -m visual                      # backend + UI booted automatically
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright")

pytestmark = pytest.mark.visual

# .../rag-accelerator-capstone/final-submission/tests/test_visual.py → parents[2] = repo root
_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _ROOT / "final-submission" / "frontend" / "app.py"
_STUB_DIR = _ROOT / "final-submission" / "tests" / "visual"
_ARTIFACTS = _STUB_DIR / "artifacts"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_http(url: str, timeout: float = 60) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - localhost only
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


@pytest.fixture(scope="session")
def ui_server():
    backend_port, ui_port = _free_port(), _free_port()
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "stub_backend:app", "--port", str(backend_port), "--log-level", "warning"],
        env={**os.environ, "PYTHONPATH": str(_STUB_DIR)},  # so `stub_backend` imports reliably
    )
    ui = None
    try:
        assert _wait_http(f"http://127.0.0.1:{backend_port}/health"), "stub backend did not start"
        env = {**os.environ, "API_BASE_URL": f"http://127.0.0.1:{backend_port}"}
        ui = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(_FRONTEND),
                "--server.port",
                str(ui_port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
                "--server.fileWatcherType",
                "none",
            ],
            env=env,
        )
        assert _wait_http(f"http://127.0.0.1:{ui_port}/_stcore/health"), "streamlit did not start"
        yield f"http://127.0.0.1:{ui_port}"
    finally:
        for proc in (ui, backend):
            if proc is not None:
                proc.terminate()
        for proc in (ui, backend):
            if proc is not None:
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(browser, width: int, theme: str):  # noqa: ANN001
    ctx = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=theme)
    return ctx.new_page()


@pytest.mark.parametrize("width,theme", [(1280, "light"), (390, "light"), (1280, "dark"), (390, "dark")])
def test_welcome_renders(ui_server, browser, width, theme):
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, width, theme)
    page.goto(ui_server, wait_until="domcontentloaded")
    expect(page.get_by_text("Learn FastAPI by building.")).to_be_visible(timeout=25_000)
    page.screenshot(path=str(_ARTIFACTS / f"welcome_{width}_{theme}.png"), full_page=True)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= width + 2, f"horizontal overflow at {width}px: scrollWidth={scroll_w}"
    page.close()


def test_chat_flow_renders_answer_and_sources(ui_server, browser):
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 1280, "light")
    page.goto(ui_server, wait_until="domcontentloaded")
    page.get_by_text("Add JWT auth").click()
    expect(page.get_by_text("OAuth2PasswordBearer", exact=False).first).to_be_visible(timeout=30_000)
    page.screenshot(path=str(_ARTIFACTS / "chat_1280_light.png"), full_page=True)
    page.close()


def test_agent_flow_shows_self_correction(ui_server, browser):
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 1280, "dark")
    page.goto(ui_server, wait_until="domcontentloaded")
    page.get_by_text("Write & run a sample endpoint").click()
    # The fix-then-pass run ends on exit 0 in the terminal block.
    expect(page.get_by_text("exit 0", exact=False).first).to_be_visible(timeout=40_000)
    page.screenshot(path=str(_ARTIFACTS / "agent_1280_dark.png"), full_page=True)
    page.close()


def _switch_mode(page, label: str) -> None:
    """Open the (collapsed) sidebar and pick a mode radio option by its label text.

    The sidebar starts collapsed (``initial_sidebar_state="collapsed"``), so the radio
    labels sit off-screen (x≈-280) until expanded. Open it first via the expand button
    (testid varies by Streamlit version — try the known ones), then click the wrapping
    ``<label>`` (the real hit target; the inner ``<p>`` reports as outside the viewport)."""
    for sel in (
        '[data-testid="stExpandSidebarButton"]',
        '[data-testid="stSidebarCollapsedControl"]',
        '[data-testid="collapsedControl"]',
    ):
        opener = page.locator(sel)
        if opener.count():
            opener.first.wait_for(state="visible", timeout=10_000)
            opener.first.click()
            break
    page.wait_for_timeout(700)  # let the sidebar slide in
    option = page.locator("label").filter(has_text=label).first
    option.wait_for(state="visible", timeout=10_000)
    option.scroll_into_view_if_needed()
    option.click()


def test_playground_runs_and_shows_terminal(ui_server, browser):
    """Playground is the most render-risky screen (editor + terminal + iframe boundary)
    and the only mode AppTest can't pixel-check. Switch to it via the sidebar radio
    (the exact path the `pending_mode` crash lived on), Run, and assert the terminal
    renders the canned stdout."""
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 1280, "light")
    page.goto(ui_server, wait_until="domcontentloaded")
    expect(page.get_by_text("Learn FastAPI by building.")).to_be_visible(timeout=25_000)  # app fully rendered first
    _switch_mode(page, "Playground — practice")
    expect(page.get_by_text("FastPilot · Playground", exact=False).first).to_be_visible(timeout=25_000)
    page.get_by_role("button", name="▶ Run").click()
    # Stub /execute returns "valid: 200 / invalid: 422" — the terminal block must show it.
    expect(page.get_by_text("invalid: 422", exact=False).first).to_be_visible(timeout=20_000)
    page.screenshot(path=str(_ARTIFACTS / "playground_1280_light.png"), full_page=True)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= 1282, f"horizontal overflow: scrollWidth={scroll_w}"
    page.close()


def test_mobile_chat_answer_no_overflow(ui_server, browser):
    """The objective overflow check, on the screen that actually risks it: the answer
    view at 390px carries code-fenced sources + long tokens that can blow out the
    viewport in a way the welcome screen never does."""
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 390, "light")
    page.goto(ui_server, wait_until="domcontentloaded")
    page.get_by_text("Add JWT auth").click()
    expect(page.get_by_text("OAuth2PasswordBearer", exact=False).first).to_be_visible(timeout=30_000)
    page.screenshot(path=str(_ARTIFACTS / "chat_390_light.png"), full_page=True)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= 392, f"horizontal overflow at 390px: scrollWidth={scroll_w}"
    page.close()
