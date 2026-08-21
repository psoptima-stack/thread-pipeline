# -*- coding: utf-8 -*-
"""
인스타그램 자동 게시 준비 상태 점검.

토큰 하나만 주면 아래를 한 번에 확인해 줍니다.
  - 토큰에 붙어 있는 권한 (instagram_basic / instagram_content_publish 등)
  - 내가 관리하는 페이지 목록과 각 페이지의 '페이지 액세스 토큰'
  - 페이지에 연결된 인스타그램 비즈니스 계정 ID (= IG_USER_ID)

사용:
  python check_setup.py --token EAAG...        # 사용자 토큰이든 페이지 토큰이든 가능
  python check_setup.py                        # instagram_config.ini / 환경변수에서 읽음
"""
import argparse
import configparser
import os
import sys

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "instagram_config.ini")
GRAPH = "https://graph.facebook.com/v21.0"

NEEDED = ["pages_show_list", "pages_read_engagement",
          "instagram_basic", "instagram_content_publish"]


def get_token(arg_token):
    if arg_token:
        return arg_token.strip()
    for key in ("IG_ACCESS_TOKEN", "FB_PAGE_ACCESS_TOKEN"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    if os.path.exists(CONFIG):
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG, encoding="utf-8")
        v = cfg["instagram"].get("access_token", "").strip()
        if v and "여기에" not in v:
            return v
    print("[중단] 토큰이 없습니다. --token EAAG... 로 넣어 주세요.")
    sys.exit(2)


def call(path, token, **params):
    r = requests.get(f"{GRAPH}/{path}",
                     params=dict(params, access_token=token), timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200:
        msg = data.get("error", {}).get("message", r.text[:200])
        return None, msg
    return data, None


def check_permissions(token):
    data, err = call("me/permissions", token)
    if err:
        if "expire" in err.lower() or "session" in err.lower():
            print(f"  · 토큰이 만료됐습니다: {err}")
        else:
            print(f"  · 권한 확인 건너뜀 (페이지 토큰이면 정상): {err}")
        return
    granted = {d["permission"] for d in data.get("data", [])
               if d.get("status") == "granted"}
    for p in NEEDED:
        mark = "O" if p in granted else "X"
        print(f"  [{mark}] {p}")
    missing = [p for p in NEEDED if p not in granted]
    if missing:
        print(f"  → 빠진 권한이 있습니다: {', '.join(missing)}")
        print("     Graph API Explorer 에서 이 권한들을 체크하고 토큰을 다시 받으세요.")


def check_instagram_login(token):
    """페이지를 거치지 않는 '인스타 로그인' 토큰 점검."""
    r = requests.get("https://graph.instagram.com/v21.0/me",
                     params={"fields": "user_id,username,account_type",
                             "access_token": token}, timeout=30)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200:
        print(f"[중단] 토큰이 인스타 로그인 방식이 아니거나 만료됐습니다: "
              f"{data.get('error', {}).get('message', r.text[:200])}")
        sys.exit(1)
    print(f"  계정        : @{data.get('username', '?')} "
          f"({data.get('account_type', '?')})")
    print(f"  IG_USER_ID  = {data.get('user_id') or data.get('id')}")
    print()
    print("이 토큰을 IG_ACCESS_TOKEN 으로 등록하고,")
    print("게시할 때 --api instagram (또는 IG_API=instagram) 을 쓰면 됩니다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", help="사용자 토큰 또는 페이지 토큰")
    ap.add_argument("--api", choices=["facebook", "instagram"], default="facebook",
                    help="instagram=페이지 없이 인스타 로그인 토큰을 점검")
    args = ap.parse_args()
    token = get_token(args.token)

    if args.api == "instagram":
        print("=" * 60)
        print("인스타 로그인 방식 점검")
        print("=" * 60)
        check_instagram_login(token)
        return

    print("=" * 60)
    print("1) 토큰 권한")
    print("=" * 60)
    check_permissions(token)

    print()
    print("=" * 60)
    print("2) 페이지와 인스타그램 연결")
    print("=" * 60)
    # connected_instagram_account 는 '계정 센터로만 묶인' 상태에서도 잡히므로
    # 부분 연결인지 완전 연결인지 구분하는 데 씀.
    data, err = call("me/accounts", token,
                     fields="id,name,access_token,"
                            "instagram_business_account{id,username},"
                            "connected_instagram_account{id,username}")
    if err:
        print(f"[중단] 페이지 목록을 못 가져왔습니다: {err}")
        if "expire" in err.lower() or "session" in err.lower():
            print("       토큰이 만료됐습니다. Graph API Explorer 에서 다시 받으세요.")
            print("       https://developers.facebook.com/tools/explorer")
            print("       (Explorer 토큰은 1~2시간짜리입니다. 오래 쓸 토큰은")
            print("        인스타_토큰받는법.md 2-1·2-2 단계로 페이지 토큰을 만드세요.)")
        else:
            print("       pages_show_list 권한이 없습니다. 권한을 체크하고 다시 받으세요.")
        sys.exit(1)

    pages = data.get("data", [])
    if not pages:
        print("[중단] 관리하는 페이지가 없습니다. 토큰을 다시 발급받아 보세요.")
        sys.exit(1)

    found = False
    for p in pages:
        ig = p.get("instagram_business_account")
        print(f"\n■ 페이지: {p['name']}  (page_id={p['id']})")
        if ig:
            found = True
            print(f"   연결된 인스타: @{ig.get('username', '?')}")
            print(f"   IG_USER_ID     = {ig['id']}")
            print(f"   IG_ACCESS_TOKEN = {p['access_token']}")
        else:
            print("   ✗ 연결된 인스타그램 비즈니스 계정 없음")
            partial = p.get("connected_instagram_account")
            if partial:
                print(f"   (참고) 계정 센터로만 묶인 인스타가 있습니다: "
                      f"@{partial.get('username', '?')}")
                print("          이 상태로는 게시 API를 쓸 수 없습니다. "
                      "페이지 설정에서 '연결된 계정'으로 다시 연결하세요.")

    print()
    print("=" * 60)
    if found:
        print("준비 완료. 위의 IG_USER_ID 와 IG_ACCESS_TOKEN 을")
        print("GitHub 저장소 Settings → Secrets and variables → Actions 에 등록하세요.")
    else:
        print("아직 페이지에 인스타그램이 연결되지 않았습니다.")
        print("business.facebook.com → 설정 → 계정 → Instagram 계정 → 연결")
    print("=" * 60)


if __name__ == "__main__":
    main()
