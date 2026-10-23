"""Render a self-contained synthetic audio player demo to standard output."""
from __future__ import annotations

import base64
import hashlib
import io
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
    # Script data is a raw-text HTML context even when its MIME type is JSON.
    text = canonical_transcript_bytes(document).decode("utf-8")
    return (text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_demo() -> str:
    """Return only the built-in synthetic demo; no caller media, paths or URLs."""
    transcript, wav = synthetic_fixture()
    script = (SOURCE_ROOT / "player/player.js").read_text(encoding="utf-8")
    style = (SOURCE_ROOT / "player/player.css").read_text(encoding="utf-8")
    def digest(source):
        return base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii")
    policy = ("default-src 'none'; base-uri 'none'; form-action 'none'; "
              f"script-src 'sha256-{digest(script)}'; style-src 'sha256-{digest(style)}'; "
              "media-src data:; connect-src 'none'; object-src 'none'")
    payload = _json_for_html(transcript)
    audio_data = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{policy}">
<meta name="referrer" content="no-referrer">
<title>NarraDock — 音声と字幕のデモ</title>
<style>{style}</style>
</head>
<body>
<main>
<header><div class="brand">NarraDock<span aria-hidden="true"> /</span></div><span class="badge">PLAYER DEMO</span></header>
<section class="intro" aria-labelledby="title">
<div class="eyebrow">LISTEN &amp; FOLLOW</div>
<h1 id="title"><span>音と字幕の</span><span>タイミングを試す。</span></h1>
<p class="description">24秒のテスト音と字幕で、再生位置の移動や追従を確認できます。<br>字幕を選んで移動しても、再生は自動で始まりません。</p>
</section>
<div class="workspace">
<section class="panel" aria-labelledby="audio-title">
<h2 id="audio-title">テスト音声</h2>
<div class="signal" aria-hidden="true">{('<i></i>' * 19)}</div>
<audio id="audio" controls preload="metadata" aria-label="テスト音声の再生コントロール"></audio>
<div id="clock" class="clock" aria-label="再生位置と長さ">0:00 / 0:24</div>
<div class="rate-row"><label for="rate">再生速度</label><select id="rate">
<option value="0.75">0.75×</option><option value="1" selected>1×（標準）</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option>
</select></div>
<p class="hint">音は字幕の開始位置を示す短い合図です。<br>文章の読み上げではありません。</p>
</section>
<section class="panel" aria-labelledby="transcript-title">
<div class="transcript-head"><h2 id="transcript-title">字幕</h2><label class="follow-control"><input id="follow" type="checkbox" checked>自動追従</label></div>
<ol id="transcript" class="transcript" tabindex="0" aria-label="字幕一覧。項目を選ぶとその時刻へ移動します。"></ol>
<p class="hint">スクロールやキーボード操作で追従を停止。チェックを入れると再開します。</p>
<p id="status" class="status" role="status" aria-live="polite"></p>
</section>
</div>
<footer>合成データによる操作デモです。実際の録音・候補の承認・公開機能は含みません。</footer>
<noscript><p>このデモの再生と字幕操作にはJavaScriptが必要です。</p></noscript>
</main>
<script id="transcript-data" type="application/json">{payload}</script>
<script id="audio-data" type="text/plain">{audio_data}</script>
<script>{script}</script>
</body></html>
'''


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
