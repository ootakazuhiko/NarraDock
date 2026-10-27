"""Render a self-contained synthetic audio player demo to standard output."""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
from pathlib import Path
import struct
import sys
import wave

from narradock_transcript import canonical_transcript_bytes, snapshot_transcript

DURATION_MS = 24000
SAMPLE_RATE = 8000
SOURCE_ROOT = Path(__file__).resolve().parent


def synthetic_fixture() -> tuple[dict, bytes]:
    """Create neutral test tones and their own cues; no example placeholder digest."""
    rows = [
        (1000, 2500, "短いテスト音から始まります。"),
        (3000, 4500, "文章を選ぶと、その位置へ移動できます。"),
        (5000, 6500, "音声の再生位置に合わせて、字幕が切り替わります。"),
        (6500, 8000, "隣り合う字幕は、境界で一つずつ切り替わります。"),
        (9000, 10500, "字幕のない区間では、強調表示が消えます。"),
        (11000, 12500, "速度を変えても、音声の位置を基準にします。"),
        (13000, 14500, "字幕欄を操作すると、自動追従が止まります。"),
        (15000, 16500, "読みたい場所を、自分のペースで確認できます。"),
        (17000, 18500, "自動追従をオンにすると、再生中の字幕へ戻ります。"),
        (19000, 20500, "一時停止しても、選んだ位置を確認できます。"),
        (21000, 22500, "This is a timing demo, not recorded speech."),
        (22500, 23500, "最後の音のあと、静かに終了します。"),
    ]
    samples = bytearray(SAMPLE_RATE * DURATION_MS // 1000 * 2)
    for index, (start, end, _) in enumerate(rows):
        # Quiet 180 ms tones mark cue starts; no speech engine or real recording.
        first = start * SAMPLE_RATE // 1000
        length = min((end - start) * SAMPLE_RATE // 1000, SAMPLE_RATE * 180 // 1000)
        for offset in range(length):
            envelope = min(1, offset / 80, (length - 1 - offset) / 80)
            value = round(1600 * envelope * math.sin(2 * math.pi * (330 + index * 30) * offset / SAMPLE_RATE))
            struct.pack_into("<h", samples, (first + offset) * 2, value)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        output.writeframes(samples)
    wav = stream.getvalue()
    transcript = {"schema_version": "timed-transcript-0.1", "project_id": "player-demo",
        "content_id": "synthetic-timing", "language": "ja",
        "audio": {"asset_id": "demo-tones", "sha256": hashlib.sha256(wav).hexdigest(),
                  "duration_ms": DURATION_MS},
        "cues": [{"id": f"cue-{index}", "start_ms": start, "end_ms": end, "text": text}
                 for index, (start, end, text) in enumerate(rows)]}
    # Identifiers must begin with a letter; numeric suffixes are permitted.
    return snapshot_transcript(transcript), wav


def _json_for_html(document: dict) -> str:
    return _escape_json_for_html(canonical_transcript_bytes(document).decode("utf-8"))


def _escape_json_for_html(text: str) -> str:
    # Script data is a raw-text HTML context even when its MIME type is JSON.
    return (text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _review_json_for_html(candidate: dict, revision: str, notes: list | None = None) -> str:
    """Encode fixed binding fields and already validated notes for script data."""
    from narradock_review import SCHEMA_VERSION as REVIEW_SCHEMA
    binding = {"schema_version": REVIEW_SCHEMA,
        "project_id": candidate["project_id"], "content_id": candidate["content_id"],
        "candidate_fingerprint": revision,
        "transcript_fingerprint": candidate["transcript"]["fingerprint"]}
    if notes is not None:
        binding["notes"] = notes
    return _escape_json_for_html(json.dumps(binding, ensure_ascii=False, sort_keys=True))


def render_demo() -> str:
    """Return only the built-in synthetic demo; no caller media, paths or URLs."""
    return _render_page(*synthetic_fixture()).decode("utf-8")


def _render_page(transcript: dict, wav: bytes, *, candidate: dict | None = None,
                 revision: str = "", payload: str | None = None,
                 review_payload: str | None = None,
                 max_bytes: int | None = None) -> bytes:
    """Internal renderer for fixed demo or previously verified preview inputs."""
    script = (SOURCE_ROOT / "player/player.js").read_text(encoding="utf-8")
    style = (SOURCE_ROOT / "player/player.css").read_text(encoding="utf-8")
    def digest(source):
        return base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii")
    policy = ("default-src 'none'; base-uri 'none'; form-action 'none'; "
              f"script-src 'sha256-{digest(script)}'; style-src 'sha256-{digest(style)}'; "
              "media-src data:; connect-src 'none'; object-src 'none'")
    payload = _json_for_html(transcript) if payload is None else payload
    preview = candidate is not None
    language = html.escape(transcript["language"], quote=True)
    page_title = "音声候補のプレビュー" if preview else "音声と字幕のデモ"
    badge = "LOCAL PREVIEW" if preview else "PLAYER DEMO"
    heading = html.escape(candidate["metadata"]["title"]) if preview else "<span>音と字幕の</span><span>タイミングを試す。</span>"
    description = ("音声と字幕を視聴して確認するためのプレビューです。<br>字幕を選んで移動しても、再生は自動で始まりません。"
                   if preview else "24秒のテスト音と字幕で、再生位置の移動や追従を確認できます。<br>字幕を選んで移動しても、再生は自動で始まりません。")
    audio_title = "音声" if preview else "テスト音声"
    audio_hint = ("字幕の位置や内容は、音声を聴いて確認してください。" if preview else
                  "音は字幕の開始位置を示す短い合図です。<br>文章の読み上げではありません。")
    footer = ("視聴確認用のローカルプレビューです。承認の記録や公開は行いません。" if preview else
              "合成データによる操作デモです。実際の録音・候補の承認・公開機能は含みません。")
    identity = ""
    review = ""
    if preview:
        credits = "".join("<li>" + html.escape(credit) + "</li>" for credit in candidate["metadata"]["credits"])
        identity = (f'<details class="identity"><summary>候補の識別情報とクレジット</summary>'
                    f'<p>プロジェクト: {html.escape(candidate["project_id"])} / コンテンツ: {html.escape(candidate["content_id"])}</p>'
                    f'<code>{html.escape(revision)}</code><ul lang="{language}">{credits}</ul></details>')
        binding = (_review_json_for_html(candidate, revision)
                   if review_payload is None else review_payload)
        review = f'''<section id="review" class="panel review" aria-labelledby="review-title">
<div class="review-head"><h2 id="review-title" tabindex="-1">視聴メモ</h2><span id="note-count">0 / 100 件</span></div>
<p class="hint">気になった位置にメモを残せます。この画面での変更は自動保存されません。JSONで保存してください。承認の記録にはなりません。</p>
<button id="note-capture" type="button" disabled>この位置にメモ</button>
<div id="note-editor" hidden>
<p id="note-anchor" class="note-anchor"></p>
<label for="note-text">メモの内容</label>
<textarea id="note-text" rows="3" maxlength="2000" aria-describedby="note-limit note-anchor"></textarea>
<p id="note-limit" class="hint">0 / 1,000 文字</p>
<div class="note-actions"><button id="note-save" type="button" disabled>メモを追加</button>
<button id="note-cancel" type="button">取り消し</button></div>
</div>
<ol id="note-list" class="note-list" aria-label="視聴メモ一覧"></ol>
<button id="note-export" type="button" disabled>メモをJSONで保存</button>
<p id="note-status" class="status" role="status" aria-live="polite"></p>
</section>
<script id="review-data" type="application/json">{binding}</script>'''
    seconds = transcript["audio"]["duration_ms"] // 1000
    duration = f"{seconds // 60}:{seconds % 60:02d}"
    prefix = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{policy}">
<meta name="referrer" content="no-referrer">
<title>NarraDock — {page_title}</title>
<style>{style}</style>
</head>
<body>
<main>
<header><div class="brand">NarraDock<span aria-hidden="true"> /</span></div><span class="badge">{badge}</span></header>
<section class="intro" aria-labelledby="title">
<div class="eyebrow">LISTEN &amp; FOLLOW</div>
<h1 id="title" lang="{language}">{heading}</h1>
<p class="description">{description}</p>
{identity}
</section>
<div class="workspace">
<section class="panel" aria-labelledby="audio-title">
<h2 id="audio-title">{audio_title}</h2>
<div class="signal" aria-hidden="true">{('<i></i>' * 19)}</div>
<audio id="audio" controls preload="metadata" aria-label="{audio_title}の再生コントロール"></audio>
<div id="clock" class="clock" aria-label="再生位置と長さ">0:00 / {duration}</div>
<div class="rate-row"><label for="rate">再生速度</label><select id="rate">
<option value="0.75">0.75×</option><option value="1" selected>1×（標準）</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option>
</select></div>
<p class="hint">{audio_hint}</p>
</section>
<section class="panel" aria-labelledby="transcript-title">
<div class="transcript-head"><h2 id="transcript-title">字幕</h2><label class="follow-control"><input id="follow" type="checkbox" checked>自動追従</label></div>
<details id="transcript-search" class="transcript-search">
<summary>字幕を検索</summary>
<label for="search-query">検索する言葉</label>
<div class="search-controls"><input id="search-query" type="search" maxlength="200" autocomplete="off" spellcheck="false" aria-describedby="search-help">
<button id="search-submit" type="button">検索</button><button id="search-clear" type="button">クリア</button></div>
<p id="search-help" class="hint">100文字以内。大文字・小文字や空白を区別して部分一致で探します。Enterでも検索できます。</p>
<p id="search-status" class="status" role="status" aria-live="polite"></p>
<ol id="search-results" lang="{language}" class="search-results" aria-label="字幕の検索結果"></ol>
</details>
<ol id="transcript" lang="{language}" class="transcript" tabindex="0" aria-label="字幕一覧。項目を選ぶとその時刻へ移動します。"></ol>
<p class="hint">スクロールやキーボード操作で追従を停止。チェックを入れると再開します。</p>
<p id="status" class="status" role="status" aria-live="polite"></p>
</section>
</div>
{review}
<footer>{footer}</footer>
<noscript><p>再生と字幕操作にはJavaScriptが必要です。</p></noscript>
</main>
<script id="transcript-data" type="application/json">'''
    # Keep the large base64 section as ASCII bytes, even with non-BMP cue text.
    parts = [prefix.encode("utf-8"), payload.encode("utf-8"),
             b'</script>\n<script id="audio-data" type="text/plain">data:audio/wav;base64,',
             base64.b64encode(wav), b"</script>\n<script>", script.encode("utf-8"),
             b"</script>\n</body></html>\n"]
    if max_bytes is not None and sum(len(part) for part in parts) > max_bytes:
        raise ValueError("Player page exceeds output limit")
    return b"".join(parts)


def main(argv: list[str] | None = None) -> int:
    if (sys.argv[1:] if argv is None else argv):
        print("The synthetic player accepts no input arguments", file=sys.stderr)
        return 2
    try:
        sys.stdout.buffer.write(render_demo().encode("utf-8"))
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        print("Synthetic player could not be rendered", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
