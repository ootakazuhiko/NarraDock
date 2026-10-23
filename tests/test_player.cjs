"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {activeCueIndex, formatTime, createController} = require("../player/player.js");

const cues = [
  {start_ms: 1000, end_ms: 2000},
  {start_ms: 2000, end_ms: 3000},
  {start_ms: 4000, end_ms: 5000}
];

function fixture({loaded = true} = {}) {
  const media = new EventTarget();
  Object.assign(media, {currentTime: 0, duration: 6, paused: true, ended: false, playbackRate: 1});
  media.pause = () => { media.paused = true; media.dispatchEvent(new Event("pause")); };
  const states = [], follows = [], messages = [];
  const frames = new Map();
  let sequence = 0;
  let isVisible = true;
  const controller = createController({
    media, cues, durationMs: 6000,
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
