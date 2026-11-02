"""실시간 분석 에이전트 - 웹소켓 체결/호가 데이터와 트리거 신호 해석

정기(1회) 분석에서는 실시간 데이터가 없으므로 LLM 호출 없이 통과한다.
"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def realtime_agent_node(state: AgentState) -> dict:
    event = state.get("trigger_event", {}) or {}
    snapshot = state.get("realtime_snapshot", []) or []

    if not event and not snapshot:
        log_agent("⚡ 실시간 에이전트", "실시간 데이터 없음 - 건너뜀")
        return {"realtime_analysis": ""}

    log_agent("⚡ 실시간 에이전트", f"신호 {len(event.get('signals', []))}건, 스냅샷 {len(snapshot)}종목 분석 중...")

    signals_text = _format_signals(event.get("signals", []))
    focus_text = _format_rows(event.get("focus", []) or [], detailed=True)
    snapshot_text = _format_rows(snapshot, detailed=False)

    prompt = f"""당신은 한국 주식 실시간 체결 데이터를 읽는 단기 트레이딩 애널리스트입니다.
웹소켓으로 수신한 체결가·거래량·체결강도·호가 데이터와 규칙 기반 신호를 해석합니다.

[발생 시각] {event.get('at', '')}

[감지된 신호]
{signals_text}

[신호 종목 실시간 상세]
{focus_text}

[감시 종목 실시간 스냅샷 (5분 변동 순)]
{snapshot_text}

지표 설명: pct_1m/pct_5m=최근 1분/5분 가격 변동(%), vol_ratio_1m=1분 거래량/평균 1분 거래량,
strength=체결강도(100 초과 시 매수 우위), buy_ratio_5m=5분 매수체결 비중(%),
imbalance=매수잔량/매도잔량, same_time_vol_rate=전일 동시간 대비 누적거래량(%).

다음을 분석해주세요:
1. 신호의 성격: 실제 수급 유입인지, 단발성 체결(펌핑·착시)인지 판단과 근거
2. 신호 종목별 단기 방향성 (추세 지속/되돌림/판단 보류)과 핵심 수치
3. 호가·체결강도로 본 매수/매도 압력
4. 리스크: 급등 후 거래량 소멸, 호가 공백, 거래정지 가능성 등
5. 지금 당장 관심을 둘 종목 TOP 3 와 진입/관망 의견 (각 1줄)

각 종목은 [종목코드 종목명] 형식으로 표기하고 300자 내외로 답해주세요."""

    llm = create_llm(temperature=0.3)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("⚡ 실시간 에이전트", f"분석 완료:\n{analysis}")

    return {
        "realtime_analysis": analysis,
        "messages": [AIMessage(content=f"[실시간 분석]: {analysis}", name="realtime_agent")],
    }


def _format_signals(signals: list[dict]) -> str:
    if not signals:
        return "없음"
    return "\n".join(
        f"  • [{s.get('label', s.get('kind', ''))}] {s.get('message', '')} (강도 {s.get('score', 0)})"
        for s in signals[:10]
    )


def _format_rows(rows: list[dict], detailed: bool) -> str:
    rows = [r for r in rows if r]
    if not rows:
        return "데이터 없음"
    lines = []
    for r in rows[:15]:
        head = (
            f"■ {r.get('name', '')}({r.get('code', '')}) {r.get('price', 0):,}원 "
            f"전일比 {r.get('change_rate', 0):+.2f}% | 1분 {r.get('pct_1m', 0):+.2f}% | 5분 {r.get('pct_5m', 0):+.2f}%"
        )
        if not detailed:
            lines.append(head + f" | 거래량비 {r.get('vol_ratio_1m', 0):.1f}x | 체결강도 {r.get('strength', 0):.0f}")
            continue
        lines.append(
            head + "\n"
            f"  1분 거래량 {r.get('vol_1m', 0):,} (평균 {r.get('avg_vol_per_min', 0):,.0f}/분, {r.get('vol_ratio_1m', 0):.1f}x) "
            f"| 5분 거래량 {r.get('vol_5m', 0):,} | 누적 {r.get('acc_volume', 0):,}\n"
            f"  체결강도 {r.get('strength', 0):.0f} | 5분 매수비중 {r.get('buy_ratio_5m', 0):.0f}% "
            f"| 호가 불균형 {r.get('imbalance', 0):.2f} | 매도1 {r.get('ask1', 0):,} / 매수1 {r.get('bid1', 0):,}\n"
            f"  당일 고/저 {r.get('high', 0):,}/{r.get('low', 0):,} | 5분 고/저 {r.get('high_5m', 0):,}/{r.get('low_5m', 0):,} "
            f"| 전일 동시간 대비 거래량 {r.get('same_time_vol_rate', 0):.0f}%"
        )
    return "\n".join(lines)
