/* 만화 필터 — 한 장 비교 모드와 여러 장 일괄 변환 모드 */
(function () {
  "use strict";

  var cfg = window.APP_CONFIG ||
    { maxUploadMb: 16, maxBatchFiles: 40, concurrency: 1, styles: [] };

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };

  var STYLE_LABEL = {};
  (cfg.styles || []).forEach(function (s) { STYLE_LABEL[s.key] = s.label; });

  // ------------------------------------------------------------ 공통 헬퍼

  function readJSON(res) {
    return res.json().catch(function () {
      throw new Error("서버 응답을 읽지 못했습니다. (" + res.status + ")");
    }).then(function (data) {
      if (!res.ok) throw new Error(data.error || "요청에 실패했습니다.");
      return data;
    });
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(readJSON);
  }

  function loadImage(img, url) {
    return new Promise(function (resolve, reject) {
      img.onload = function () { resolve(); };
      img.onerror = function () { reject(new Error("이미지를 불러오지 못했습니다.")); };
      img.src = url;
    });
  }

  function isImage(file) {
    if (file.type) return file.type.indexOf("image/") === 0;
    return /\.(jpe?g|png|webp|bmp|tiff?)$/i.test(file.name || "");
  }

  function tooBig(file) {
    return file.size > cfg.maxUploadMb * 1024 * 1024;
  }

  function showError(el, msg) {
    el.textContent = msg || "";
    el.hidden = !msg;
  }

  // 순서대로 하나씩 처리한다. 업로드처럼 순서가 중요한 일에 쓴다.
  function sequential(items, worker) {
    return items.reduce(function (chain, item, i) {
      return chain.then(function () { return worker(item, i); });
    }, Promise.resolve());
  }

  // 한 번에 limit개씩 굴린다. 서버가 코어를 여러 개 쓸 수 있을 때 그만큼 빨라진다.
  // limit이 1이면 예전처럼 한 장씩 순서대로 처리한다.
  function pooled(items, worker) {
    var limit = Math.max(1, cfg.concurrency | 0);
    if (limit === 1) return sequential(items, worker);

    var next = 0;
    function lane() {
      var i = next++;
      if (i >= items.length) return Promise.resolve();
      return Promise.resolve(worker(items[i], i)).then(lane);
    }
    var lanes = [];
    for (var n = 0; n < Math.min(limit, items.length); n++) lanes.push(lane());
    return Promise.all(lanes);
  }

  function segmented(group, onChange) {
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-colors]");
      if (!btn || btn.classList.contains("on")) return;
      $$("button", group).forEach(function (b) { b.classList.remove("on"); });
      btn.classList.add("on");
      onChange(parseInt(btn.dataset.colors, 10) || 0);
    });
  }

  // ------------------------------------------------------------ 확대 보기

  var lightbox = $("#lightbox");
  var lightboxImg = $("#lightbox-img");
  var lightboxCap = $("#lightbox-cap");

  function openLightbox(src, caption) {
    lightboxImg.src = src;
    lightboxCap.textContent = caption || "";
    lightbox.hidden = false;
  }

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

  // ------------------------------------------------------------ 모드 전환

  var modeSections = { single: $("#single-mode"), batch: $("#batch-mode") };
  var currentMode = "single";

  $("#modes").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    currentMode = btn.dataset.mode;
    $$("#modes .mode").forEach(function (b) {
      b.classList.toggle("on", b === btn);
    });
    Object.keys(modeSections).forEach(function (key) {
      modeSections[key].hidden = key !== currentMode;
    });
  });

  // ========================================================== 한 장 비교

  var single = (function () {
    var dropzone = $("#dropzone");
    var fileInput = $("#file-input");
    var uploader = $("#uploader");
    var errorEl = $("#upload-error");
    var uploadProgress = $("#upload-progress");
    var workspace = $("#workspace");
    var sourceThumb = $("#source-thumb");
    var sourceName = $("#source-name");
    var sourceSize = $("#source-size");
    var progressCount = $("#progress-count");
    var btnZip = $("#btn-zip");
    var btnReset = $("#btn-reset");

    var state = { token: null, name: "", colors: 0, run: 0, busy: false };
    var cards = {};

    $$("#single-mode .card").forEach(function (el) {
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

    function handleFile(file) {
      if (!file) return;
      showError(errorEl, "");

      if (!isImage(file)) return showError(errorEl, "이미지 파일만 올릴 수 있어요.");
      if (tooBig(file)) {
        return showError(errorEl, "파일이 너무 큽니다. " + cfg.maxUploadMb + "MB 이하로 올려 주세요.");
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
        .catch(function (err) { showError(errorEl, err.message); })
        .then(function () {
          uploadProgress.hidden = true;
          dropzone.classList.remove("over");
          fileInput.value = "";
        });
    }

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
      var done = 0;
      showProgress(done, list.length);

      return pooled(list, function (style) {
        if (run !== state.run) return;
        return transformOne(style, run).then(function () {
          if (run === state.run) showProgress(++done, list.length);
        });
      }).then(function () {
        if (run === state.run) setBusy(false);
      });
    }

    function showProgress(done, total) {
      progressCount.textContent = done < total ? done + " / " + total + " 변환 중…" : "";
    }

    function setBusy(busy) {
      // 진행 상황은 옆의 카운터가 알려주므로 버튼 글씨는 그대로 둔다.
      state.busy = busy;
      btnZip.disabled = busy;
    }

    fileInput.addEventListener("change", function () {
      handleFile(fileInput.files && fileInput.files[0]);
    });

    dropzone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });

    segmented($("#colors"), function (next) {
      if (state.busy || next === state.colors) return;
      state.colors = next;
      // 색상 수의 영향을 받는 스타일만 다시 그린다.
      runAll(Object.keys(cards).filter(function (s) { return cards[s].tunable; }));
    });

    btnZip.addEventListener("click", function () {
      if (!state.token || state.busy) return;
      window.location.href = "/api/zip/" + state.token + "?colors=" + state.colors;
    });

    btnReset.addEventListener("click", function () {
      state.run++;
      state.token = null;
      setBusy(false);
      progressCount.textContent = "";
      Object.keys(cards).forEach(function (s) { resetCard(cards[s]); });
      workspace.hidden = true;
      uploader.hidden = false;
      showError(errorEl, "");
      window.scrollTo({ top: 0, behavior: "smooth" });
    });

    Object.keys(cards).forEach(function (style) {
      var card = cards[style];
      function open() {
        if (card.done) openLightbox(card.img.src, card.label + " · " + state.name);
      }
      card.zoom.addEventListener("click", open);
      card.img.addEventListener("click", open);
    });

    return {
      handleFile: handleFile,
      isIdle: function () { return workspace.hidden; },
      dropzone: dropzone
    };
  })();

  // ====================================================== 여러 장 한 번에

  var batch = (function () {
    var dropzone = $("#batch-dropzone");
    var fileInput = $("#batch-file-input");
    var folderInput = $("#batch-folder-input");
    var errorEl = $("#batch-error");
    var setup = $("#batch-setup");
    var stack = $("#batch-stack");
    var countEl = $("#batch-count");
    var namesEl = $("#batch-names");
    var chips = $("#batch-styles");
    var grid = $("#batch-grid");
    var progressEl = $("#batch-progress");
    var hintEl = $("#batch-hint");
    var btnRun = $("#btn-batch-run");
    var btnZip = $("#btn-batch-zip");
    var btnClear = $("#btn-batch-clear");

    var state = { token: null, items: [], colors: 0, busy: false, run: 0 };

    function selectedStyles() {
      var picked = $$(".chip.on", chips).map(function (c) { return c.dataset.style; });
      if (picked.length) return picked;
      // 스타일이 하나뿐이라 선택기를 숨긴 경우 — 켜져 있는 것을 그대로 쓴다.
      return (cfg.styles || []).map(function (s) { return s.key; });
    }

    function isTunable(style) {
      var chip = $('.chip[data-style="' + style + '"]', chips);
      if (chip) return chip.dataset.tunable === "1";
      var info = (cfg.styles || []).filter(function (s) { return s.key === style; })[0];
      return !!(info && info.tunable);
    }

    function refreshRunButton() {
      var total = state.items.length * selectedStyles().length;
      btnRun.disabled = state.busy || total === 0;
      btnRun.textContent = total ? "변환 시작 (" + total + "장)" : "변환 시작";

      // 오래 걸릴 작업은 미리 알려 준다. 장당 1초쯤 걸린다고 잡는다.
      if (total > 40) {
        hintEl.textContent = "한 장에 1초쯤 걸려요. 이 작업은 대략 " +
          Math.max(1, Math.round(total / 60)) + "분 예상돼요.";
        hintEl.hidden = false;
      } else {
        hintEl.hidden = true;
      }
    }

    function renderStack() {
      stack.innerHTML = "";
      state.items.slice(0, 4).forEach(function (item, i) {
        var img = document.createElement("img");
        img.src = item.src_url;
        img.alt = "";
        img.style.zIndex = String(4 - i);
        stack.appendChild(img);
      });
      dropzone.classList.toggle("compact", state.items.length > 0);
      countEl.textContent = state.items.length + "장 준비됨";
      namesEl.textContent = state.items.slice(0, 3).map(function (i) { return i.name; })
        .join(", ") + (state.items.length > 3 ? " 외 " + (state.items.length - 3) + "장" : "");
    }

    function pick(fileList) {
      var files = Array.prototype.slice.call(fileList || []);
      var images = files.filter(isImage);
      var skippedBig = images.filter(tooBig);
      images = images.filter(function (f) { return !tooBig(f); });

      var notes = [];
      if (files.length > images.length + skippedBig.length) {
        notes.push("이미지가 아닌 파일 " + (files.length - images.length - skippedBig.length) + "개는 건너뛰었어요.");
      }
      if (skippedBig.length) {
        notes.push(cfg.maxUploadMb + "MB가 넘는 " + skippedBig.length + "장은 건너뛰었어요.");
      }
      if (images.length > cfg.maxBatchFiles) {
        notes.push("한 번에 " + cfg.maxBatchFiles + "장까지만 올릴 수 있어 앞에서부터 잘랐어요.");
        images = images.slice(0, cfg.maxBatchFiles);
      }
      if (!images.length) {
        return showError(errorEl, notes.concat("올릴 이미지가 없어요.").join(" "));
      }
      showError(errorEl, notes.join(" "));

      // 이름순으로 올려야 폴더를 통째로 올렸을 때 순서가 자연스럽다.
      images.sort(function (a, b) {
        return (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name);
      });

      state.busy = true;
      refreshRunButton();
      grid.innerHTML = "";
      btnZip.hidden = true;
      progressEl.textContent = "업로드 중… 0 / " + images.length;

      postJSON("/api/batch/create", {}).then(function (data) {
        state.token = data.token;
        state.items = [];
        setup.hidden = false;
        var done = 0;
        return sequential(images, function (file) {
          var form = new FormData();
          form.append("token", state.token);
          form.append("image", file);
          return fetch("/api/batch/add", { method: "POST", body: form })
            .then(readJSON)
            .then(function (item) {
              state.items.push(item);
              progressEl.textContent = "업로드 중… " + (++done) + " / " + images.length;
              renderStack();
            })
            .catch(function () {
              progressEl.textContent = "업로드 중… " + (++done) + " / " + images.length;
            });
        });
      }).then(function () {
        progressEl.textContent = "";
        if (!state.items.length) showError(errorEl, "올릴 수 있는 이미지가 없었어요.");
      }).catch(function (err) {
        showError(errorEl, err.message);
      }).then(function () {
        state.busy = false;
        refreshRunButton();
        fileInput.value = "";
        folderInput.value = "";
      });
    }

    function addCard(item, style) {
      var card = document.createElement("article");
      card.className = "card";
      card.innerHTML =
        '<div class="frame"><img class="result" hidden alt="">' +
        '<div class="state busy">그리는 중…</div></div>' +
        '<div class="card-foot"><div><strong></strong>' +
        '<p class="muted"></p></div>' +
        '<a class="btn btn-sm download" hidden download>저장</a></div>';
      $("strong", card).textContent = item.name;
      $(".muted", card).textContent = STYLE_LABEL[style] || style;
      grid.appendChild(card);
      return card;
    }

    function run() {
      var styles = selectedStyles();
      if (!state.token || !state.items.length || !styles.length || state.busy) return;

      var jobs = [];
      state.items.forEach(function (item) {
        styles.forEach(function (style) { jobs.push({ item: item, style: style }); });
      });

      var runId = ++state.run;
      state.busy = true;
      btnZip.hidden = true;
      grid.innerHTML = "";
      refreshRunButton();

      var done = 0;
      progressEl.textContent = "0 / " + jobs.length + " 변환 중…";

      pooled(jobs, function (job) {
        if (runId !== state.run) return;
        var card = addCard(job.item, job.style);
        var img = $(".result", card);
        var stateEl = $(".state", card);

        return postJSON("/api/transform", {
          token: state.token,
          index: job.item.index,
          style: job.style,
          colors: isTunable(job.style) ? state.colors : 0
        }).then(function (data) {
          if (runId !== state.run) return;
          return loadImage(img, data.url).then(function () {
            img.hidden = false;
            stateEl.hidden = true;
            var link = $(".download", card);
            link.hidden = false;
            link.href = data.download_url;
            img.addEventListener("click", function () {
              openLightbox(img.src, job.item.name + " · " + (STYLE_LABEL[job.style] || job.style));
            });
          });
        }).catch(function (err) {
          if (runId !== state.run) return;
          stateEl.textContent = err.message || "변환 실패";
          stateEl.className = "state failed";
        }).then(function () {
          if (runId === state.run) {
            progressEl.textContent = (++done) + " / " + jobs.length + " 변환 중…";
          }
        });
      }).then(function () {
        if (runId !== state.run) return;
        state.busy = false;
        progressEl.textContent = jobs.length + "장 완료";
        btnZip.hidden = false;
        refreshRunButton();
      });
    }

    function clear() {
      state.run++;
      state.token = null;
      state.items = [];
      state.busy = false;
      setup.hidden = true;
      grid.innerHTML = "";
      stack.innerHTML = "";
      dropzone.classList.remove("compact");
      progressEl.textContent = "";
      btnZip.hidden = true;
      showError(errorEl, "");
      refreshRunButton();
    }

    // 라벨 안의 가짜 버튼 — 폴더 쪽은 다른 input을 열어야 한다.
    $("#pick-files").addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      fileInput.click();
    });

    $("#pick-folder").addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      folderInput.click();
    });

    fileInput.addEventListener("change", function () { pick(fileInput.files); });
    folderInput.addEventListener("change", function () { pick(folderInput.files); });

    dropzone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });

    chips.addEventListener("click", function (e) {
      var chip = e.target.closest(".chip");
      if (!chip || state.busy) return;
      chip.classList.toggle("on");
      refreshRunButton();
    });

    $("#btn-style-all").addEventListener("click", function () {
      if (state.busy) return;
      var all = $$(".chip", chips);
      var everyOn = all.every(function (c) { return c.classList.contains("on"); });
      all.forEach(function (c) { c.classList.toggle("on", !everyOn); });
      // 하나도 없으면 첫 번째는 남겨 둔다.
      if (everyOn && all.length) all[0].classList.add("on");
      refreshRunButton();
    });

    segmented($("#batch-colors"), function (next) { state.colors = next; });

    btnRun.addEventListener("click", run);
    btnClear.addEventListener("click", clear);

    btnZip.addEventListener("click", function () {
      if (!state.token) return;
      window.location.href = "/api/zip/" + state.token +
        "?colors=" + state.colors + "&styles=" + selectedStyles().join(",");
    });

    refreshRunButton();

    return { pick: pick, dropzone: dropzone };
  })();

  // ------------------------------------------------- 드래그앤드롭 · 붙여넣기

  ["dragenter", "dragover"].forEach(function (type) {
    window.addEventListener(type, function (e) {
      e.preventDefault();
      var zone = currentMode === "batch" ? batch.dropzone : single.dropzone;
      if (currentMode === "single" && !single.isIdle()) return;
      zone.classList.add("over");
    });
  });

  ["dragleave", "drop"].forEach(function (type) {
    window.addEventListener(type, function (e) {
      e.preventDefault();
      if (type === "dragleave" && e.relatedTarget) return;
      single.dropzone.classList.remove("over");
      batch.dropzone.classList.remove("over");
    });
  });

  window.addEventListener("drop", function (e) {
    var files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;
    if (currentMode === "batch") batch.pick(files);
    else single.handleFile(files[0]);
  });

  window.addEventListener("paste", function (e) {
    var files = e.clipboardData && e.clipboardData.files;
    if (!files || !files.length) return;
    if (currentMode === "batch") batch.pick(files);
    else single.handleFile(files[0]);
  });
})();
