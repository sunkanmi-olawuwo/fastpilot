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

# .../fastpilot/tests/test_visual.py → parents[1] = repo root
_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND = _ROOT / "frontend" / "app.py"
_STUB_DIR = _ROOT / "tests" / "visual"
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


def _collapse_sidebar(page) -> None:  # noqa: ANN001
    """Collapse the (expanded-by-default) sidebar so it stops overlaying the main content
    on a narrow viewport — the realistic mobile flow (tap to close), and what lets the
    content-overflow checks click the welcome chips. Waits for the collapse button to paint
    (it isn't in the DOM at first load) before clicking; best-effort so it never raises."""
    btn = page.locator('[data-testid="stSidebarCollapseButton"]').first
    try:
        btn.wait_for(state="visible", timeout=8000)
        btn.click()
        page.locator('[data-testid="stSidebar"][aria-expanded="false"]').wait_for(timeout=5000)
        page.wait_for_timeout(400)  # let it finish sliding out
    except Exception:  # noqa: BLE001 - collapsing is a convenience, not an assertion
        pass


def _wait_monaco(page, timeout_ms: int = 9000) -> None:  # noqa: ANN001
    """Best-effort wait for the Monaco editor (in its component iframe) to paint its code
    lines, so a Playground screenshot captures the editor and not the "Loading…" spinner.
    Monaco loads asynchronously and may fall back to a plain text area — so this never
    raises: if the editor doesn't appear, we wait out a short grace period and proceed."""
    for sel in ('iframe[title*="monaco" i]', 'iframe[title*="st_monaco" i]'):
        try:
            page.frame_locator(sel).locator(".view-line").first.wait_for(state="visible", timeout=timeout_ms)
            page.wait_for_timeout(700)  # let syntax highlighting settle
            return
        except Exception:  # noqa: BLE001 - Monaco is a nicety, not an assertion
            continue
    page.wait_for_timeout(2000)


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


@pytest.mark.parametrize("theme,expected_bg", [("dark", "rgb(12, 18, 34)"), ("light", "rgb(250, 250, 249)")])
def test_theme_drives_whole_app_surface(ui_server, browser, theme, expected_bg):
    """The active theme drives the *entire* app surface, not just the custom CSS layer: the
    `.stApp` background matches the theme token. This guards the in-app light/dark toggle —
    forcing a theme now makes Streamlit's native surface follow (it used to track only
    prefers-color-scheme, which is why a manual light choice left half the UI dark)."""
    page = _open(browser, 1280, theme)
    page.goto(ui_server, wait_until="load")
    page.wait_for_timeout(1500)
    bg = page.evaluate("getComputedStyle(document.querySelector('.stApp')).backgroundColor")
    assert bg == expected_bg, f"{theme}: .stApp background={bg}, expected {expected_bg}"
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


def test_citations_in_code_not_mangled_no_overflow(ui_server, browser):
    """Regression: citations inside code (inline/fenced) must NOT be wrapped in <sup> —
    that leaks literal `sup class=...` text into the code and widens non-wrapping code
    lines into a horizontal scroll. Prose `[1]`/`[2]` still render as superscripts, the
    in-code `[3]`/`[4]` stay plain, and nothing overflows the viewport. The stub answer
    carries all four cases."""
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 1280, "light")
    page.goto(ui_server, wait_until="domcontentloaded")
    page.get_by_text("Add JWT auth").click()
    expect(page.get_by_text("OAuth2PasswordBearer", exact=False).first).to_be_visible(timeout=30_000)
    # Wait for the LAST snippet so the stream is complete before counting citations.
    expect(page.get_by_text("verify_token", exact=False).first).to_be_visible(timeout=30_000)
    body = page.evaluate("document.body.innerText")
    assert "sup class" not in body, "citation <sup> leaked as literal text (wrapped inside code)"
    assert page.locator("sup.fp-cite").count() >= 2, "prose [1]/[2] should render as superscripts"
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= 1282, f"horizontal overflow from wide code line: scrollWidth={scroll_w}"
    page.close()


