"""뉴스/공시 분석 에이전트 - 시장 뉴스 및 기업 공시 분석"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_stock_news, get_top_volume_stocks, get_stock_price
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def news_analyst_node(state: AgentState) -> dict:
    log_agent("📰 뉴스 분석 에이전트", "뉴스 데이터 수집 중...")

    market_context = state.get("market_analysis", "")

    # 거래량 상위 종목에서 뉴스 수집 (KOSPI 상위 7 + KOSDAQ 상위 7)
    kospi_top = get_top_volume_stocks("KOSPI", limit=7)
    kosdaq_top = get_top_volume_stocks("KOSDAQ", limit=7)
    all_top = kospi_top + kosdaq_top

    news_data = []
    seen_codes = set()
    for stock in all_top:
        code = stock.get("code", "")
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        try:
            price_info = get_stock_price(code)
            news = get_stock_news(code, limit=10)
            if news:
                news_data.append({
                    "code": code,
                    "name": price_info.get("name", stock.get("name", "")),
                    "price": price_info.get("price", ""),
                    "change_rate": price_info.get("change_rate", ""),
                    "market": "KOSPI" if stock in kospi_top else "KOSDAQ",
                    "news": news,
                })
        except Exception:
            pass

    news_text = _format_news(news_data)

    prompt = f"""당신은 한국 주식시장 전문 뉴스/공시 분석 애널리스트입니다.
종목별 뉴스를 심층 분석하여 시장에 미치는 영향을 파악합니다.

[시장 전반 분석 컨텍스트]
{market_context}

[수집된 종목별 뉴스 ({len(news_data)}개 종목)]
{news_text}

다음 항목을 분석해주세요:

1. 핵심 호재 뉴스
   - 실적 개선, 신사업, 계약 체결, 해외 진출 등 긍정 신호
   - 영향받을 종목 명시 ([종목코드 종목명])

2. 핵심 악재 뉴스
   - 실적 악화, 소송, 규제, 리콜 등 부정 신호
   - 영향받을 종목 명시

3. 섹터/테마 분석
   - 특정 테마(AI·반도체·2차전지·바이오 등)에 뉴스가 집중되는지
   - 섹터 순환 신호 포착

4. 주목 뉴스 종목 TOP 3
   - 뉴스 모멘텀이 가장 강한 종목 3개와 이유

5. 뉴스 기반 시장 센티멘트
   - 전체적인 뉴스 흐름이 시장에 미칠 영향 (긍정/중립/부정)
   - 시장 분석과 뉴스 방향의 일치 여부"""

    llm = create_llm(temperature=0.3)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
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
        lines.append(
            f"\n▶ {item['name']}({item['code']}) [{item['market']}] "
            f"{item['price']}원 ({item['change_rate']}%)"
        )
        for i, n in enumerate(item.get("news", []), 1):
            lines.append(f"   {i}. {n.get('title', '')}  [{n.get('time', '')}]")
    return "\n".join(lines)
