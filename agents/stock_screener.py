"""종목 스크리닝 에이전트 - 조건에 맞는 투자 유망 종목 발굴"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_top_volume_stocks, get_stock_price
from config import GOOGLE_API_KEY, GEMINI_MODEL
from utils.logger import log_agent


def stock_screener_node(state: AgentState) -> dict:
    log_agent("🔍 스크리닝 에이전트", "종목 스크리닝 중...")

    market_analysis = state.get("market_analysis", "")
    news_analysis = state.get("news_analysis", "")

    kospi_stocks = get_top_volume_stocks("KOSPI", limit=10)
    kosdaq_stocks = get_top_volume_stocks("KOSDAQ", limit=10)
    all_stocks = kospi_stocks + kosdaq_stocks

    detailed_stocks = []
    for stock in all_stocks[:5]:
        code = stock.get("code", "")
        if code:
            try:
                detail = get_stock_price(code)
                detail["volume_rank"] = stock.get("rank", "")
                detail["volume_rate"] = stock.get("volume_rate", "")
                detail["market"] = "KOSPI" if stock in kospi_stocks else "KOSDAQ"
                detailed_stocks.append(detail)
            except Exception:
                pass

    stocks_text = _format_detailed_stocks(detailed_stocks)
    candidate_list = _format_candidates(all_stocks)

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.4,
    )

    prompt = f"""당신은 한국 주식시장 전문 종목 발굴 애널리스트입니다.
시장 데이터와 뉴스 분석을 바탕으로 투자 유망 종목을 스크리닝합니다.

[시장 분석]
{market_analysis}

[뉴스 분석]
{news_analysis}

[상세 데이터 종목 (거래량 상위 5종목)]
{stocks_text}

[전체 거래량 상위 후보군]
{candidate_list}

다음을 수행해주세요:
1. 위 데이터를 기반으로 투자 유망 종목 3-5개를 선정해주세요
2. 각 종목에 대해 선정 이유를 간략히 설명해주세요
3. 선정 종목의 매수 적정 가격대와 목표가를 제시해주세요
4. 스크리닝 기준 (모멘텀/가치/성장 등) 설명
5. 리스크 요인도 언급해주세요

답변 형식:
- 추천종목: [종목코드 종목명] - 이유 (목표가: xxx원)
형태로 종목별로 작성해주세요."""

    response = llm.invoke([HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("🔍 스크리닝 에이전트", f"스크리닝 완료:\n{analysis}")

    screened = [
        {"code": s.get("code", ""), "name": s.get("name", ""), "price": s.get("price", "")}
        for s in detailed_stocks
    ]

    return {
        "screened_stocks": screened,
        "screening_analysis": analysis,
        "messages": [AIMessage(content=f"[스크리닝 에이전트]: {analysis}", name="stock_screener")],
    }


def _format_detailed_stocks(stocks: list[dict]) -> str:
    if not stocks:
        return "데이터 없음"
    lines = []
    for s in stocks:
        lines.append(
            f"- {s.get('name', '')}({s.get('code', '')}) [{s.get('market', '')}]\n"
            f"  현재가: {s.get('price', '')}원 | 등락률: {s.get('change_rate', '')}%\n"
            f"  PER: {s.get('per', '')} | PBR: {s.get('pbr', '')} | 시총: {s.get('market_cap', '')}억\n"
            f"  52주 최고: {s.get('52w_high', '')} | 최저: {s.get('52w_low', '')}\n"
            f"  거래량 순위: {s.get('volume_rank', '')}위 | 거래량 증가율: {s.get('volume_rate', '')}%"
        )
    return "\n".join(lines)


def _format_candidates(stocks: list[dict]) -> str:
    if not stocks:
        return "데이터 없음"
    lines = [
        f"  {s.get('rank', '')}위 {s.get('name', '')}({s.get('code', '')}) "
        f"{s.get('price', '')}원 ({s.get('change_rate', '')}%)"
        for s in stocks
    ]
    return "\n".join(lines)
