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
HALFTONE_PITCH = 150      # 긴 변을 이 값으로 나눈 만큼이 망점 한 칸
SKETCH_SIGMA_DIV = 120    # 긴 변을 이 값으로 나눈 만큼이 연필 획 굵기
PENCIL_TONE = 0.30        # 연필 음영의 진하기 (0이면 흰 여백만 남는다)
PENCIL_INK = 2.0          # 연필 획을 진하게 하는 배수
CRAYON_INK = 3.5          # 색연필 획을 진하게 하는 배수
CRAYON_PAPER = 0.22       # 색연필 색을 종이 쪽으로 옅게 미는 정도
NEON_EDGE_KEEP = 0.06     # 네온에서 선으로 살릴 상위 그라디언트 비율
PIXEL_CELLS = 140         # 픽셀 스타일의 가로 칸 수


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


def _sketch_layers(img):
    """연필 계열이 함께 쓰는 밑작업 — 평활화한 원본과 0~1 스케치.

    예전에는 cv2.pencilSketch를 썼는데, 나뭇잎이나 잔디처럼 잔결이 촘촘한
    곳에서 획이 겹쳐 새까맣게 뭉쳤다. 지금은 흑백을 뒤집어 흐린 것으로
    나누는 닷지 기법을 쓴다. 밝기 차가 생긴 자리에만 획이 남아서
    아무리 결이 촘촘해도 검게 메워지지 않는다.
    """
    smooth = cv2.bilateralFilter(img, 9, 60, 60)
    gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # 획 굵기가 해상도를 따라가도록 흐림 반경을 사진 크기에 비례시킨다.
    sigma = max(3.0, max(img.shape[:2]) / SKETCH_SIGMA_DIV)
    blur = cv2.GaussianBlur(255.0 - gray, (0, 0), sigma)
    sketch = gray * 255.0 / np.maximum(255.0 - blur, 1.0)
    return smooth, np.clip(sketch, 0, 255) / 255.0


def _ink(sketch, amount):
    """그은 자리만 골라 진하게 만든다. 흰 여백은 그대로 둔다."""
    return np.clip(1.0 - (1.0 - sketch) * amount, 0.0, 1.0)


