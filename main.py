import asyncio
import time
import crawler
import translator
import uploader
import config
import external_news

def run_external(token):
    """외부 매체(Tavily) 기사 수집 → 번역 → 업로드. 실패해도 공식 뉴스 흐름에 영향 없음."""
    print("🚀 외부 기사 수집 시작 (Tavily)...")
    history = external_news.load_history()
    articles = external_news.fetch(history)

    for i, art in enumerate(articles):
        try:
            translated = translator.translate_article(
                art['content'], lang=art['lang'], outlet=art['outlet'])
        except Exception as e:
            print(f"❌ 번역 실패 ({art['title']}): {e}")
            external_news.record(history, art, 'failed')
            continue

        # 대표 사진 1장 (실패해도 사진 없이 게시)
        if config.DRY_RUN:
            image_path = None
            print(f"🧪 [DRY_RUN] 대표 사진 URL: {external_news.fetch_lead_image(art['url'])}")
        else:
            image_path = external_news.download_lead_image(art['url'])
        photo_line = f"\n📷 사진: {art['outlet']}" if image_path else ""
        post = {
            'translated_text': f"{translated}\n\n---\n원문 출처: {art['outlet']} - {art['url']}{photo_line}",
            'image_path': image_path,
        }
        if config.DRY_RUN:
            print(f"🧪 [DRY_RUN] {art['outlet']} 번역 결과:\n{post['translated_text'][:800]}\n")
            continue  # DRY_RUN은 히스토리에 기록하지 않아 다시 테스트 가능
        if not token:
            external_news.record(history, art, 'failed')
            continue
        ok = uploader.upload_single_article(post, token, menu_id=config.menu_id_for(art['key']))
        external_news.record(history, art, 'posted' if ok else 'failed')
        print(f"{'✅' if ok else '❌'} 외부 기사 업로드 [{art['outlet']}] {art['title'][:40]}")
        if i < len(articles) - 1:
            time.sleep(10)

    if not config.DRY_RUN:
        external_news.save_history(history)


async def main():
    print(f"📌 게시 대상: {config.TARGET} / DRY_RUN={config.DRY_RUN}")
    if config.TARGET != 'prod' and not config.TARGET_CLUB_ID and not config.DRY_RUN:
        print("❌ NAVER_CLUB_ID_TEST/NAVER_MENU_ID_TEST 가 설정되지 않았습니다.")
        return

    # 1. 뉴스 수집
    print("🚀 뉴스 수집 시작...")
    news_list = await crawler.get_borussia_news()
    
    if not news_list:
        print("💤 새로운 공식 뉴스가 없습니다.")
        news_list = []

    # 2. 번역 및 데이터 구성
    print(f"🚀 {len(news_list)}개의 기사 번역 시작...")
    ready_to_post = []
    for news in news_list:
        try:
            translated_text = translator.translate_article(news['content'])
            final_content = f"{translated_text}\n\n---\n원문 출처: {news['link']}"
            ready_to_post.insert(0, {
                'translated_text': final_content,
                'image_path': news['image_path'],
                'images': news.get('images', []),
                'videos': news.get('videos', []),
            })
            print(f"✅ 번역 완료: {news['title']}")
        except Exception as e:
            print(f"❌ 번역 실패 ({news['title']}): {e}")

    # 3. 네이버 카페 업로드
    print("🚀 카페 업로드 시작...")
    token = None if config.DRY_RUN else uploader.get_naver_access_token()

    if config.DRY_RUN:
        for post in ready_to_post:
            print(f"🧪 [DRY_RUN] 공식 기사:\n{post['translated_text'][:500]}\n")
    elif token:
        for i, post in enumerate(ready_to_post):
            success = uploader.upload_single_article(post, token)
            if success:
                print(f"✅ 업로드 완료 [{i+1}/{len(ready_to_post)}]")
            else:
                print(f"❌ 업로드 실패 [{i+1}/{len(ready_to_post)}]")
            
            if i < len(ready_to_post) - 1:
                print("⏳ 10초 대기...")
                time.sleep(10)

    # 4. 외부 매체 기사 (격리: 실패해도 위 공식 뉴스 결과에 영향 없음)
    if config.EXTERNAL_ENABLED:
        if not config.DRY_RUN and not token:
            token = uploader.get_naver_access_token()
        try:
            run_external(token)
        except Exception as e:
            print(f"❌ 외부 기사 처리 중 오류: {e}")


if __name__ == "__main__":

    asyncio.run(main())