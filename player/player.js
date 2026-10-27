"use strict";

// This adapter receives the generator's synthetic fixture or verified candidate preview.
function activeCueIndex(cues, milliseconds) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return -1;
  let low = 0;
  let high = cues.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (cues[middle].start_ms <= milliseconds) low = middle + 1;
    else high = middle;
  }
  const index = low - 1;
  return index >= 0 && milliseconds < cues[index].end_ms ? index : -1;
}

function formatTime(milliseconds) {
  const seconds = Math.floor(Math.max(0, milliseconds) / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function mediaMilliseconds(seconds) {
  const value = seconds * 1000;
  const nearest = Math.round(value);
  // A millisecond seek such as 1.001 s can multiply to 1000.9999999999999.
  return Math.abs(value - nearest) <= Number.EPSILON * Math.max(1, Math.abs(value))
    ? nearest : value;
}

const SEARCH_QUERY_LIMIT = 100;

function searchCueIndices(cues, query) {
  if (typeof query !== "string" || query.length > SEARCH_QUERY_LIMIT * 2) {
    throw new Error("Invalid search query");
  }
  const points = [...query];
  if (points.length > SEARCH_QUERY_LIMIT || points.some(char => {
    const code = char.codePointAt(0);
    return code >= 0xd800 && code <= 0xdfff;
  })) {
    throw new Error("Invalid search query");
  }
  if (!query.trim()) return [];
  // Literal, case-sensitive matching within each validated cue; no regex or normalization.
  return cues.flatMap((cue, index) => cue.text.includes(query) ? [index] : []);
}

function mountTranscriptSearch(document, transcript, controller) {
  const input = document.getElementById("search-query");
  const submit = document.getElementById("search-submit");
  const clear = document.getElementById("search-clear");
  const results = document.getElementById("search-results");
  const status = document.getElementById("search-status");
  let available = false;
  let composing = false;
  function reset() {
    results.replaceChildren();
    status.textContent = "";
  }
  function search() {
    if (composing) return;
    reset();
    let indices;
    try { indices = searchCueIndices(transcript.cues, input.value); }
    catch {
      status.textContent = "検索語を確認してください（100文字以内）。";
      return;
    }
    for (const index of indices) {
      const cue = transcript.cues[index];
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";
      button.disabled = !available;
      const time = document.createElement("span");
      time.className = "cue-time";
      time.textContent = `${formatTime(cue.start_ms)}.${String(cue.start_ms % 1000).padStart(3, "0")}`;
      const text = document.createElement("span");
      text.className = "cue-text";
      text.textContent = cue.text;
      button.append(time, text);
      button.setAttribute("aria-label", `${time.textContent} に移動: ${cue.text}`);
      button.addEventListener("click", () => {
        if (!available) return;
        controller.manualScroll();
        controller.seek(cue.start_ms / 1000);
      });
      item.append(button);
      results.append(item);
    }
    status.textContent = !input.value.trim() ? "検索する言葉を入力してください。"
      : indices.length ? `${indices.length}件見つかりました。選ぶとその時刻へ移動します。`
      : "一致する字幕はありません。";
  }
  input.addEventListener("input", reset);
  input.addEventListener("compositionstart", () => { composing = true; reset(); });
  input.addEventListener("compositionend", () => { composing = false; });
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing && event.keyCode !== 229 && !composing) {
      event.preventDefault();
      search();
    }
  });
  submit.addEventListener("click", search);
  clear.addEventListener("click", () => {
    input.value = "";
    reset();
    input.focus();
  });
  results.addEventListener("focusin", () => controller.manualScroll());
  return {setAvailable(value) {
    if (value === available) return;
    available = value;
    results.querySelectorAll("button").forEach(button => { button.disabled = !value; });
  }};
}

