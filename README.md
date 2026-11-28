# BorussiaReporter
Translate articles from borussia.de and post it on Naver Cafe Borussia Park Korea

## 환경 변수 / Secrets
- 기존: `GOOGLE_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `NAVER_REFRESH_TOKEN`, `NAVER_CLUB_ID`, `NAVER_MENU_ID`(본 카페)
- 외부 기사(Tavily): `TAVILY_API_KEY`
- 모의 카페: `NAVER_CLUB_ID_TEST`, `NAVER_MENU_ID_TEST`
- 스위치: `TARGET=test|prod`(기본 test), `DRY_RUN=1`(번역만, 업로드 없음), `EXTERNAL_ENABLED=0`(외부 기사 끄기), `EXTERNAL_MAX_POSTS`(1회 최대 건수, 기본 5)

- 언론사별 게시판: `NAVER_MENU_ID_{RP|SKY|BILD|KICKER}_TEST`(모의 카페), `NAVER_MENU_ID_{RP|SKY|BILD|KICKER}`(본 카페). 미설정이면 기본 게시판(`NAVER_MENU_ID[_TEST]`)에 올라갑니다.

외부 기사는 RP Online / Sky Sport(sport.sky.de) / Bild / Kicker 대상이며 유료(paywall) 기사는 건너뜁니다.
처리한 URL 메타데이터만 `data/external_history.json`에 저장합니다(원문 미저장).

외부 기사에는 기사 페이지의 대표 사진(og:image) 1장이 첨부됩니다(실패하면 사진 없이 게시). `RESET_SKIPPED=1`이면 이전에 유료/무관으로 스킵된 URL을 다시 평가합니다.

외부 기사는 기본적으로 한국어 불릿 요약 + 원문 링크로 올라가며, 제목은 `[매체명] 제목` 형태이며 `<카테고리>` 태그는 붙이지 않습니다. 인터뷰·기자회견(제목/URL에 Interview, Stimmen, Pressekonferenz 등)은 전문 번역합니다. `EXTERNAL_MODE=full`(레포 Variables)이면 전부 전문 번역합니다.

외부 기사는 게시 시각 기준 24시간 이내(`EXTERNAL_MAX_AGE_HOURS`)만 올립니다. 게시 시각은 Tavily 날짜에 시각이 없으면 기사 페이지 메타(article:published_time, JSON-LD 등)로 보강하며, 끝내 알 수 없으면 스킵합니다.

RP Online(`rp_scraper.py`)과 Bild(`bild_scraper.py`)는 Tavily 대신 직접 스크랩합니다(목록 → 기사 페이지의 게시 시각/`isAccessibleForFree`/본문). 목록을 못 읽으면 해당 매체는 자동으로 Tavily로 대체됩니다. Kicker(봇 차단)와 Sky(403)는 Tavily를 씁니다. 라이브티커 기사는 제외합니다.
