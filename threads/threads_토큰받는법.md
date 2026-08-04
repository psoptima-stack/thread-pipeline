# 🔑 스레드 자동 게시용 토큰 발급 방법 (최초 1회, 약 10~15분)

스레드 자동 업로드를 켜려면 **접근 토큰(access token)**과 **계정 ID** 두 개가 필요합니다.
아래를 따라 발급받아 `threads_config.ini`에 넣으면, 이후엔 완전 자동입니다.

> ⚠️ 전제: 인스타그램/스레드 계정이 **프로페셔널(비즈니스 또는 크리에이터)** 계정이어야 API를 쓸 수 있어요.
> (스레드 앱 → 설정 → 계정 → 프로페셔널 계정으로 전환)

---

## 1단계 — 메타 개발자 앱 만들기
1. https://developers.facebook.com 접속 → 우측 상단 **로그인**(페이스북 계정)
2. 상단 **내 앱(My Apps)** → **앱 만들기(Create App)**
3. 사용 사례(use case)에서 **"Threads API 액세스"** 관련 항목 선택 → 계속
4. 앱 이름(예: makesmile-auto) 입력하고 생성

## 2단계 — Threads 사용 사례 추가 & 권한
1. 앱 대시보드 → 좌측 **사용 사례(Use cases)** 또는 **제품 추가**에서 **Threads** 선택
2. **권한(Permissions)**에서 아래 두 개를 추가:
   - `threads_basic`
   - `threads_content_publish`

## 3단계 — 액세스 토큰 생성
1. Threads 설정 화면의 **"액세스 토큰 생성(Generate access token)"** 클릭
2. 본인 스레드 계정으로 로그인/승인
3. 생성된 토큰 복사 → 이게 **단기 토큰**(1~2시간짜리)입니다.

## 4단계 — 장기 토큰으로 교환 (60일 유효)
아래 주소의 `단기토큰`과 `앱시크릿` 자리를 채워 브라우저 주소창에 붙여넣기:
```
https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=앱시크릿&access_token=단기토큰
```
- **앱시크릿**: 앱 대시보드 → 설정 → 기본 설정 → 앱 시크릿 코드
- 결과로 나오는 `access_token` 값이 **장기 토큰**입니다. 이걸 사용하세요.

## 5단계 — 내 계정 ID 확인
아래 주소의 `장기토큰` 자리를 채워 브라우저에 붙여넣기:
```
https://graph.threads.net/v1.0/me?fields=id,username&access_token=장기토큰
```
- 결과의 `"id"` 값이 **user_id** 입니다.

---

## 6단계 — 설정 파일에 입력
`threads/threads_config.ini` 를 메모장으로 열어:
```
access_token = (4단계의 장기 토큰)
user_id = (5단계의 id)
```
저장.

## 7단계 — 테스트
PowerShell에서:
```powershell
cd "C:\Users\유나\OneDrive\바탕 화면\writer"
.\.venv\Scripts\python.exe threads\post_to_threads.py --date 2026-07-24
```
스레드 앱에 글이 연쇄로 올라오면 성공! 이후 화·금 18시 자동 게시됩니다.

---

## 🔄 60일마다 토큰 갱신
장기 토큰은 60일 유효하며, 만료 전 아래로 갱신됩니다 (자동 갱신 스크립트도 원하면 만들어드려요):
```
https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=현재토큰
```

## ❓ 어려우면
1~5단계가 번거로우면, 알려주세요. 각 화면을 캡처해서 보내주시면 어디를 누를지 하나씩 짚어드리겠습니다.
