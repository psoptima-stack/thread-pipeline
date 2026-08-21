# -*- coding: utf-8 -*-
"""
발행일에 그날 카드 이미지를 인스타그램(프로페셔널 계정)에 캐러셀로 게시.

동작:
  - '../email/발행일정.csv' 에서 오늘(또는 --date) 글을 찾음
  - 'cards/<날짜>/01.jpg, 02.jpg ...' 를 캐러셀 이미지로 사용
    (없으면 make_cards.py 를 먼저 돌리라고 알려주고 종료)
  - '../threads/<html basename>.txt' 로 캡션을 만들어 함께 올림
  - 오늘 발행할 글이 없으면 조용히 종료

이미지 주소:
  인스타 API는 '공개된 https 이미지 주소'만 받습니다. 파일 업로드가 안 됩니다.
  그래서 카드 이미지를 GitHub 저장소에 커밋해 두고 raw 주소로 넘깁니다.
    https://raw.githubusercontent.com/<소유자>/<저장소>/<ref>/instagram/cards/<날짜>/01.jpg
  다른 곳에 올린다면 IG_IMAGE_BASE_URL 로 기준 주소를 바꿀 수 있습니다.

재시작:
  - 게시에 성공하면 progress/<날짜>.json 에 기록
  - 이미 올린 날짜를 다시 실행하면 아무것도 하지 않음(중복 게시 방지)

사용:
  python post_to_instagram.py                # 오늘 날짜 기준 실제 게시
  python post_to_instagram.py --dry-run      # 게시 없이 캡션·이미지 주소만 확인
  python post_to_instagram.py --date 2026-08-18
  python post_to_instagram.py --restart      # 기록 무시하고 다시 게시(중복 주의)
  python post_to_instagram.py --api instagram   # 페이지 없이 인스타 로그인 토큰으로
"""
import argparse
import configparser
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(BASE, "..", "email", "발행일정.csv")
THREADS_DIR = os.path.join(BASE, "..", "threads")
CARDS_DIR = os.path.join(BASE, "cards")
CONFIG = os.path.join(BASE, "instagram_config.ini")
PROGRESS_DIR = os.path.join(BASE, "progress")
# 게시 경로는 두 가지. 둘 다 캐러셀 게시 방식은 같고 주소와 토큰만 다름.
#   facebook  : 페이스북 페이지에 연결된 인스타 계정 (IG_USER_ID + 페이지 토큰)
#   instagram : 페이지 없이 인스타 로그인만으로 (Instagram API with Instagram Login)
GRAPH_FB = "https://graph.facebook.com/v21.0"
GRAPH_IG = "https://graph.instagram.com/v21.0"
GRAPH = GRAPH_FB        # main() 에서 --api 값에 따라 바뀜

MAX_CARDS = 10          # 캐러셀 한 게시물 최대 장수
CAPTION_LIMIT = 2200    # 인스타 캡션 글자 제한
BLOG = "makesmile.tistory.com"

RETRY_DELAYS = [5, 15, 45]   # 초. 마지막 시도까지 총 4번
RETRY_MESSAGES = ("api access blocked", "please reduce the amount of data",
                  "temporarily", "try again", "rate limit",
                  "media upload has failed")   # 이미지 내려받기 일시 실패 포함


def load_config(api):
    # 클라우드: 환경변수 우선 / 로컬: instagram_config.ini
    ig_user_id = os.environ.get("IG_USER_ID", "").strip()
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not (ig_user_id and token) and os.path.exists(CONFIG):
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG, encoding="utf-8")
        s = cfg["instagram"]
        ig_user_id = ig_user_id or s.get("ig_user_id", "").strip()
        token = token or s.get("access_token", "").strip()
    if "여기에" in ig_user_id:
        ig_user_id = ""
    if "여기에" in token:
        token = ""

    # 인스타 로그인 방식은 토큰 자체가 계정을 가리키므로 ID가 없어도 됨
    if api == "instagram" and not ig_user_id:
        ig_user_id = "me"

    if not ig_user_id or not token:
        print("[중단] ig_user_id / access_token 이 없습니다. "
              "instagram_config.ini 또는 환경변수(IG_USER_ID / IG_ACCESS_TOKEN)를 설정하세요.")
        sys.exit(2)
    return ig_user_id, token


