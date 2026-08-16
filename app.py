#!/usr/bin/env python3
"""이미지를 만화풍으로 바꿔주는 웹 앱."""
import io
import json
import os
import re
import time
import uuid
import zipfile

import cv2
import numpy as np
from flask import Flask, abort, jsonify, request, send_file, render_template

from cartoon import STYLE_INFO, STYLES, apply_style, fit, normalize_colors

MAX_UPLOAD_MB = int(os.environ.get("CARTOON_MAX_UPLOAD_MB", "16"))
MAX_AGE_SECONDS = int(os.environ.get("CARTOON_MAX_AGE_SECONDS", "3600"))
MAX_BATCH_FILES = int(os.environ.get("CARTOON_MAX_BATCH_FILES", "40"))
WORK_DIR = os.environ.get(
    "CARTOON_WORKDIR",
    os.path.join(os.environ.get("TMPDIR", "/tmp"), "cartoon_web"),
)
JPEG_PARAMS = [cv2.IMWRITE_JPEG_QUALITY, 95]

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MIN_COLORS, MAX_COLORS = 3, 32

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
os.makedirs(WORK_DIR, exist_ok=True)


# ---------------------------------------------------------------- 저장소 유틸
#
# 한 번의 작업(=토큰)이 이미지를 여러 장 담을 수 있다. 한 장짜리 변환은
# 장이 하나뿐인 작업일 뿐이라 저장 구조가 하나로 통일된다.
#
#   {token}_meta.json       {"stems": ["사진1", "사진2"], "created": ...}
#   {token}_{i}_src.jpg     i번째 원본(축소본)
#   {token}_{i}_{style}-{colors}.jpg   변환 결과


def _path(token, name):
    return os.path.join(WORK_DIR, f"{token}_{name}")


def _item_path(token, index, name):
    return _path(token, f"{index}_{name}")


def _check_token(token):
    """토큰 형식을 검증한다 — 경로 조작을 막기 위한 필수 관문."""
    if not TOKEN_RE.match(token or ""):
        abort(404, description="잘못된 주소입니다.")
    return token


