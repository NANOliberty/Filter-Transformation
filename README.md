# 🎨 만화 필터

사진을 올리면 네 가지 만화풍 스타일로 바꿔 주는 웹 앱입니다.
OpenCV 필터를 그대로 쓰기 때문에 CLI로 돌린 결과와 웹에서 받은 결과가 동일합니다.

## 스타일

| 키 | 이름 | 설명 | 색상 수 조절 |
|---|---|---|---|
| `soft` | 소프트 | `cv2.stylization` — 수채화처럼 부드럽게 번지는 느낌 | ✕ |
| `blobby` | 블로비 | Mean-shift + 색상 양자화 — 뭉텅한 스티커 느낌 | ○ (기본 12색) |
| `poster` | 포스터 | Bilateral + 색상 양자화 — 납작한 포스터 느낌 | ○ (기본 7색) |
| `ink` | 잉크 | 적응형 이진화 윤곽선 + 색상 양자화 — 만화책 느낌 | ○ (기본 10색) |

## 실행

```bash
python3 -m venv .venv
source .venv/bin/activate          # 윈도우: .venv\Scripts\activate
pip install -r requirements.txt

python app.py                      # http://127.0.0.1:5000
```

`PORT`, `HOST` 환경변수로 주소를 바꿀 수 있습니다.

## 사용법

1. 사진을 드래그해서 놓거나, 영역을 클릭해 고르거나, <kbd>Ctrl</kbd>+<kbd>V</kbd>로 붙여넣습니다.
2. 네 가지 스타일이 순서대로 변환됩니다.
3. **색상 수**를 바꾸면 영향을 받는 세 스타일이 다시 그려집니다. (`자동`은 스타일별 기본값)
4. 카드의 **저장** 버튼으로 한 장씩, **전체 다운로드**로 네 장을 zip으로 받습니다.

입력 이미지는 긴 변이 1400px을 넘으면 자동으로 줄여서 처리합니다.

## CLI

웹 없이 폴더 단위로 일괄 변환할 수도 있습니다.

```bash
python cartoonize.py photos/ -o out/ -s all      # 네 스타일 전부
python cartoonize.py a.jpg -s ink                # 한 장, 잉크 스타일만
```

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PORT` | `5000` | 서버 포트 |
| `HOST` | `127.0.0.1` | 바인딩 주소 |
| `CARTOON_MAX_UPLOAD_MB` | `16` | 업로드 용량 상한 |
| `CARTOON_MAX_AGE_SECONDS` | `3600` | 임시 파일 보관 시간 |
| `CARTOON_WORKDIR` | `$TMPDIR/cartoon_web` | 임시 파일 위치 |
| `CARTOON_DEBUG` | (없음) | 값을 주면 Flask 디버그 모드 |

## 배포

`python app.py`의 개발 서버 대신 gunicorn을 씁니다. 변환은 CPU를 오래 쓰므로
타임아웃을 넉넉히 잡고, 워커 수는 코어 수에 맞춥니다.

```bash
gunicorn -w 2 --threads 2 --timeout 120 -b 0.0.0.0:$PORT app:app
```

Render·Railway·Fly 등에서는 저장소의 `Procfile`이 그대로 쓰입니다.
`opencv-python-headless`를 쓰므로 GUI 라이브러리 없이도 설치됩니다.

## 이미지 보관

업로드한 원본과 변환 결과는 서버의 임시 디렉터리에만 저장되고,
새 업로드가 들어올 때 한 시간이 지난 파일이 자동으로 삭제됩니다.
컨테이너를 여러 개 띄우면 인스턴스마다 임시 파일이 따로 생기므로,
같은 세션이 같은 인스턴스로 가도록 세션 고정을 켜거나 워커를 하나로 두세요.
