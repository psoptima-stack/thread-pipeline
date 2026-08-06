# -*- coding: utf-8 -*-
"""
발행일 오후 1시에 그날 올릴 글을 이메일로 발송하는 스크립트.

동작:
  - '발행일정.csv'에서 오늘 날짜(또는 --date 지정일)에 해당하는 글을 찾음
  - '../html/<파일>' 의 HTML 본문을 읽어 이메일로 발송
  - 오늘 발행할 글이 없으면 아무것도 안 함(조용히 종료)

사용:
  python send_today_post.py                # 오늘 날짜 기준 실제 발송
  python send_today_post.py --dry-run      # 발송 안 하고 미리보기만
  python send_today_post.py --date 2026-07-31   # 특정 날짜로 테스트
"""
import argparse
import configparser
import csv
import datetime
import os
import smtplib
import ssl
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

BASE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(BASE, "발행일정.csv")
CONFIG = os.path.join(BASE, "email_config.ini")
CONFIG_EXAMPLE = os.path.join(BASE, "email_config.example.ini")
HTML_DIR = os.path.join(BASE, "..", "html")
THREADS_DIR = os.path.join(BASE, "..", "threads")


def load_threads(html_file):
    """html 파일명과 같은 이름의 threads/*.txt 가 있으면 그 내용을 반환."""
    base = os.path.splitext(html_file)[0]
    path = os.path.join(THREADS_DIR, base + ".txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return None


def load_config():
    # 로컬: email_config.ini 사용 / 클라우드: email_config.example.ini + SMTP_PASSWORD 환경변수
    path = CONFIG if os.path.exists(CONFIG) else CONFIG_EXAMPLE
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    s = dict(cfg["smtp"])
    env_pw = os.environ.get("SMTP_PASSWORD")
    if env_pw:
        s["password"] = env_pw
    if not s.get("password") or "여기에" in s.get("password", ""):
        print("[중단] 비밀번호가 없습니다. email_config.ini 에 입력하거나 SMTP_PASSWORD 환경변수를 설정하세요.")
        sys.exit(2)
    return s


def find_today_row(target_date):
    with open(SCHEDULE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["date"].strip() == target_date:
                return row
    return None


def build_email_body(title, html_body, target_date, threads_text=None):
    """메일 상단에 안내문 + 스레드용 버전 + 아래에 블로그 본문(HTML)."""
    guide = f"""
    <div style="background:#fff7e6;border:1px solid #ffd591;border-radius:8px;
                padding:14px 16px;margin-bottom:20px;font-size:14px;color:#614700;
                font-family:'Malgun Gothic',sans-serif;">
      📌 <b>오늘({target_date}) 오후 6시에 올릴 글입니다.</b><br>
      · <b>티스토리</b>: 아래 '블로그 전문'을 글쓰기 HTML 모드에 붙여넣고 예약 발행<br>
      · <b>스레드</b>: '스레드용 버전'을 [1/n]부터 순서대로 게시<br>
      제목: <b>{title}</b>
    </div>
    """

    threads_section = ""
    if threads_text:
        import html as _html
        escaped = _html.escape(threads_text)
        threads_section = f"""
    <div style="background:#f0f5ff;border:1px solid #adc6ff;border-radius:8px;
                padding:16px;margin:20px 0;">
      <div style="font-weight:bold;color:#1d39c4;margin-bottom:10px;">
        🧵 스레드용 버전 (구간별로 나눠 게시)
      </div>
      <pre style="white-space:pre-wrap;font-family:'Malgun Gothic',sans-serif;
                  font-size:14px;line-height:1.7;color:#222;margin:0;">{escaped}</pre>
    </div>
    """

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:'Malgun Gothic',sans-serif;line-height:1.8;
             max-width:680px;margin:0 auto;color:#222;">
{guide}
{threads_section}
<div style="font-weight:bold;color:#555;margin:24px 0 6px;">📝 블로그 전문 (티스토리용)</div>
<hr style="border:none;border-top:1px dashed #ccc;margin:8px 0 20px;">
{html_body}
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (미지정 시 오늘)")
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 미리보기")
    args = ap.parse_args()

    target_date = args.date or datetime.date.today().isoformat()
    row = find_today_row(target_date)

    if not row:
        print(f"[알림] {target_date} 에 발행할 글이 일정표에 없습니다. 종료합니다.")
        return

    html_path = os.path.join(HTML_DIR, row["html_file"])
    if not os.path.exists(html_path):
        print(f"[경고] 본문 파일이 없습니다: {html_path}")
        return

    with open(html_path, encoding="utf-8") as f:
        html_body = f.read()

    title = row["title"]
    tags = row.get("tags", "")
    threads_text = load_threads(row["html_file"])
    full_html = build_email_body(title, html_body, target_date, threads_text)
    subject = f"[티스토리+스레드 발행] {title}"

    if args.dry_run:
        print("===== DRY RUN (실제 발송 안 함) =====")
        print(f"날짜   : {target_date}")
        print(f"제목   : {title}")
        print(f"태그   : {tags}")
        print(f"본문   : {html_path} ({len(html_body)}자)")
        print(f"스레드 : {'있음' if threads_text else '없음'}")
        print("설정 정상 시 이 내용이 메일로 발송됩니다.")
        return

    s = load_config()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = str(Header(subject, "utf-8"))
    msg["From"] = formataddr((str(Header("웃음 연재 발행봇", "utf-8")), s["from_addr"]))
    msg["To"] = s["to_addr"]
    text_fallback = f"오늘 발행할 글: {title}\n(HTML로 보세요)\n태그: {tags}"
    msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    # 네이버 SMTP가 일시적으로 거부하는 경우가 있어 재시도. 인증 실패는 재시도 무의미.
    context = ssl.create_default_context()
    delays = [5, 15, 45]
    for attempt in range(len(delays) + 1):
        try:
            with smtplib.SMTP_SSL(s["host"], int(s["port"]), context=context) as server:
                server.login(s["user"], s["password"])
                server.sendmail(s["from_addr"], [s["to_addr"]], msg.as_string())
            break
        except smtplib.SMTPAuthenticationError as e:
            print(f"[중단] 로그인 실패 — 앱 비밀번호를 확인하세요: {e}")
            sys.exit(1)
        except (smtplib.SMTPException, OSError) as e:
            if attempt >= len(delays):
                print(f"[중단] 메일 발송 실패({len(delays) + 1}회 시도): {e}")
                sys.exit(1)
            wait = delays[attempt]
            print(f"  [재시도] 발송 실패({e}) / {wait}초 후 {attempt + 2}번째 시도")
            time.sleep(wait)

    print(f"[완료] {target_date} '{title}' 메일 발송 성공 → {s['to_addr']}")


if __name__ == "__main__":
    main()