def find_today_row(target_date):
    with open(SCHEDULE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["date"].strip() == target_date:
                return row
    return None


def build_caption(text, row):
    """스레드 원고의 '━━━ [1/4] ━━━' 구분선을 지우고 하나의 캡션으로 합침.
    인스타는 캡션 링크가 눌리지 않으므로 블로그 안내를 프로필 링크로 바꿈."""
    parts = re.split(r"━━━.*?━━━", text)
    body = "\n\n".join(p.strip() for p in parts if p.strip())
    body = body.replace("🔗 전문은 블로그에서", "🔗 전문은 프로필 링크에서")
    body = body.replace(BLOG, "")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()   # 링크 줄을 지우며 생긴 빈 줄 정리

    # 원고에 해시태그 줄이 없으면 발행일정 csv 의 tags 로 채움
    if "#" not in body:
        tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
        if tags:
            body += "\n\n" + " ".join("#" + t.replace(" ", "") for t in tags[:30])

    if len(body) > CAPTION_LIMIT:
        body = body[:CAPTION_LIMIT - 1].rstrip() + "…"
    return body


def find_cards(target_date):
    """cards/<날짜>/ 의 이미지 파일명을 번호 순으로."""
    d = os.path.join(CARDS_DIR, target_date)
    if not os.path.isdir(d):
        return []
    names = [n for n in os.listdir(d) if n.lower().endswith((".jpg", ".jpeg"))]
    return sorted(names)


def default_repo():
    """GitHub Actions 에서는 환경변수, 로컬에서는 git remote 에서 소유자/저장소를 얻음."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo:
        return repo
    try:
        url = subprocess.check_output(
            ["git", "-C", BASE, "config", "--get", "remote.origin.url"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def build_image_urls(target_date, names, ref):
    base = os.environ.get("IG_IMAGE_BASE_URL", "").strip().rstrip("/")
    if base:
        return [f"{base}/{target_date}/{n}" for n in names]
    repo = default_repo()
    if not repo:
        print("[중단] 이미지 주소를 만들 수 없습니다. "
              "IG_IMAGE_BASE_URL 을 설정하거나 GitHub 저장소에서 실행하세요.")
        sys.exit(2)
    return [f"https://raw.githubusercontent.com/{repo}/{ref}/"
            f"instagram/cards/{target_date}/{n}" for n in names]


def _progress_path(target_date):
    return os.path.join(PROGRESS_DIR, f"{target_date}.json")


def already_posted(target_date):
    path = _progress_path(target_date)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("media_id")
    except (ValueError, OSError):
        return None


def save_progress(target_date, media_id, count):
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    with open(_progress_path(target_date), "w", encoding="utf-8") as f:
        json.dump({"date": target_date, "media_id": media_id, "cards": count},
                  f, ensure_ascii=False, indent=2)


def _is_retryable(resp):
    if resp.status_code >= 500 or resp.status_code == 429:
        return True
    if resp.status_code == 400:
        body = resp.text.lower()
        return any(m in body for m in RETRY_MESSAGES)
    return False


def api_post(path, token, params, what):
    """일시적 오류는 재시도. 토큰 만료·권한 없음은 즉시 중단."""
    url = f"{GRAPH}/{path}"
    data = dict(params, access_token=token)
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(url, data=data, timeout=60)
            if r.status_code == 200:
                return r.json()["id"]
            last = f"HTTP {r.status_code} {r.text[:300]}"
            if not _is_retryable(r):
                raise RuntimeError(f"{what} 실패(재시도 불가): {last}")
        except requests.exceptions.RequestException as e:
            last = f"통신 오류: {e}"

        if attempt < len(RETRY_DELAYS):
            wait = RETRY_DELAYS[attempt]
            print(f"  [재시도] {what}: {last} / {wait}초 후 {attempt + 2}번째 시도")
            time.sleep(wait)

    raise RuntimeError(f"{what} 실패({len(RETRY_DELAYS) + 1}회 시도): {last}")


def wait_ready(container_id, token, tries=20, wait=5):
    """인스타 서버가 이미지를 다 받아오면 FINISHED. 그 전에 발행하면 실패함."""
    for _ in range(tries):
        try:
            r = requests.get(f"{GRAPH}/{container_id}",
                             params={"fields": "status_code,status",
                                     "access_token": token}, timeout=30)
            info = r.json() if r.status_code == 200 else {}
        except requests.exceptions.RequestException:
            info = {}
        status = info.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"이미지 처리 실패: {info.get('status', '')[:300]}")
        time.sleep(wait)
    raise RuntimeError(f"이미지 처리 대기 시간 초과(container={container_id})")


def publish_carousel(ig_user_id, token, image_urls, caption):
    children = []
    for i, url in enumerate(image_urls, start=1):
        cid = api_post(f"{ig_user_id}/media", token,
                       {"image_url": url, "is_carousel_item": "true"},
                       f"{i}번 카드 업로드")
        wait_ready(cid, token)
        children.append(cid)
        print(f"  [{i}/{len(image_urls)}] 카드 준비 완료")

    parent = api_post(f"{ig_user_id}/media", token,
                      {"media_type": "CAROUSEL",
                       "children": ",".join(children),
                       "caption": caption},
                      "캐러셀 묶기")
    wait_ready(parent, token)
    return api_post(f"{ig_user_id}/media_publish", token,
                    {"creation_id": parent}, "게시")


def publish_single(ig_user_id, token, image_url, caption):
    cid = api_post(f"{ig_user_id}/media", token,
                   {"image_url": image_url, "caption": caption}, "이미지 업로드")
    wait_ready(cid, token)
    return api_post(f"{ig_user_id}/media_publish", token,
                    {"creation_id": cid}, "게시")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (미지정 시 오늘)")
    ap.add_argument("--dry-run", action="store_true",
                    help="게시 없이 캡션·이미지 주소만 확인")
    ap.add_argument("--restart", action="store_true",
                    help="이미 게시한 날짜라도 다시 게시(중복 주의)")
    ap.add_argument("--ref", default=os.environ.get("IG_IMAGE_REF", "main"),
                    help="이미지 주소에 쓸 브랜치나 커밋 (기본 main)")
    ap.add_argument("--api", choices=["facebook", "instagram"],
                    default=os.environ.get("IG_API", "facebook"),
                    help="facebook=페이지 연결 방식(기본), "
                         "instagram=페이지 없이 인스타 로그인 방식")
    args = ap.parse_args()

    global GRAPH
    GRAPH = GRAPH_IG if args.api == "instagram" else GRAPH_FB

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

    names = find_cards(target_date)
    if not names:
        print(f"[경고] 카드 이미지가 없습니다: {os.path.join(CARDS_DIR, target_date)}\n"
              f"        먼저 python make_cards.py --date {target_date} 를 실행하세요.")
        return
    if len(names) > MAX_CARDS:
        print(f"[주의] 카드가 {len(names)}장이라 앞 {MAX_CARDS}장만 올립니다.")
        names = names[:MAX_CARDS]

    with open(txt_path, encoding="utf-8") as f:
        caption = build_caption(f.read(), row)
    if not caption:
        print("[경고] 캡션으로 쓸 내용이 없습니다.")
        return

    image_urls = build_image_urls(target_date, names, args.ref)

    if args.dry_run:
        print(f"===== DRY RUN ({target_date}) — 카드 {len(names)}장, "
              f"캡션 {len(caption)}자 =====")
        for u in image_urls:
            print(" ", u)
        print()
        print(caption)
        return

    if not args.restart:
        done = already_posted(target_date)
        if done:
            print(f"[알림] {target_date} 는 이미 게시했습니다(media_id={done}). "
                  f"중복 게시를 막기 위해 종료합니다. (다시 올리려면 --restart)")
            return

    ig_user_id, token = load_config(args.api)
    try:
        if len(image_urls) == 1:
            media_id = publish_single(ig_user_id, token, image_urls[0], caption)
        else:
            media_id = publish_carousel(ig_user_id, token, image_urls, caption)
    except RuntimeError as e:
        print(f"[중단] {e}")
        sys.exit(1)

    save_progress(target_date, media_id, len(image_urls))
    print(f"[완료] {target_date} 인스타그램 게시 성공  media_id={media_id}")


if __name__ == "__main__":
    main()
