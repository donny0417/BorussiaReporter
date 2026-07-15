import asyncio
import re
import time
from playwright.async_api import async_playwright
import config
import crawler
import translator
import uploader

URL = "https://www.borussia.de/news/gesundheits-und-leistungscheck-laeutet-vorbereitung-ein-1"


async def crawl_one(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1200}
        )
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        title = await page.evaluate("() => { const h1 = document.querySelector('h1'); return h1 ? h1.textContent.trim() : ''; }")
        clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()

        image_path = f"{config.IMAGE_DIR}/{clean_title}.png"
        await page.screenshot(path=image_path, clip={'x': 40, 'y': 100, 'width': 1200, 'height': 600})

        await crawler.dismiss_cookie_consent(page)
        for _ in range(6):
            await page.mouse.wheel(0, 1200)
            await asyncio.sleep(0.3)

        media = await page.evaluate(crawler.MEDIA_MARKER_JS, title)
        images, videos = [], []
        for m in media:
            if m['type'] == 'image':
                src = m.get('src') or ''
                if src and not src.startswith('data:'):
                    images.append({'marker': m['marker'], 'url': src})
                else:
                    fallback_path = f"{config.IMAGE_DIR}/{clean_title}_{m['marker'].replace(':', '_')}.png"
                    el = await page.query_selector(f'[data-crawler-marker="{m["marker"]}"]')
                    if el:
                        await el.screenshot(path=fallback_path)
                        images.append({'marker': m['marker'], 'fallback_screenshot': fallback_path})
            else:
                videos.append({'marker': m['marker'], 'url': m['src']})

        content = await page.evaluate("() => document.body.innerText")
        if "ZURÜCK ZUR NEWSÜBERSICHT" in content:
            content = content.split("ZURÜCK ZUR NEWSÜBERSICHT")[0]
        content = content.strip()

        await browser.close()
        return {'title': title, 'link': url, 'content': content, 'image_path': image_path, 'images': images, 'videos': videos}


async def main():
    print("🚀 [수동 테스트] 지정 기사 크롤링:", URL)
    news = await crawl_one(URL)
    print(f"이미지 {len(news['images'])}개, 영상 {len(news['videos'])}개 발견")

    translated_text = translator.translate_article(news['content'])
    final_content = f"{translated_text}\n\n---\n원문 출처: {news['link']}"
    post = {
        'translated_text': final_content,
        'image_path': news['image_path'],
        'images': news['images'],
        'videos': news['videos'],
    }

    token = uploader.get_naver_access_token()
    success = uploader.upload_single_article(post, token)
    print("✅ 업로드 성공" if success else "❌ 업로드 실패")


if __name__ == "__main__":
    asyncio.run(main())
