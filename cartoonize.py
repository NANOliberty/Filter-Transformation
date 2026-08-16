#!/usr/bin/env python3
"""폴더/파일 단위로 이미지를 만화풍으로 일괄 변환하는 CLI."""
import argparse
import os
import sys

import cv2

from cartoon import EXTS, STYLES, fit


def collect(path):
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        return sorted(os.path.join(path, f) for f in os.listdir(path)
                      if os.path.splitext(f)[1].lower() in EXTS)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="이미지 파일 또는 폴더")
    ap.add_argument("-o", "--outdir", default="./cartoon_out")
    ap.add_argument("-s", "--style", default="blobby",
                    choices=list(STYLES) + ["all"])
    args = ap.parse_args()

    files = collect(args.input)
    if not files:
        sys.exit(f"[!] 이미지 없음: {args.input}")

    os.makedirs(args.outdir, exist_ok=True)
    styles = list(STYLES) if args.style == "all" else [args.style]

    for f in files:
        img = cv2.imread(f)
        if img is None:
            print(f"[!] 읽기 실패: {f}")
            continue
        img = fit(img)
        stem = os.path.splitext(os.path.basename(f))[0]
        for name in styles:
            dst = os.path.join(args.outdir, f"{stem}_{name}.jpg")
            cv2.imwrite(dst, STYLES[name](img), [cv2.IMWRITE_JPEG_QUALITY, 95])
            print(f"[+] {dst}")


if __name__ == "__main__":
    main()
