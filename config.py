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

# --- 외부 기사(Tavily) 설정 ---
# Secret에 공백/줄바꿈/따옴표가 섞여 들어가는 경우가 많아 정리한다
TAVILY_API_KEY = (os.getenv("TAVILY_API_KEY") or "").strip().strip("\"'")
EXTERNAL_ENABLED = os.getenv("EXTERNAL_ENABLED", "1") == "1"
EXTERNAL_MAX_POSTS = int(os.getenv("EXTERNAL_MAX_POSTS", "8"))          # 1회 실행당 총 상한
# 같은 소식을 여러 매체가 쓴 경우 남길 매체의 우선순위(왼쪽이 우선, 매체 키 기준)
EXTERNAL_OUTLET_PRIORITY = [k.strip().upper() for k in os.getenv("EXTERNAL_OUTLET_PRIORITY", "RP,KICKER,SKY,BILD").split(",") if k.strip()]
EXTERNAL_MAX_PER_OUTLET = int(os.getenv("EXTERNAL_MAX_PER_OUTLET", "3"))  # 매체당 상한(한 매체 쏠림 방지)
# 외부 기사 처리 방식: summary(기본, 인터뷰/기자회견만 전문 번역) | full(전부 전문 번역)
EXTERNAL_MODE = os.getenv("EXTERNAL_MODE", "summary").lower()
EXTERNAL_MAX_AGE_HOURS = int(os.getenv("EXTERNAL_MAX_AGE_HOURS", "24"))  # 게시 시각 기준 이 시간 이내 기사만
RESET_SKIPPED = os.getenv("RESET_SKIPPED", "0") == "1"  # 이전에 skipped로 기록된 URL을 다시 평가

# --- 게시 대상 전환: 기본값 test (실수로 본 카페에 올라가는 것을 방지) ---
TARGET = os.getenv("TARGET", "test").lower()
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
NAVER_CLUB_ID_TEST = os.getenv("NAVER_CLUB_ID_TEST")
NAVER_MENU_ID_TEST = os.getenv("NAVER_MENU_ID_TEST")
if TARGET == "prod":
    TARGET_CLUB_ID, TARGET_MENU_ID = NAVER_CLUB_ID, NAVER_MENU_ID
else:
    TARGET_CLUB_ID, TARGET_MENU_ID = NAVER_CLUB_ID_TEST, NAVER_MENU_ID_TEST


def menu_id_for(outlet_key):
    """언론사별 게시판 ID. 예) TARGET=test, RP -> NAVER_MENU_ID_RP_TEST (prod는 NAVER_MENU_ID_RP).
    설정되지 않았으면 기본 게시판(TARGET_MENU_ID)으로 올린다."""
    suffix = "_TEST" if TARGET != "prod" else ""
    return os.getenv(f"NAVER_MENU_ID_{outlet_key}{suffix}") or TARGET_MENU_ID


# [경로 설정 수정]
# GitHub Actions 서버는 경로 구조가 다르므로 __file__을 기준으로 잡는 게 가장 안전합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "borussia_images")
HISTORY_FILE = os.path.join(BASE_DIR, "processed_titles.txt")
DATA_DIR = os.path.join(BASE_DIR, "data")
EXTERNAL_HISTORY_FILE = os.path.join(DATA_DIR, "external_history.json")
OFFICIAL_RECENT_FILE = os.path.join(DATA_DIR, "official_recent.json")  # 최근 공식 기사 제목/도입부(중복 비교용)

if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
