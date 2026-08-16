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


def _path(token, name):
    return os.path.join(WORK_DIR, f"{token}_{name}")


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


# -------------------------------------------------------------------- 라우트


@app.get("/")
def index():
    return render_template("index.html", styles=STYLE_INFO,
                           max_upload_mb=MAX_UPLOAD_MB,
                           min_colors=MIN_COLORS, max_colors=MAX_COLORS)


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.post("/api/upload")
def upload():
    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify(error="이미지 파일을 선택해 주세요."), 400

    raw = file.read()
    if not raw:
        return jsonify(error="빈 파일입니다."), 400

    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return jsonify(error="읽을 수 없는 이미지 형식입니다. "
                             "JPG·PNG·WEBP·BMP·TIFF를 지원합니다."), 400

    _purge_old()

    token = uuid.uuid4().hex
    img = fit(img)
    with open(_path(token, "src.jpg"), "wb") as fp:
        fp.write(_encode_jpeg(img))
    meta = {"stem": _safe_stem(file.filename), "created": time.time()}
    with open(_path(token, "meta.json"), "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False)

    h, w = img.shape[:2]
    return jsonify(token=token, width=w, height=h, name=meta["stem"],
                   src_url=f"/api/image/{token}/src")


@app.post("/api/transform")
def transform():
    data = request.get_json(silent=True) or {}
    token = _check_token(str(data.get("token", "")))
    style = str(data.get("style", ""))
    if style not in STYLES:
        return jsonify(error="알 수 없는 스타일입니다."), 400

    try:
        colors = int(data.get("colors") or 0)
    except (TypeError, ValueError):
        return jsonify(error="색상 수가 올바르지 않습니다."), 400
    if colors and not (MIN_COLORS <= colors <= MAX_COLORS):
        return jsonify(error=f"색상 수는 {MIN_COLORS}~{MAX_COLORS} 사이여야 합니다."), 400
    colors = normalize_colors(style, colors)

    _meta(token)  # 만료 확인
    src = _path(token, "src.jpg")
    if not os.path.exists(src):
        return jsonify(error="이미지가 만료되었습니다. 다시 업로드해 주세요."), 404

    out_path = _path(token, f"{style}-{colors}.jpg")
    started = time.time()
    if not os.path.exists(out_path):
        img = cv2.imread(src)
        if img is None:
            return jsonify(error="이미지를 읽지 못했습니다."), 500
        with open(out_path, "wb") as fp:
            fp.write(_encode_jpeg(apply_style(img, style, colors)))

    return jsonify(style=style, colors=colors,
                   url=f"/api/image/{token}/{style}/{colors}",
                   download_url=f"/api/image/{token}/{style}/{colors}?dl=1",
                   ms=int((time.time() - started) * 1000))


@app.get("/api/image/<token>/src")
def image_src(token):
    _check_token(token)
    return _serve(_path(token, "src.jpg"))


@app.get("/api/image/<token>/<style>/<int:colors>")
def image_result(token, style, colors):
    _check_token(token)
    if style not in STYLES:
        abort(404)
    if colors and not (MIN_COLORS <= colors <= MAX_COLORS):
        abort(404)
    name = None
    if request.args.get("dl"):
        name = f"{_meta(token)['stem']}_{style}.jpg"
    return _serve(_path(token, f"{style}-{colors}.jpg"), name)


@app.get("/api/zip/<token>")
def download_zip(token):
    _check_token(token)
    stem = _meta(token)["stem"]
    try:
        wanted = int(request.args.get("colors") or 0)
    except ValueError:
        wanted = 0
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for style in STYLES:
            # 요청한 색상 수를 우선 쓰고, 없으면 남아 있는 결과라도 담는다.
            candidates = [normalize_colors(style, wanted)]
            candidates += [c for c in range(0, MAX_COLORS + 1)
                           if c not in candidates]
            for colors in candidates:
                p = _path(token, f"{style}-{colors}.jpg")
                if os.path.exists(p):
                    zf.write(p, f"{stem}_{style}.jpg")
                    count += 1
                    break
    if not count:
        abort(404, description="다운로드할 결과가 없습니다.")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{stem}_cartoon.zip")


# -------------------------------------------------------------------- 에러


@app.errorhandler(404)
@app.errorhandler(500)
def _json_error(err):
    desc = getattr(err, "description", "요청을 처리하지 못했습니다.")
    if request.path.startswith("/api/"):
        return jsonify(error=desc), err.code
    return render_template("index.html", styles=STYLE_INFO,
                           max_upload_mb=MAX_UPLOAD_MB,
                           min_colors=MIN_COLORS,
                           max_colors=MAX_COLORS), err.code


@app.errorhandler(413)
def _too_large(_err):
    return jsonify(error=f"파일이 너무 큽니다. {MAX_UPLOAD_MB}MB 이하로 올려 주세요."), 413


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")),
            debug=bool(os.environ.get("CARTOON_DEBUG")))
