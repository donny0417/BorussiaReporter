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

        for _ in range(3):
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

        for i, a in enumerate(articles[:5]):
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
                
                # 본문 대기 (혹시 모르니)
                try: await page.wait_for_selector("article", timeout=3000)
                except: pass

                # === [사용자 요청 수정 부분] ===
                content = ""
                
                # 전략: 전체 텍스트 중 뉴스 섹션 추정 영역
                # 일단 전체 텍스트를 가져옵니다.
                content = await page.evaluate("() => document.body.innerText")
                
                # 필요 없는 상/하단 문구 제거 (Footer 부분 잘라내기)
                # "ZURÜCK ZUR NEWSÜBERSICHT" (뉴스 목록으로 돌아가기) 버튼이 나오면 그 뒤는 광고나 푸터이므로 버립니다.
                if "ZURÜCK ZUR NEWSÜBERSICHT" in content:
                    content = content.split("ZURÜCK ZUR NEWSÜBERSICHT")[0]
                
                # 불필요한 공백 정리
                content = content.strip()
                # ==============================

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
                # 이제 503이 아니라 실제 본문 길이가 찍힐 겁니다.
                print(f"      📄 수집 완료 (본문 길이: {len(content)})")

            except Exception as e:
                print(f"      ❌ 상세 페이지 처리 에러: {e}")

        await browser.close()
        return final_task_list

