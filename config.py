import os
# from dotenv import load_dotenv 
# load_dotenv() # GitHub Actions에서는 자동으로 주입되므로 주석 처리해도 됨 (로컬 테스트용)

# [중요] os.getenv를 사용하여 GitHub Secrets에서 값을 받아옵니다.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NAVER_REFRESH_TOKEN = os.getenv("NAVER_REFRESH_TOKEN")
NAVER_CLUB_ID = os.getenv("NAVER_CLUB_ID")
NAVER_MENU_ID = os.getenv("NAVER_MENU_ID")

# [경로 설정 수정]
# GitHub Actions 서버는 경로 구조가 다르므로 __file__을 기준으로 잡는 게 가장 안전합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "borussia_images")
HISTORY_FILE = os.path.join(BASE_DIR, "processed_titles.txt")

if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)