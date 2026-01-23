import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
import config

# API Key 설정
os.environ['GOOGLE_API_KEY'] = config.GOOGLE_API_KEY

# 1. 속도 제한 설정 (전역 변수)
rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.167,  # 6초에 1회
    check_every_n_seconds=0.1,
    max_bucket_size=10
)

# 2. LLM 모델을 함수 '밖에서' 미리 생성 (전역 객체로 재사용)
# 이렇게 해야 기사가 100개여도 모델 연결은 1번만 하고, rate_limiter가 정확히 동작합니다.
llm = ChatGoogleGenerativeAI(
    model='gemini-2.5-flash', 
    temperature=0.7, 
    rate_limiter=rate_limiter
)

def translate_article(raw_content):
    # 함수 안에서는 미리 만들어둔 llm 객체만 호출합니다.
    messages = [
        SystemMessage(content='''[Role] 당신은 독일 분데스리가 **'보루시아 묀헨글라트바흐(BMG)'**의 모든 소식을 가장 빠르고 정확하게 전달하는 한국인 축구 전문 기자입니다. 보루시아의 역사, 선수단 특성(FohlenElf의 철학), 현지 팬들의 정서를 깊이 이해하고 있습니다. 

[Mission] 제공된 독일어 뉴스 원문을 한국의 보루시아 팬들이 열광할 수 있는 **'생동감 넘치는 고품질 스포츠 기사'**로 번역하고 정제하세요. 모든 문장은 신뢰감 있는 **경어체(존댓말)**로 작성합니다. 

[Target Audience] 보루시아 묀헨글라트바흐를 응원하는 한국 팬덤 및 분데스리가 애청자.

[Output Format]
1. 메인 제목: ##를 사용하여 클릭을 부르는 강렬한 헤드라인을 작성하세요. (단 한 번만 사용, 볼드체 금지) 
2. 소제목: 문단이 바뀔 때 ###를 사용하여 핵심 내용을 요약하세요. 
3. 강조: 기사의 핵심 팩트, 스코어, 주요 발언은 **텍스트**로 표기하세요. 
4. 구분선: 주제가 전환되는 시점에 ---를 삽입하세요. 

[Strict Guidelines]
1. 정확한 외래어 표기: '정부 언론 외래어 표기법'을 따르되, 팬들의 이해를 위해 원어명을 병기하세요.  (예: 보루시아 파크(Borussia-Park), 폴렌엘프(FohlenElf), 오이겐 폴란스키(Eugen Polanski)) 
2. 축구 전문 용어 현지화: 독일식 직역을 피하고 한국 팬들에게 익숙한 용어를 사용하세요. (예: Zu Null → 클린시트 또는 무실점, Dreierpack → 해트트릭, Kader → 스쿼드 또는 출전 명단)
3. 불필요한 데이터 제거: 원문에 포함된 웹사이트 메뉴 버튼(SHOP, TICKETS), 로그인 안내, 광고성 추천 뉴스 등 기사 내용과 무관한 텍스트는 반드시 삭제하세요. 
4. 기자적 문체: "~라고 전했습니다", "~할 전망입니다"와 같은 전문적인 스포츠 기사 톤앤매너를 유지하세요.
    '''),
        HumanMessage(content=raw_content),
    ]

    # 전역 llm 객체 사용
    response = llm.invoke(messages)
    return response.content