function createController({media, cues, durationMs, view, requestFrame, cancelFrame, visible}) {
  let following = true;
  let unavailable = false;
  let ready = false;
  let destroyed = false;
  let previous = -1;
  let frame = null;

  function sync(forceFollow = false) {
    if (destroyed) return;
    const validTime = Number.isFinite(media.currentTime) && media.currentTime >= 0;
    const elapsedMs = validTime
      ? Math.max(0, Math.min(durationMs, mediaMilliseconds(media.currentTime))) : 0;
    const active = !ready || !validTime || unavailable || media.ended || elapsedMs >= durationMs
      ? -1 : activeCueIndex(cues, elapsedMs);
    view.render({active, elapsedMs, durationMs, following, unavailable, ready,
      playbackRate: media.playbackRate});
    if (following && active >= 0 && (forceFollow || active !== previous)) view.follow(active);
    previous = active;
  }

  function stopFrame() {
    if (frame !== null) cancelFrame(frame);
    frame = null;
  }

  function schedule() {
    if (!destroyed && !unavailable && ready && !media.paused && !media.ended && visible() && frame === null) {
      frame = requestFrame(() => {
        frame = null;
        sync();
        schedule();
      });
    }
  }

  function update() {
    sync();
    if (!ready || media.paused || media.ended || !visible()) stopFrame();
    else schedule();
  }

  function fail() {
    unavailable = true;
    stopFrame();
    media.pause();
    sync();
    view.announce("音声を読み込めませんでした。対応するブラウザーで開き直してください。");
  }

  const events = ["timeupdate", "seeking", "seeked", "play", "pause", "ratechange", "ended"];
  events.forEach(name => media.addEventListener(name, update));
  media.addEventListener("error", fail);
  function loaded() {
    // Allow one millisecond for declared-duration rounding and browser representation.
    if (!Number.isFinite(media.duration) || Math.abs(media.duration * 1000 - durationMs) > 1) fail();
    else {
      ready = true;
      update();
    }
  }
  media.addEventListener("loadedmetadata", loaded);
  function reset() {
    ready = false;
    stopFrame();
    sync();
  }
  media.addEventListener("emptied", reset);
  media.addEventListener("loadstart", reset);
  sync();

  return {
    sync: update,
    visibilityChanged: update,
    seek(seconds) {
      if (destroyed || unavailable || !ready || !Number.isFinite(seconds)) return;
      try {
        media.currentTime = Math.min(durationMs / 1000, Math.max(0, seconds));
        sync();
      } catch {
        fail();
      }
    },
    setRate(value) {
      if (destroyed || unavailable || !ready || ![0.75, 1, 1.25, 1.5, 2].includes(value)) return;
      try {
        media.playbackRate = value;
        sync();
      } catch {
        fail();
      }
    },
    setFollowing(value) {
      if (destroyed || unavailable || !ready) return;
      following = Boolean(value);
      sync(following);
      view.announce(following ? "字幕の自動追従を再開しました。" : "字幕の自動追従を停止しました。");
    },
    manualScroll() {
      if (following && !unavailable && !destroyed) this.setFollowing(false);
    },
    destroy() {
      destroyed = true;
      stopFrame();
      events.forEach(name => media.removeEventListener(name, update));
      media.removeEventListener("error", fail);
      media.removeEventListener("loadedmetadata", loaded);
      media.removeEventListener("emptied", reset);
      media.removeEventListener("loadstart", reset);
    }
  };
}

const NOTE_LIMITS = Object.freeze({count: 100, text: 1000, bytes: 512 * 1024});

function validNoteText(text) {
  // Count Unicode code points; reject lone surrogates before TextEncoder can replace them.
  return typeof text === "string" && text.length >= 1 && text.length <= 2 * NOTE_LIMITS.text
    && [...text].length <= NOTE_LIMITS.text
    && /[^\s]/u.test(text) && !/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\ud800-\udfff]/u.test(text);
}

function noteAnchor(cues, durationMs, seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) throw new Error("Invalid note position");
  const at_ms = Math.min(durationMs, Math.floor(mediaMilliseconds(seconds)));
  const index = activeCueIndex(cues, at_ms);
  return {at_ms, cue_id: index < 0 ? null : cues[index].id};
}

