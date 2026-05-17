"""뉴스/공시 분석 에이전트 - 시장 뉴스 및 기업 공시 분석"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_stock_news, get_top_volume_stocks
from config import GOOGLE_API_KEY, GEMINI_MODEL
from utils.logger import log_agent


def news_analyst_node(state: AgentState) -> dict:
    log_agent("📰 뉴스 분석 에이전트", "뉴스 데이터 수집 중...")

    top_stocks = get_top_volume_stocks("KOSPI", limit=3) + get_top_volume_stocks("KOSDAQ", limit=3)
    news_data = []

    for stock in top_stocks:
        code = stock.get("code", "")
        if code:
            try:
                news = get_stock_news(code)
                if news:
                    news_data.append({
                        "stock": f"{stock.get('name', '')}({code})",
                        "news": news,
                    })
            except Exception:
                pass

    news_text = _format_news(news_data)
    market_context = state.get("market_analysis", "")

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.3,
    )

    prompt = f"""당신은 한국 주식시장 전문 뉴스/공시 분석가입니다.
주식 시장에 영향을 미치는 뉴스와 공시를 분석합니다.

[시장 분석 컨텍스트]
{market_context}

[수집된 종목별 뉴스]
{news_text}

다음 항목을 분석해주세요:
1. 시장에 긍정적/부정적 영향을 줄 주요 뉴스
2. 특정 섹터나 테마에 영향을 미치는 뉴스 트렌드
3. 주목할 기업들의 공시나 이슈
4. 뉴스 흐름이 시사하는 투자 시사점
5. 시장 분석가 의견과의 일치/불일치 여부

200-300자 이내로 핵심 분석을 제공해주세요."""

    response = llm.invoke([HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("📰 뉴스 분석 에이전트", f"분석 완료:\n{analysis}")

    return {
        "news_analysis": analysis,
        "messages": [AIMessage(content=f"[뉴스 분석가]: {analysis}", name="news_analyst")],
    }


def _format_news(news_data: list[dict]) -> str:
    if not news_data:
        return "뉴스 데이터를 가져올 수 없습니다."
    lines = []
    for item in news_data:
        lines.append(f"\n[{item['stock']}]")
        for n in item.get("news", []):
            lines.append(f"  - {n.get('title', '')} ({n.get('time', '')})")
    return "\n".join(lines) if lines else "뉴스 없음"
