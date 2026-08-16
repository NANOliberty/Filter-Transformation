/* 만화 필터 — 업로드하고 네 가지 스타일로 변환하는 프런트엔드 */
(function () {
  "use strict";

  var cfg = window.APP_CONFIG || { maxUploadMb: 16, styles: [] };

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };

  var dropzone = $("#dropzone");
  var fileInput = $("#file-input");
  var uploader = $("#uploader");
  var uploadError = $("#upload-error");
  var uploadProgress = $("#upload-progress");
  var workspace = $("#workspace");
  var sourceThumb = $("#source-thumb");
  var sourceName = $("#source-name");
  var sourceSize = $("#source-size");
  var colorsGroup = $("#colors");
  var btnZip = $("#btn-zip");
  var btnReset = $("#btn-reset");
  var lightbox = $("#lightbox");
  var lightboxImg = $("#lightbox-img");
  var lightboxCap = $("#lightbox-cap");

  var state = { token: null, name: "", colors: 0, run: 0, busy: false };

  var cards = {};
  $$(".card").forEach(function (el) {
    cards[el.dataset.style] = {
      el: el,
      tunable: el.dataset.tunable === "1",
      img: $(".result", el),
      state: $(".state", el),
      zoom: $(".zoom", el),
      download: $(".download", el),
      label: $("strong", el).textContent,
      done: false
    };
  });

  // ------------------------------------------------------------ 헬퍼

  function showError(msg) {
    uploadError.textContent = msg;
    uploadError.hidden = !msg;
  }

  function setCardState(card, text, cls) {
    card.state.textContent = text || "";
    card.state.className = "state" + (cls ? " " + cls : "");
    card.state.hidden = !text;
  }

  function resetCard(card) {
    card.done = false;
    card.img.hidden = true;
    card.img.removeAttribute("src");
    card.zoom.hidden = true;
    card.download.hidden = true;
    setCardState(card, "대기 중", "");
  }

  function loadImage(img, url) {
    return new Promise(function (resolve, reject) {
      img.onload = function () { resolve(); };
      img.onerror = function () { reject(new Error("이미지를 불러오지 못했습니다.")); };
      img.src = url;
    });
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(readJSON);
  }

  function readJSON(res) {
    return res.json().catch(function () {
      throw new Error("서버 응답을 읽지 못했습니다. (" + res.status + ")");
    }).then(function (data) {
      if (!res.ok) throw new Error(data.error || "요청에 실패했습니다.");
      return data;
    });
  }

  // ------------------------------------------------------------ 업로드

  function handleFile(file) {
    if (!file) return;
    showError("");

    if (file.type && file.type.indexOf("image/") !== 0) {
      showError("이미지 파일만 올릴 수 있어요.");
      return;
    }
    if (file.size > cfg.maxUploadMb * 1024 * 1024) {
      showError("파일이 너무 큽니다. " + cfg.maxUploadMb + "MB 이하로 올려 주세요.");
      return;
    }

    var form = new FormData();
    form.append("image", file);

    uploadProgress.hidden = false;
    dropzone.classList.add("over");

    fetch("/api/upload", { method: "POST", body: form })
      .then(readJSON)
      .then(function (data) {
        state.token = data.token;
        state.name = data.name;
        sourceThumb.src = data.src_url;
        sourceName.textContent = data.name;
        sourceSize.textContent = data.width + " × " + data.height + " px";
        uploader.hidden = true;
        workspace.hidden = false;
        return runAll();
      })
      .catch(function (err) { showError(err.message); })
      .then(function () {
        uploadProgress.hidden = true;
        dropzone.classList.remove("over");
        fileInput.value = "";
      });
  }

  // ------------------------------------------------------------ 변환

  function transformOne(style, run) {
    var card = cards[style];
    setCardState(card, "그리는 중…", "busy");

    return postJSON("/api/transform", {
      token: state.token,
      style: style,
      colors: card.tunable ? state.colors : 0
    }).then(function (data) {
      if (run !== state.run) return;
      return loadImage(card.img, data.url).then(function () {
        if (run !== state.run) return;
        card.img.hidden = false;
        card.zoom.hidden = false;
        card.download.hidden = false;
        card.download.href = data.download_url;
        card.done = true;
        setCardState(card, "", "");
      });
    }).catch(function (err) {
      if (run !== state.run) return;
      card.done = false;
      setCardState(card, err.message || "변환에 실패했어요.", "failed");
    });
  }

  function runAll(only) {
    var run = ++state.run;
    var list = Object.keys(cards).filter(function (style) {
      return !only || only.indexOf(style) !== -1;
    });

    list.forEach(function (style) { resetCard(cards[style]); });
    setBusy(true);

    // CPU를 아끼려고 한 장씩 순서대로 처리한다.
    return list.reduce(function (chain, style) {
      return chain.then(function () {
        if (run !== state.run) return;
        return transformOne(style, run);
      });
    }, Promise.resolve()).then(function () {
      if (run === state.run) setBusy(false);
    });
  }

  function setBusy(busy) {
    state.busy = busy;
    btnZip.disabled = busy;
    btnZip.textContent = busy ? "변환 중…" : "전체 다운로드";
  }

  // ------------------------------------------------------------ 이벤트

  fileInput.addEventListener("change", function () {
    handleFile(fileInput.files && fileInput.files[0]);
  });

  dropzone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach(function (type) {
    window.addEventListener(type, function (e) {
      e.preventDefault();
      if (!workspace.hidden) return;
      dropzone.classList.add("over");
    });
  });

  ["dragleave", "drop"].forEach(function (type) {
    window.addEventListener(type, function (e) {
      e.preventDefault();
      if (type === "dragleave" && e.relatedTarget) return;
      dropzone.classList.remove("over");
    });
  });

  window.addEventListener("drop", function (e) {
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) handleFile(files[0]);
  });

  window.addEventListener("paste", function (e) {
    var items = e.clipboardData && e.clipboardData.files;
    if (items && items.length) handleFile(items[0]);
  });

  colorsGroup.addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-colors]");
    if (!btn || state.busy) return;
    $$("button", colorsGroup).forEach(function (b) { b.classList.remove("on"); });
    btn.classList.add("on");

    var next = parseInt(btn.dataset.colors, 10) || 0;
    if (next === state.colors) return;
    state.colors = next;

    // 색상 수의 영향을 받는 스타일만 다시 그린다.
    var affected = Object.keys(cards).filter(function (s) { return cards[s].tunable; });
    runAll(affected);
  });

  btnZip.addEventListener("click", function () {
    if (!state.token || state.busy) return;
    window.location.href = "/api/zip/" + state.token + "?colors=" + state.colors;
  });

  btnReset.addEventListener("click", function () {
    state.run++;
    state.token = null;
    setBusy(false);
    Object.keys(cards).forEach(function (s) { resetCard(cards[s]); });
    workspace.hidden = true;
    uploader.hidden = false;
    showError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // 확대 보기
  Object.keys(cards).forEach(function (style) {
    var card = cards[style];
    function open() {
      if (!card.done) return;
      lightboxImg.src = card.img.src;
      lightboxCap.textContent = card.label + " · " + state.name;
      lightbox.hidden = false;
    }
    card.zoom.addEventListener("click", open);
    card.img.addEventListener("click", open);
  });

  function closeLightbox() {
    lightbox.hidden = true;
    lightboxImg.removeAttribute("src");
  }

  lightbox.addEventListener("click", function (e) {
    if (e.target === lightbox || e.target.classList.contains("lb-close")) closeLightbox();
  });

  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !lightbox.hidden) closeLightbox();
  });
})();
