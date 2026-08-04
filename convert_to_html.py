# -*- coding: utf-8 -*-
"""마크다운 글 -> 티스토리 HTML 모드용 HTML 변환기.
- 맨 위 H1(# 제목)은 티스토리 '제목' 칸에 따로 넣으므로 본문에서 제외.
- tables, blockquote 등 확장 활성화.
"""
import os
import re
import markdown

SRC = "posts"
OUT = "html"
os.makedirs(OUT, exist_ok=True)

# posts 폴더의 모든 .md 파일 변환
files = sorted(f for f in os.listdir(SRC) if f.endswith(".md"))

md = markdown.Markdown(extensions=["tables", "fenced_code", "nl2br"])

for fn in files:
    path = os.path.join(SRC, fn)
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # 첫 H1 라인(제목) 추출 후 본문에서 제거
    lines = text.splitlines()
    title = ""
    body_lines = []
    for i, line in enumerate(lines):
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        body_lines.append(line)
    body_md = "\n".join(body_lines).strip()

    md.reset()
    html = md.convert(body_md)

    out_name = os.path.splitext(fn)[0] + ".html"
    with open(os.path.join(OUT, out_name), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[제목] {title}")
    print(f"  -> html/{out_name}\n")

print("완료")
