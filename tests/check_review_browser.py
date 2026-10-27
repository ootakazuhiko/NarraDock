"""Explicit Chromium note/export/restore acceptance; all inputs are synthetic."""
import argparse
import copy
import json
from pathlib import Path

from check_player_browser import synthetic_page_server, wait_condition
from check_preview_browser import synthetic_preview, synthetic_preview_inputs
import narradock_candidates as candidates
import narradock_player as player
import narradock_review as review


def check(browser_executable: str, screenshots: Path | None = None) -> None:
    from playwright.sync_api import sync_playwright

    output, receipt, _, _ = synthetic_preview()
    candidate, transcript, _, _ = synthetic_preview_inputs()
    assert receipt["candidate_fingerprint"] == candidates.candidate_fingerprint(
        candidate, project_id=candidate["project_id"])
    payload = [output.decode("utf-8")]
    checks = []
    with synthetic_page_server(payload) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=browser_executable, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
        context.route("http://**/*", lambda route: route.continue_()
                      if route.request.url == url else route.abort())
        context.route("https://**/*", lambda route: route.abort())
        downloads, errors, external = [], [], []
        def watch_page(page):
            page.on("download", lambda item: downloads.append(item))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external.append(request.url)
                    if request.url.startswith(("http:", "https:")) and request.url != url else None)
        context.on("page", watch_page)
        page = context.new_page()
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        capture, save = page.locator("#note-capture"), page.locator("#note-save")
        text, export = page.locator("#note-text"), page.locator("#note-export")
        audio = page.locator("#audio")
        assert capture.is_enabled() and export.is_disabled()
        assert audio.evaluate("audio => audio.paused")
        assert not downloads
        checks.append("candidate-only notes initialize without playback or download")

        def seek(seconds):
            audio.evaluate("(audio, seconds) => { audio.currentTime = seconds; }", seconds)
            wait_condition(page, "document.getElementById('audio').seeking === false")

        seek(1.234)
        capture.click()
        assert text.evaluate("element => document.activeElement === element")
        anchor = page.locator("#note-anchor").text_content()
        assert "0:01.234" in anchor
        assert capture.is_disabled() and export.is_disabled()
        text.fill("Draft remains while searching.")
        page.locator("#transcript-search summary").click()
        page.locator("#search-query").fill(transcript["cues"][3]["text"])
        page.locator("#search-query").press("Enter")
        page.locator(".search-result").first.click()
        wait_condition(page, "Math.abs(document.getElementById('audio').currentTime - 6.5) < .001")
        assert page.locator("#note-anchor").text_content() == anchor
        assert text.input_value() == "Draft remains while searching."
        assert export.is_disabled()
        checks.append("search navigation leaves the pending note text and captured anchor unchanged")
        literal = '</script><img src=x onerror="alert(1)">&\n🎵'
        text.fill(literal)
        save.click()
        assert page.locator(".note-text").text_content() == literal
        assert "0:01.234" in page.locator(".note-seek").text_content()
        assert page.locator("img").count() == 0
        assert audio.evaluate("audio => audio.paused && audio.currentTime === 6.5")
        checks.append("anchor stays fixed during input and literal multiline text is safe")

        page.locator(".note-edit").click()
        text.fill("Cancelled change")
        assert export.is_disabled()
        page.locator("#note-cancel").click()
        assert page.locator(".note-text").text_content() == literal
        page.locator(".note-edit").click()
        text.fill(literal + "\nEdited.")
        save.click()
        page.locator(".note-seek").focus()
        page.keyboard.press("Enter")
        wait_condition(page, "Math.abs(document.getElementById('audio').currentTime - 1.234) < .001")
        assert audio.evaluate("audio => audio.paused")
        assert page.locator(".note-seek").evaluate("element => document.activeElement === element")
        checks.append("editing/cancel preserves position and keyboard note navigation preserves pause/focus")

        for seconds, message in ((2.7, "Gap note."), (24, "End note.")):
            seek(seconds)
            capture.click()
            text.fill(message)
            save.click()
        assert page.locator(".note-text").count() == 3
        checks.append("gap and end positions can receive notes without inventing cue references")

        capture.click()
        for invalid in (" \n\t\ufeff", "x" * 1001, "bad\u0000", "bad\ud800"):
            # Programmatic assignment also tests the handler beyond HTML maxlength.
            text.evaluate("(element, value) => { element.value = value; element.dispatchEvent(new Event('input')); }", invalid)
            assert save.is_disabled()
        text.fill("🎵" * 1000)
        assert save.is_enabled()
        save.click()
        assert page.locator(".note-text").last.text_content() == "🎵" * 1000
        page.locator(".note-delete").last.click()
        assert page.locator(".note-text").count() == 3
        checks.append("Unicode length/control checks and explicit deletion")

        # Simulate a Blob failure without changing content policy; notes remain available.
        page.evaluate("() => { window.originalBlob = window.Blob; window.Blob = function() { throw new Error('Synthetic failure'); }; }")
        export.click()
        assert not downloads
        assert "書き出せません" in page.locator("#note-status").text_content()
        assert page.locator(".note-text").count() == 3
        page.evaluate("window.Blob = window.originalBlob; delete window.originalBlob;")
        checks.append("export failure retains notes and reports a fixed message")

        with page.expect_download() as requested:
            export.click()
        download = requested.value
        assert download.suggested_filename == "narradock-review-notes.json"
        assert download.failure() is None
        data = Path(download.path()).read_bytes()
        loaded = review.load_review_notes(data, candidate=candidate, transcript=transcript,
            project_id=candidate["project_id"], expected_fingerprint=receipt["candidate_fingerprint"])
        assert [note["at_ms"] for note in loaded["notes"]] == [1234, 2700, 24000]
        assert [note["cue_id"] for note in loaded["notes"]] == ["cue-0", None, None]
        assert loaded["notes"][0]["text"] == literal + "\nEdited."
        changed = copy.deepcopy(candidate)
        changed["metadata"]["title"] = "Another selected title"
        try:
            review.load_review_notes(data, candidate=changed, transcript=transcript,
                project_id=candidate["project_id"], expected_fingerprint=candidates.candidate_fingerprint(
                    changed, project_id=candidate["project_id"]))
        except review.ReviewNotesError:
            pass
        else:
            raise AssertionError("Stale browser export accepted")
        assert len(downloads) == 1
        checks.append("real Blob download passes Python binding validation and rejects another candidate revision")

        page.evaluate("""() => {
          while (document.querySelectorAll('.note-text').length < 100) {
            document.getElementById('note-capture').click();
            const input = document.getElementById('note-text');
            input.value = 'Synthetic limit note.';
            input.dispatchEvent(new Event('input'));
            document.getElementById('note-save').click();
          }
        }""")
        assert capture.is_disabled() and export.is_enabled()
        assert export.evaluate("element => document.activeElement === element")
        page.locator(".note-edit").first.click()
        page.locator("#note-cancel").click()
        assert export.evaluate("element => document.activeElement === element")
        page.locator(".note-edit").first.click()
        save.click()
        assert export.evaluate("element => document.activeElement === element")
        page.evaluate("""() => {
          while (document.querySelectorAll('.note-text').length > 3) {
            Array.from(document.querySelectorAll('.note-delete')).at(-1).click();
          }
        }""")
        assert capture.is_enabled()
        checks.append("100-note cap and edit/cancel keep focus on an enabled control")

        # A media failure disables new positions/navigation, but permits existing notes to be exported.
        audio.evaluate("audio => audio.dispatchEvent(new Event('error'))")
        assert capture.is_disabled()
        assert page.locator(".note-seek").first.is_disabled()
        assert export.is_enabled()
        page.locator(".note-edit").first.click()
        page.locator("#note-cancel").click()
        assert export.evaluate("element => document.activeElement === element")
        checks.append("media failure preserves notes and export while disabling new anchors")

        page.locator("#review").scroll_into_view_if_needed()
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "review-desktop.png"), full_page=True)
            (screenshots / "synthetic-review-notes.json").write_bytes(data)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        if screenshots:
            page.screenshot(path=str(screenshots / "review-narrow.png"), full_page=True)
        assert page.evaluate("localStorage.length === 0 && sessionStorage.length === 0")
        assert not errors, errors
        assert not external, "Unexpected external request"
        checks.append("narrow layout, no storage, no script errors or external requests")

        # Restore the actual downloaded bytes through the public Python API.
        page.close()
        restored, restored_receipt, _, _ = synthetic_preview(review_notes=data)
        payload[0] = restored.decode("utf-8")
        page = context.new_page()
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        capture, save = page.locator("#note-capture"), page.locator("#note-save")
        text, export = page.locator("#note-text"), page.locator("#note-export")
        audio = page.locator("#audio")
        assert page.locator(".note-text").all_text_contents() == [note["text"] for note in loaded["notes"]]
        assert page.locator(".note-seek").all_text_contents() == [
            "0:01.234 / 字幕 1", "0:02.700 / 字幕のない位置", "0:24.000 / 字幕のない位置"]
        assert "3 / 100" in page.locator("#note-count").text_content()
        assert "読み込みました" in page.locator("#note-status").text_content()
        assert capture.is_enabled() and export.is_enabled()
        assert audio.evaluate("audio => audio.paused && audio.currentTime === 0")
        assert page.evaluate("document.activeElement === document.body")
        assert page.locator("img, iframe").count() == 0
        assert len(downloads) == 1
        assert restored_receipt["html"] != receipt["html"]
        assert not restored_receipt["human_reviewed"]
        checks.append("downloaded JSON restores literal text, order and anchors without playback, focus or download side effects")

        page.locator("#transcript-search summary").click()
        page.locator("#search-query").fill("<img")
        page.locator("#search-query").press("Enter")
        page.locator(".search-result").click()
        wait_condition(page, "Math.abs(document.getElementById('audio').currentTime - 1) < .001")
        assert page.locator(".note-text").all_text_contents() == [note["text"] for note in loaded["notes"]]
        assert len(downloads) == 1
        checks.append("search in a restored preview leaves notes unchanged and triggers no export")

        with page.expect_download() as requested:
            export.click()
        restored_data = Path(requested.value.path()).read_bytes()
        assert requested.value.failure() is None
        assert review.load_review_notes(restored_data, candidate=candidate, transcript=transcript,
            project_id=candidate["project_id"], expected_fingerprint=receipt["candidate_fingerprint"]) == loaded
        checks.append("unchanged restored notes export the same validated document")

        page.locator(".note-edit").first.click()
        text.fill(loaded["notes"][0]["text"] + "\nRestored edit.")
        save.click()
        page.locator(".note-delete").nth(1).click()
        page.locator(".note-seek").first.focus()
        page.keyboard.press("Enter")
        wait_condition(page, "Math.abs(document.getElementById('audio').currentTime - 1.234) < .001")
        assert audio.evaluate("audio => audio.paused")
        assert page.locator(".note-seek").first.evaluate("element => document.activeElement === element")
        seek(2.7)
        capture.click()
        text.fill("Replacement gap note.")
        save.click()
        with page.expect_download() as requested:
            export.click()
        edited_data = Path(requested.value.path()).read_bytes()
        assert requested.value.failure() is None
        edited = review.load_review_notes(edited_data, candidate=candidate, transcript=transcript,
            project_id=candidate["project_id"], expected_fingerprint=receipt["candidate_fingerprint"])
        assert edited == {**loaded, "notes": [
            {**loaded["notes"][0], "text": loaded["notes"][0]["text"] + "\nRestored edit."},
            loaded["notes"][2], {"at_ms": 2700, "cue_id": None, "text": "Replacement gap note."}]}
        assert len(downloads) == 3
        checks.append("restored notes can be edited, deleted, navigated and appended with a valid new export")

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.evaluate("localStorage.length === 0 && sessionStorage.length === 0")
        if screenshots:
            page.screenshot(path=str(screenshots / "review-restored-narrow.png"), full_page=True)
            (screenshots / "synthetic-restored-notes.json").write_bytes(edited_data)
        page.close()
        page = context.new_page()
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        assert page.locator(".note-text").all_text_contents() == [note["text"] for note in loaded["notes"]]
        assert page.locator("#audio").evaluate("audio => audio.paused && audio.currentTime === 0")
        assert len(downloads) == 3
        checks.append("reopening HTML restores its embedded snapshot without persisting later edits or playback position")

        page.close()
        full = {**loaded, "notes": [loaded["notes"][0]] * 100}
        payload[0] = synthetic_preview(review_notes=json.dumps(full, ensure_ascii=False).encode())[0].decode()
        page = context.new_page()
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        assert page.locator(".note-text").count() == 100
        assert page.locator("#note-capture").is_disabled()
        assert page.locator("#note-export").is_enabled()
        page.locator(".note-edit").first.click()
        page.locator("#note-cancel").click()
        assert page.locator("#note-export").evaluate("element => document.activeElement === element")
        page.locator(".note-delete").last.click()
        assert page.locator("#note-capture").is_enabled()
        checks.append("a full restored snapshot enforces the count limit while retaining edit and delete controls")

        page.evaluate("""() => {
          while (document.querySelector('.note-delete')) {
            document.querySelector('.note-delete').click();
          }
        }""")
        assert page.locator("#note-export").is_enabled()
        assert page.evaluate("""() => {
          const event = new Event('beforeunload', {cancelable: true});
          window.dispatchEvent(event);
          return event.defaultPrevented;
        }""")
        with page.expect_download() as requested:
            page.locator("#note-export").click()
        cleared_data = Path(requested.value.path()).read_bytes()
        assert requested.value.failure() is None
        assert review.load_review_notes(cleared_data, candidate=candidate, transcript=transcript,
            project_id=candidate["project_id"], expected_fingerprint=receipt["candidate_fingerprint"]) == {
                **loaded, "notes": []}
        checks.append("deleting every restored note permits an empty export and retains the unload warning")

        page.close()
        payload[0] = synthetic_preview(review_notes=cleared_data)[0].decode()
        page = context.new_page()
        page.goto(url)
        wait_condition(page, "document.getElementById('audio').readyState >= 2")
        assert page.locator(".note-text").count() == 0
        assert page.locator("#note-capture").is_enabled()
        assert page.locator("#note-export").is_disabled()
        assert len(downloads) == 4
        checks.append("an empty restored snapshot starts with normal capture and no export")

        page.close()
        payload[0] = player.render_demo()
        demo = context.new_page()
        demo.goto(url)
        wait_condition(demo, "document.getElementById('audio').readyState >= 2")
        assert demo.locator("#review").count() == 0
        checks.append("standalone synthetic demo retains its playback-only scope")
        assert not errors, errors
        assert not external, "Unexpected external request"
        print(f"Chromium {browser.version}: {len(checks)} review browser checks passed")
        for item in checks:
            print("PASS:", item)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", required=True)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    check(args.browser_executable, args.screenshots)