def _meta(token):
    try:
        with open(_path(token, "meta.json"), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        abort(404, description="만료되었거나 존재하지 않는 이미지입니다.")


def _save_meta(token, meta):
    with open(_path(token, "meta.json"), "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False)


def _check_index(meta, index):
    if not 0 <= index < len(meta["stems"]):
        abort(404, description="없는 이미지입니다.")
    return index


def _purge_old():
    """오래된 작업 파일을 지운다. 업로드마다 한 번씩 훑는다."""
    now = time.time()
    try:
        entries = os.listdir(WORK_DIR)
    except OSError:
        return
    for name in entries:
        p = os.path.join(WORK_DIR, name)
        try:
            if now - os.path.getmtime(p) > MAX_AGE_SECONDS:
                os.remove(p)
        except OSError:
            pass


def _safe_stem(name):
    """업로드 파일명에서 다운로드용 이름을 만든다."""
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    stem = re.sub(r"[^\w가-힣 .-]", "", stem).strip(" .")
    return stem[:60] or "image"


def _encode_jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, JPEG_PARAMS)
    if not ok:
        abort(500, description="이미지 인코딩에 실패했습니다.")
    return buf.tobytes()


def _serve(path, download_name=None):
    if not os.path.exists(path):
        abort(404, description="결과가 만료되었습니다. 다시 변환해 주세요.")
    return send_file(path, mimetype="image/jpeg",
                     as_attachment=bool(download_name),
                     download_name=download_name,
                     max_age=0 if download_name else 3600)


def _store_source(token, index, raw):
    """업로드된 바이트를 디코딩·축소해 원본 자리에 저장한다."""
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = fit(img)
    with open(_item_path(token, index, "src.jpg"), "wb") as fp:
        fp.write(_encode_jpeg(img))
    h, w = img.shape[:2]
    return w, h


def _parse_colors(value):
    try:
        colors = int(value or 0)
    except (TypeError, ValueError):
        abort(400, description="색상 수가 올바르지 않습니다.")
    if colors and not (MIN_COLORS <= colors <= MAX_COLORS):
        abort(400, description=f"색상 수는 {MIN_COLORS}~{MAX_COLORS} 사이여야 합니다.")
    return colors


def _result_url(token, index, style, colors, download=False):
    url = f"/api/image/{token}/{index}/{style}/{colors}"
    return url + "?dl=1" if download else url


def _item_json(token, index, stem, size):
    return {"index": index, "name": stem, "width": size[0], "height": size[1],
            "src_url": f"/api/image/{token}/{index}/src"}


# -------------------------------------------------------------------- 라우트


@app.get("/")
def index():
    return render_template("index.html", styles=STYLE_INFO,
                           max_upload_mb=MAX_UPLOAD_MB,
                           max_batch_files=MAX_BATCH_FILES,
                           min_colors=MIN_COLORS, max_colors=MAX_COLORS)


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.post("/api/upload")
def upload():
    """한 장짜리 작업을 만든다."""
    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify(error="이미지 파일을 선택해 주세요."), 400

    raw = file.read()
    if not raw:
        return jsonify(error="빈 파일입니다."), 400

    _purge_old()
    token = uuid.uuid4().hex
    size = _store_source(token, 0, raw)
    if size is None:
        return jsonify(error="읽을 수 없는 이미지 형식입니다. "
                             "JPG·PNG·WEBP·BMP·TIFF를 지원합니다."), 400

    stem = _safe_stem(file.filename)
    _save_meta(token, {"stems": [stem], "created": time.time()})
    return jsonify(token=token, **_item_json(token, 0, stem, size))


@app.post("/api/batch/create")
def batch_create():
    """빈 일괄 변환 작업을 만든다. 파일은 한 장씩 따로 올린다."""
    _purge_old()
    token = uuid.uuid4().hex
    _save_meta(token, {"stems": [], "created": time.time()})
    return jsonify(token=token, max_files=MAX_BATCH_FILES)


@app.post("/api/batch/add")
def batch_add():
    """일괄 작업에 이미지 한 장을 덧붙인다.

    한 요청에 한 장만 받는다. 요청 크기 제한을 장당으로 걸 수 있고,
    브라우저가 진행 상황을 장 단위로 보여줄 수 있다.
    """
    token = _check_token(request.form.get("token", ""))
    meta = _meta(token)
    if len(meta["stems"]) >= MAX_BATCH_FILES:
        return jsonify(error=f"한 번에 {MAX_BATCH_FILES}장까지 올릴 수 있어요."), 400

    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify(error="이미지 파일을 선택해 주세요."), 400

    raw = file.read()
    if not raw:
        return jsonify(error="빈 파일입니다."), 400

    index = len(meta["stems"])
    size = _store_source(token, index, raw)
    if size is None:
        return jsonify(error="읽을 수 없는 이미지 형식입니다."), 400

    stem = _safe_stem(file.filename)
    meta["stems"].append(stem)
    _save_meta(token, meta)
    return jsonify(**_item_json(token, index, stem, size))


@app.post("/api/transform")
def transform():
    data = request.get_json(silent=True) or {}
    token = _check_token(str(data.get("token", "")))
    style = str(data.get("style", ""))
    if style not in STYLES:
        return jsonify(error="알 수 없는 스타일입니다."), 400

    colors = normalize_colors(style, _parse_colors(data.get("colors")))
    meta = _meta(token)
    try:
        index = _check_index(meta, int(data.get("index") or 0))
    except (TypeError, ValueError):
        return jsonify(error="이미지 번호가 올바르지 않습니다."), 400

    src = _item_path(token, index, "src.jpg")
    if not os.path.exists(src):
        return jsonify(error="이미지가 만료되었습니다. 다시 업로드해 주세요."), 404

    out_path = _item_path(token, index, f"{style}-{colors}.jpg")
    started = time.time()
    if not os.path.exists(out_path):
        img = cv2.imread(src)
        if img is None:
            return jsonify(error="이미지를 읽지 못했습니다."), 500
        with open(out_path, "wb") as fp:
            fp.write(_encode_jpeg(apply_style(img, style, colors)))

    return jsonify(style=style, colors=colors, index=index,
                   url=_result_url(token, index, style, colors),
                   download_url=_result_url(token, index, style, colors, True),
                   ms=int((time.time() - started) * 1000))


@app.get("/api/image/<token>/<int:index>/src")
def image_src(token, index):
    _check_token(token)
    _check_index(_meta(token), index)
    return _serve(_item_path(token, index, "src.jpg"))


@app.get("/api/image/<token>/<int:index>/<style>/<int:colors>")
def image_result(token, index, style, colors):
    _check_token(token)
    if style not in STYLES:
        abort(404)
    if colors and not (MIN_COLORS <= colors <= MAX_COLORS):
        abort(404)
    meta = _meta(token)
    _check_index(meta, index)
    name = None
    if request.args.get("dl"):
        name = f"{meta['stems'][index]}_{style}.jpg"
    return _serve(_item_path(token, index, f"{style}-{colors}.jpg"), name)


@app.get("/api/zip/<token>")
def download_zip(token):
    """작업에 남아 있는 결과를 한 파일로 묶는다.

    styles를 주면 그 스타일만, 없으면 결과가 있는 스타일을 모두 담는다.
    """
    _check_token(token)
    meta = _meta(token)
    stems = meta["stems"]
    wanted = _parse_colors(request.args.get("colors"))

    styles = [s for s in request.args.get("styles", "").split(",") if s]
    unknown = [s for s in styles if s not in STYLES]
    if unknown:
        abort(400, description="알 수 없는 스타일입니다.")
    styles = styles or list(STYLES)

    # 파일 이름이 겹치면 앞에 번호를 붙여 서로 덮어쓰지 않게 한다.
    counts = {}
    for stem in stems:
        counts[stem] = counts.get(stem, 0) + 1

    found = []
    for index, stem in enumerate(stems):
        label = f"{index + 1:02d}_{stem}" if counts[stem] > 1 else stem
        for style in styles:
            path = _find_result(token, index, style, wanted)
            if path is not None:
                found.append((style, f"{label}_{style}.jpg", path))
    if not found:
        abort(404, description="다운로드할 결과가 없습니다.")

    # 실제로 담긴 스타일이 둘 이상일 때만 폴더로 나눈다.
    grouped = len({style for style, _, _ in found}) > 1
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for style, arc, path in found:
            zf.write(path, f"{style}/{arc}" if grouped else arc)

    buf.seek(0)
    base = stems[0] if len(stems) == 1 else f"{len(stems)}장"
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{base}_cartoon.zip")


def _find_result(token, index, style, wanted):
    """요청한 색상 수를 우선 쓰고, 없으면 남아 있는 결과라도 찾는다."""
    candidates = [normalize_colors(style, wanted)]
    candidates += [c for c in range(0, MAX_COLORS + 1) if c not in candidates]
    for colors in candidates:
        path = _item_path(token, index, f"{style}-{colors}.jpg")
        if os.path.exists(path):
            return path
    return None


# -------------------------------------------------------------------- 에러


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def _json_error(err):
    desc = getattr(err, "description", "요청을 처리하지 못했습니다.")
    if request.path.startswith("/api/"):
        return jsonify(error=desc), err.code
    return render_template("index.html", styles=STYLE_INFO,
                           max_upload_mb=MAX_UPLOAD_MB,
                           max_batch_files=MAX_BATCH_FILES,
                           min_colors=MIN_COLORS,
                           max_colors=MAX_COLORS), err.code


@app.errorhandler(413)
def _too_large(_err):
    return jsonify(error=f"파일이 너무 큽니다. {MAX_UPLOAD_MB}MB 이하로 올려 주세요."), 413


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")),
            debug=bool(os.environ.get("CARTOON_DEBUG")))
