"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {activeCueIndex, formatTime, createController} = require("../player/player.js");
const {NOTE_LIMITS, validNoteText, noteAnchor, createReviewNotes} = require("../player/player.js");
const {searchCueIndices, SEARCH_QUERY_LIMIT} = require("../player/player.js");
const noteCases = require("./fixtures/review-notes-cases.json");

const cues = [
  {start_ms: 1000, end_ms: 2000},
  {start_ms: 2000, end_ms: 3000},
  {start_ms: 4000, end_ms: 5000}
];

test("transcript search returns each matching cue once in transcript order", () => {
  const source = [{text: "音の確認。音が続きます。"}, {text: "別の字幕。"}, {text: "音の終わり。"}];
  assert.deepEqual(searchCueIndices(source, "音"), [0, 2]);
  assert.deepEqual(searchCueIndices(source, "見つからない"), []);
  assert.deepEqual(searchCueIndices(source, "音の確認。音"), [0]);
});

test("search treats markup and regular expression symbols as literal text", () => {
  const source = [{text: '</script><img src=x onerror="alert(1)"> & .* [x] 🎵'}, {text: "anything"}];
  for (const query of ["</script>", "<img", "&", ".*", "[x]", "🎵"]) {
    assert.deepEqual(searchCueIndices(source, query), [0]);
  }
  assert.deepEqual(searchCueIndices(source, "^.*$"), []);
});

test("search preserves case, spaces and Unicode distinctions without crossing cue boundaries", () => {
  const source = [{text: "ABC abc"}, {text: "abc next"}, {text: "e\u0301 é Ａ A"}];
  assert.deepEqual(searchCueIndices(source, "ABC"), [0]);
  assert.deepEqual(searchCueIndices(source, "Abc"), []);
  assert.deepEqual(searchCueIndices(source, " abc"), [0]);
  assert.deepEqual(searchCueIndices(source, "abc "), [1]);
  assert.deepEqual(searchCueIndices(source, "abcabc"), []);
  assert.deepEqual(searchCueIndices([{text: "e\u0301 Ａ"}], "é"), []);
  assert.deepEqual(searchCueIndices([{text: "e\u0301 Ａ"}], "A"), []);
  for (const empty of ["", "  ", "\t\n", "\u3000"]) assert.deepEqual(searchCueIndices(source, empty), []);
});

test("search query bounds count Unicode code points and reject without truncating", () => {
  for (const unit of ["x", "🎵"]) {
    const query = unit.repeat(SEARCH_QUERY_LIMIT);
    assert.deepEqual(searchCueIndices([{text: query}], query), [0]);
    assert.throws(() => searchCueIndices([{text: query}], query + unit), /^Error: Invalid search query$/);
  }
  for (const bad of [null, 3, [], {}, "x".repeat(10000), "\ud83c", "\udfb5", "音\ud83c"]) {
    assert.throws(() => searchCueIndices([{text: "音🎵"}], bad), /^Error: Invalid search query$/);
  }
});

test("search does not mutate cues, reuse another page's results or truncate matching cues", () => {
  const source = Array.from({length: 1000}, (_, i) => Object.freeze({id: `cue-${i}`, text: "Match"}));
  Object.freeze(source);
  const results = searchCueIndices(source, "Match");
  assert.equal(results.length, 1000);
  assert.equal(results.at(-1), 999);
  results.length = 0;
  assert.deepEqual(searchCueIndices([{id: "cue-0", text: "Different"}], "Match"), []);
  assert.equal(searchCueIndices(source, "Match").length, 1000);
});

function noteFixture() {
  const binding = {schema_version: "candidate-review-notes-0.1", project_id: "sample-project",
    content_id: "sample-content", candidate_fingerprint: "a".repeat(64), transcript_fingerprint: "b".repeat(64)};
  const transcript = {audio: {duration_ms: 6000}, cues: cues.map((cue, i) =>
    ({...cue, id: ["first", "second", "last"][i]}))};
  return {binding, transcript, model: createReviewNotes(binding, transcript)};
}

test("review text uses shared Unicode conformance cases", () => {
  for (const item of noteCases.text_cases) {
    assert.equal(validNoteText(item.text), item.valid, item.name);
  }
});

test("review text limits count Unicode code points without truncation", () => {
  for (const char of ["x", "🎵"]) {
    assert.equal(validNoteText(char.repeat(1000)), true);
    assert.equal(validNoteText(char.repeat(1001)), false);
  }
});

