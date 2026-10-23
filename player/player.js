"use strict";

// This adapter receives only the generator's validated synthetic fixture.
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
      ? Math.max(0, Math.min(durationMs, media.currentTime * 1000)) : 0;
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
    // Synthetic WAV duration is exact; allow the browser a millisecond of representation error.
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
  const controller = createController({
    media, cues: transcript.cues, durationMs: transcript.audio.duration_ms,
    requestFrame: callback => window.requestAnimationFrame(callback),
    cancelFrame: handle => window.cancelAnimationFrame(handle),
    visible: () => !document.hidden,
    view: {
      render(state) {
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
  // Native controls initiate playback only through a user's action. No autoplay or persistence.
  media.src = document.getElementById("audio-data").textContent;
  media.load();
  return controller;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {activeCueIndex, formatTime, createController};
} else {
  mountPlayer(document, window);
}