def test_agent_flow_shows_self_correction(ui_server, browser):
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 1280, "dark")
    page.goto(ui_server, wait_until="domcontentloaded")
    page.get_by_text("Write & run a sample endpoint").click()
    # The fix-then-pass run ends on exit 0 in the terminal block.
    expect(page.get_by_text("exit 0", exact=False).first).to_be_visible(timeout=40_000)
    # Wait for the completed static re-render (the "Send to Playground" button only
    # appears in _render_run) so the attempt-2 code block is populated, not mid-stream blank.
    expect(page.get_by_role("button", name="Send to Playground")).to_be_visible(timeout=20_000)
    expect(page.get_by_text("class User", exact=False).first).to_be_visible(timeout=10_000)
    page.screenshot(path=str(_ARTIFACTS / "agent_1280_dark.png"), full_page=True)
    page.close()


def _switch_mode(page, label: str) -> None:
    """Pick a mode radio option by its label text, expanding the sidebar first if needed.

    The sidebar now defaults to expanded (``initial_sidebar_state="expanded"``), so the
    radio labels are usually on-screen already. But on a narrow viewport Streamlit may
    still collapse it — so if a (visible) expand control is present, click it first. Then
    click the wrapping ``<label>`` (the real hit target; the inner ``<p>`` reports as
    outside the viewport)."""
    for sel in (
        '[data-testid="stExpandSidebarButton"]',
        '[data-testid="stSidebarCollapsedControl"]',
        '[data-testid="collapsedControl"]',
    ):
        opener = page.locator(sel)
        if opener.count() and opener.first.is_visible():
            opener.first.click()
            page.wait_for_timeout(700)  # let the sidebar slide in
            break
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
    # The Monaco editor renders in an iframe and shows "Loading…" until it paints — wait for
    # the iframe's code lines so the screenshot captures the populated editor, not the spinner.
    _wait_monaco(page)
    page.get_by_role("button", name="▶ Run").click()
    # Stub /execute returns "valid: 200 / invalid: 422" — the terminal block must show it.
    expect(page.get_by_text("invalid: 422", exact=False).first).to_be_visible(timeout=20_000)
    page.wait_for_timeout(400)  # let the terminal block settle
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
    _collapse_sidebar(page)  # sidebar defaults expanded; on mobile it overlays the chips
    page.get_by_text("Add JWT auth").click()
    expect(page.get_by_text("OAuth2PasswordBearer", exact=False).first).to_be_visible(timeout=30_000)
    page.screenshot(path=str(_ARTIFACTS / "chat_390_light.png"), full_page=True)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= 392, f"horizontal overflow at 390px: scrollWidth={scroll_w}"
    page.close()


def test_mobile_agent_timeline_no_overflow(ui_server, browser):
    """AC3.5: the agent step-timeline + per-attempt st.code blocks + terminal output
    must stay readable at 390px with no horizontal overflow — code blocks scroll
    inside themselves rather than blowing out the viewport."""
    from playwright.sync_api import expect

    _ARTIFACTS.mkdir(exist_ok=True)
    page = _open(browser, 390, "dark")
    page.goto(ui_server, wait_until="domcontentloaded")
    _collapse_sidebar(page)  # sidebar defaults expanded; on mobile it overlays the chips
    page.get_by_text("Write & run a sample endpoint").click()
    # Run to completion (✗ attempt 1 → ✓ attempt 2) so the full timeline + both code
    # blocks + terminal are on screen when we measure.
    expect(page.get_by_text("exit 0", exact=False).first).to_be_visible(timeout=40_000)
    expect(page.get_by_role("button", name="Send to Playground")).to_be_visible(timeout=20_000)
    page.screenshot(path=str(_ARTIFACTS / "agent_390_dark.png"), full_page=True)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= 392, f"horizontal overflow at 390px: scrollWidth={scroll_w}"
    page.close()
