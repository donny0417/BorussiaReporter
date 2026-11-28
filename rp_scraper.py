"""RP Online(rp-online.de) Borussia 섹션 직접 스크랩.

- 목록 페이지(JSON-LD ItemList)에서 BMG 기사 URL을 최신순으로 얻는다.
- 기사 페이지에서 게시 시각(article:published_time), 유료 여부(JSON-LD isAccessibleForFree),
  대표 사진(og:image), 본문(.cXenseParse 블록)을 읽는다.
Tavily 크레딧을 쓰지 않고, 유료/시각 판별이 정확하다. 네트워크/구조 변경으로 실패하면 None을 돌려줘
호출 측이 Tavily로 대체할 수 있게 한다.
"""
import json
import re
import time

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://rp-online.de/sport/fussball/borussia/"
ARTICLE_PREFIX = "https://rp-online.de/sport/fussball/borussia/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "de,en;q=0.8"}
MAX_LIST = 15
REQUEST_PAUSE = 0.5  # 초: 서버 부담/차단 방지

_NOISE_RE = re.compile(r"Kostenpflichtiger Inhalt|Anzeige\b|Lesen Sie auch:?|Mehr zum Thema:?")


def parse_list(html):
    """목록 페이지 HTML -> 기사 URL 리스트(최신순, 중복 제거). 구조를 못 찾으면 빈 리스트."""
    urls = []
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and d.get("@type") == "ItemList":
                for item in d.get("itemListElement") or []:
                    url = item.get("url") if isinstance(item, dict) else None
                    if url and url.startswith(ARTICLE_PREFIX) and url not in urls:
                        urls.append(url)
    return urls


def _meta(soup, key):
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return tag.get("content", "").strip() if tag and tag.get("content") else None


def parse_article(html, url):
    """기사 페이지 HTML -> dict(title, published, image, paywalled, content). 본문을 못 읽으면 None."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = (_meta(soup, "og:title") or (h1.get_text(" ", strip=True) if h1 else "")).strip()
    published = _meta(soup, "article:published_time")

    accessible = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and "Article" in str(d.get("@type")):
                published = published or d.get("datePublished")
                if "isAccessibleForFree" in d:
                    accessible = d["isAccessibleForFree"] not in (False, "False", "false")
    paywalled = accessible is False or bool(soup.select_one("[class*=park-paywall]"))

    blocks = []
    for b in soup.select(".cXenseParse"):
        text = _NOISE_RE.sub("", b.get_text(" ", strip=True))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            blocks.append(text)
    content = "\n\n".join(blocks)
    if not title or not content:
        return None
    return {"url": url, "title": title, "published": published, "image": _meta(soup, "og:image"),
            "paywalled": paywalled, "content": content}


def _get(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def collect(skip_urls=()):
    """새 RP 기사들을 읽어 리스트로 반환한다. skip_urls(이미 처리한 URL)는 요청하지 않는다.
    목록 자체를 못 읽으면 None(=스크랩 불가, 호출 측이 Tavily로 대체)."""
    try:
        urls = parse_list(_get(LIST_URL))
    except Exception as e:
        print(f"⚠️ RP 목록 페이지 읽기 실패: {e}")
        return None
    if not urls:
        print("⚠️ RP 목록에서 기사 URL을 찾지 못했습니다(페이지 구조 변경 가능성)")
        return None

    articles = []
    todo = [u for u in urls[:MAX_LIST] if u not in set(skip_urls)]
    print(f"📰 RP 직접 스크랩: 목록 {len(urls[:MAX_LIST])}건 중 신규 {len(todo)}건")
    for url in todo:
        try:
            art = parse_article(_get(url), url)
        except Exception as e:
            print(f"   ⚠️ RP 기사 읽기 실패 ({url[-50:]}): {e}")
            continue
        finally:
            time.sleep(REQUEST_PAUSE)
        if art:
            articles.append(art)
        else:
            print(f"   ⚠️ RP 기사 본문을 읽지 못함: {url[-50:]}")
    return articles
