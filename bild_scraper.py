"""Bild(bild.de) Borussia Mönchengladbach 팀 페이지 직접 스크랩.

- 팀 페이지의 기사 티저에서 BMG 관련 기사 URL을 얻는다(타 팀 기사가 섞여 있어 URL/티저 텍스트로 거른다).
- 기사 페이지의 JSON-LD(NewsArticle)에서 게시 시각(datePublished)과 유료 여부(isAccessibleForFree),
  본문은 div.article-body 아래 <p>에서 읽는다. 영상/코너 모음처럼 NewsArticle 정보가 없는 페이지는 건너뛴다.
실패하면 None을 돌려줘 호출 측이 Tavily로 대체할 수 있게 한다.
"""
import json
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.bild.de"
LIST_URL = (BASE + "/sport/fussball/borussia-moenchengladbach/"
            "startseite-borussia-moenchengladbach-31074418.bild.html")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "de,en;q=0.8"}
MAX_LIST = 20
REQUEST_PAUSE = 0.5
BMG_RE = re.compile(r"gladbach|borussia|fohlen|\bbmg\b", re.I)


def parse_list(html):
    """팀 페이지 HTML -> BMG 관련 기사 URL 리스트(페이지 노출 순서, 중복 제거)."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for teaser in soup.select("article[class*=teaser]"):
        link = teaser.find("a", href=re.compile(r"^/sport/fussball/[^#]+"))
        if not link:
            continue
        url = BASE + link["href"].split("?")[0]
        text = f"{link['href']} {teaser.get_text(' ', strip=True)}"
        if url not in urls and BMG_RE.search(text):
            urls.append(url)
    return urls


def _meta(soup, key):
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return tag.get("content", "").strip() if tag and tag.get("content") else None


def parse_article(html, url):
    """기사 페이지 HTML -> dict(title, published, image, paywalled, content). 기사 정보가 없으면 None."""
    soup = BeautifulSoup(html, "html.parser")
    published = None
    accessible = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and "Article" in str(d.get("@type")):
                published = d.get("datePublished")
                if "isAccessibleForFree" in d:
                    accessible = d["isAccessibleForFree"] not in (False, "False", "false")
    if not published:   # 영상/코너 모음 등: 시각을 알 수 없어 24시간 필터를 적용할 수 없다
        return None

    h1 = soup.find("h1")
    title = (_meta(soup, "og:title") or (h1.get_text(" ", strip=True) if h1 else "")).strip()
    body = soup.select_one("div.article-body")
    paragraphs = []
    if body:
        for p in body.find_all("p"):
            text = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
            if text:
                paragraphs.append(text)
    content = "\n\n".join(paragraphs)
    if not title or not content:
        return None
    return {"url": url, "title": title, "published": published, "image": _meta(soup, "og:image"),
            "paywalled": accessible is False, "content": content}


def _get(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def collect(skip_urls=()):
    """새 Bild 기사들을 읽어 리스트로 반환한다. 팀 페이지를 못 읽으면 None(Tavily로 대체)."""
    try:
        urls = parse_list(_get(LIST_URL))
    except Exception as e:
        print(f"⚠️ Bild 팀 페이지 읽기 실패: {e}")
        return None
    if not urls:
        print("⚠️ Bild 팀 페이지에서 기사 URL을 찾지 못했습니다(페이지 구조 변경 가능성)")
        return None

    skip = set(skip_urls)
    todo = [u for u in urls[:MAX_LIST] if u not in skip]
    print(f"📰 Bild 직접 스크랩: 목록 {len(urls[:MAX_LIST])}건 중 신규 {len(todo)}건")
    articles = []
    for url in todo:
        try:
            art = parse_article(_get(url), url)
        except Exception as e:
            print(f"   ⚠️ Bild 기사 읽기 실패 ({url[-50:]}): {e}")
            continue
        finally:
            time.sleep(REQUEST_PAUSE)
        if art:
            articles.append(art)
    return articles
