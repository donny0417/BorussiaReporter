import asyncio
import time
import crawler
import translator
import uploader

async def main():
    # 1. 뉴스 수집
    print("🚀 뉴스 수집 시작...")
    news_list = await crawler.get_borussia_news()
    
    if not news_list:
        print("💤 새로운 뉴스가 없습니다.")
        return

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
    token = uploader.get_naver_access_token()
    
    if token:
        for i, post in enumerate(ready_to_post):
            success = uploader.upload_single_article(post, token)
            if success:
                print(f"✅ 업로드 완료 [{i+1}/{len(ready_to_post)}]")
            else:
                print(f"❌ 업로드 실패 [{i+1}/{len(ready_to_post)}]")
            
            if i < len(ready_to_post) - 1:
                print("⏳ 10초 대기...")
                time.sleep(10)

if __name__ == "__main__":

    asyncio.run(main())