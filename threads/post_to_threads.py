# -*- coding: utf-8 -*-
"""
발행일에 그날 스레드용 원고를 Threads에 '연쇄 스레드'로 자동 게시.

동작:
  - '../email/발행일정.csv' 에서 오늘(또는 --date) 글을 찾음
  - 'threads/<html basename>.txt' 를 '━━━' 구분선으로 나눠 각 구간을 게시
  - 첫 구간 = 원글, 이후 구간 = 직전 게시물의 답글(reply) → 연쇄 스레드 완성
  - 오늘 발행할 글이 없으면 종료

재시작:
  - 게시에 성공할 때마다 진행 상태를 progress/<날짜>.json 에 기록
  - 중간에 실패한 뒤 다시 실행하면 '이미 올라간 구간은 건너뛰고' 이어서 게시
  - 이미 전부 끝난 날짜를 다시 실행하면 아무것도 하지 않음(중복 게시 방지)

사용:
  python post_to_threads.py                # 오늘 날짜 기준 실제 게시
  python post_to_threads.py --dry-run      # 게시 없이 구간 분할 미리보기
  python post_to_threads.py --date 2026-07-24
  python post_to_threads.py --restart      # 진행 기록 무시하고 처음부터 다시
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
CONFIG = os.path.join(BASE, "threads_config.ini")
PROGRESS_DIR = os.path.join(BASE, "progress")
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


def _progress_path(target_date):
    return os.path.join(PROGRESS_DIR, f"{target_date}.json")


def load_progress(target_date, total):
    """이전 실행이 남긴 진행 기록을 읽어 (게시완료 개수, 마지막 media_id) 반환."""
    path = _progress_path(target_date)
    if not os.path.exists(path):
        return 0, None
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except (ValueError, OSError) as e:
        print(f"[알림] 진행 기록을 읽지 못해 처음부터 게시합니다: {e}")
        return 0, None
    # 원고를 고쳐 구간 수가 달라졌다면 이어 붙이는 게 위험하므로 무시
    if st.get("total") != total:
        print("[알림] 원고의 구간 수가 달라졌습니다. 진행 기록을 무시하고 처음부터 게시합니다.")
        return 0, None
    return int(st.get("posted", 0)), st.get("last_media_id")


def save_progress(target_date, total, posted, last_media_id):
    """구간 하나가 올라갈 때마다 즉시 기록. 도중에 죽어도 여기까지는 남음."""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    with open(_progress_path(target_date), "w", encoding="utf-8") as f:
        json.dump({"date": target_date, "total": total, "posted": posted,
                   "last_media_id": last_media_id}, f, ensure_ascii=False, indent=2)


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
    ap.add_argument("--restart", action="store_true",
                    help="진행 기록을 무시하고 처음부터 다시 게시(중복 주의)")
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
    total = len(segs)

    # 이전 실행이 어디까지 올렸는지 확인 (--restart 면 무시)
    posted, prev_id = (0, None) if args.restart else load_progress(target_date, total)
    if posted >= total:
        print(f"[알림] {target_date} 는 이미 {total}개 구간을 모두 게시했습니다. "
              f"중복 게시를 막기 위해 종료합니다. (다시 올리려면 --restart)")
        return
    if posted:
        print(f"[재시작] {posted}/{total}개가 이미 게시되어 있어 "
              f"{posted + 1}번째 구간부터 이어서 올립니다.")

    for i in range(posted, total):
        try:
            cid = create_container(token, user_id, segs[i], reply_to_id=prev_id)
            time.sleep(3)  # 컨테이너 처리 대기
            media_id = publish_container(token, user_id, cid)
        except RuntimeError as e:
            print(f"[중단] {i + 1}/{total}번째 구간에서 실패: {e}")
            print(f"[안내] {i}개까지는 게시가 끝났습니다. 진행 기록을 남겨두었으니 "
                  f"다시 실행하면 {i + 1}번째 구간부터 이어서 올립니다.")
            sys.exit(1)
        prev_id = media_id
        save_progress(target_date, total, i + 1, media_id)   # 한 구간마다 즉시 기록
        print(f"[게시 {i + 1}/{total}] OK  media_id={media_id}")
        time.sleep(2)

    print(f"[완료] {target_date} 스레드 연쇄 게시 성공 ({total}개)")


if __name__ == "__main__":
    main()
