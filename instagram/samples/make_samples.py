# -*- coding: utf-8 -*-
"""인스타 카드 배경 톤 샘플 4종 생성 (1080x1350, 4:5)"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
FONT_R = r"C:\Windows\Fonts\NanumGothic.ttf"
FONT_B = r"C:\Windows\Fonts\NanumGothicBold.ttf"

W, H = 1080, 1350
MARGIN = 100

TEXT = """지하철 유리창에 비친
내 얼굴을 보고
깜짝 놀란 적 있나요?

화난 것도 아닌데
잔뜩 찌푸리고 있던 그 얼굴.

그게 바로
'습관이 된 표정'입니다."""

THEMES = {
    "A_크림": dict(bg="#F7F3EC", fg="#2E2A26", accent="#C4703F", sub="#8B8177"),
    "B_다크": dict(bg="#1E2229", fg="#F0EDE8", accent="#E0A458", sub="#8A9099"),
    "C_화이트포인트": dict(bg="#FFFFFF", fg="#1A1A1A", accent="#2563EB", sub="#9AA0A6"),
    "D_세이지": dict(bg="#E8EDE6", fg="#2B332A", accent="#6B8F5E", sub="#7C8A78"),
}


def wrap(draw, text, font, max_w):
    """픽셀 폭 기준 줄바꿈. 원고의 빈 줄은 그대로 살림."""
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def make(name, t):
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img)

    body = ImageFont.truetype(FONT_R, 52)
    badge = ImageFont.truetype(FONT_B, 30)
    foot = ImageFont.truetype(FONT_R, 28)

    # 상단 포인트 바 — 시리즈 식별용
    d.rectangle([MARGIN, 110, MARGIN + 90, 118], fill=t["accent"])
    d.text((MARGIN, 150), "얼굴은 마음이 그리는 지도", font=badge, fill=t["accent"])

    # 본문
    lines = wrap(d, TEXT, body, W - MARGIN * 2)
    lh = 84
    y = (H - len(lines) * lh) // 2 + 30
    for ln in lines:
        d.text((MARGIN, y), ln, font=body, fill=t["fg"])
        y += lh

    # 하단
    d.text((MARGIN, H - 130), "makesmile.tistory.com", font=foot, fill=t["sub"])
    d.text((W - MARGIN - d.textlength("1 / 4", font=foot), H - 130),
           "1 / 4", font=foot, fill=t["sub"])

    p = os.path.join(OUT, f"card_{name}.png")
    img.save(p, quality=95)
    print(p)


for n, t in THEMES.items():
    make(n, t)
