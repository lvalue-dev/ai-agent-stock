"""시장 분석 에이전트 - KOSPI/KOSDAQ 지수 및 시장 흐름 분석"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_market_index, get_top_volume_stocks
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def market_analyst_node(state: AgentState) -> dict:
    log_agent("📊 시장 분석 에이전트", "시장 데이터 수집 중...")

    kospi = get_market_index("KOSPI")
    kosdaq = get_market_index("KOSDAQ")
    top_kospi = get_top_volume_stocks("KOSPI", limit=5)
    top_kosdaq = get_top_volume_stocks("KOSDAQ", limit=5)

    market_data = f"""
=== 실시간 시장 데이터 ===

[KOSPI]
- 현재 지수: {kospi['index']}
- 등락: {kospi['change']} ({kospi['change_rate']}%)
- 거래량: {kospi['volume']}
- 거래대금: {kospi['trade_amount']}
- 고가: {kospi['high']} / 저가: {kospi['low']}

[KOSDAQ]
- 현재 지수: {kosdaq['index']}
- 등락: {kosdaq['change']} ({kosdaq['change_rate']}%)
- 거래량: {kosdaq['volume']}
- 거래대금: {kosdaq['trade_amount']}
- 고가: {kosdaq['high']} / 저가: {kosdaq['low']}

[KOSPI 거래량 상위 5종목]
{_format_stocks(top_kospi)}

[KOSDAQ 거래량 상위 5종목]
{_format_stocks(top_kosdaq)}
"""

    prompt = f"""당신은 한국 주식시장 전문 시장 분석가입니다.
다음 실시간 시장 데이터를 분석하여 전문적인 시장 분석을 제공해주세요.

{market_data}

다음 항목을 포함하여 분석해주세요:
1. 현재 시장 흐름 (강세/약세/횡보)
2. KOSPI와 KOSDAQ의 상대적 강도 비교
3. 거래량 분석을 통한 시장 참여도
4. 주목할 만한 섹터나 테마
5. 단기 시장 방향성 전망
6. 매매 전략 관점에서의 시장 환경 평가 (매수 우호적/비우호적/중립)

200-300자 이내의 핵심 분석을 제공해주세요."""

    llm = create_llm(temperature=0.3)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("📊 시장 분석 에이전트", f"분석 완료:\n{analysis}")

    return {
        "market_analysis": analysis,
        "messages": [AIMessage(content=f"[시장 분석가]: {analysis}", name="market_analyst")],
    }


def _format_stocks(stocks: list[dict]) -> str:
    if not stocks:
        return "  데이터 없음"
    lines = []
    for s in stocks:
        lines.append(
            f"  {s.get('rank', '')}위 {s.get('name', '')}({s.get('code', '')}) "
            f"- {s.get('price', '')}원 ({s.get('change_rate', '')}%) "
            f"거래량: {s.get('volume', '')}"
        )
    return "\n".join(lines)
