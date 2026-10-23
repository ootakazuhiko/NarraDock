"""Explicit Chromium acceptance; requires an already installed Playwright and browser.

This is separate from unittest discovery and does not install dependencies or
claim Safari/mobile-device compatibility. All media and pages are synthetic.
"""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import narradock_player as player


@contextmanager
def synthetic_page_server(payload):
    """Serve exactly an in-memory fixture on loopback; never map filesystem paths."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            data = payload[0].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def wait_condition(page, expression, *, arg=None):
    # Evaluate through the browser debugger; do not enable unsafe-eval in the page.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if page.evaluate(expression, arg):
            return
        page.wait_for_timeout(50)
    raise AssertionError("Browser condition timed out: " + expression)


def check(browser_executable: str, screenshots: Path | None = None) -> None:
    from playwright.sync_api import sync_playwright

    checks = []
    payload = [player.render_demo()]
    with synthetic_page_server(payload) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=browser_executable, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 1000}, reduced_motion="reduce")
        remote_requests, errors = [], []
        context.route("http://**/*", lambda route: route.continue_()
                      if route.request.url == url else route.abort())
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        page.on("request", lambda request: remote_requests.append(request.url)
                if request.url.startswith(("http:", "https:")) and request.url != url else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        assert page.locator(".cue").count() == 12
        assert page.locator("#follow").is_enabled()
        assert page.locator("#audio").evaluate("audio => audio.paused && audio.currentTime === 0")
        checks.append("metadata, controls and no autoplay")

        def seek(seconds, active):
            page.locator("#audio").evaluate("(audio, time) => { audio.currentTime = time; }", seconds)
            wait_condition(page, "document.getElementById('audio').seeking === false")
            wait_condition(page, "expected => { const cue = document.querySelector('[aria-current]'); "
                                   "return (cue ? cue.id : null) === expected; }", arg=active)

        for seconds, active in ((0,None),(1,"cue-0"),(2.5,None),(6.5,"cue-3"),
                                (8.5,None),(23.5,None),(24,None)):
            seek(seconds, active)
        checks.append("media-clock boundaries, adjacent cues, gaps and end")

        page.locator("#cue-2").click()
        assert page.locator("#audio").evaluate("audio => audio.paused && Math.abs(audio.currentTime - 5) < .01")
        assert page.locator("#cue-2").get_attribute("aria-current") == "true"
        checks.append("cue navigation preserves pause")

        audio_control = page.locator("#audio")
        audio_control.focus()
        page.keyboard.press("Space")
        wait_condition(page, "!document.getElementById('audio').paused && document.getElementById('audio').currentTime > 5.1")
        page.keyboard.press("Space")
        wait_condition(page, "document.getElementById('audio').paused")
        stopped = audio_control.evaluate("audio => audio.currentTime")
        page.wait_for_timeout(150)
        assert abs(audio_control.evaluate("audio => audio.currentTime") - stopped) < .02
        checks.append("native keyboard play/pause and real clock advance")

        page.locator("#rate").select_option("2")
        assert audio_control.evaluate("audio => audio.playbackRate") == 2
        seek(4.5, None)
        audio_control.focus()
        page.keyboard.press("Space")
        wait_condition(page, "document.getElementById('audio').currentTime > 5.05")
        assert page.locator("#cue-2").get_attribute("aria-current") == "true"
        page.keyboard.press("Space")
        wait_condition(page, "document.getElementById('audio').paused")
        checks.append("rate control and playback-driven highlighting")

        for rate in (1.5, 0.5, 1.75):
            audio_control.evaluate("(audio, value) => { audio.playbackRate = value; }", rate)
            wait_condition(page, "value => document.getElementById('rate').value === String(value)", arg=rate)
        page.locator("#rate").select_option("1")
        assert audio_control.evaluate("audio => audio.playbackRate") == 1
        assert page.locator("#native-rate").count() == 0
        checks.append("native rate changes synchronize preset and extra select values")

        audio_control.evaluate("audio => audio.load()")
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        assert page.locator("#rate").is_enabled()
        assert page.locator("[aria-current]").count() == 0
        checks.append("real media reload restores ready state")

        page.locator("#follow").check()
        page.locator("#rate").focus()
        page.evaluate("window.scrollTo(0, 0)")
        seek(21.2, "cue-10")
        assert page.locator("#transcript").evaluate("list => list.scrollTop > 0")
        assert page.locator("#rate").evaluate("element => document.activeElement === element")
        assert page.evaluate("window.scrollY") == 0
        box = page.locator("#transcript").bounding_box()
        row = page.locator("#cue-10").bounding_box()
        assert row["y"] >= box["y"] and row["y"] + row["height"] <= box["y"] + box["height"]
        checks.append("follow scrolls only the transcript without focus movement")

        page.locator("#transcript").hover()
        page.mouse.wheel(0, -1200)
        wait_condition(page, "!document.getElementById('follow').checked")
        page.locator("#transcript").evaluate("list => { list.scrollTop = 0; }")
        seek(19.2, "cue-9")
        assert page.locator("#transcript").evaluate("list => list.scrollTop") == 0
        page.locator("#follow").check()
        assert page.locator("#transcript").evaluate("list => list.scrollTop > 0")
        checks.append("manual scroll suspends follow until explicit restart")

        page.locator("#cue-1").focus()
        page.keyboard.press("Enter")
        assert audio_control.evaluate("audio => audio.paused && Math.abs(audio.currentTime - 3) < .01")
        assert page.locator("#cue-1").evaluate("element => document.activeElement === element")
        assert not page.locator("#follow").is_checked()
        assert page.locator("#clock").get_attribute("aria-live") is None
        assert page.locator("#transcript").get_attribute("aria-live") is None
        assert page.locator("#cue-1").evaluate("element => getComputedStyle(element).outlineStyle") != "none"
        checks.append("keyboard cue activation, visible focus, no live clock chatter")

        seek(23.5, None)
        audio_control.focus()
        page.keyboard.press("Space")
        wait_condition(page, "document.getElementById('audio').ended")
        assert page.locator("[aria-current]").count() == 0
        checks.append("actual media ended clears highlighting")

        # Visibility event wiring is exercised here; hidden scheduling is covered in Node.
        seek(9.2, "cue-4")
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        assert page.locator("#cue-4").get_attribute("aria-current") == "true"
        checks.append("visibility event resynchronization")
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "player-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        page.locator("#cue-5").focus()
        page.keyboard.press("Enter")
        assert page.locator("#cue-5").get_attribute("aria-current") == "true"
        checks.append("narrow viewport and reduced-motion mode")
        if screenshots:
            page.screenshot(path=str(screenshots / "player-narrow.png"), full_page=True)

        transcript, wav = player.synthetic_fixture()
        literal = '</script><img src=x onerror="alert(1)">& <b>literal</b>'
        transcript["cues"][0]["text"] = literal
        with patch.object(player, "synthetic_fixture", return_value=(transcript, wav)):
            payload[0] = player.render_demo()
        page.reload()
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        assert page.locator("#cue-0 .cue-text").text_content() == literal
        assert page.locator("img").count() == 0
        assert not errors, errors
        assert not remote_requests, "Unexpected remote request"
        checks.append("literal text rendering and no external resource requests")

        audio_control.evaluate("audio => audio.dispatchEvent(new Event('error'))")
        assert page.locator("#cue-0").is_disabled()
        assert page.locator("#rate").is_disabled()
        assert page.locator("#follow").is_disabled()
        assert page.locator("[aria-current]").count() == 0
        assert page.locator("#status").text_content()
        checks.append("fixed media-error state")
        print(f"Chromium {browser.version}: {len(checks)} browser checks passed")
        for item in checks:
            print("PASS:", item)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", required=True)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    check(args.browser_executable, args.screenshots)
