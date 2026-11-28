"""Tavily 검색으로 외부 매체(RP, Sky Sports, Bild, Kicker)의 BMG 기사를 수집한다.

비용 절감 원칙: LLM 번역 호출 전에 (1) 이미 처리한 URL, (2) 무관한 기사,
(3) 유료(paywall) 기사를 모두 걸러낸다. 원문 본문은 저장하지 않고 메타데이터만 기록한다.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config
import bild_scraper
import rp_scraper

# 도메인 -> (표시명, 언어, 게시판 키). 게시판 키는 config.menu_id_for()의 환경변수 접미사로 쓰인다.
OUTLETS = {
    "rp-online.de": ("RP Online", "de", "RP"),
    "sport.sky.de": ("Sky Sport", "de", "SKY"),
    "bild.de": ("Bild", "de", "BILD"),
    "kicker.de": ("Kicker", "de", "KICKER"),
}
# 직접 스크랩 가능한 매체(도메인 -> 모듈). Kicker는 봇 차단(DataDome), Sky는 403이라 Tavily 사용
DIRECT_SCRAPERS = {"rp-online.de": rp_scraper, "bild.de": bild_scraper}
QUERY = "Borussia Mönchengladbach Gladbach"  # 도메인별로 1회씩 검색(편중 방지)
DAYS = max(1, -(-config.EXTERNAL_MAX_AGE_HOURS // 24))  # Tavily 검색 범위(일). 24시간이면 1일 — 날짜 없는 결과도 이 범위 안으로 본다
BERLIN = ZoneInfo("Europe/Berlin")
RESULTS_PER_DOMAIN = 5
PAYWALL_HEAD_CHARS = 600  # 내비/푸터의 상시 노출 문구 오판 방지: 제목+본문 앞부분만 검사
MIN_IMAGE_BYTES = 10 * 1024  # 이보다 작으면 로고/플레이스홀더로 보고 첨부 안 함
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36")

MIN_SCORE = 0.4          # Tavily 관련도 점수 하한
MIN_CONTENT_CHARS = 1500  # 이보다 짧으면 paywall로 잘린 것으로 간주
MIN_TRUSTED_CHARS = 500  # 직접 스크랩 기사의 최소 본문 길이(속보성 짧은 기사 허용)
MAX_CONTENT_CHARS = 12000  # 번역 토큰 상한
HISTORY_LIMIT = 300

RELEVANT_RE = re.compile(r"gladbach|mönchengladbach|moenchengladbach|borussia|fohlen|\bBMG\b", re.I)
PAYWALL_RE = re.compile(
    r"BILDplus|BILD\s?plus|Bild\+|kicker\s?plus|\bRP\+|RP\s?Plus|Plus-Artikel|"
    r"Jetzt weiterlesen|weiterlesen mit|Nur für Abonnenten|Exklusiv für Abonnenten|"
    r"WOW-Abo|Sky Sport Abo|Mit WOW weiterlesen",
    re.I,
)
LIVETICKER_RE = re.compile(r"live-?ticker", re.I)
PAYWALL_URL_RE = re.compile(r"/plus/|bild-plus|/plus-|kicker-plus", re.I)


# ---------- 히스토리 (메타데이터만) ----------
def load_history():
    try:
        with open(config.EXTERNAL_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.EXTERNAL_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-HISTORY_LIMIT:], f, ensure_ascii=False, indent=1)


def record(history, article, status, reason="", extra=None):
    """status: posted | skipped_paywall | skipped_irrelevant | skipped_stale | skipped_duplicate | failed. reason은 스킵 원인 요약(본문 아님)."""
    history.append({
        "url": article["url"],
        "title": article.get("title", ""),
        "outlet": article.get("outlet", ""),
        "published": article.get("published_date", ""),
        "status": status,
        "reason": reason,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **(extra or {}),
    })


def _seen_urls(history):
    # failed는 재시도 대상이므로 중복으로 보지 않는다
    return {h["url"] for h in history if h.get("status") != "failed"}


# ---------- 필터 ----------
def _outlet_of(url):
    host = (urlparse(url).hostname or "").lower()
    for domain, info in OUTLETS.items():
        if host == domain or host.endswith("." + domain):
            return info
    return None


def classify(result):
    """통과면 None, 아니면 (status, reason)."""
    url = result.get("url", "")
    title = result.get("title", "") or ""
    content = result.get("raw_content") or ""
    score = result.get("score", 1)
    if score < MIN_SCORE and not RELEVANT_RE.search(f"{title} {url}"):  # 제목/URL에 팀명이 있으면 점수가 낮아도 후보
        return "skipped_irrelevant", f"score={score:.2f}<{MIN_SCORE}"
    # 제목에 팀명이 없어도 URL(borussia-moenchengladbach 등)에 있으면 관련 기사로 본다
    if not RELEVANT_RE.search(f"{title} {url} {content[:3000]}"):
        return "skipped_irrelevant", "no BMG keyword"
    if LIVETICKER_RE.search(title):  # 경기 중계 로그는 요약 가치가 낮다(경기 후 리뷰 기사가 따로 나옴)
        return "skipped_irrelevant", "liveticker"
    if result.get("_trusted"):  # 직접 스크랩: 사이트가 알려준 유료 플래그를 신뢰, 문구 휴리스틱은 쓰지 않음
        if result.get("_paywalled"):
            return "skipped_paywall", "isAccessibleForFree=false"
        if len(content) < MIN_TRUSTED_CHARS:
            return "skipped_paywall", f"short content len={len(content)}"
        return None
    if PAYWALL_URL_RE.search(url):
        return "skipped_paywall", "paywall url pattern"
    m = PAYWALL_RE.search(f"{title} {content[:PAYWALL_HEAD_CHARS]}")
    if m:
        return "skipped_paywall", f"marker={m.group(0)!r}"
    if len(content) < MIN_CONTENT_CHARS:
        return "skipped_paywall", f"short content len={len(content)}"
    return None


# ---------- 처리 방식 결정 ----------
# 인터뷰/기자회견은 발언 맥락이 중요하므로 전문 번역, 나머지는 요약
FULL_TRANSLATION_RE = re.compile(
    r"interview|\bstimmen\b|pressekonferenz|\bpk\b|im gespräch|im gespraech",
    re.I,
)


def needs_full_translation(article):
    """True면 전문 번역, False면 요약. EXTERNAL_MODE=full이면 항상 전문 번역."""
    if config.EXTERNAL_MODE == "full":
        return True
    return bool(FULL_TRANSLATION_RE.search(f"{article.get('title', '')} {article.get('url', '')}"))


def format_title(text, outlet):
    """첫 줄(제목)에서 모델이 붙였을 <카테고리> 태그·[매체명]을 지우고 '[매체명] 제목'으로 통일한다."""
    head, _, rest = text.strip().partition("\n")
    title = re.sub(r"^#+\s*", "", head).strip()
    prev = None
    while prev != title:  # <태그>, [대괄호 머리말]이 여러 개 붙은 경우까지 제거
        prev = title
        title = re.sub(r"^(<[^>\n]{1,20}>|\[[^\]\n]{1,30}\])\s*", "", title)
    return f"## [{outlet}] {title}\n{rest}" if rest else f"## [{outlet}] {title}"


# ---------- 대표 사진 ----------
_PAGE_CACHE = {}


def _find_date_published(node):
    """JSON-LD 구조에서 datePublished를 재귀적으로 찾는다."""
    if isinstance(node, dict):
        if node.get("datePublished"):
            return node["datePublished"]
        for v in node.values():
            found = _find_date_published(v)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_date_published(v)
            if found:
                return found
    return None


def fetch_page_meta(url):
    """기사 페이지를 한 번만 받아 대표 사진(og:image)과 게시 시각을 추출한다. 실패해도 예외 없이 빈 값."""
    if url in _PAGE_CACHE:
        return _PAGE_CACHE[url]
    meta = {"image": None, "published": None}
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "de,en;q=0.8"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"property": "og:image:url"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                meta["image"] = urljoin(url, tag["content"].strip())
                break
        for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"},
                      {"property": "og:article:published_time"}, {"itemprop": "datePublished"},
                      {"name": "date"}, {"name": "pubdate"}, {"name": "publish-date"}, {"name": "DC.date.issued"}):
            tag = soup.find("meta", attrs=attrs)
            value = tag.get("content") or tag.get("datetime") if tag else None
            if value:
                meta["published"] = value.strip()
                break
        if not meta["published"]:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    meta["published"] = _find_date_published(json.loads(script.string or ""))
                except Exception:
                    continue
                if meta["published"]:
                    break
        if not meta["published"]:
            t = soup.find("time", attrs={"datetime": True})
            if t:
                meta["published"] = t["datetime"].strip()
    except Exception as e:
        print(f"      ⚠️ 기사 페이지 확인 실패 ({urlparse(url).hostname}): {e}")
    _PAGE_CACHE[url] = meta
    return meta


def fetch_lead_image(url):
    """기사 페이지의 대표 사진 URL. 실패하면 None."""
    return fetch_page_meta(url)["image"]


# ---------- 게시 시각(24시간 이내) 필터 ----------
def parse_datetime(value):
    """문자열 -> (aware datetime, 시각 포함 여부). 해석 불가면 None. 시간대 없으면 독일 시간으로 간주."""
    if not value:
        return None
    value = str(value).strip()
    dt = None
    try:
        dt = parsedate_to_datetime(value)          # RFC 822 (Tavily)
    except Exception:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # ISO 8601 (페이지 메타)
        except Exception:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt, bool(re.search(r"\d{1,2}:\d{2}", value))


def resolve_published(tavily_value, url):
    """Tavily 날짜에 시각이 있으면 그대로, 없으면 기사 페이지 메타에서 보강한다. (dt, has_time) 또는 None."""
    p = parse_datetime(tavily_value)
    if p and p[1]:
        return p
    page = parse_datetime(fetch_page_meta(url)["published"])
    return page or p


def is_fresh(published, now=None):
    """True/False, 게시 시각을 알 수 없으면 None. 날짜만 알면(시각 없음) 오늘·어제(독일 날짜) 기사를 허용한다."""
    if not published:
        return None
    dt, has_time = published
    now = now or datetime.now(timezone.utc)
    if has_time:
        age_hours = (now - dt).total_seconds() / 3600
        return -1 <= age_hours <= config.EXTERNAL_MAX_AGE_HOURS   # -1: 시계 오차 허용
    days = (now.astimezone(BERLIN).date() - dt.astimezone(BERLIN).date()).days
    return 0 <= days <= -(-config.EXTERNAL_MAX_AGE_HOURS // 24)


def download_lead_image(url):
    """대표 사진을 내려받아 로컬 경로를 반환. 없거나 너무 작으면(로고 등) None."""
    import uploader  # 지연 import: 기존 다운로드 로직(_download_image) 재사용
    img_url = fetch_lead_image(url)
    if not img_url:
        print("      📷 대표 사진 없음")
        return None
    path = uploader._download_image(img_url)
    if not path or os.path.getsize(path) < MIN_IMAGE_BYTES:
        print(f"      📷 사진 제외(다운로드 실패 또는 {MIN_IMAGE_BYTES//1024}KB 미만): {img_url[:90]}")
        return None
    print(f"      📷 대표 사진 확보: {img_url[:90]}")
    return path


# ---------- 수집 ----------
def _add_direct_candidates(candidates, seen, scraper):
    """직접 스크랩한 기사를 Tavily 결과와 같은 형태로 candidates에 넣는다. 스크랩 불가면 False."""
    try:
        arts = scraper.collect(skip_urls=seen)
    except Exception as e:
        print(f"⚠️ 직접 스크랩 오류 ({scraper.__name__}): {e}")
        return False
    if arts is None:
        return False
    for a in arts:
        candidates[a["url"]] = {
            "url": a["url"], "title": a["title"], "raw_content": a["content"], "score": 1.0,
            "published_date": a["published"] or "", "_trusted": True, "_paywalled": a["paywalled"],
        }
        # 대표 사진·게시 시각을 이미 알고 있으므로 기사 페이지를 다시 요청하지 않도록 캐시에 넣는다
        _PAGE_CACHE[a["url"]] = {"image": a["image"], "published": a["published"]}
    return True


def _fill_missing_content(client, candidates):
    """Tavily 검색이 raw_content를 비우거나 너무 짧게 보낸 기사를 extract API로 보충한다.
    제목/URL이 BMG 관련인 것만 대상으로 해 크레딧을 아끼며(5 URL당 1크레딧), 실패해도 조용히 넘어간다."""
    missing = [u for u, r in candidates.items()
               if len((r.get("raw_content") or "").strip()) < MIN_CONTENT_CHARS
               and not r.get("_trusted")
               and RELEVANT_RE.search(f"{r.get('title', '')} {u}")]
    if not missing:
        return
    filled = 0
    for i in range(0, len(missing), 20):   # extract는 한 번에 최대 20 URL
        chunk = missing[i:i + 20]
        try:
            res = client.extract(urls=chunk, extract_depth="basic")
        except Exception as e:
            print(f"⚠️ Tavily extract 실패 ({len(chunk)}건): {e}")
            continue
        for item in res.get("results", []):
            text = (item.get("raw_content") or "").strip()
            cur = candidates.get(item.get("url"), {}).get("raw_content") or ""
            if text and len(text) > len(cur) and item.get("url") in candidates:
                candidates[item["url"]]["raw_content"] = text
                filled += 1
    print(f"🧩 본문이 비었거나 짧던 {len(missing)}건 중 {filled}건을 extract로 보충")


# ---------- 공식 기사와의 중복 제거 ----------
OFFICIAL_KEEP_HOURS = 72   # 이 시간 안에 올린 공식 기사와만 비교
OFFICIAL_TITLES_FALLBACK = 8  # data 기록이 없을 때 processed_titles.txt의 최근 제목(제목만) 사용


def load_official_recent():
    try:
        with open(config.OFFICIAL_RECENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_official_recent(items):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.OFFICIAL_RECENT_FILE, "w", encoding="utf-8") as f:
        json.dump(items[-30:], f, ensure_ascii=False, indent=1)


def make_official_entry(title, translated_text, link=""):
    """업로드한 공식 기사에서 비교용 요약(번역 제목 + 도입부 약 300자)만 뽑는다. 본문 전체는 저장하지 않는다."""
    head, _, rest = translated_text.strip().partition("\n")
    ko_title = re.sub(r"^#+\s*", "", head).strip()
    lead = re.sub(r"\[\[(IMG|VID):\d+\]\]|[#*>\-]+|\s+", " ", rest.split("---")[0]).strip()
    return {"title": f"{title} / {ko_title}", "lead": lead[:300], "link": link,
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def official_for_compare(recent, history=None):
    """이미 올라간 기사 목록: 최근 72시간 이내 공식 기사 + 앞서 올린 외부 기사(history) + (기록이 부족하면) processed_titles.txt의 최근 제목."""
    now = datetime.now(timezone.utc)
    items = []
    for o in recent:
        try:
            if (now - datetime.fromisoformat(o["posted_at"])).total_seconds() <= OFFICIAL_KEEP_HOURS * 3600:
                items.append(o)
        except Exception:
            continue
    for h in history or []:   # 앞서 올린 외부 기사(번역 제목 + 우리 요약 도입부만 저장되어 있음)
        try:
            if (h.get("status") == "posted" and h.get("compare_title") and
                    (now - datetime.fromisoformat(h["recorded_at"])).total_seconds() <= OFFICIAL_KEEP_HOURS * 3600):
                items.append({"title": f"[{h.get('outlet', '')}] {h['compare_title']}", "lead": h.get("compare_lead", "")})
        except Exception:
            continue
    if len(items) < OFFICIAL_TITLES_FALLBACK:
        try:
            with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
                titles = [t.strip() for t in f if t.strip()][-OFFICIAL_TITLES_FALLBACK:]
            known = " ".join(o["title"] for o in items)
            items += [{"title": t, "lead": ""} for t in titles if t not in known]
        except FileNotFoundError:
            pass
    return items


def drop_official_duplicates(passed, official, history):
    """필터를 통과한 (시각, 기사) 목록에서 공식 기사와 같은 내용인 것을 뺀다(LLM 1회 호출, 실패 시 그대로)."""
    if not passed or not official:
        return passed
    import translator  # 지연 import: 직접 실행/테스트 시 Gemini 설정 없이도 모듈이 로드되도록
    cands = [{"title": a["title"], "lead": re.sub(r"\s+", " ", a["content"])[:300]} for _, a in passed]
    dups = translator.find_duplicates(cands, official)
    keep = []
    for i, (dt, art) in enumerate(passed):
        if i in dups:
            why = f"공식 기사와 중복: {official[dups[i]]['title'][:60]}"
            print(f"   ⏭️ [{art['outlet']}] skipped_duplicate ({why}): {art['title'][:40]}")
            record(history, art, "skipped_duplicate", why)
        else:
            keep.append((dt, art))
    return keep


def _outlet_rank(key):
    """우선순위가 높을수록 큰 값(목록에 없는 매체는 가장 낮음)."""
    order = config.EXTERNAL_OUTLET_PRIORITY
    return len(order) - order.index(key) if key in order else 0


def drop_cross_duplicates(passed, history):
    """통과한 (시각, 기사) 목록에서 매체끼리 같은 소식을 다룬 기사를 묶어 대표 1건만 남긴다(LLM 1회, 실패 시 그대로).
    대표 선택: 인터뷰/기자회견(전문 번역 대상) 우선 → 매체 우선순위(RP > Kicker > Sky > Bild) → 본문이 긴 기사 → 최신."""
    if len(passed) < 2:
        return passed
    import translator
    cands = [{"title": a["title"], "lead": re.sub(r"\s+", " ", a["content"])[:300]} for _, a in passed]
    drop = set()
    for ids in translator.group_duplicates(cands):
        best = max(ids, key=lambda i: (needs_full_translation(passed[i][1]), _outlet_rank(passed[i][1]["key"]),
                                       len(passed[i][1]["content"]), passed[i][0]))
        for i in ids:
            if i != best:
                drop.add(i)
                art = passed[i][1]
                why = f"다른 매체 기사와 중복: [{passed[best][1]['outlet']}] {passed[best][1]['title'][:50]}"
                print(f"   ⏭️ [{art['outlet']}] skipped_duplicate ({why}): {art['title'][:40]}")
                record(history, art, "skipped_duplicate", why)
    return [p for i, p in enumerate(passed) if i not in drop]


def select_balanced(passed, max_total=None, max_per_outlet=None):
    """통과 기사를 매체별 최신순 큐로 나눠 라운드로빈으로 뽑는다(총 상한, 매체당 상한 적용).
    하루 1회 실행 + 24시간 필터라 상한 밖 기사는 사라지므로, 특정 매체가 상한을 독점하지 않게 한다."""
    max_total = max_total or config.EXTERNAL_MAX_POSTS
    max_per_outlet = max_per_outlet or config.EXTERNAL_MAX_PER_OUTLET
    queues = {}
    for dt, art in sorted(passed, key=lambda x: x[0], reverse=True):
        queues.setdefault(art["key"], []).append((dt, art))
    picked, taken = [], {k: 0 for k in queues}
    while len(picked) < max_total:
        progressed = False
        # 이번 라운드는 가장 최신 기사를 가진 매체부터
        for key in sorted((k for k in queues if queues[k]), key=lambda k: queues[k][0][0], reverse=True):
            if taken[key] < max_per_outlet and len(picked) < max_total:
                picked.append(queues[key].pop(0)[1])
                taken[key] += 1
                progressed = True
        if not progressed:
            break
    return picked


def fetch(history=None, official=None):
    """새로 번역할 외부 기사 리스트를 반환한다. history는 스킵 기록이 추가되어 갱신된다.
    official: 최근 공식 기사 목록(제목/도입부). 같은 내용의 외부 기사는 제외한다."""
    from tavily import TavilyClient

    if not config.TAVILY_API_KEY:
        print("⚠️ TAVILY_API_KEY 없음 - 외부 기사 수집 건너뜀")
        return []
    if not config.TAVILY_API_KEY.startswith("tvly-"):
        print("⚠️ TAVILY_API_KEY가 'tvly-'로 시작하지 않습니다. 키 값을 다시 확인하세요.")
    history = history if history is not None else load_history()
    if config.RESET_SKIPPED:
        before = len(history)
        history[:] = [h for h in history if not str(h.get("status", "")).startswith("skipped")]
        print(f"♻️ RESET_SKIPPED: 스킵 기록 {before - len(history)}건 초기화")
    seen = _seen_urls(history)
    client = TavilyClient(api_key=config.TAVILY_API_KEY)

    candidates = {}
    # 직접 스크랩에 성공한 매체는 Tavily 검색에서 제외(크레딧 절약). 실패하면 Tavily로 대체한다.
    scraped = {domain for domain, scraper in DIRECT_SCRAPERS.items()
               if _add_direct_candidates(candidates, seen, scraper)}
    for domain in OUTLETS:
        if domain in scraped:
            continue
        try:
            res = client.search(
                query=QUERY,
                topic="news",
                search_depth="basic",          # 1 크레딧
                days=DAYS,
                max_results=RESULTS_PER_DOMAIN,
                include_domains=[domain],
                include_raw_content=True,      # 별도 extract 호출 불필요
            )
        except Exception as e:
            print(f"⚠️ Tavily 검색 실패 ({domain}): {e}")
            if "api key" in str(e).lower() or "unauthorized" in str(e).lower():
                print("❌ Tavily 인증 오류 - 이후 쿼리를 중단합니다. GitHub Secret TAVILY_API_KEY를 확인하세요.")
                break
            continue
        for r in res.get("results", []):
            url = r.get("url")
            if url and url not in seen and url not in candidates:
                r["_tavily_window"] = True   # Tavily가 DAYS 범위 안으로 걸러 준 결과
                candidates[url] = r

    _fill_missing_content(client, candidates)

    passed = []   # (게시 시각, 기사) — 필터를 통과한 기사. 마지막에 매체별로 고르게 선택한다
    for url, r in sorted(candidates.items(), key=lambda kv: kv[1].get("score", 0), reverse=True):
        info = _outlet_of(url)
        if not info:
            continue
        outlet, lang, key = info
        art = {
            "title": (r.get("title") or "").strip(),
            "url": url,
            "outlet": outlet,
            "key": key,
            "lang": lang,
            "content": (r.get("raw_content") or "")[:MAX_CONTENT_CHARS],
            "published_date": r.get("published_date", ""),
        }
        verdict = classify(r)
        if verdict:
            status, why = verdict
            print(f"   ⏭️ [{outlet}] {status} ({why}, len={len(r.get('raw_content') or '')}, "
                  f"score={r.get('score', 0):.2f}): {art['title'][:50]}")
            record(history, art, status, why)
            continue
        published = resolve_published(r.get("published_date"), url)
        fresh = is_fresh(published)
        if published is None and r.get("_tavily_window"):
            # Tavily가 날짜를 주지 않고 사이트(Kicker 등)가 봇 차단으로 읽히지 않는 경우:
            # 최근 DAYS일 범위로 검색된 결과이므로 허용한다(시각 순서는 범위 중간값으로 취급)
            published = (datetime.now(timezone.utc) - timedelta(hours=config.EXTERNAL_MAX_AGE_HOURS / 2), False)
            print(f"   🕒 [{outlet}] 게시 시각 불명 - Tavily {DAYS}일 검색 결과로 간주: {art['title'][:40]}")
            fresh = True
        if fresh is not True:
            why = ("게시 시각 불명" if published is None
                   else f"{published[0].astimezone(BERLIN):%Y-%m-%d %H:%M} (>{config.EXTERNAL_MAX_AGE_HOURS}h)")
            print(f"   ⏭️ [{outlet}] skipped_stale ({why}): {art['title'][:50]}")
            record(history, art, "skipped_stale", why)
            continue
        art["published_date"] = published[0].isoformat(timespec="minutes")
        passed.append((published[0], art))

    passed = drop_official_duplicates(passed, official, history)
    passed = drop_cross_duplicates(passed, history)
    articles = select_balanced(passed)
    print(f"📰 외부 기사 후보 {len(candidates)}건 → 필터 통과 {len(passed)}건 → 번역 대상 {len(articles)}건"
          + (f" (상한으로 제외 {len(passed) - len(articles)}건)" if len(passed) > len(articles) else ""))
    return articles
