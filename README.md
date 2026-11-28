# BorussiaReporter
Translate articles from borussia.de and post it on Naver Cafe Borussia Park Korea

## 환경 변수 / Secrets
- 기존: `GOOGLE_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `NAVER_REFRESH_TOKEN`, `NAVER_CLUB_ID`, `NAVER_MENU_ID`(본 카페)
- 외부 기사(Tavily): `TAVILY_API_KEY`
- 모의 카페: `NAVER_CLUB_ID_TEST`, `NAVER_MENU_ID_TEST`
- 스위치: `TARGET=test|prod`(기본 test), `DRY_RUN=1`(번역만, 업로드 없음), `EXTERNAL_ENABLED=0`(외부 기사 끄기), `EXTERNAL_MAX_POSTS`(1회 최대 건수, 기본 5)

외부 기사는 RP Online / Sky Sports / Bild / Kicker 대상이며 유료(paywall) 기사는 건너뜁니다.
처리한 URL 메타데이터만 `data/external_history.json`에 저장합니다(원문 미저장).
