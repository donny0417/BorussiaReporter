import os
import re
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import config

# 히스토리 관리 함수
def manage_history(new_title):
    history = []
    if not os.path.exists(config.HISTORY_FILE):
        with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
            pass

    with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
        history = [line.strip() for line in f if line.strip()]

    if new_title in history:
        return True

    history.append(new_title)
    if len(history) > 30:
        history = history[-30:]

    with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
        for title in history:
            f.write(title + "\n")
    return False


# 본문 중간 이미지/영상에 위치 마커를 삽입하고 수집하는 스크립트.
# borussia.de는 <article> 태그가 없는 SPA라, "실제 기사 제목 요소 ~ '뒤로가기(Newsübersicht)' 요소" 사이
# 문서 순서 범위를 본문으로 간주한다. 다른 기사로 링크되는 "관련 기사" 카드 이미지는 제외한다.
MEDIA_MARKER_JS = """
(articleTitle) => {
    function findTitleEl(text) {
        if (!text) return document.querySelector('h1');
        const candidates = Array.from(document.querySelectorAll('h1, h2, h3, div, span, p'));
        for (const el of candidates) {
            if (el.children.length === 0 && el.textContent && el.textContent.trim() === text.trim()) {
                return el;
            }
        }
        return document.querySelector('h1');
    }

    function findBackEl() {
        const all = Array.from(document.querySelectorAll('body *'));
        for (const el of all) {
            if (el.children.length === 0 && el.textContent && el.textContent.includes('Newsübersicht')) {
                return el;
            }
        }
        return null;
    }

    function isBetween(el, start, end) {
        if (start) {
            const cmp = start.compareDocumentPosition(el);
            if (!(cmp & Node.DOCUMENT_POSITION_FOLLOWING)) return false;
        }
        if (end) {
            const cmp2 = el.compareDocumentPosition(end);
            if (!(cmp2 & Node.DOCUMENT_POSITION_FOLLOWING)) return false;
        }
        return true;
    }

    const titleEl = findTitleEl(articleTitle);
    const backEl = findBackEl();

    const MIN_W = 200;
    const MIN_H = 120;
    const allMedia = Array.from(document.querySelectorAll('img, video, iframe'));
    const results = [];
    let imgIdx = 0;
    let vidIdx = 0;

    for (const el of allMedia) {
        if (!isBetween(el, titleEl, backEl)) continue;
        if (el.closest('a[href^="/news/"]')) continue; // 관련 기사 카드 제외

        if (el.tagName === 'IMG') {
            const rect = el.getBoundingClientRect();
            if (rect.width < MIN_W || rect.height < MIN_H) continue; // 아이콘/로고 제외

            const marker = `IMG:${imgIdx}`;
            imgIdx++;
            const src = el.currentSrc || el.src || '';
            el.setAttribute('data-crawler-marker', marker);
            el.parentNode.insertBefore(document.createTextNode(` [[${marker}]] `), el);
            results.push({ type: 'image', marker, src });
        } else {
            let src = '';
            if (el.tagName === 'IFRAME') {
                src = el.src || '';
            } else {
                src = el.currentSrc || el.src || '';
                if (!src) {
                    const source = el.querySelector('source');
                    if (source) src = source.src;
                }
            }
            if (!src) continue; // 쿠키 동의 전이거나 실제 영상이 없는 placeholder

            const marker = `VID:${vidIdx}`;
            vidIdx++;
            el.parentNode.insertBefore(document.createTextNode(` [[${marker}]] `), el);
            results.push({ type: 'video', marker, src });
        }
    }

    return results;
}
"""


async def dismiss_cookie_consent(page):
    # consentmanager.net 배너: 동의 전에는 본문 내 영상/iframe의 src가 비어있음
    try:
        btn = page.locator("#cmpwelcomebtnyes").first
        if await btn.count() > 0:
            await btn.click(timeout=3000)
            await asyncio.sleep(1)
    except Exception:
        pass


