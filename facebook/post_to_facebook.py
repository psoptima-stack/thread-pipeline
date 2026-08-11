# -*- coding: utf-8 -*-
"""
발행일에 그날 원고를 페이스북 페이지에 게시.

동작:
  - '../email/발행일정.csv' 에서 오늘(또는 --date) 글을 찾음
  - '../threads/<html basename>.txt' 를 읽어 '━━━' 구분선을 지우고
    하나의 긴 게시물로 합쳐서 페이지에 게시 (페이스북은 글자 제한이 넉넉함)
  - 오늘 발행할 글이 없으면 조용히 종료

재시작:
  - 게시에 성공하면 progress/<날짜>.json 에 기록
  - 이미 올린 날짜를 다시 실행하면 아무것도 하지 않음(중복 게시 방지)

사용:
  python post_to_facebook.py                # 오늘 날짜 기준 실제 게시
  python post_to_facebook.py --dry-run      # 게시 없이 미리보기
  python post_to_facebook.py --date 2026-08-18
  python post_to_facebook.py --restart      # 기록 무시하고 다시 게시(중복 주의)
"""
import argparse
import configparser
import csv
import datetime
import json
import os
import re
import sys
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(BASE, "..", "email", "발행일정.csv")
THREADS_DIR = os.path.join(BASE, "..", "threads")
CONFIG = os.path.join(BASE, "facebook_config.ini")
PROGRESS_DIR = os.path.join(BASE, "progress")
GRAPH = "https://graph.facebook.com/v21.0"

RETRY_DELAYS = [5, 15, 45]   # 초. 마지막 시도까지 총 4번
RETRY_MESSAGES = ("api access blocked", "please reduce the amount of data",
                  "temporarily", "try again", "rate limit")


def load_config():
    # 클라우드: 환경변수 우선 / 로컬: facebook_config.ini
    page_id = os.environ.get("FB_PAGE_ID", "").strip()
    token = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not (page_id and token) and os.path.exists(CONFIG):
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG, encoding="utf-8")
        f = cfg["facebook"]
        page_id = page_id or f.get("page_id", "").strip()
        token = token or f.get("access_token", "").strip()
    if not page_id or not token or "여기에" in page_id or "여기에" in token:
        print("[중단] page_id / access_token 이 없습니다. "
              "facebook_config.ini 또는 환경변수(FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN)를 설정하세요.")
        sys.exit(2)
    return page_id, token


def find_today_row(target_date):
    with open(SCHEDULE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["date"].strip() == target_date:
                return row
    return None


def build_message(text):
    """스레드용 원고의 '━━━ [1/4] ━━━' 구분선을 지우고 하나의 글로 합침."""
    parts = re.split(r"━━━.*?━━━", text)
    segs = [p.strip() for p in parts if p.strip()]
    return "\n\n".join(segs)


def _progress_path(target_date):
    return os.path.join(PROGRESS_DIR, f"{target_date}.json")


def already_posted(target_date):
    path = _progress_path(target_date)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("post_id")
    except (ValueError, OSError):
        return None


def save_progress(target_date, post_id):
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    with open(_progress_path(target_date), "w", encoding="utf-8") as f:
        json.dump({"date": target_date, "post_id": post_id},
                  f, ensure_ascii=False, indent=2)


def _is_retryable(resp):
    if resp.status_code >= 500 or resp.status_code == 429:
        return True
    if resp.status_code == 400:
        body = resp.text.lower()
        return any(m in body for m in RETRY_MESSAGES)
    return False


def post_to_page(page_id, token, message):
    """일시적 오류는 재시도. 토큰 만료·권한 없음은 즉시 중단."""
    url = f"{GRAPH}/{page_id}/feed"
    params = {"message": message, "access_token": token}
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(url, data=params, timeout=30)
            if r.status_code == 200:
                return r.json()["id"]
            last = f"HTTP {r.status_code} {r.text[:200]}"
            if not _is_retryable(r):
                raise RuntimeError(f"게시 실패(재시도 불가): {last}")
        except requests.exceptions.RequestException as e:
            last = f"통신 오류: {e}"

        if attempt < len(RETRY_DELAYS):
            wait = RETRY_DELAYS[attempt]
            print(f"  [재시도] {last} / {wait}초 후 {attempt + 2}번째 시도")
            time.sleep(wait)

    raise RuntimeError(f"게시 실패({len(RETRY_DELAYS) + 1}회 시도): {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (미지정 시 오늘)")
    ap.add_argument("--dry-run", action="store_true", help="게시 없이 미리보기")
    ap.add_argument("--restart", action="store_true",
                    help="이미 게시한 날짜라도 다시 게시(중복 주의)")
    args = ap.parse_args()

    target_date = args.date or datetime.date.today().isoformat()
    row = find_today_row(target_date)
    if not row:
        print(f"[알림] {target_date} 에 발행할 글이 없습니다. 종료합니다.")
        return

    base = os.path.splitext(row["html_file"])[0]
    txt_path = os.path.join(THREADS_DIR, base + ".txt")
    if not os.path.exists(txt_path):
        print(f"[경고] 원고가 없습니다: {txt_path}")
        return

    with open(txt_path, encoding="utf-8") as f:
        message = build_message(f.read())

    if not message:
        print("[경고] 게시할 내용이 없습니다.")
        return

    if args.dry_run:
        print(f"===== DRY RUN ({target_date}) — {len(message)}자 =====\n")
        print(message)
        return

    if not args.restart:
        done = already_posted(target_date)
        if done:
            print(f"[알림] {target_date} 는 이미 게시했습니다(post_id={done}). "
                  f"중복 게시를 막기 위해 종료합니다. (다시 올리려면 --restart)")
            return

    page_id, token = load_config()
    try:
        post_id = post_to_page(page_id, token, message)
    except RuntimeError as e:
        print(f"[중단] {e}")
        sys.exit(1)

    save_progress(target_date, post_id)
    print(f"[완료] {target_date} 페이스북 게시 성공  post_id={post_id}")


if __name__ == "__main__":
    main()
