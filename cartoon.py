"""이미지를 만화풍으로 바꾸는 필터 모음.

CLI(cartoonize.py)와 웹 서버(app.py)가 이 모듈을 함께 사용한다.
"""
import cv2
import numpy as np

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MAX_SIDE = 1400


def fit(img, max_side=MAX_SIDE):
    """긴 변이 max_side를 넘으면 비율을 유지한 채 줄인다."""
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img
    s = max_side / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


# 이전 이름과의 호환용
_fit = fit


def quantize(img, k=10):
    """K-means 색상 양자화 — 색을 k개로 줄여 뭉텅한 면을 만든다."""
    Z = img.reshape((-1, 3)).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(Z, k, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    return np.uint8(centers)[labels.flatten()].reshape(img.shape)


def style_soft(img, colors=None):
    """색 수와 무관한 스타일 — colors 인자는 무시한다."""
    return cv2.stylization(img, sigma_s=60, sigma_r=0.45)


def style_blobby(img, colors=None):
    out = cv2.pyrMeanShiftFiltering(img, sp=20, sr=45, maxLevel=1)
    out = quantize(out, k=colors or 12)
    return cv2.medianBlur(out, 7)


def style_poster(img, colors=None):
    out = cv2.bilateralFilter(img, 9, 100, 100)
    out = quantize(out, k=colors or 7)
    return cv2.medianBlur(out, 5)


def style_ink(img, colors=None):
    gray = cv2.medianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 5)
    edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY, 9, 6)
    color = quantize(cv2.bilateralFilter(img, 9, 250, 250), k=colors or 10)
    return cv2.bitwise_and(color, color, mask=edges)


STYLES = {"soft": style_soft, "blobby": style_blobby,
          "poster": style_poster, "ink": style_ink}

# 웹 UI에 노출할 스타일 정보. tunable=False면 색상 수 조절이 의미 없다.
STYLE_INFO = [
    {"key": "soft", "label": "소프트",
     "desc": "수채화처럼 부드럽게 번지는 느낌", "tunable": False},
    {"key": "blobby", "label": "블로비",
     "desc": "색 덩어리가 뭉텅뭉텅한 스티커 느낌", "tunable": True},
    {"key": "poster", "label": "포스터",
     "desc": "색을 확 줄인 납작한 포스터 느낌", "tunable": True},
    {"key": "ink", "label": "잉크",
     "desc": "검은 윤곽선이 살아있는 만화책 느낌", "tunable": True},
]


# 색상 수 조절이 실제로 결과를 바꾸는 스타일
TUNABLE = {s["key"] for s in STYLE_INFO if s["tunable"]}


def normalize_colors(style, colors):
    """조절이 무의미한 스타일은 색상 수를 0(기본값)으로 눕힌다."""
    return int(colors or 0) if style in TUNABLE else 0


def apply_style(img, style, colors=None):
    """style 이름으로 필터를 적용한다. colors는 None/0이면 스타일 기본값."""
    if style not in STYLES:
        raise KeyError(style)
    return STYLES[style](img, colors or None)