async def get_borussia_news(ignore_history=False):
    async with async_playwright() as p:
        print("🚀 브라우저 실행 중...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1200}
        )
        page = await context.new_page()

        print("🌐 뉴스 목록 페이지 접속 중...")
        try:
            await page.goto("https://www.borussia.de/news", wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"⚠️ 페이지 로딩 시간 초과 또는 에러: {e}")

        await dismiss_cookie_consent(page)

        for _ in range(5):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1)

        list_content = await page.content()
        list_soup = BeautifulSoup(list_content, 'html.parser')

        articles = list_soup.select('a[href^="/news/"]')
        print(f"📊 발견된 기사 링크 수: {len(articles)}개")

        if len(articles) == 0:
            print("❌ 기사를 하나도 못 찾았습니다.")
            await browser.close()
            return []

        final_task_list = []

        for i, a in enumerate(articles[:10]):
            title = a.select_one('h3').get_text(strip=True) if a.select_one('h3') else "제목 없음"
            full_url = f"https://www.borussia.de{a['href']}"

            print(f"   [{i+1}] 검토 중: {title}")

            if not ignore_history:
                if manage_history(title):
                    print(f"      ⏭️ [스킵] 이미 히스토리에 존재함")
                    continue
            else:
                print(f"      ⚡ [테스트 모드] 히스토리 무시하고 수집 진행")

            # 상세 수집 시작
            try:
                print(f"      ✅ 상세 페이지 이동 중...")
                await page.goto(full_url, wait_until="domcontentloaded", timeout=60000)

                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass

                clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()

                # 리드 이미지 캡처 (기존 방식 그대로: 쿠키 동의 처리/스크롤을 하기 전, 페이지 로드 직후 상단 고정 영역).
                # 쿠키 동의창을 닫으면 상단에 프로모션 배너가 노출되며 레이아웃이 바뀌어 엉뚱한 영역이 찍히므로,
                # 그 부수효과가 생기기 전에 먼저 캡처한다.
                image_path = f"{config.IMAGE_DIR}/{clean_title}.png"
                await page.screenshot(path=image_path, clip={'x': 40, 'y': 100, 'width': 1200, 'height': 600})

                await dismiss_cookie_consent(page)

                for _ in range(6):
                    await page.mouse.wheel(0, 1200)
                    await asyncio.sleep(0.3)

                # 본문 중간 이미지/영상 위치에 마커 삽입 + 수집
                media = []
                try:
                    media = await page.evaluate(MEDIA_MARKER_JS, title)
                except Exception as e:
                    print(f"      ⚠️ 미디어 마커 삽입 실패: {e}")

                images = []
                videos = []
                for m in media:
                    if m['type'] == 'image':
                        src = m.get('src') or ''
                        if src and not src.startswith('data:'):
                            images.append({'marker': m['marker'], 'url': src})
                        else:
                            # URL 추출 실패: 해당 요소가 실제로 있던 위치를 스크린샷으로 대체
                            fallback_path = f"{config.IMAGE_DIR}/{clean_title}_{m['marker'].replace(':', '_')}.png"
                            try:
                                el = await page.query_selector(f'[data-crawler-marker="{m["marker"]}"]')
                                if el:
                                    await el.screenshot(path=fallback_path)
                                    images.append({'marker': m['marker'], 'fallback_screenshot': fallback_path})
                            except Exception as e:
                                print(f"      ⚠️ 대체 스크린샷 실패 ({m['marker']}): {e}")
                    else:
                        videos.append({'marker': m['marker'], 'url': m['src']})

                # === [사용자 요청 수정 부분] ===
                content = ""

                # 전략: 전체 텍스트 중 뉴스 섹션 추정 영역
                # 일단 전체 텍스트를 가져옵니다. (마커가 삽입된 상태라 이미지/영상 위치도 함께 포함됨)
                content = await page.evaluate("() => document.body.innerText")

                # 필요 없는 상/하단 문구 제거 (Footer 부분 잘라내기)
                # "ZURÜCK ZUR NEWSÜBERSICHT" (뉴스 목록으로 돌아가기) 버튼이 나오면 그 뒤는 광고나 푸터이므로 버립니다.
                if "ZURÜCK ZUR NEWSÜBERSICHT" in content:
                    content = content.split("ZURÜCK ZUR NEWSÜBERSICHT")[0]

                # 불필요한 공백 정리
                content = content.strip()
                # ==============================

                final_task_list.append({
                    'title': title,
                    'link': full_url,
                    'content': content,
                    'image_path': image_path,
                    'images': images,
                    'videos': videos,
                })
                # 이제 503이 아니라 실제 본문 길이가 찍힐 겁니다.
                print(f"      📄 수집 완료 (본문 길이: {len(content)}, 추가 이미지 {len(images)}개, 영상 {len(videos)}개)")

            except Exception as e:
                print(f"      ❌ 상세 페이지 처리 에러: {e}")

        await browser.close()
        return final_task_list