test("note anchor floors media time and uses shared half-open cue boundaries", () => {
  const {transcript} = noteFixture();
  for (const expected of noteCases.anchor_cases) {
    assert.deepEqual(noteAnchor(transcript.cues, 6000, expected.at_ms / 1000), expected);
  }
  assert.deepEqual(noteAnchor(transcript.cues, 6000, 1.9999), {at_ms: 1999, cue_id: "first"});
  assert.deepEqual(noteAnchor(transcript.cues, 6000, 7), {at_ms: 6000, cue_id: null});
  for (const seconds of [NaN, Infinity, -1, "1", null]) {
    assert.throws(() => noteAnchor(transcript.cues, 6000, seconds));
  }
});

test("note edit preserves the anchor and order; removal uses stable internal IDs", () => {
  const {model} = noteFixture();
  model.save({at_ms: 4000, cue_id: "last"}, "Later first.");
  model.save({at_ms: 1000, cue_id: "first"}, "Earlier second.");
  const [later, earlier] = model.entries();
  model.save(later, "Edited.", later.id);
  assert.deepEqual(model.entries().map(note => note.at_ms), [4000, 1000]);
  model.remove(later.id);
  assert.equal(model.entries()[0].id, earlier.id);
  model.save({at_ms: 6000, cue_id: null}, "End.");
  assert.notEqual(model.entries()[1].id, later.id);
  assert.throws(() => model.save(later, "Deleted.", later.id));
});

test("millisecond seeks resist representation noise without rounding genuinely earlier positions", () => {
  const precise = [{id: "first", start_ms: 1001, end_ms: 2001},
    {id: "second", start_ms: 2001, end_ms: 3000}];
  assert.deepEqual(noteAnchor(precise, 6000, 1001 / 1000), {at_ms: 1001, cue_id: "first"});
  assert.deepEqual(noteAnchor(precise, 6000, 1.0009), {at_ms: 1000, cue_id: null});
  assert.deepEqual(noteAnchor(precise, 6000, 2001 / 1000), {at_ms: 2001, cue_id: "second"});
  const f = fixture({sampleCues: precise});
  for (const [seconds, active] of [[1.001, 0], [1.0009, -1], [2.001, 1], [2.0009, 0]]) {
    f.controller.seek(seconds);
    assert.equal(f.last().active, active, String(seconds));
  }
});

test("note selection and saved records do not follow caller mutations", () => {
  const {model, binding, transcript} = noteFixture();
  const anchor = {at_ms: 1500, cue_id: "first"};
  model.save(anchor, "Fixed position.");
  const expected = model.serialize();
  anchor.at_ms = 4500;
  binding.candidate_fingerprint = "c".repeat(64);
  transcript.cues[0].id = "changed";
  model.entries()[0].text = "Changed outside model";
  assert.equal(model.serialize(), expected);
});

test("invalid note positions and text never change the record", () => {
  const {model} = noteFixture();
  for (const at_ms of [true, -1, 6001, 1500.5, "1500", NaN, Infinity]) {
    assert.throws(() => model.save({at_ms, cue_id: "first"}, "Note."));
  }
  for (const cue_id of [null, "second", true, 0]) {
    assert.throws(() => model.save({at_ms: 1500, cue_id}, "Note."));
  }
  assert.throws(() => model.save({at_ms: 1500, cue_id: "first"}, " "));
  assert.deepEqual(model.entries(), []);
});

test("100-note boundary permits edits and reuse after deletion", () => {
  const {model} = noteFixture();
  for (let i = 0; i < NOTE_LIMITS.count; i++) model.save({at_ms: 0, cue_id: null}, "🎵".repeat(1000));
  const first = model.entries()[0];
  model.save(first, "Updated.", first.id);
  assert.throws(() => model.save({at_ms: 0, cue_id: null}, "One more."));
  assert.ok(new TextEncoder().encode(model.serialize()).length <= NOTE_LIMITS.bytes);
  model.remove(first.id);
  model.save({at_ms: 6000, cue_id: null}, "Replacement.");
  assert.equal(model.entries().length, NOTE_LIMITS.count);
});

