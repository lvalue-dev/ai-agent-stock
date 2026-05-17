"""기관/외국인 투자자 분석 에이전트"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_investor_trading, get_top_volume_stocks, get_stock_price
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def institutional_agent_node(state: AgentState) -> dict:
    log_agent("🏦 기관/외국인 에이전트", "투자자 매매동향 수집 중...")

    screened_stocks = state.get("screened_stocks", [])

    # 스크리닝 종목 + 거래량 상위 종목으로 분석 대상 구성
    kospi_top = get_top_volume_stocks("KOSPI", limit=10)
    kosdaq_top = get_top_volume_stocks("KOSDAQ", limit=10)
    all_candidates = {s["code"]: s for s in screened_stocks if s.get("code")}
    for s in kospi_top + kosdaq_top:
        code = s.get("code", "")
        if code and code not in all_candidates and len(all_candidates) < 12:
            all_candidates[code] = s

    investor_data = []
    for code, base in all_candidates.items():
        try:
            inv = get_investor_trading(code)
            if "error" not in inv:
                price_info = get_stock_price(code)
                investor_data.append({
                    **base,
                    "name": price_info.get("name", base.get("name", "")),
                    "price": price_info.get("price", base.get("price", "")),
                    **inv,
                })
        except Exception:
            pass

    inv_text = _format_investor_data(investor_data)

    prompt = f"""당신은 기관투자자 및 외국인 투자 동향 전문 애널리스트입니다.
스마트머니(기관·외국인)의 움직임을 추적하여 투자 방향을 분석합니다.

[종목별 투자자 매매동향]
{inv_text}

다음 항목을 분석해주세요:
1. 기관 순매수 상위 종목: 기관이 집중 매수하는 종목과 그 의미
2. 외국인 순매수 상위 종목: 외국인이 선호하는 종목 트렌드
3. 개인 vs 기관 대립 종목: 개인이 팔고 기관이 사거나 그 반대인 종목
4. 기관/외국인 동시 매수 종목: 스마트머니 집중 구간
5. 매도 압력 주의 종목: 기관/외국인 동시 이탈 종목

투자 관점에서 가장 주목해야 할 종목과 그 이유를 명확히 제시해주세요.
각 종목은 [종목코드 종목명] 형식으로 표기해주세요."""

    llm = create_llm(temperature=0.3)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("🏦 기관/외국인 에이전트", f"분석 완료:\n{analysis}")

    return {
        "institutional_analysis": analysis,
        "institutional_stocks_raw": investor_data,
        "messages": [AIMessage(content=f"[기관/외국인 분석]: {analysis}", name="institutional_agent")],
    }


def _format_investor_data(data: list[dict]) -> str:
    if not data:
        return "투자자 데이터 없음"
    lines = []
    for s in data:
        inst_net = s.get("institution_net_buy", "0")
        frgn_net = s.get("foreign_net_buy", "0")
        indv_net = s.get("individual_net_buy", "0")

        def sign(v: str) -> str:
            try:
                return f"+{v}" if int(v.replace(",", "")) > 0 else v
            except Exception:
                return v

        lines.append(
            f"■ {s.get('name','')}({s.get('code','')}) {s.get('price','')}원\n"
            f"  기관: {sign(inst_net)}주 ({_fmt_amount(s.get('institution_net_amount','0'))}억)\n"
            f"  외국인: {sign(frgn_net)}주 ({_fmt_amount(s.get('foreign_net_amount','0'))}억)\n"
            f"  개인: {sign(indv_net)}주 ({_fmt_amount(s.get('individual_net_amount','0'))}억)\n"
            f"  신탁: {sign(s.get('trust_net_buy','0'))}주"
        )
    return "\n".join(lines)


def _fmt_amount(v: str) -> str:
    try:
        return f"{int(v.replace(',', '')) // 100_000_000:,}"
    except Exception:
        return v
