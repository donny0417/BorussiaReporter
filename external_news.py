"""Tavily 검색으로 외부 매체(RP, Sky Sports, Bild, Kicker)의 BMG 기사를 수집한다.

비용 절감 원칙: LLM 번역 호출 전에 (1) 이미 처리한 URL, (2) 무관한 기사,
(3) 유료(paywall) 기사를 모두 걸러낸다. 원문 본문은 저장하지 않고 메타데이터만 기록한다.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import config

# 도메인 -> (표시명, 언어, 게시판 키). 게시판 키는 config.menu_id_for()의 환경변수 접미사로 쓰인다.
OUTLETS = {
    "rp-online.de": ("RP Online", "de", "RP"),
    "sport.sky.de": ("Sky Sport", "de", "SKY"),
    "bild.de": ("Bild", "de", "BILD"),
    "kicker.de": ("Kicker", "de", "KICKER"),
}
QUERIES = ["Borussia Mönchengladbach", "Gladbach Fohlen"]

MIN_SCORE = 0.4          # Tavily 관련도 점수 하한
MIN_CONTENT_CHARS = 1500  # 이보다 짧으면 paywall로 잘린 것으로 간주
MAX_CONTENT_CHARS = 12000  # 번역 토큰 상한
HISTORY_LIMIT = 300

RELEVANT_RE = re.compile(r"gladbach|mönchengladbach|moenchengladbach|borussia|fohlen|\bBMG\b", re.I)
PAYWALL_RE = re.compile(
    r"BILDplus|BILD\s?plus|Bild\+|kicker\s?plus|\bRP\+|RP\s?Plus|Plus-Artikel|"
    r"Jetzt weiterlesen|weiterlesen mit|Nur für Abonnenten|Exklusiv für Abonnenten|"
    r"Sky Q|WOW-Abo|mit WOW|Sky Sport Abo",
    re.I,
)
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


def record(history, article, status):
    """status: posted | skipped_paywall | skipped_irrelevant | failed"""
    history.append({
        "url": article["url"],
        "title": article.get("title", ""),
        "outlet": article.get("outlet", ""),
        "published": article.get("published_date", ""),
        "status": status,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
    """None이면 통과, 아니면 스킵 사유 status 문자열."""
    url = result.get("url", "")
    title = result.get("title", "") or ""
    content = result.get("raw_content") or ""
    if result.get("score", 1) < MIN_SCORE or not RELEVANT_RE.search(title + " " + content[:3000]):
        return "skipped_irrelevant"
    if (PAYWALL_URL_RE.search(url) or PAYWALL_RE.search(title)
            or PAYWALL_RE.search(content) or len(content) < MIN_CONTENT_CHARS):
        return "skipped_paywall"
    return None


# ---------- 수집 ----------
def fetch(history=None):
    """새로 번역할 외부 기사 리스트를 반환한다. history는 스킵 기록이 추가되어 갱신된다."""
    from tavily import TavilyClient

    if not config.TAVILY_API_KEY:
        print("⚠️ TAVILY_API_KEY 없음 - 외부 기사 수집 건너뜀")
        return []
    history = history if history is not None else load_history()
    seen = _seen_urls(history)
    client = TavilyClient(api_key=config.TAVILY_API_KEY)

    candidates = {}
    for q in QUERIES:
        try:
            res = client.search(
                query=q,
                topic="news",
                search_depth="basic",          # 1 크레딧
                days=2,
                max_results=10,
                include_domains=list(OUTLETS),
                include_raw_content=True,      # 별도 extract 호출 불필요
            )
        except Exception as e:
            print(f"⚠️ Tavily 검색 실패 ({q}): {e}")
            continue
        for r in res.get("results", []):
            url = r.get("url")
            if url and url not in seen and url not in candidates:
                candidates[url] = r

    articles = []
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
        reason = classify(r)
        if reason:
            print(f"   ⏭️ [{outlet}] {reason}: {art['title'][:50]}")
            record(history, art, reason)
            continue
        if len(articles) >= config.EXTERNAL_MAX_POSTS:
            continue  # 상한 초과분은 기록하지 않아 다음 실행에서 다시 후보가 된다
        articles.append(art)
    print(f"📰 외부 기사 후보 {len(candidates)}건 → 번역 대상 {len(articles)}건")
    return articles