test("JSON export preserves literal text, contains only binding and notes, and is repeatable", () => {
  const {model, binding} = noteFixture();
  const text = '</script><img src=x onerror="alert(1)">\n🎵';
  model.save({at_ms: 1500, cue_id: "first"}, text);
  const output = JSON.parse(model.serialize());
  assert.deepEqual(output, {...binding, notes: [{at_ms: 1500, cue_id: "first", text}]});
  assert.equal(model.serialize(), model.serialize());
  model.remove(model.entries()[0].id);
  assert.deepEqual(JSON.parse(model.serialize()), {...binding, notes: []});
});

test("restored notes retain order/text and can be edited, removed and extended", () => {
  const {binding, transcript} = noteFixture();
  const saved = [{at_ms: 4000, cue_id: "last", text: "Later first.\n🎵"},
    {at_ms: 1500, cue_id: "first", text: "Earlier second."},
    {at_ms: 6000, cue_id: null, text: "End."}];
  const model = createReviewNotes(binding, transcript, saved);
  assert.deepEqual(JSON.parse(model.serialize()), {...binding, notes: saved});
  const first = model.entries()[0];
  model.save(first, "Edited.", first.id);
  model.remove(model.entries()[1].id);
  model.save({at_ms: 0, cue_id: null}, "New note.");
  assert.deepEqual(JSON.parse(model.serialize()).notes.map(note => note.at_ms), [4000, 6000, 0]);
  assert.equal(new Set(model.entries().map(note => note.id)).size, 3);
  assert.equal(saved[0].text, "Later first.\n🎵");
  saved[0].text = "Changed source";
  assert.equal(model.entries()[0].text, "Edited.");
});

test("invalid initial notes fail before a model is returned", () => {
  const {binding, transcript} = noteFixture();
  const good = {at_ms: 1500, cue_id: "first", text: "Note."};
  for (const bad of [null, {}, [null], [{}], [good, {...good, cue_id: null}],
    [{...good, extra: true}], [{...good, text: ""}], Array(101).fill(good)]) {
    assert.throws(() => createReviewNotes(binding, transcript, bad));
  }
  assert.deepEqual(createReviewNotes(binding, transcript, []).entries(), []);
});

test("100 restored notes preserve the cap and allow edits and replacement", () => {
  const {binding, transcript} = noteFixture();
  const saved = Array.from({length: 100}, () => ({at_ms: 1500, cue_id: "first", text: "🎵".repeat(1000)}));
  const model = createReviewNotes(binding, transcript, saved);
  assert.equal(model.entries().length, 100);
  assert.throws(() => model.save(saved[0], "Overflow"));
  const first = model.entries()[0];
  model.save(first, "Edited.", first.id);
  model.remove(first.id);
  model.save({at_ms: 0, cue_id: null}, "Replacement.");
  assert.equal(model.entries().length, 100);
  assert.equal(new Set(model.entries().map(note => note.id)).size, 100);
});

function fixture({loaded = true, sampleCues = cues} = {}) {
  const media = new EventTarget();
  Object.assign(media, {currentTime: 0, duration: 6, paused: true, ended: false, playbackRate: 1});
  media.pause = () => { media.paused = true; media.dispatchEvent(new Event("pause")); };
  const states = [], follows = [], messages = [];
  const frames = new Map();
  let sequence = 0;
  let isVisible = true;
  const controller = createController({
    media, cues: sampleCues, durationMs: 6000,
    view: {
      render: state => states.push(state), follow: index => follows.push(index),
      announce: message => messages.push(message)
    },
    requestFrame: callback => { const id = ++sequence; frames.set(id, callback); return id; },
    cancelFrame: id => frames.delete(id), visible: () => isVisible
  });
  const emit = name => media.dispatchEvent(new Event(name));
  if (loaded) emit("loadedmetadata");
  return {media, controller, states, follows, messages, frames, emit,
    last: () => states.at(-1),
    visible(value) { isVisible = value; controller.visibilityChanged(); },
    tick() { const [id, callback] = frames.entries().next().value; frames.delete(id); callback(); }
  };
}

test("half-open cues respect leading/internal/trailing gaps and adjacency", () => {
  for (const [time, expected] of [[0,-1],[999.9,-1],[1000,0],[1999.9,0],[2000,1],
    [2999.9,1],[3000,-1],[3999.9,-1],[4000,2],[5000,-1],[6000,-1]]) {
    assert.equal(activeCueIndex(cues, time), expected, String(time));
  }
});

