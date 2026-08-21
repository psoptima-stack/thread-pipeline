# -*- coding: utf-8 -*-
"""
발행일 원고를 인스타그램 캐러셀 카드 이미지로 변환.

동작:
  - '../email/발행일정.csv' 에서 오늘(또는 --date) 글을 찾음
  - '../threads/<html basename>.txt' 의 '━━━' 구간을 카드 한 장씩으로
  - 1장은 제목 표지, 이후는 본문. 마지막 장 하단에 안내 문구
  - 결과: cards/<날짜>/01.jpg, 02.jpg, ...
    (인스타그램 게시 API는 JPEG만 받으므로 기본 확장자가 jpg)

사용:
  python make_cards.py                 # 오늘 날짜
  python make_cards.py --date 2026-08-18
  python make_cards.py --format png    # 미리보기용 PNG
"""
import argparse
import csv
import datetime
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(BASE, "..", "email", "발행일정.csv")
THREADS_DIR = os.path.join(BASE, "..", "threads")
FONT_DIR = os.path.join(BASE, "fonts")
CARDS_DIR = os.path.join(BASE, "cards")

W, H = 1080, 1350          # 인스타 4:5 (피드에서 가장 넓게 보이는 비율)
MARGIN = 100
BLOG = "makesmile.tistory.com"

# 세이지 톤
THEME = {
    "bg": "#E8EDE6",
    "fg": "#2B332A",
    "accent": "#6B8F5E",
    "sub": "#7C8A78",
}

FONT_REGULAR = os.path.join(FONT_DIR, "NanumGothic.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "NanumGothicBold.ttf")


def find_row(target_date):
    with open(SCHEDULE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["date"].strip() == target_date:
                return row
    return None


def clean_tail(text):
    """마지막 구간에 붙은 블로그 링크·해시태그 줄을 카드에서 제외."""
    keep = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("#") or s.startswith("🔗") or BLOG in s:
            continue
        keep.append(line)
    return "\n".join(keep).strip()


def split_segments(text):
    parts = re.split(r"━━━.*?━━━", text)
    return [clean_tail(p) for p in parts if clean_tail(p)]


def wrap(draw, text, font, max_w):
    """픽셀 폭 기준 줄바꿈. 어절(띄어쓰기) 단위로 끊어 단어가 잘리지 않게 함.
    한 어절이 한 줄보다 길면 그때만 글자 단위로 자름. 원고의 빈 줄은 유지."""
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
            cand = word if not cur else cur + " " + word
            if draw.textlength(cand, font=font) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
            # 어절 하나가 통째로 너무 길면 글자 단위로 분해
            if draw.textlength(word, font=font) <= max_w:
                cur = word
            else:
                for ch in word:
                    if draw.textlength(cur + ch, font=font) <= max_w:
                        cur += ch
                    else:
                        lines.append(cur)
                        cur = ch
        if cur:
            lines.append(cur)
    return lines


def fit_font(draw, text, max_w, max_h, path, sizes):
    """글자 수가 구간마다 달라서, 넘치지 않는 가장 큰 크기를 고름."""
    for size in sizes:
        font = ImageFont.truetype(path, size)
        lines = wrap(draw, text, font, max_w)
        line_h = int(size * 1.62)
        if len(lines) * line_h <= max_h:
            return font, lines, line_h
    # 가장 작은 크기로도 넘치면 그대로 사용(잘릴 수 있음)
    font = ImageFont.truetype(path, sizes[-1])
    lines = wrap(draw, text, font, max_w)
    return font, lines, int(sizes[-1] * 1.62)


def save_card(img, out):
    """JPEG는 색번짐(크로마 서브샘플링)을 끄고 저장해야 글자가 뭉개지지 않음."""
    if out.lower().endswith((".jpg", ".jpeg")):
        img.save(out, quality=95, subsampling=0)
    else:
        img.save(out)


def base_card():
    img = Image.new("RGB", (W, H), THEME["bg"])
    d = ImageDraw.Draw(img)
    # 시리즈 식별용 포인트 바
    d.rectangle([MARGIN, 110, MARGIN + 90, 118], fill=THEME["accent"])
    return img, d


def footer(d, page, total, last=False):
    foot = ImageFont.truetype(FONT_REGULAR, 28)
    left = "전문은 프로필 링크에서" if last else BLOG
    d.text((MARGIN, H - 130), left, font=foot, fill=THEME["sub"])
    num = f"{page} / {total}"
    d.text((W - MARGIN - d.textlength(num, font=foot), H - 130),
           num, font=foot, fill=THEME["sub"])


def make_cover(title, series, total, out):
    img, d = base_card()
    d.text((MARGIN, 150), series, font=ImageFont.truetype(FONT_BOLD, 30),
           fill=THEME["accent"])

    font, lines, lh = fit_font(d, title, W - MARGIN * 2, 620,
                               FONT_BOLD, [76, 68, 60, 54, 48])
    y = (H - len(lines) * lh) // 2
    for ln in lines:
        d.text((MARGIN, y), ln, font=font, fill=THEME["fg"])
        y += lh

    d.text((MARGIN, y + 60), "→ 넘겨서 읽기",
           font=ImageFont.truetype(FONT_REGULAR, 32), fill=THEME["accent"])
    footer(d, 1, total)
    save_card(img, out)


def make_body(text, page, total, out):
    img, d = base_card()
    font, lines, lh = fit_font(d, text, W - MARGIN * 2, 880,
                               FONT_REGULAR, [56, 52, 48, 44, 40, 36])
    y = (H - len(lines) * lh) // 2 + 20
    for ln in lines:
        d.text((MARGIN, y), ln, font=font, fill=THEME["fg"])
        y += lh
    footer(d, page, total, last=(page == total))
    save_card(img, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (미지정 시 오늘)")
    ap.add_argument("--format", choices=["jpg", "png"], default="jpg",
                    help="저장 형식 (기본 jpg — 인스타 게시 API는 JPEG만 허용)")
    args = ap.parse_args()
    ext = args.format

    target_date = args.date or datetime.date.today().isoformat()
    row = find_row(target_date)
    if not row:
        print(f"[알림] {target_date} 에 발행할 글이 없습니다. 종료합니다.")
        return

    base = os.path.splitext(row["html_file"])[0]
    txt_path = os.path.join(THREADS_DIR, base + ".txt")
    if not os.path.exists(txt_path):
        print(f"[경고] 원고가 없습니다: {txt_path}")
        return

    with open(txt_path, encoding="utf-8") as f:
        segs = split_segments(f.read())
    if not segs:
        print("[경고] 카드로 만들 내용이 없습니다.")
        return

    out_dir = os.path.join(CARDS_DIR, target_date)
    os.makedirs(out_dir, exist_ok=True)

    total = len(segs) + 1      # 표지 + 본문
    if total > 10:
        print(f"[주의] 카드가 {total}장입니다. 인스타 캐러셀은 최대 10장이라 "
              f"게시할 때 앞 10장만 올라갑니다.")
    series = "얼굴은 마음이 그리는 지도"
    make_cover(row["title"], series, total, os.path.join(out_dir, f"01.{ext}"))
    for i, seg in enumerate(segs, start=2):
        make_body(seg, i, total, os.path.join(out_dir, f"{i:02d}.{ext}"))

    print(f"[완료] {target_date} 카드 {total}장 생성 → {out_dir}")


if __name__ == "__main__":
    main()
