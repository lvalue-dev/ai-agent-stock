"""거래량 분석 에이전트 - 종목별 거래량 패턴 및 모멘텀 분석"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_top_volume_stocks, get_stock_price, get_daily_volume
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def volume_agent_node(state: AgentState) -> dict:
    log_agent("📈 거래량 분석 에이전트", "거래량 데이터 수집 중...")

    screened_stocks = state.get("screened_stocks", [])

    # 시장 전체 거래량 상위 종목
    kospi_vol = get_top_volume_stocks("KOSPI", limit=15)
    kosdaq_vol = get_top_volume_stocks("KOSDAQ", limit=15)
    all_volume_leaders = kospi_vol + kosdaq_vol

    # 스크리닝된 종목 + 거래량 상위 종목 중 최대 8개 상세 분석
    detail_targets = {s["code"]: s for s in screened_stocks if s.get("code")}
    for s in all_volume_leaders[:10]:
        code = s.get("code", "")
        if code and code not in detail_targets and len(detail_targets) < 8:
            detail_targets[code] = s

    detailed = []
    for code, base_info in detail_targets.items():
        try:
            price_info = get_stock_price(code)
            daily = get_daily_volume(code, days=10)
            detailed.append({
                **base_info,
                **price_info,
                "daily_history": daily,
            })
        except Exception:
            pass

    volume_leaders_text = _format_volume_leaders(kospi_vol[:10], kosdaq_vol[:10])
    detail_text = _format_detail(detailed)

    prompt = f"""당신은 거래량 분석 전문 퀀트 애널리스트입니다.
거래량 패턴과 모멘텀을 분석하여 투자 신호를 도출합니다.

[시장 전체 거래량 상위 종목]
{volume_leaders_text}

[스크리닝 후보 + 거래량 상위 종목 상세 분석]
{detail_text}

다음 항목을 분석해주세요:
1. 거래량 급증 종목: 평소 대비 거래량이 비정상적으로 증가한 종목과 원인 추정
2. 거래량 모멘텀: 최근 10일 거래량 추이로 보는 매집/분산 신호
3. 거래대금 집중도: 어느 시장/섹터에 자금이 몰리는지
4. 주의 종목: 거래량 대비 주가 움직임이 이상한 종목 (펌핑 등)
5. 거래량 기준 매수/매도 유망 종목 TOP 3

각 종목은 [종목코드 종목명] 형식으로 표기해주세요."""

    llm = create_llm(temperature=0.3)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("📈 거래량 분석 에이전트", f"분석 완료:\n{analysis}")

    # raw 데이터: 차트용 (거래량 상위 전체 목록)
    volume_raw = []
    for s in all_volume_leaders[:20]:
        volume_raw.append({
            "name": s.get("name", ""),
            "code": s.get("code", ""),
            "volume": s.get("volume", "0"),
            "volume_rate": s.get("volume_rate", "0"),
            "change_rate": s.get("change_rate", "0"),
            "price": s.get("price", "0"),
            "market": "KOSPI" if s in kospi_vol else "KOSDAQ",
        })

    return {
        "volume_analysis": analysis,
        "volume_stocks_raw": volume_raw,
        "messages": [AIMessage(content=f"[거래량 분석]: {analysis}", name="volume_agent")],
    }


def _format_volume_leaders(kospi: list[dict], kosdaq: list[dict]) -> str:
    def row(s: dict) -> str:
        rank = s.get("rank", "")
        return (
            f"  {rank}위 {s.get('name','')}({s.get('code','')}) "
            f"{s.get('price','')}원 ({s.get('change_rate','')}%) "
            f"거래량:{s.get('volume','')} 증감:{s.get('volume_rate','')}%"
        )

    lines = ["▶ KOSPI 거래량 상위"] + [row(s) for s in kospi]
    lines += ["▶ KOSDAQ 거래량 상위"] + [row(s) for s in kosdaq]
    return "\n".join(lines)


def _format_detail(stocks: list[dict]) -> str:
    if not stocks:
        return "상세 데이터 없음"
    lines = []
    for s in stocks:
        history = s.get("daily_history", [])
        vol_trend = " → ".join(
            f"{d.get('date','')[4:8]}:{int(d.get('volume','0').replace(',',''))//10000}만"
            for d in history[:5] if d.get("volume")
        )
        lines.append(
            f"■ {s.get('name','')}({s.get('code','')})\n"
            f"  현재가: {s.get('price','')}원 | 등락: {s.get('change_rate','')}%\n"
            f"  당일거래량: {s.get('volume','')} | 거래량증감: {s.get('volume_rate','')}%\n"
            f"  5일 거래량 추이: {vol_trend if vol_trend else '데이터없음'}\n"
            f"  시가총액: {s.get('market_cap','')}억 | PER: {s.get('per','')} | PBR: {s.get('pbr','')}"
        )
    return "\n".join(lines)