test("invalid clock and empty cue list never activate a cue", () => {
  for (const time of [NaN, Infinity, -Infinity, -1, undefined, "1000"]) {
    assert.equal(activeCueIndex(cues, time), -1);
  }
  assert.equal(activeCueIndex([], 1000), -1);
});

test("clock formats elapsed whole seconds without accumulating ticks", () => {
  assert.equal(formatTime(0), "0:00");
  assert.equal(formatTime(59999), "0:59");
  assert.equal(formatTime(60000), "1:00");
  assert.equal(formatTime(3600000), "60:00");
});

test("controls wait for metadata and never initiate playback", () => {
  const f = fixture({loaded:false});
  assert.equal(f.last().ready, false);
  f.controller.seek(2);
  f.controller.setRate(2);
  assert.equal(f.media.currentTime, 0);
  assert.equal(f.media.playbackRate, 1);
  f.emit("loadedmetadata");
  assert.equal(f.last().ready, true);
  assert.equal(f.media.paused, true);
  assert.equal(f.frames.size, 0);
});

test("seek clamps to the timeline and preserves paused state", () => {
  const f = fixture();
  f.controller.seek(2);
  assert.equal(f.last().active, 1);
  assert.equal(f.media.paused, true);
  f.controller.seek(-10);
  assert.equal(f.media.currentTime, 0);
  f.controller.seek(100);
  assert.equal(f.media.currentTime, 6);
  assert.equal(f.last().active, -1);
  f.controller.seek(NaN);
  assert.equal(f.media.currentTime, 6);
});

test("seek while playing preserves playback", () => {
  const f = fixture();
  f.media.paused = false;
  f.emit("play");
  f.controller.seek(4.5);
  assert.equal(f.media.paused, false);
  assert.equal(f.last().active, 2);
});

test("every media clock event recomputes highlight from currentTime", () => {
  for (const event of ["timeupdate", "seeking", "seeked", "play", "pause", "ratechange"]) {
    const f = fixture();
    f.media.currentTime = 2.5;
    f.emit(event);
    assert.equal(f.last().active, 1, event);
    f.media.currentTime = 3.5;
    f.emit(event);
    assert.equal(f.last().active, -1, event);
  }
});

test("animation callbacks read the media clock without advancing it", () => {
  const f = fixture();
  f.media.paused = false;
  f.media.currentTime = 1.5;
  f.emit("play");
  f.emit("play");
  assert.equal(f.frames.size, 1);
  for (let index=0; index<20; index++) f.tick();
  assert.equal(f.media.currentTime, 1.5);
  assert.equal(f.last().elapsedMs, 1500);
  f.media.currentTime = 4.5;
  f.tick();
  assert.equal(f.last().active, 2);
});

test("pause cancels animation but retains cue at the stopped position", () => {
  const f = fixture();
  f.media.paused = false;
  f.media.currentTime = 1.5;
  f.emit("play");
  f.media.pause();
  assert.equal(f.frames.size, 0);
  assert.equal(f.last().active, 0);
});

test("rate changes do not multiply cue time or trigger playback", () => {
  const f = fixture();
  f.controller.seek(2.5);
  for (const rate of [0.75,1,1.25,1.5,2]) {
    f.controller.setRate(rate);
    assert.equal(f.media.playbackRate, rate);
    assert.equal(f.last().active, 1);
    assert.equal(f.media.paused, true);
  }
  for (const rate of [0, -1, 4, NaN, "1"]) f.controller.setRate(rate);
  assert.equal(f.media.playbackRate, 2);
});

test("native rate changes are reflected without retiming the clock", () => {
  const f = fixture();
  f.controller.seek(2.5);
  for (const rate of [0.5, 1.5, 1.75]) {
    f.media.playbackRate = rate;
    f.emit("ratechange");
    assert.equal(f.last().playbackRate, rate);
    assert.equal(f.last().elapsedMs, 2500);
    assert.equal(f.last().active, 1);
  }
});

