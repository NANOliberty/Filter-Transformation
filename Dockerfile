# 어디서든 같은 방식으로 뜨는 배포용 이미지.
# opencv-python-headless를 쓰므로 GUI 라이브러리를 따로 넣지 않아도 된다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성을 먼저 설치해 두면 코드만 고쳤을 때 이 층이 캐시된다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 변환은 CPU를 오래 쓴다. 워커 수는 WEB_CONCURRENCY로 조절한다.
# 임시 파일이 워커의 로컬 디스크에 남으므로 인스턴스는 하나로 두어야 한다.
ENV PORT=8000 \
    WEB_CONCURRENCY=2

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz')"

CMD gunicorn -w $WEB_CONCURRENCY --threads 2 --timeout 180 \
    -b 0.0.0.0:$PORT app:app
