/* ============================================================
   무드 페어링 — main.js
   사용자 입력 → fetch('/api/pair') → 결과 렌더 → localStorage 기록
   ============================================================ */

(function () {
  "use strict";

  var MIN_LEN = 10;
  var MAX_LEN = 500;
  var TIMEOUT_MS = 15000;
  var STORAGE_KEY = "moodPairing.history.v1";
  var HISTORY_LIMIT = 30;

  /* ---------- 요소 ---------- */
  var $ = function (id) { return document.getElementById(id); };

  var navToggle = $("navToggle");
  var navMenu = $("navMenu");
  var form = $("pairForm");
  var queryInput = $("queryInput");
  var charCount = $("charCount");
  var lyricsSelect = $("lyricsSelect");
  var countSelect = $("countSelect");
  var submitBtn = $("submitBtn");
  var statusBox = $("status");
  var resultBox = $("result");
  var resultSummary = $("resultSummary");
  var tracksBox = $("tracks");
  var letterBox = $("letter");
  var letterBody = $("letterBody");
  var adjustInput = $("adjustInput");
  var adjustApply = $("adjustApply");
  var moreBtn = $("moreBtn");
  var historyList = $("historyList");
  var historyCount = $("historyCount");
  var historyEmpty = $("historyEmpty");
  var exportBtn = $("exportBtn");
  var clearBtn = $("clearBtn");
  var player = $("player");

  /* ---------- 세션 상태 (새로고침하면 사라짐) ---------- */
  var state = {
    query: "",
    lyrics: "any",
    count: 5,
    adjust: "",
    excluded: [],   // 이번 세션에서 이미 본 곡 — 중복 제거용
    busy: false
  };

  var currentBtn = null; // 재생 중인 버튼

  /* ============================================================
     네비게이션
     ============================================================ */

  navToggle.addEventListener("click", function () {
    var open = navMenu.classList.toggle("is-open");
    navToggle.setAttribute("aria-expanded", String(open));
    navToggle.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
  });

  navMenu.addEventListener("click", function (e) {
    if (e.target.tagName === "A") {
      navMenu.classList.remove("is-open");
      navToggle.setAttribute("aria-expanded", "false");
    }
  });

  /* ============================================================
     입력 폼
     ============================================================ */

  function updateCount() {
    var n = queryInput.value.length;
    charCount.textContent = n;
    charCount.parentNode.classList.toggle("is-over", n > MAX_LEN);
  }

  queryInput.addEventListener("input", updateCount);
  updateCount();

  $("exampleChips").addEventListener("click", function (e) {
    var chip = e.target.closest(".chip");
    if (!chip) return;
    queryInput.value = chip.dataset.fill;
    updateCount();
    queryInput.focus();
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = queryInput.value.trim();

    // 실패 처리 ① 빈 입력 / 너무 짧은 입력
    if (q.length < MIN_LEN) {
      showStatus("조금만 더 자세히 적어주세요. 길수록 정확해져요. (최소 " + MIN_LEN + "자)", "error");
      queryInput.focus();
      return;
    }
    if (q.length > MAX_LEN) {
      showStatus("입력이 너무 깁니다. " + MAX_LEN + "자 이내로 줄여주세요.", "error");
      return;
    }

    state.query = q;
    state.lyrics = lyricsSelect.value;
    state.count = parseInt(countSelect.value, 10);
    state.adjust = "";
    state.excluded = [];
    adjustInput.value = "";

    search();
  });

  /* ---------- 조정 칩 / 자유 입력 조정 ---------- */

  $("adjustChips").addEventListener("click", function (e) {
    var chip = e.target.closest(".chip");
    if (!chip) return;
    applyAdjust(chip.dataset.adjust);
  });

  adjustApply.addEventListener("click", function () {
    var text = adjustInput.value.trim();
    if (!text) {
      showStatus("어떤 방향으로 바꿀지 한 줄 적어주세요.", "error");
      adjustInput.focus();
      return;
    }
    applyAdjust(text);
  });

  adjustInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); adjustApply.click(); }
  });

  function applyAdjust(text) {
    if (state.busy) return;
    state.adjust = text;
    state.excluded = [];   // 방향이 바뀌었으니 제외 목록은 비움
    search();
  }

  /* ---------- 같은 무드로 더 보기 (중복만 제외, 취향 추론 아님) ---------- */

  moreBtn.addEventListener("click", function () {
    if (state.busy || !state.query) return;
    search();
  });

  /* ============================================================
     검색 — fetch + 타임아웃
     ============================================================ */

  function search() {
    if (state.busy) return;
    setBusy(true);
    showStatus("문장을 읽고, 곡을 고르고, 실제로 있는 곡인지 확인하고 있어요", "loading");

    var controller = new AbortController();
    // 실패 처리 ③ 지연/타임아웃
    var timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);

    fetch("/api/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: state.query,
        lyrics: state.lyrics,
        count: state.count,
        adjust: state.adjust,
        exclude: state.excluded
      }),
      signal: controller.signal
    })
      .then(function (res) {
        clearTimeout(timer);
        // 서버리스 함수가 죽거나 시간 초과되면 JSON이 아닌 응답이 올 수 있다.
        return res.text().then(function (raw) {
          var data = null;
          try { data = JSON.parse(raw); } catch (e) { /* JSON이 아님 */ }
          if (!res.ok || !data) {
            throw new HttpError(res.status, data && data.message);
          }
          return data;
        });
      })
      .then(function (data) {
        if (data.safety) {                       // 위기 표현 감지
          renderSafety(data.safety);
          return;
        }
        if (!data.tracks || data.tracks.length === 0) {
          showStatus("이 문장으로는 곡을 찾지 못했어요. 상황이나 분위기를 조금 더 구체적으로 적어보시겠어요?", "warn");
          return;
        }
        render(data);
        saveHistory(data);
      })
      .catch(function (err) {
        clearTimeout(timer);
        if (err.name === "AbortError") {
          // 실패 처리 ③
          showStatus("응답이 지연되고 있어요. 잠시 후 다시 시도해주세요.", "warn");
        } else if (err instanceof HttpError) {
          // 실패 처리 ② API 오류 (4xx / 5xx)
          showStatus(err.message || "지금은 곡을 찾지 못했어요. 잠시 후 다시 시도해주세요.", "error");
        } else {
          showStatus("네트워크 연결을 확인해주세요.", "error");
        }
      })
      .then(function () { setBusy(false); });
  }

  function HttpError(status, message) {
    this.name = "HttpError";
    this.status = status;
    this.message = message || "";
  }
  HttpError.prototype = Object.create(Error.prototype);

  function setBusy(busy) {
    state.busy = busy;
    submitBtn.disabled = busy;
    moreBtn.disabled = busy;
    adjustApply.disabled = busy;
    submitBtn.textContent = busy ? "찾는 중…" : "곡과 문장 받기";
  }

  function showStatus(msg, kind) {
    statusBox.hidden = false;
    statusBox.className = "status" + (kind && kind !== "loading" ? " status--" + kind : "");
    statusBox.textContent = "";
    var span = document.createElement("span");
    span.textContent = msg;
    if (kind === "loading") span.className = "status__dots";
    statusBox.appendChild(span);
  }

  function hideStatus() { statusBox.hidden = true; }

  /* ============================================================
     결과 렌더 — AI가 돌려준 문자열은 전부 textContent로만 넣는다
     ============================================================ */

  function render(data) {
    hideStatus();
    stopPlayback();

    resultSummary.textContent = data.mood_summary || "";

    tracksBox.textContent = "";
    data.tracks.forEach(function (t) {
      tracksBox.appendChild(trackCard(t));
      state.excluded.push(t.artist + " - " + t.title);
    });

    if (data.original_text) {
      letterBody.textContent = data.original_text;
      letterBox.hidden = false;
    } else {
      letterBox.hidden = true;
    }

    resultBox.hidden = false;

    if (data.fallback_used) {
      showStatus("정확히 맞는 곡이 적어서, 키워드로 찾은 곡을 함께 담았어요.", "warn");
    }

    resultBox.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function trackCard(t) {
    var card = el("article", "track");

    var art = document.createElement("img");
    art.className = "track__art";
    art.loading = "lazy";
    art.alt = "";
    art.src = t.artwork || "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E";
    card.appendChild(art);

    var body = el("div", "track__body");
    body.appendChild(el("h3", "track__title", t.title));
    body.appendChild(el("p", "track__artist", t.artist));
    if (t.note) body.appendChild(el("p", "track__note", t.note));
    card.appendChild(body);

    var actions = el("div", "track__actions");

    var play = document.createElement("button");
    play.type = "button";
    play.className = "track__btn";
    play.textContent = "▶";
    if (t.preview_url) {
      play.title = "30초 미리듣기";
      play.setAttribute("aria-label", t.title + " 미리듣기");
      play.addEventListener("click", function () { togglePlay(play, t.preview_url); });
    } else {
      play.setAttribute("aria-disabled", "true");
      play.title = "이 곡은 미리듣기를 제공하지 않아요";
      play.disabled = true;
    }
    actions.appendChild(play);

    if (t.track_url) {
      var link = document.createElement("a");
      link.className = "track__btn";
      link.href = t.track_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "↗";
      link.title = "음원 페이지에서 열기";
      link.setAttribute("aria-label", t.title + " 음원 페이지 열기");
      actions.appendChild(link);
    }

    card.appendChild(actions);
    return card;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function renderSafety(msg) {
    hideStatus();
    resultBox.hidden = true;
    statusBox.hidden = false;
    statusBox.className = "status status--warn";
    statusBox.textContent = "";
    statusBox.appendChild(el("p", null, msg));
    var p = el("p", null, "자살예방 상담전화 109 · 정신건강 상담전화 1577-0199 (24시간)");
    p.style.marginTop = "8px";
    p.style.fontWeight = "600";
    statusBox.appendChild(p);
  }

  /* ---------- 30초 미리듣기 ---------- */

  function togglePlay(btn, url) {
    if (currentBtn === btn && !player.paused) { stopPlayback(); return; }
    stopPlayback();
    player.src = url;
    player.play().then(function () {
      btn.classList.add("is-playing");
      btn.textContent = "❚❚";
      currentBtn = btn;
    }).catch(function () {
      showStatus("미리듣기를 재생하지 못했어요.", "warn");
    });
  }

  function stopPlayback() {
    player.pause();
    if (currentBtn) {
      currentBtn.classList.remove("is-playing");
      currentBtn.textContent = "▶";
      currentBtn = null;
    }
  }

  player.addEventListener("ended", stopPlayback);

  /* ============================================================
     검색 기록 — localStorage에만 저장. 서버로 보내지 않고,
     다음 검색 결과에도 반영하지 않는다 (열람 전용).
     ============================================================ */

  function loadHistory() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function writeHistory(list) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, HISTORY_LIMIT)));
    } catch (e) {
      /* 용량 초과 등은 무시 — 기록은 부가 기능 */
    }
  }

  function saveHistory(data) {
    var list = loadHistory();
    list.unshift({
      id: String(Date.now()),
      at: new Date().toISOString(),
      query: state.query,
      adjust: state.adjust,
      summary: data.mood_summary || "",
      text: data.original_text || "",
      tracks: data.tracks.map(function (t) {
        return { artist: t.artist, title: t.title, url: t.track_url || "" };
      })
    });
    writeHistory(list);
    renderHistory();
  }

  function renderHistory() {
    var list = loadHistory();
    historyCount.textContent = "저장된 기록 " + list.length + "개";
    historyEmpty.hidden = list.length > 0;
    historyList.textContent = "";

    list.forEach(function (item) {
      var box = el("article", "history__item");

      var when = new Date(item.at);
      var label = when.toLocaleString("ko-KR", {
        year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"
      });
      box.appendChild(el("p", "history__date", label + (item.adjust ? " · 조정: " + item.adjust : "")));
      box.appendChild(el("p", "history__query", item.query));

      var names = item.tracks.map(function (t) { return t.title + " — " + t.artist; }).join(" · ");
      box.appendChild(el("p", "history__tracks", names));

      var acts = el("div", "history__item-actions");

      var again = document.createElement("button");
      again.type = "button";
      again.className = "btn btn--ghost btn--sm";
      again.textContent = "같은 문장으로 다시 검색";
      again.addEventListener("click", function () {
        queryInput.value = item.query;
        updateCount();
        state.query = item.query;
        state.lyrics = lyricsSelect.value;
        state.count = parseInt(countSelect.value, 10);
        state.adjust = "";
        state.excluded = [];
        document.getElementById("pair").scrollIntoView({ behavior: "smooth" });
        search();
      });
      acts.appendChild(again);

      var del = document.createElement("button");
      del.type = "button";
      del.className = "btn btn--ghost btn--sm btn--danger";
      del.textContent = "삭제";
      del.addEventListener("click", function () {
        writeHistory(loadHistory().filter(function (x) { return x.id !== item.id; }));
        renderHistory();
      });
      acts.appendChild(del);

      box.appendChild(acts);
      historyList.appendChild(box);
    });
  }

  clearBtn.addEventListener("click", function () {
    if (loadHistory().length === 0) return;
    if (!window.confirm("저장된 검색 기록을 모두 지웁니다. 되돌릴 수 없어요. 계속할까요?")) return;
    localStorage.removeItem(STORAGE_KEY);
    renderHistory();
  });

  exportBtn.addEventListener("click", function () {
    var list = loadHistory();
    if (list.length === 0) { alert("내보낼 기록이 없습니다."); return; }

    var text = list.map(function (item) {
      var lines = [
        "[" + new Date(item.at).toLocaleString("ko-KR") + "]",
        "검색: " + item.query
      ];
      if (item.adjust) lines.push("조정: " + item.adjust);
      lines.push("무드: " + item.summary);
      item.tracks.forEach(function (t) { lines.push("  - " + t.title + " / " + t.artist + (t.url ? " " + t.url : "")); });
      if (item.text) lines.push("문장: " + item.text);
      return lines.join("\n");
    }).join("\n\n----------------\n\n");

    var blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "mood-pairing-history.txt";
    a.click();
    URL.revokeObjectURL(url);
  });

  renderHistory();
})();
