#!/usr/bin/env python3
"""내 컴퓨터에서 만화 필터를 띄우는 실행기.

    python run.py

필요한 것을 알아서 갖춰 놓고 브라우저까지 열어 준다.

1. 가상환경(.venv)이 없으면 만들고 의존성을 설치한 뒤 그 파이썬으로 다시 실행
2. 이 컴퓨터의 코어 수에 맞춰 설정을 잡음
3. 서버를 띄우고 브라우저를 염

서버를 끄려면 이 창에서 Ctrl+C.
"""
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def venv_python():
    """가상환경 안의 파이썬 경로. 윈도우는 Scripts, 나머지는 bin."""
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def in_venv():
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_venv():
    """가상환경을 갖추고, 아직 그 안이 아니면 그쪽 파이썬으로 다시 실행한다."""
    if in_venv():
        return

    if not venv_python().exists():
        print("[1/3] 가상환경을 만드는 중… (.venv)")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        print("[2/3] 필요한 것을 설치하는 중… 처음 한 번만 몇 분 걸립니다")
        subprocess.check_call([str(venv_python()), "-m", "pip", "install",
                               "--upgrade", "pip", "--quiet"])
        subprocess.check_call([str(venv_python()), "-m", "pip", "install",
                               "-r", str(REQUIREMENTS), "--quiet"])

    # 준비된 파이썬으로 이 스크립트를 다시 실행한다.
    os.execv(str(venv_python()), [str(venv_python()), str(Path(__file__).resolve())])


def tune():
    """이 컴퓨터에 맞는 기본값. 환경변수로 미리 정해 둔 값이 있으면 그것을 존중한다."""
    cores = os.cpu_count() or 2

    defaults = {
        # 내 컴퓨터에서는 화질을 아낄 이유가 없다.
        "CARTOON_MAX_SIDE": "2000",
        # 변환을 한 번에 몇 장씩 굴릴지. OpenCV가 이미 코어를 나눠 쓰므로
        # 코어 수만큼 올려도 그만큼 배로 빨라지지는 않는다.
        "CARTOON_CONCURRENCY": str(max(1, min(cores // 2, 4))),
        # 폴더째 넣고 돌리는 용도라 넉넉하게.
        "CARTOON_MAX_BATCH_FILES": "200",
        "CARTOON_MAX_UPLOAD_MB": "64",
        # 결과를 천천히 골라 담을 수 있게 여섯 시간.
        "CARTOON_MAX_AGE_SECONDS": "21600",
        "PORT": "5000",
        "HOST": "127.0.0.1",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    return cores


def main():
    ensure_venv()
    cores = tune()

    try:
        import app  # 환경변수를 먼저 세운 뒤에 읽어 들여야 한다
    except ImportError as err:
        # 예전에 만들어 둔 .venv가 비어 있는 경우가 대부분이다.
        print(f"\n필요한 것이 빠져 있습니다: {err}")
        print(f"{VENV} 폴더를 지우고 다시 실행해 보세요.")
        sys.exit(1)

    host = os.environ["HOST"]
    port = int(os.environ["PORT"])
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"

    print(f"[3/3] 준비 끝 — 코어 {cores}개")
    print(f"      처리 해상도 {os.environ['CARTOON_MAX_SIDE']}px, "
          f"동시 변환 {os.environ['CARTOON_CONCURRENCY']}장, "
          f"일괄 {os.environ['CARTOON_MAX_BATCH_FILES']}장까지")
    print(f"      {url}  (끄려면 Ctrl+C)")

    if not os.environ.get("CARTOON_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # 여러 장을 동시에 변환하려면 요청을 동시에 받아야 한다.
    app.app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n서버를 껐습니다.")