function createReviewNotes(binding, transcript, initialNotes = []) {
  const selected = {...binding};
  const cues = transcript.cues.map(cue => ({...cue}));
  const duration = transcript.audio.duration_ms;
  let sequence = 0;
  let notes = [];
  const model = {
    entries() { return notes.map(note => ({...note})); },
    save(anchor, text, id = null) {
      const index = id === null ? -1 : notes.findIndex(note => note.id === id);
      if ((id !== null && index < 0) || (id === null && notes.length >= NOTE_LIMITS.count)
          || !validNoteText(text) || !Number.isInteger(anchor.at_ms)
          || anchor.at_ms < 0 || anchor.at_ms > duration) throw new Error("Invalid review note");
      const active = activeCueIndex(cues, anchor.at_ms);
      if (anchor.cue_id !== (active < 0 ? null : cues[active].id)) throw new Error("Invalid note cue");
      const note = {id: id === null ? ++sequence : id, at_ms: anchor.at_ms, cue_id: anchor.cue_id, text};
      if (index < 0) notes.push(note);
      else notes[index] = note;
    },
    remove(id) { notes = notes.filter(note => note.id !== id); },
    serialize() {
      const output = JSON.stringify({...selected,
        notes: notes.map(({at_ms, cue_id, text}) => ({at_ms, cue_id, text}))}, null, 2) + "\n";
      if (new TextEncoder().encode(output).length > NOTE_LIMITS.bytes) throw new Error("Notes exceed limit");
      return output;
    }
  };
  // Initial notes come only from the generator's revision-validated snapshot.
  // Initialize before exposing the model: a failure cannot leave partial state.
  if (!Array.isArray(initialNotes) || initialNotes.length > NOTE_LIMITS.count) {
    throw new Error("Invalid initial notes");
  }
  for (const note of initialNotes) {
    if (!note || Object.keys(note).sort().join(",") !== "at_ms,cue_id,text") {
      throw new Error("Invalid initial note");
    }
    model.save(note, note.text);
  }
  return model;
}

