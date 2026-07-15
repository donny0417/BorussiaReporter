import os
import re
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
# 만약 config 파일이 따로 없다면 테스트용 변수로 대체하세요.
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

        # 무한 스크롤 다운 (처음 5회)
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

        # 최대 상위 10개 기사 크롤링 진행
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

            # 기사 상세 페이지 이동
            detail_page = await context.new_page()
            try:
                print(f"      📖 상세 페이지 이동: {full_url}")
                await detail_page.goto(full_url, wait_until="networkidle", timeout=30000)
                await dismiss_cookie_consent(detail_page)
                
                # JavaScript 마커 삽입 및 미디어 목록 수집 실행
                media_list = await detail_page.evaluate(MEDIA_MARKER_JS, title)
                
                # 마커가 텍스트 노드로 삽입된 이후의 최종 HTML 수집
                detail_html = await detail_page.content()
                detail_soup = BeautifulSoup(detail_html, 'html.parser')
                
                # 본문 텍스트 추출 가공 (예: 특정 div 영역 또는 p 태그 수집)
                # borussia.de는 article 태그가 없으므로 본문 텍스트 내에 [[IMG:X]] 또는 [[VID:X]] 마커가 포함됩니다.
                paragraphs = detail_soup.find_all(['p', 'div'])
                content_texts = []
                for p in paragraphs:
                    # 마커 문자열([[IMG: 또는 [[VID:)을 포함하거나 본문 구성에 적합한 요소들만 필터링
                    txt = p.get_text(separator=" ", strip=True)
                    if any(marker['marker'] in txt for marker in media_list) or (len(txt) > 20 and not p.find('a', href=re.compile(r'^/news/'))):
                        if txt not in content_texts:
                            content_texts.append(txt)
                
                full_content = "\n\n".join(content_texts)
                
                final_task_list.append({
                    "title": title,
                    "url": full_url,
                    "content": full_content,
                    "media": media_list
                })
                print(f"      ✓ 성공적으로 수집 완료 (미디어 {len(media_list)}개 발견)")
                
            except Exception as e:
                print(f"      ❌ 상세 페이지 처리 중 에러 발생: {e}")
            finally:
                await detail_page.close()
                await asyncio.sleep(1) # 부하 방지용 대기

        await browser.close()
        return final_task_list