def style_pencil(img, colors=None):
    """연필 스케치 — 흑백 선과 부드러운 음영."""
    smooth, sketch = _sketch_layers(img)

    # 밝기에 따라 옅은 음영을 깔아 준다. 이게 없으면 하늘처럼 매끈한 면이
    # 그대로 흰 여백이 되어 그리다 만 그림처럼 보인다.
    lum = cv2.GaussianBlur(cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY),
                           (0, 0), 3).astype(np.float32)
    tone = 255.0 - (255.0 - lum) * PENCIL_TONE

    out = np.clip(_ink(sketch, PENCIL_INK) * tone, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def style_crayon(img, colors=None):
    """색연필 — 옅게 칠한 색 위에 연필선을 곱해 얹는다."""
    smooth, sketch = _sketch_layers(img)

    hsv = cv2.cvtColor(smooth, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.35, 0, 255)
    color = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    color = color * (1 - CRAYON_PAPER) + 255.0 * CRAYON_PAPER  # 종이 쪽으로 옅게

    out = color * _ink(sketch, CRAYON_INK)[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


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


def _bold_lines(img, keep=0.04, cut=0.5, thickness=2, min_part=1500):
    """굵고 이어지는 윤곽선만 남긴 마스크(255=선).

    잔디나 털처럼 결이 촘촘한 곳에서는 짧은 선 조각이 사방에 생겨 검은
    점처럼 뿌려진다. 결을 먼저 눌러 놓고, 이어진 덩어리가 일정 크기를
    넘는 것만 남기면 굵은 외곽선만 살아남는다.
    """
    flat = cv2.edgePreservingFilter(img, flags=cv2.RECURS_FILTER,
                                    sigma_s=60, sigma_r=0.45)
    mask = (_edge_strength(flat, keep) > cut).astype(np.uint8)

    h, w = mask.shape
    min_area = max(20, int(h * w / min_part))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    big = np.where(stats[:, cv2.CC_STAT_AREA] >= min_area)[0]
    big = big[big != 0]                      # 0번은 배경
    mask = np.isin(labels, big).astype(np.uint8) * 255

    if thickness > 1:
        mask = cv2.dilate(mask, np.ones((thickness, thickness), np.uint8))
    return mask


def style_pop(img, colors=None):
    """팝아트 — 채도를 끌어올리고 색을 줄인 뒤 굵은 선을 얹는다."""
    base = cv2.bilateralFilter(img, 9, 120, 120)
    hsv = cv2.cvtColor(base, cv2.COLOR_BGR2HSV).astype(np.int32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 2.1, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 1.12 + 12, 0, 255)
    vivid = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    out = quantize(vivid, k=colors or 5)
    out[_bold_lines(base) > 0] = (25, 20, 30)
    return out


def style_pixel(img, colors=None):
    """픽셀 — 굵은 픽셀로 줄여 색을 묶고 그대로 확대한다."""
    h, w = img.shape[:2]
    sw = min(PIXEL_CELLS, w)
    sh = max(int(round(h * sw / w)), 1)

    small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.25, 0, 255)   # 게임 화면처럼 또렷하게
    small = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    small = quantize(small, k=colors or 16)

    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def style_horror(img, colors=None):
    """호러 — 핏기를 걷어내고 검게 눌러 앉힌 뒤 가장자리를 어둡게 만든다."""
    base = cv2.bilateralFilter(img, 9, 90, 90)

    # 색을 거의 다 걷어내고 푸른 기만 남긴다.
    hsv = cv2.cvtColor(base, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.08
    drained = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    drained *= np.float32([1.16, 1.00, 0.90])           # B, G, R

    # 어두운 쪽을 더 어둡게 누르는 S자 커브
    x = np.arange(256, dtype=np.float32) / 255.0
    lut = np.uint8(np.clip((x - 0.5) * 1.6 + 0.5, 0, 1) ** 1.6 * 255)
    out = cv2.LUT(np.clip(drained, 0, 255).astype(np.uint8), lut).astype(np.float32)

    # 밝은 곳이 번지는 헐레이션 — 싸구려 필름으로 찍은 듯한 느낌을 준다.
    out += cv2.GaussianBlur(np.clip(out - 150, 0, None), (0, 0), 12) * 0.35

    # 가장자리로 갈수록 빛이 죽는 비네트
    h, w = out.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / np.sqrt(2)
    out *= np.clip(1.0 - 0.85 * dist ** 1.7, 0.05, 1.0)[..., None]

    # 필름 그레인 — 시드를 고정해 같은 사진은 늘 같은 결과가 나오게 한다.
    out += np.random.default_rng(20240816).normal(0, 15, (h, w, 1)).astype(np.float32)

    return np.clip(out, 0, 255).astype(np.uint8)


def _edge_strength(img, keep):
    """상위 keep 비율만 선으로 남기는 0~1 세기 맵.

    고정 임계값을 쓰면 잔디·털처럼 결이 많은 사진에서 화면 전체가 선이
    되어 버린다. 그라디언트 분위수로 기준을 잡으면 어떤 사진이든 선의
    양이 비슷하게 유지된다.
    """
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (0, 0), 2)
    mag = cv2.magnitude(cv2.Scharr(gray, cv2.CV_32F, 1, 0),
                        cv2.Scharr(gray, cv2.CV_32F, 0, 1))
    hi = float(np.quantile(mag, 1.0 - keep))
    lo = hi * 0.35
    return np.clip((mag - lo) / max(hi - lo, 1e-6), 0, 1)


def style_neon(img, colors=None):
    """네온 — 어두운 배경 위에 형광 윤곽선이 빛나는 느낌."""
    # 결을 먼저 눌러 두어야 잔디 같은 잔무늬가 통째로 발광하지 않는다.
    flat = cv2.edgePreservingFilter(img, flags=cv2.RECURS_FILTER,
                                    sigma_s=60, sigma_r=0.5)
    strength = _edge_strength(flat, NEON_EDGE_KEEP)
    glow = cv2.GaussianBlur(strength, (0, 0), 5)
    glow = glow / max(float(glow.max()), 1e-6) * 0.55

    # 밝기에 따라 시안↔마젠타로 물드는 형광 색판
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (0, 0), 2)
    tint = cv2.applyColorMap(gray, cv2.COLORMAP_COOL).astype(np.float32)

    amount = np.clip(strength + glow, 0, 1)[..., None]
    dark = cv2.bilateralFilter(img, 9, 150, 150).astype(np.float32) * 0.30

    # 더하기 대신 스크린 합성 — 밝은 곳이 255에 뭉개지지 않고 빛처럼 얹힌다.
    light = tint * amount
    out = 255.0 - (255.0 - dark) * (255.0 - light) / 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def style_halftone(img, colors=None, cell=None):
    """하프톤 — 인쇄물 망점처럼 색점 크기로 명암을 표현한다."""
    flat = quantize(cv2.bilateralFilter(img, 9, 120, 120), k=colors or 8)
    h, w = flat.shape[:2]
    # 망점 크기는 해상도에 비례시켜, 사진이 커져도 같은 인상을 유지한다.
    cell = int(cell or np.clip(round(max(h, w) / HALFTONE_PITCH), 4, 12))

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
          "neon": style_neon, "pixel": style_pixel, "horror": style_horror,
          "pencil": style_pencil, "crayon": style_crayon}

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
    {"key": "pixel", "label": "픽셀",
     "desc": "옛날 게임 화면 같은 도트 그림", "tunable": True},
    {"key": "horror", "label": "호러",
     "desc": "핏기 없이 어둡게 가라앉은 공포 영화 톤", "tunable": False},
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
