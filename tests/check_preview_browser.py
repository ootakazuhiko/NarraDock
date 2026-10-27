"""Explicit Chromium acceptance of a candidate preview using only synthetic inputs.

Requires an already installed Playwright/browser; does not install dependencies.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from check_player_browser import synthetic_page_server, wait_condition
import narradock_candidates as candidates
import narradock_player as player
import narradock_preview as previews
import narradock_transcript as transcripts


def synthetic_preview_inputs():
    sidecar, wav = player.synthetic_fixture()
    literal = '</script><img src=x onerror="alert(1)">& <b>literal</b> 🎵'
    sidecar["language"] = "en"
    sidecar["cues"][0]["text"] = literal
    candidate = {"schema_version": candidates.TRANSCRIPT_SCHEMA_VERSION,
        "project_id": sidecar["project_id"], "content_id": sidecar["content_id"],
        "audio": {**sidecar["audio"], "size_bytes": len(wav)},
        "metadata": {"title": literal, "language": "en", "credits": [literal, "x" * 200]},
        "transcript": {"fingerprint": transcripts.fingerprint(sidecar)}}
    return candidate, sidecar, wav, literal


def synthetic_preview(*, review_notes=None):
    candidate, sidecar, wav, literal = synthetic_preview_inputs()
    revision = candidates.candidate_fingerprint(candidate, project_id=candidate["project_id"])
    registry = {"schema_version": "asset-registry-0.1", "project_id": candidate["project_id"],
        "assets": [{key: value for key, value in candidate["audio"].items() if key != "duration_ms"}]}
    registry["assets"][0]["path"] = "synthetic.wav"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "synthetic.wav").write_bytes(wav)
        output, receipt = previews.build_candidate_preview(candidate, project_id=candidate["project_id"],
            expected_fingerprint=revision, transcript=sidecar, registry=registry, project_root=root,
            review_notes=review_notes)
    return output, receipt, literal, wav


def check(browser_executable: str, screenshots: Path | None = None) -> None:
    from playwright.sync_api import sync_playwright

    output, receipt, literal, wav = synthetic_preview()
    checks = []
    with synthetic_page_server([output.decode("utf-8")]) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=browser_executable, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 1000}, reduced_motion="reduce")
        context.route("http://**/*", lambda route: route.continue_()
                      if route.request.url == url else route.abort())
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        external, errors = [], []
        page.on("request", lambda request: external.append(request.url)
                if request.url.startswith(("http:", "https:")) and request.url != url else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        audio = page.locator("#audio")
        assert audio.evaluate("audio => audio.paused && audio.currentTime === 0 && audio.duration === 24")
        assert page.locator(".cue").count() == 12
        assert page.locator("#follow").is_enabled()
        checks.append("verified candidate initializes playback without autoplay")

        page.locator(".identity summary").click()
        assert page.locator("#title").text_content() == literal
        assert page.locator(".identity li").first.text_content() == literal
        assert page.locator("#cue-0 .cue-text").text_content() == literal
        assert page.locator("img").count() == 0
        assert page.locator("#title").get_attribute("lang") == "en"
        assert page.locator("#transcript").get_attribute("lang") == "en"
        assert page.locator(".identity code").text_content() == receipt["candidate_fingerprint"]
        checks.append("literal metadata/cues, language and selected candidate revision")

        digest = page.evaluate("""async () => {
          const value = document.getElementById('audio-data').textContent.split(',')[1];
          const data = Uint8Array.from(atob(value), c => c.charCodeAt(0));
          const hash = await crypto.subtle.digest('SHA-256', data);
          return Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, '0')).join('');
        }""")
        assert digest == hashlib.sha256(wav).hexdigest() == receipt["measurements"]["audio"]["sha256"]
        checks.append("browser receives exactly the measured and verified WAV")

        page.locator("#cue-2").focus()
        page.keyboard.press("Enter")
        wait_condition(page, "document.getElementById('cue-2').hasAttribute('aria-current')")
        assert audio.evaluate("audio => audio.paused && Math.abs(audio.currentTime - 5) < .01")
        audio.focus()
        page.keyboard.press("Space")
        wait_condition(page, "document.getElementById('audio').currentTime > 5.1")
        page.keyboard.press("Space")
        wait_condition(page, "document.getElementById('audio').paused")
        checks.append("keyboard cue seek and native playback advance the media clock")

        page.locator("#rate").select_option("2")
        assert audio.evaluate("audio => audio.playbackRate") == 2
        for seconds, active in ((2.7, None), (6.5, "cue-3"), (24, None)):
            audio.evaluate("(audio, seconds) => { audio.currentTime = seconds; }", seconds)
            wait_condition(page, "expected => { const cue = document.querySelector('[aria-current]'); "
                           "return (cue ? cue.id : null) === expected; }", arg=active)
        checks.append("rate control, gap, adjacent boundary and media end")

        page.locator("#follow").check()
        page.locator("#rate").focus()
        audio.evaluate("audio => { audio.currentTime = 21.2; }")
        wait_condition(page, "document.getElementById('cue-10').hasAttribute('aria-current')")
        assert page.locator("#transcript").evaluate("list => list.scrollTop > 0")
        assert page.locator("#rate").evaluate("item => document.activeElement === item")
        checks.append("candidate transcript follow preserves control focus")
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "preview-desktop.png"), full_page=True)
            (screenshots / "synthetic-preview.html").write_bytes(output)
            (screenshots / "synthetic-preview-receipt.json").write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        if screenshots:
            page.screenshot(path=str(screenshots / "preview-narrow.png"), full_page=True)
        checks.append("narrow viewport handles long metadata and candidate fingerprint")
        assert not errors, errors
        assert not external, "Unexpected external request"
        checks.append("no script errors or external resource requests")
        print(f"Chromium {browser.version}: {len(checks)} candidate browser checks passed")
        for item in checks:
            print("PASS:", item)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", required=True)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    check(args.browser_executable, args.screenshots)
