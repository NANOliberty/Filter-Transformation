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


KMEANS_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
KMEANS_SAMPLE = 80000     # 중심을 학습할 때 쓰는 최대 픽셀 수
MEANSHIFT_SIDE = 700      # 평균이동 필터를 돌릴 최대 해상도


def _nearest_center(Z, centers, chunk=1 << 20):
    """각 픽셀을 가장 가까운 중심에 배정한다.

    거리 비교에는 ‖z‖²이 필요 없으므로 ‖c‖² − 2·z·c 만 계산한다.
    행렬 곱 한 번이면 되고, 메모리를 아끼려 덩어리로 끊어 돈다.
    """
    half_sq = (centers ** 2).sum(1) * 0.5
    out = np.empty(Z.shape[0], np.int32)
    for i in range(0, Z.shape[0], chunk):
        block = Z[i:i + chunk]
        out[i:i + chunk] = (half_sq - block @ centers.T).argmin(1)
    return out


def quantize(img, k=10):
    """K-means 색상 양자화 — 색을 k개로 줄여 뭉텅한 면을 만든다.

    큰 이미지는 픽셀을 고르게 솎아 중심만 학습하고, 배정은 전체 픽셀에 한다.
    모든 픽셀로 학습할 때와 결과는 사실상 같으면서 열 배쯤 빠르다.
    """
    Z = img.reshape((-1, 3)).astype(np.float32)
    step = max(Z.shape[0] // KMEANS_SAMPLE, 1)
    data = Z if step == 1 else np.ascontiguousarray(Z[::step])
    _, _, centers = cv2.kmeans(data, k, None, KMEANS_CRITERIA, 5,
                               cv2.KMEANS_PP_CENTERS)
    return np.uint8(centers)[_nearest_center(Z, centers)].reshape(img.shape)


def style_soft(img, colors=None):
    """색 수와 무관한 스타일 — colors 인자는 무시한다."""
    return cv2.stylization(img, sigma_s=60, sigma_r=0.45)


def style_blobby(img, colors=None):
    # 평균이동 필터는 해상도가 커질수록 급격히 느려진다. 작게 줄여 돌린 뒤
    # 원래 크기로 되돌린다 — 어차피 색을 뭉치는 필터라 차이가 거의 없다.
    h, w = img.shape[:2]
    scale = min(1.0, MEANSHIFT_SIDE / max(h, w))
    if scale < 1.0:
        small = cv2.resize(img, (max(int(w * scale), 1), max(int(h * scale), 1)),
                           interpolation=cv2.INTER_AREA)
        shifted = cv2.pyrMeanShiftFiltering(small, sp=max(int(20 * scale), 2),
                                            sr=45, maxLevel=1)
        out = cv2.resize(shifted, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
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


def style_pencil(img, colors=None):
    """연필 스케치 — 흑백 선과 부드러운 음영."""
    gray, _ = cv2.pencilSketch(img, sigma_s=60, sigma_r=0.07, shade_factor=0.045)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def style_crayon(img, colors=None):
    """색연필 — 종이 위에 색으로 슥슥 그린 느낌."""
    _, color = cv2.pencilSketch(img, sigma_s=60, sigma_r=0.07, shade_factor=0.04)
    return color


def style_oil(img, colors=None):
    """유화 — 주변에서 가장 흔한 밝기의 색으로 뭉개 붓자국을 만든다."""
    levels = max(int(colors or 8), 3)
    radius = 4
    ksize = (radius * 2 + 1, radius * 2 + 1)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    idx = (gray.astype(np.float32) * (levels / 256.0)).astype(np.int32)
    src = img.astype(np.float32)

    best_count = np.zeros(gray.shape, np.float32)
    best_sum = np.zeros(img.shape, np.float32)
    for level in range(levels):
        mask = (idx == level).astype(np.float32)
        count = cv2.boxFilter(mask, -1, ksize, normalize=False)
        total = cv2.boxFilter(src * mask[..., None], -1, ksize, normalize=False)
        better = count > best_count
        best_count = np.where(better, count, best_count)
        best_sum = np.where(better[..., None], total, best_sum)

    out = best_sum / np.maximum(best_count, 1)[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


def _outline(img, block=9, c=7, thickness=1):
    """굵기를 조절할 수 있는 윤곽선 마스크(255=선)를 만든다."""
    gray = cv2.medianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 5)
    edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY_INV, block, c)
    edges = cv2.medianBlur(edges, 3)  # 자잘한 점 노이즈 제거
    if thickness > 1:
        edges = cv2.dilate(edges, np.ones((thickness, thickness), np.uint8))
    return edges


def style_pop(img, colors=None):
    """팝아트 — 채도를 끌어올리고 색을 줄인 뒤 굵은 선을 얹는다."""
    base = cv2.bilateralFilter(img, 9, 120, 120)
    hsv = cv2.cvtColor(base, cv2.COLOR_BGR2HSV).astype(np.int32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 2.1, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 1.12 + 12, 0, 255)
    vivid = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    out = quantize(vivid, k=colors or 5)
    # 털·머리카락 같은 잔결에서 선이 부서지지 않도록 부드럽게 만든 뒤 딴다.
    out[_outline(base, block=15, c=11, thickness=3) > 0] = (25, 20, 30)
    return out


def style_neon(img, colors=None):
    """네온 — 어두운 배경 위에 형광 윤곽선이 빛나는 느낌."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.bitwise_or(cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 140),
                           _outline(img))
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))

    glow = cv2.GaussianBlur(edges.astype(np.float32) / 255.0, (0, 0), 5)
    glow = glow / max(float(glow.max()), 1e-6)

    # 밝기에 따라 시안↔마젠타로 물드는 형광 색판
    tint = cv2.applyColorMap(cv2.GaussianBlur(gray, (0, 0), 2),
                             cv2.COLORMAP_COOL).astype(np.float32)

    line = (edges > 0).astype(np.float32)[..., None]
    amount = np.clip(glow[..., None] * 1.5 + line, 0, 1)
    dark = cv2.bilateralFilter(img, 9, 150, 150).astype(np.float32) * 0.28
    return np.clip(dark * (1 - amount) + tint * amount, 0, 255).astype(np.uint8)


def style_halftone(img, colors=None, cell=None):
    """하프톤 — 인쇄물 망점처럼 색점 크기로 명암을 표현한다."""
    flat = quantize(cv2.bilateralFilter(img, 9, 120, 120), k=colors or 8)
    h, w = flat.shape[:2]
    # 망점 크기는 해상도에 비례시켜, 사진이 커져도 같은 인상을 유지한다.
    cell = int(cell or np.clip(round(max(h, w) / 90), 6, 16))

    # 셀 단위 평균 밝기 — 어두울수록 점이 커진다.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    sh, sw = max(h // cell, 1), max(w // cell, 1)
    lum = cv2.resize(cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA),
                     (w, h), interpolation=cv2.INTER_NEAREST)

    # 망점 격자를 살짝 기울여 인쇄물 느낌을 낸다.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = np.deg2rad(22.0)
    rx = xx * np.cos(ang) + yy * np.sin(ang)
    ry = -xx * np.sin(ang) + yy * np.cos(ang)
    dx = (rx % cell) - cell / 2.0
    dy = (ry % cell) - cell / 2.0
    dist = np.sqrt(dx * dx + dy * dy)

    radius = np.sqrt(np.clip(1.0 - lum, 0, 1)) * (cell * 0.72)
    dots = dist <= radius

    paper = np.full_like(flat, 247)
    return np.where(dots[..., None], flat, paper)


STYLES = {"soft": style_soft, "blobby": style_blobby,
          "poster": style_poster, "ink": style_ink,
          "pop": style_pop, "oil": style_oil, "halftone": style_halftone,
          "neon": style_neon, "pencil": style_pencil, "crayon": style_crayon}

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
    {"key": "pop", "label": "팝아트",
     "desc": "쨍한 색과 굵은 선의 팝아트 포스터", "tunable": True},
    {"key": "oil", "label": "유화",
     "desc": "붓으로 뭉갠 듯한 유화 질감", "tunable": True},
    {"key": "halftone", "label": "하프톤",
     "desc": "옛날 인쇄물 같은 망점 무늬", "tunable": True},
    {"key": "neon", "label": "네온",
     "desc": "어두운 배경에 형광 윤곽선이 빛나는 느낌", "tunable": False},
    {"key": "pencil", "label": "연필",
     "desc": "흑백 연필 스케치", "tunable": False},
    {"key": "crayon", "label": "색연필",
     "desc": "종이에 색연필로 슥슥 그린 느낌", "tunable": False},
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
