"""Tavily 검색으로 외부 매체(RP, Sky Sports, Bild, Kicker)의 BMG 기사를 수집한다.

비용 절감 원칙: LLM 번역 호출 전에 (1) 이미 처리한 URL, (2) 무관한 기사,
(3) 유료(paywall) 기사를 모두 걸러낸다. 원문 본문은 저장하지 않고 메타데이터만 기록한다.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config

# 도메인 -> (표시명, 언어, 게시판 키). 게시판 키는 config.menu_id_for()의 환경변수 접미사로 쓰인다.
OUTLETS = {
    "rp-online.de": ("RP Online", "de", "RP"),
    "sport.sky.de": ("Sky Sport", "de", "SKY"),
    "bild.de": ("Bild", "de", "BILD"),
    "kicker.de": ("Kicker", "de", "KICKER"),
}
QUERY = "Borussia Mönchengladbach Gladbach"  # 도메인별로 1회씩 검색(편중 방지)
DAYS = 3
RESULTS_PER_DOMAIN = 5
PAYWALL_HEAD_CHARS = 600  # 내비/푸터의 상시 노출 문구 오판 방지: 제목+본문 앞부분만 검사
MIN_IMAGE_BYTES = 10 * 1024  # 이보다 작으면 로고/플레이스홀더로 보고 첨부 안 함
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36")

MIN_SCORE = 0.4          # Tavily 관련도 점수 하한
MIN_CONTENT_CHARS = 1500  # 이보다 짧으면 paywall로 잘린 것으로 간주
MAX_CONTENT_CHARS = 12000  # 번역 토큰 상한
HISTORY_LIMIT = 300

RELEVANT_RE = re.compile(r"gladbach|mönchengladbach|moenchengladbach|borussia|fohlen|\bBMG\b", re.I)
PAYWALL_RE = re.compile(
    r"BILDplus|BILD\s?plus|Bild\+|kicker\s?plus|\bRP\+|RP\s?Plus|Plus-Artikel|"
    r"Jetzt weiterlesen|weiterlesen mit|Nur für Abonnenten|Exklusiv für Abonnenten|"
    r"WOW-Abo|Sky Sport Abo|Mit WOW weiterlesen",
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


def record(history, article, status, reason=""):
    """status: posted | skipped_paywall | skipped_irrelevant | failed. reason은 스킵 원인 요약(본문 아님)."""
    history.append({
        "url": article["url"],
        "title": article.get("title", ""),
        "outlet": article.get("outlet", ""),
        "published": article.get("published_date", ""),
        "status": status,
        "reason": reason,
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
    """통과면 None, 아니면 (status, reason)."""
    url = result.get("url", "")
    title = result.get("title", "") or ""
    content = result.get("raw_content") or ""
    score = result.get("score", 1)
    if score < MIN_SCORE:
        return "skipped_irrelevant", f"score={score:.2f}<{MIN_SCORE}"
    # 제목에 팀명이 없어도 URL(borussia-moenchengladbach 등)에 있으면 관련 기사로 본다
    if not RELEVANT_RE.search(f"{title} {url} {content[:3000]}"):
        return "skipped_irrelevant", "no BMG keyword"
    if PAYWALL_URL_RE.search(url):
        return "skipped_paywall", "paywall url pattern"
    m = PAYWALL_RE.search(f"{title} {content[:PAYWALL_HEAD_CHARS]}")
    if m:
        return "skipped_paywall", f"marker={m.group(0)!r}"
    if len(content) < MIN_CONTENT_CHARS:
        return "skipped_paywall", f"short content len={len(content)}"
    return None


# ---------- 대표 사진 ----------
def fetch_lead_image(url):
    """기사 페이지의 og:image(없으면 twitter:image) URL을 반환. 실패하면 None."""
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "de,en;q=0.8"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"property": "og:image:url"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return urljoin(url, tag["content"].strip())
    except Exception as e:
        print(f"      ⚠️ 대표 사진 확인 실패 ({urlparse(url).hostname}): {e}")
    return None


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
def fetch(history=None):
    """새로 번역할 외부 기사 리스트를 반환한다. history는 스킵 기록이 추가되어 갱신된다."""
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
    for domain in OUTLETS:
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
        verdict = classify(r)
        if verdict:
            status, why = verdict
            print(f"   ⏭️ [{outlet}] {status} ({why}, len={len(r.get('raw_content') or '')}, "
                  f"score={r.get('score', 0):.2f}): {art['title'][:50]}")
            record(history, art, status, why)
            continue
        if len(articles) >= config.EXTERNAL_MAX_POSTS:
            continue  # 상한 초과분은 기록하지 않아 다음 실행에서 다시 후보가 된다
        articles.append(art)
    print(f"📰 외부 기사 후보 {len(candidates)}건 → 번역 대상 {len(articles)}건")
    return articles
