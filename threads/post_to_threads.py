# -*- coding: utf-8 -*-
"""
발행일에 그날 스레드용 원고를 Threads에 '연쇄 스레드'로 자동 게시.

동작:
  - '../email/발행일정.csv' 에서 오늘(또는 --date) 글을 찾음
  - 'threads/<html basename>.txt' 를 '━━━' 구분선으로 나눠 각 구간을 게시
  - 첫 구간 = 원글, 이후 구간 = 직전 게시물의 답글(reply) → 연쇄 스레드 완성
  - 오늘 발행할 글이 없으면 종료

사용:
  python post_to_threads.py                # 오늘 날짜 기준 실제 게시
  python post_to_threads.py --dry-run      # 게시 없이 구간 분할 미리보기
  python post_to_threads.py --date 2026-07-24
"""
import argparse
import configparser
import csv
import datetime
import os
import re
import sys
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(BASE, "..", "email", "발행일정.csv")
CONFIG = os.path.join(BASE, "threads_config.ini")
GRAPH = "https://graph.threads.net/v1.0"


def load_config():
    # 클라우드: 환경변수 우선 / 로컬: threads_config.ini
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("THREADS_USER_ID", "").strip()
    if not (token and user_id) and os.path.exists(CONFIG):
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG, encoding="utf-8")
        t = cfg["threads"]
        token = token or t.get("access_token", "").strip()
        user_id = user_id or t.get("user_id", "").strip()
    if not token or not user_id or "여기에" in token or "여기에" in user_id:
        print("[중단] access_token / user_id 가 없습니다. "
              "threads_config.ini 또는 환경변수(THREADS_ACCESS_TOKEN / THREADS_USER_ID)를 설정하세요.")
        sys.exit(2)
    return token, user_id


def find_today_row(target_date):
    with open(SCHEDULE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["date"].strip() == target_date:
                return row
    return None


def split_segments(text):
    """'━━━ [1/4] ━━━' 같은 구분선 기준으로 본문을 나눔.
    구분선 라벨은 제거하고 실제 게시할 텍스트만 반환."""
    parts = re.split(r"━━━.*?━━━", text)
    segs = [p.strip() for p in parts if p.strip()]
    return segs


# 일시적 장애로 판단해 재시도할 조건 (네트워크 끊김, 서버 오류, 호출량 초과,
# 그리고 실제로 겪었던 'API access blocked' — 잠시 뒤 저절로 풀리는 경우가 있음)
RETRY_DELAYS = [5, 15, 45]   # 초. 마지막 시도까지 총 4번
RETRY_MESSAGES = ("api access blocked", "please reduce the amount of data",
                  "temporarily", "try again")


def _is_retryable(resp):
    if resp.status_code >= 500 or resp.status_code == 429:
        return True
    if resp.status_code == 400:
        body = resp.text.lower()
        return any(m in body for m in RETRY_MESSAGES)
    return False


def _post(url, params, what):
    """스레드 API 호출 + 일시적 오류 재시도. 실패하면 예외를 그대로 올림."""
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(url, data=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code} {r.text[:200]}"
            if not _is_retryable(r):
                # 토큰 만료·권한 없음·본문 거부 등은 재시도해도 소용없음
                raise RuntimeError(f"{what} 실패(재시도 불가): {last}")
        except requests.exceptions.RequestException as e:
            last = f"통신 오류: {e}"

        if attempt < len(RETRY_DELAYS):
            wait = RETRY_DELAYS[attempt]
            print(f"  [재시도] {what} — {last} / {wait}초 후 {attempt + 2}번째 시도")
            time.sleep(wait)

    raise RuntimeError(f"{what} 실패({len(RETRY_DELAYS) + 1}회 시도): {last}")


def create_container(token, user_id, text, reply_to_id=None):
    params = {
        "media_type": "TEXT",
        "text": text,
        "access_token": token,
    }
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    return _post(f"{GRAPH}/{user_id}/threads", params, "컨테이너 생성")["id"]


def publish_container(token, user_id, creation_id):
    params = {"creation_id": creation_id, "access_token": token}
    return _post(f"{GRAPH}/{user_id}/threads_publish", params, "게시")["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (미지정 시 오늘)")
    ap.add_argument("--dry-run", action="store_true", help="게시 없이 미리보기")
    args = ap.parse_args()

    target_date = args.date or datetime.date.today().isoformat()
    row = find_today_row(target_date)
    if not row:
        print(f"[알림] {target_date} 에 발행할 글이 없습니다. 종료합니다.")
        return

    base = os.path.splitext(row["html_file"])[0]
    txt_path = os.path.join(BASE, base + ".txt")
    if not os.path.exists(txt_path):
        print(f"[경고] 스레드 원고가 없습니다: {txt_path}")
        return

    with open(txt_path, encoding="utf-8") as f:
        segs = split_segments(f.read())

    if not segs:
        print("[경고] 게시할 구간이 없습니다.")
        return

    # 각 구간 500자 제한 확인
    for i, s in enumerate(segs, 1):
        if len(s) > 500:
            print(f"[경고] {i}번째 구간이 500자를 초과합니다({len(s)}자). 스레드가 거부할 수 있습니다.")

    if args.dry_run:
        print(f"===== DRY RUN ({target_date}) — 총 {len(segs)}개 구간 =====\n")
        for i, s in enumerate(segs, 1):
            print(f"--- [{i}/{len(segs)}] ({len(s)}자) ---\n{s}\n")
        return

    token, user_id = load_config()
    prev_id = None
    done = 0
    for i, s in enumerate(segs, 1):
        try:
            cid = create_container(token, user_id, s, reply_to_id=prev_id)
            time.sleep(3)  # 컨테이너 처리 대기
            media_id = publish_container(token, user_id, cid)
        except RuntimeError as e:
            # 앞부분이 이미 올라갔다면 그대로 두고 중단. 통째로 재실행하면 중복 게시됨.
            print(f"[중단] {i}/{len(segs)}번째 구간에서 실패: {e}")
            if done:
                print(f"[주의] {done}개 구간은 이미 게시되었습니다. "
                      f"그대로 재실행하면 중복 게시됩니다. "
                      f"스레드에서 확인 후 {i}번째 구간부터 손으로 이어 붙이세요.")
            sys.exit(1)
        print(f"[게시 {i}/{len(segs)}] OK  media_id={media_id}")
        prev_id = media_id
        done += 1
        time.sleep(2)

    print(f"[완료] {target_date} 스레드 연쇄 게시 성공 ({len(segs)}개)")


if __name__ == "__main__":
    main()
