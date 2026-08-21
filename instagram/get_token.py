# -*- coding: utf-8 -*-
"""
인스타그램 장기 액세스 토큰을 직접 받아오는 도구.

앱 대시보드의 '토큰 생성' 버튼이 자주 실패해서(팝업·쿠키 문제),
같은 일을 브라우저 주소창과 이 스크립트로 나눠서 합니다.

── 순서 ──────────────────────────────────────────────
1) 로그인 주소 만들기
     python get_token.py url --app-id 1611898950281500

   나온 주소를 브라우저에 붙여넣고 인스타 로그인 → 허용.
   주소창이 https://localhost/?code=AQB... 로 바뀝니다.
   (페이지는 '연결할 수 없음' 으로 보여도 정상입니다. 주소창의 code 값만 씁니다.)

2) 코드를 토큰으로 바꾸기
     python get_token.py exchange --app-id 1611898950281500 \
            --app-secret <앱시크릿> --code <code값>

   60일짜리 장기 토큰이 나옵니다.

3) 만료 전 갱신 (60일마다)
     python get_token.py refresh --token <기존토큰>
──────────────────────────────────────────────────────

주의: code 는 한 번만 쓸 수 있고 몇 분 안에 만료됩니다.
      실패하면 1)부터 다시 하세요.
"""
import argparse
import sys
import urllib.parse

import requests

AUTH = "https://www.instagram.com/oauth/authorize"
TOKEN = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"

# 게시에 필요한 최소 권한
SCOPES = "instagram_business_basic,instagram_business_content_publish"

# 앱 대시보드 '비즈니스 로그인 설정' 의 리디렉션 URI 와 글자 하나까지 같아야 함
DEFAULT_REDIRECT = "https://localhost/"


def cmd_url(args):
    q = urllib.parse.urlencode({
        "client_id": args.app_id,
        "redirect_uri": args.redirect,
        "response_type": "code",
        "scope": SCOPES,
    })
    print("아래 주소를 브라우저에 붙여넣고 인스타 로그인 → 허용 하세요.\n")
    print(f"{AUTH}?{q}\n")
    print("허용 후 주소창이 이렇게 바뀝니다:")
    print(f"  {args.redirect}?code=AQB...#_")
    print("  → code= 뒤부터 #_ 앞까지를 복사해서 exchange 에 넘기세요.")
    print("\n※ 앱 대시보드 '3. Instagram 비즈니스 로그인 설정' 의")
    print(f"   리디렉션 URI 에 {args.redirect} 를 등록해 두어야 합니다.")


def _show(resp, what):
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200:
        err = data.get("error_message") or data.get("error", {}).get("message") \
            or resp.text[:300]
        print(f"[중단] {what} 실패: {err}")
        sys.exit(1)
    return data


def cmd_exchange(args):
    # 1단계: code → 단기 토큰(1시간)
    code = args.code.split("#")[0].strip()
    short = _show(requests.post(TOKEN, data={
        "client_id": args.app_id,
        "client_secret": args.app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": args.redirect,
        "code": code,
    }, timeout=30), "단기 토큰 교환")

    print(f"단기 토큰 발급 완료 (user_id={short.get('user_id')})")

    # 2단계: 단기 토큰 → 장기 토큰(60일)
    long_ = _show(requests.get(f"{GRAPH}/access_token", params={
        "grant_type": "ig_exchange_token",
        "client_secret": args.app_secret,
        "access_token": short["access_token"],
    }, timeout=30), "장기 토큰 교환")

    days = int(long_.get("expires_in", 0)) // 86400
    print()
    print("=" * 60)
    print(f"IG_USER_ID      = {short.get('user_id')}")
    print(f"IG_ACCESS_TOKEN = {long_['access_token']}")
    print(f"유효기간         = 약 {days}일")
    print("=" * 60)
    print("GitHub 저장소 Settings → Secrets and variables → Actions 에 등록하세요.")


def cmd_refresh(args):
    data = _show(requests.get(f"{GRAPH}/refresh_access_token", params={
        "grant_type": "ig_refresh_token",
        "access_token": args.token,
    }, timeout=30), "토큰 갱신")
    days = int(data.get("expires_in", 0)) // 86400

    if args.raw:
        # 워크플로에서 값만 받아 Secret 에 넣기 위한 출력
        print(data["access_token"])
        return

    print("=" * 60)
    print(f"IG_ACCESS_TOKEN = {data['access_token']}")
    print(f"유효기간         = 약 {days}일")
    print("=" * 60)
    print("Secret 값을 이 토큰으로 바꿔 주세요.")


def main():
    ap = argparse.ArgumentParser(description="인스타그램 장기 토큰 발급/갱신")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("url", help="로그인 주소 만들기")
    p.add_argument("--app-id", required=True, help="Instagram 앱 ID")
    p.add_argument("--redirect", default=DEFAULT_REDIRECT)
    p.set_defaults(func=cmd_url)

    p = sub.add_parser("exchange", help="code 를 장기 토큰으로 교환")
    p.add_argument("--app-id", required=True)
    p.add_argument("--app-secret", required=True, help="Instagram 앱 시크릿 코드")
    p.add_argument("--code", required=True, help="주소창의 code 값")
    p.add_argument("--redirect", default=DEFAULT_REDIRECT)
    p.set_defaults(func=cmd_exchange)

    p = sub.add_parser("refresh", help="60일 토큰 갱신(24시간 이상 지난 토큰만 가능)")
    p.add_argument("--token", required=True)
    p.add_argument("--raw", action="store_true",
                   help="새 토큰 값만 출력(워크플로 자동 갱신용)")
    p.set_defaults(func=cmd_refresh)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
