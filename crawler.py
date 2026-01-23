import os
import re
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import config

# 히스토리 관리 함수
def manage_history(new_title):
    history = []
    # 파일이 없으면 생성
    if not os.path.exists(config.HISTORY_FILE):
        with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
            pass

    with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
        history = [line.strip() for line in f if line.strip()]

    if new_title in history:
        return True # 이미 존재함 (중복)

    # 새 타이틀 추가 및 30개 유지
    history.append(new_title)
    if len(history) > 30:
        history = history[-30:]

    with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
        for title in history:
            f.write(title + "\n")
    return False

async def get_borussia_news(ignore_history=False): # 테스트를 위해 ignore_history 옵션 추가
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
            # 에러가 나도 일단 진행해봅니다 (일부 로딩됐을 수 있음)

        # 스크롤을 좀 더 확실하게 여러 번 내림
        for _ in range(3):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1)

        # 디버깅: 현재 페이지 타이틀 확인
        page_title = await page.title()
        print(f"🔎 접속된 페이지 제목: {page_title}")

        list_content = await page.content()
        list_soup = BeautifulSoup(list_content, 'html.parser')
        
        # 선택자 확인
        articles = list_soup.select('a[href^="/news/"]')
        print(f"📊 발견된 기사 링크 수: {len(articles)}개")

        if len(articles) == 0:
            print("❌ 기사를 하나도 못 찾았습니다. 선택자(a[href^='/news/'])가 맞지 않거나 페이지가 덜 로딩되었습니다.")
            await browser.close()
            return []

        final_task_list = []

        # 상위 5개만 검토
        for i, a in enumerate(articles[:5]):
            title = a.select_one('h3').get_text(strip=True) if a.select_one('h3') else "제목 없음"
            full_url = f"https://www.borussia.de{a['href']}"
            
            print(f"   [{i+1}] 검토 중: {title}")

            # ignore_history가 True면 중복 체크를 건너뜀 (무조건 수집)
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
                
                # 본문 대기
                try: await page.wait_for_selector("article", timeout=5000)
                except: pass

                # 본문 추출 시도
                content = ""
                content_el = await page.query_selector("article")
                if content_el: 
                    content = (await content_el.inner_text()).strip()
                
                if not content:
                    content_el = await page.query_selector(".news-detail__content")
                    if content_el: content = (await content_el.inner_text()).strip()

                if not content:
                    # 최후의 수단: 본문이 없으면 그냥 body 전체 긁기 (테스트용)
                    content = await page.evaluate("() => document.body.innerText")
                    content = content[:500] + "..." # 너무 기니까 자르기

                # 이미지 캡처
                clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
                image_path = f"{config.IMAGE_DIR}/{clean_title}.png"
                await page.screenshot(path=image_path, clip={'x': 40, 'y': 100, 'width': 1200, 'height': 600})

                final_task_list.append({
                    'title': title,
                    'link': full_url,
                    'content': content,
                    'image_path': image_path
                })
                print(f"      📄 수집 완료 (본문 길이: {len(content)})")

            except Exception as e:
                print(f"      ❌ 상세 페이지 처리 에러: {e}")

        await browser.close()

        return final_task_list