test("media reload clears ready state, cancels frames and blocks seeks until metadata", () => {
  for (const event of ["emptied", "loadstart"]) {
    const f = fixture();
    f.media.paused = false;
    f.media.currentTime = 1.5;
    f.emit("play");
    f.media.currentTime = 0;
    f.media.duration = NaN;
    f.emit(event);
    assert.equal(f.last().ready, false);
    assert.equal(f.last().active, -1);
    assert.equal(f.frames.size, 0);
    f.emit("play");
    assert.equal(f.frames.size, 0);
    f.controller.seek(4.5);
    assert.equal(f.media.currentTime, 0);
    f.media.duration = 6;
    f.emit("loadedmetadata");
    assert.equal(f.last().ready, true);
    f.controller.seek(4.5);
    assert.equal(f.last().active, 2);
  }
});

test("rate setter exceptions produce a fixed error state", () => {
  const f = fixture();
  Object.defineProperty(f.media, "playbackRate", {get:()=>1, set:()=>{throw new Error("private");}});
  f.controller.setRate(2);
  assert.equal(f.last().unavailable, true);
  assert.ok(!f.messages[0].includes("private"));
});

test("hidden document cancels frames and foreground resynchronizes", () => {
  const f = fixture();
  f.media.paused = false;
  f.emit("play");
  f.visible(false);
  assert.equal(f.frames.size, 0);
  f.media.currentTime = 4.5;
  f.visible(true);
  assert.equal(f.last().active, 2);
  assert.equal(f.frames.size, 1);
});

test("follow happens on cue changes, not every frame", () => {
  const f = fixture();
  f.controller.seek(1.5);
  f.controller.sync();
  f.controller.sync();
  assert.deepEqual(f.follows, [0]);
  f.controller.seek(2);
  assert.deepEqual(f.follows, [0,1]);
});

test("manual navigation suspends follow until explicit re-enable", () => {
  const f = fixture();
  f.controller.seek(1.5);
  f.controller.manualScroll();
  f.controller.manualScroll();
  f.controller.seek(4.5);
  assert.equal(f.last().following, false);
  assert.deepEqual(f.follows, [0]);
  assert.equal(f.messages.length, 1);
  f.controller.setFollowing(true);
  assert.deepEqual(f.follows, [0,2]);
  assert.equal(f.last().following, true);
});

test("explicit follow off still updates highlight and clock", () => {
  const f = fixture();
  f.controller.setFollowing(false);
  f.controller.seek(4.5);
  assert.equal(f.last().elapsedMs, 4500);
  assert.equal(f.last().active, 2);
  assert.deepEqual(f.follows, []);
});

test("ended clears highlight and stops frames even with a stale cue clock", () => {
  const f = fixture();
  f.media.paused = false;
  f.media.currentTime = 2.5;
  f.emit("play");
  f.media.ended = true;
  f.emit("ended");
  assert.equal(f.last().active, -1);
  assert.equal(f.frames.size, 0);
});

test("invalid media times clear rather than choosing the first cue", () => {
  const f = fixture();
  for (const time of [NaN, Infinity, -1]) {
    f.media.currentTime = time;
    f.controller.sync();
    assert.equal(f.last().active, -1);
  }
});

test("media failure stops playback, clears highlight and blocks navigation", () => {
  const f = fixture();
  f.media.currentTime = 1.5;
  f.media.paused = false;
  f.emit("play");
  f.emit("error");
  assert.equal(f.media.paused, true);
  assert.equal(f.last().active, -1);
  assert.equal(f.last().unavailable, true);
  assert.equal(f.frames.size, 0);
  f.controller.seek(4.5);
  assert.equal(f.media.currentTime, 1.5);
  assert.equal(f.messages.length, 1);
});

test("unexpected decoded duration fails closed", () => {
  for (const duration of [NaN, Infinity, 0, 5.9, 6.1]) {
    const f = fixture({loaded:false});
    f.media.duration = duration;
    f.emit("loadedmetadata");
    assert.equal(f.last().unavailable, true);
  }
});

test("seek exception becomes a fixed failure state", () => {
  const f = fixture();
  Object.defineProperty(f.media, "currentTime", {get:()=>0, set:()=>{throw new Error("private");}});
  f.controller.seek(2);
  assert.equal(f.last().unavailable, true);
  assert.ok(!f.messages[0].includes("private"));
});

test("destroy removes listeners and cancels scheduled work", () => {
  const f = fixture();
  f.media.paused = false;
  f.emit("play");
  f.controller.destroy();
  const count = f.states.length;
  f.emit("timeupdate");
  f.controller.sync();
  f.controller.seek(4);
  assert.equal(f.states.length, count);
  assert.equal(f.frames.size, 0);
});