function mountReviewNotes(document, window, transcript, media, controller) {
  const data = document.getElementById("review-data");
  if (!data) return null;
  const {notes = [], ...binding} = JSON.parse(data.textContent);
  const model = createReviewNotes(binding, transcript, notes);
  const hasInitialNotes = notes.length > 0;
  const capture = document.getElementById("note-capture");
  const editor = document.getElementById("note-editor");
  const input = document.getElementById("note-text");
  const save = document.getElementById("note-save");
  const cancel = document.getElementById("note-cancel");
  const list = document.getElementById("note-list");
  const download = document.getElementById("note-export");
  const status = document.getElementById("note-status");
  let available = false;
  let pending = null;
  let objectURL = null;
  let revokeTimer = null;
  function label(anchor) {
    const index = transcript.cues.findIndex(cue => cue.id === anchor.cue_id);
    return `${formatTime(anchor.at_ms)}.${String(anchor.at_ms % 1000).padStart(3, "0")} / `
      + (index < 0 ? "字幕のない位置" : `字幕 ${index + 1}`);
  }
  function controls() {
    const count = model.entries().length;
    capture.disabled = !available || pending !== null || count >= NOTE_LIMITS.count;
    save.disabled = !pending || !validNoteText(input.value);
    download.disabled = (count === 0 && !hasInitialNotes) || pending !== null;
    document.getElementById("note-limit").textContent = `${[...input.value].length} / 1,000 文字`;
    document.getElementById("note-count").textContent = `${count} / 100 件`;
    list.querySelectorAll(".note-seek").forEach(button => { button.disabled = !available; });
    list.querySelectorAll(".note-edit, .note-delete").forEach(button => { button.disabled = pending !== null; });
  }
  function start(anchor, text = "", id = null) {
    pending = {...anchor, id};
    input.value = text;
    editor.hidden = false;
    document.getElementById("note-anchor").textContent = `メモの位置（固定）: ${label(anchor)}`;
    save.textContent = id === null ? "メモを追加" : "変更を反映";
    status.textContent = "追加または取り消しの後、JSONで保存できます。";
    controls();
    input.focus();
  }
  function focusHome() {
    if (!capture.disabled) capture.focus();
    else if (!download.disabled) download.focus();
    else document.getElementById("review-title").focus();
  }
  function finish() {
    pending = null;
    input.value = "";
    editor.hidden = true;
    controls();
    focusHome();
  }
  function renderList() {
    list.replaceChildren();
    for (const note of model.entries()) {
      const item = document.createElement("li");
      const actions = document.createElement("div");
      actions.className = "note-actions";
      const seek = document.createElement("button");
      seek.type = "button";
      seek.className = "note-seek";
      seek.textContent = label(note);
      seek.addEventListener("click", () => controller.seek(note.at_ms / 1000));
      const text = document.createElement("p");
      text.className = "note-text";
      text.textContent = note.text;
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "note-edit";
      edit.textContent = "編集";
      edit.setAttribute("aria-label", `${label(note)} のメモを編集`);
      edit.addEventListener("click", () => start(note, note.text, note.id));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "note-delete";
      remove.textContent = "削除";
      remove.setAttribute("aria-label", `${label(note)} のメモを削除`);
      remove.addEventListener("click", () => {
        model.remove(note.id);
        renderList();
        focusHome();
        status.textContent = "メモを削除しました。";
      });
      actions.append(seek, edit, remove);
      item.append(actions, text);
      list.append(item);
    }
    controls();
  }
  capture.addEventListener("click", () => {
    if (!available || pending) return;
    try { start(noteAnchor(transcript.cues, transcript.audio.duration_ms, media.currentTime)); }
    catch { status.textContent = "再生位置を取得できませんでした。"; }
  });
  input.addEventListener("input", controls);
  save.addEventListener("click", () => {
    if (!pending) return;
    try {
      model.save(pending, input.value, pending.id);
      finish();
      renderList();
      status.textContent = "メモに反映しました。保存するにはJSONを書き出してください。";
    } catch { status.textContent = "メモを反映できませんでした。文字数と入力内容を確認してください。"; }
  });
  cancel.addEventListener("click", () => { finish(); status.textContent = "入力を取り消しました。"; });
  function releaseURL() {
    if (revokeTimer !== null) window.clearTimeout(revokeTimer);
    if (objectURL !== null) window.URL.revokeObjectURL(objectURL);
    revokeTimer = objectURL = null;
  }
  download.addEventListener("click", () => {
    if (pending || (model.entries().length === 0 && !hasInitialNotes)) return;
    let link = null;
    try {
      const output = model.serialize();
      releaseURL();
      objectURL = window.URL.createObjectURL(new window.Blob([output], {type: "application/json;charset=utf-8"}));
      link = document.createElement("a");
      link.href = objectURL;
      link.download = "narradock-review-notes.json";
      document.body.append(link);
      link.click();
      revokeTimer = window.setTimeout(releaseURL, 60000);
      status.textContent = "JSONのダウンロードを開始しました。ブラウザーで保存結果を確認してください。";
    } catch {
      releaseURL();
      status.textContent = "JSONを書き出せませんでした。メモはこのページに残っています。";
    } finally { if (link) link.remove(); }
  });
  window.addEventListener("pagehide", releaseURL);
  window.addEventListener("beforeunload", event => {
    if (hasInitialNotes || model.entries().length || (pending && input.value)) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  renderList();
  if (model.entries().length) status.textContent = "保存済みのメモを読み込みました。変更後はJSONで保存してください。";
  return {setAvailable(value) {
    if (available !== value) { available = value; controls(); }
  }};
}

function mountPlayer(document, window) {
  const transcript = JSON.parse(document.getElementById("transcript-data").textContent);
  const media = document.getElementById("audio");
  const list = document.getElementById("transcript");
  const follow = document.getElementById("follow");
  const rate = document.getElementById("rate");
  const clock = document.getElementById("clock");
  const status = document.getElementById("status");
  const buttons = transcript.cues.map((cue, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cue";
    button.id = `cue-${index}`;
    const time = document.createElement("span");
    time.className = "cue-time";
    time.textContent = formatTime(cue.start_ms);
    const text = document.createElement("span");
    text.className = "cue-text";
    text.textContent = cue.text;
    button.append(time, text);
    button.setAttribute("aria-label", `${time.textContent} に移動: ${cue.text}`);
    item.append(button);
    list.append(item);
    return button;
  });
  let active = -1;
  let review = null;
  let search = null;
  const controller = createController({
    media, cues: transcript.cues, durationMs: transcript.audio.duration_ms,
    requestFrame: callback => window.requestAnimationFrame(callback),
    cancelFrame: handle => window.cancelAnimationFrame(handle),
    visible: () => !document.hidden,
    view: {
      render(state) {
        if (review) review.setAvailable(state.ready && !state.unavailable);
        if (search) search.setAvailable(state.ready && !state.unavailable);
        clock.textContent = `${formatTime(state.elapsedMs)} / ${formatTime(state.durationMs)}`;
        follow.checked = state.following;
        follow.disabled = rate.disabled = state.unavailable || !state.ready;
        const currentRate = String(state.playbackRate);
        const nativeRate = document.getElementById("native-rate");
        if (nativeRate && nativeRate.value !== currentRate) nativeRate.remove();
        if (rate.value !== currentRate) {
          // Native audio controls may offer rates outside this select's presets.
          if (![...rate.options].some(option => option.value === currentRate)) {
            const option = document.createElement("option");
            option.id = "native-rate";
            option.value = currentRate;
            option.textContent = `${currentRate}×（音声コントロール）`;
            rate.append(option);
          }
          rate.value = currentRate;
        }
        if (active !== state.active) {
          if (active >= 0) buttons[active].removeAttribute("aria-current");
          if (state.active >= 0) buttons[state.active].setAttribute("aria-current", "true");
          active = state.active;
        }
        buttons.forEach(button => { button.disabled = state.unavailable || !state.ready; });
      },
      follow(index) {
        const row = buttons[index].getBoundingClientRect();
        const box = list.getBoundingClientRect();
        if (row.top < box.top || row.bottom > box.bottom) {
          list.scrollTop += row.top - box.top - (box.height - row.height) / 2;
        }
      },
      announce(message) { status.textContent = message; }
    }
  });
  buttons.forEach((button, index) => {
    button.addEventListener("click", () => controller.seek(transcript.cues[index].start_ms / 1000));
  });
  follow.addEventListener("change", () => controller.setFollowing(follow.checked));
  rate.addEventListener("change", () => controller.setRate(Number(rate.value)));
  list.addEventListener("wheel", () => controller.manualScroll(), {passive: true});
  list.addEventListener("touchstart", () => controller.manualScroll(), {passive: true});
  list.addEventListener("pointerdown", () => controller.manualScroll(), {passive: true});
  list.addEventListener("focusin", () => controller.manualScroll());
  list.addEventListener("keydown", event => {
    if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) {
      controller.manualScroll();
    }
  });
  document.addEventListener("visibilitychange", () => controller.visibilityChanged());
  window.addEventListener("pageshow", () => controller.visibilityChanged());
  review = mountReviewNotes(document, window, transcript, media, controller);
  search = mountTranscriptSearch(document, transcript, controller);
  // Native controls initiate playback only through a user's action. No autoplay or persistence.
  media.src = document.getElementById("audio-data").textContent;
  media.load();
  return controller;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {activeCueIndex, formatTime, createController, NOTE_LIMITS,
    validNoteText, noteAnchor, createReviewNotes, SEARCH_QUERY_LIMIT, searchCueIndices};
} else {
  mountPlayer(document, window);
}
