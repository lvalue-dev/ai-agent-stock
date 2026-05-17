"""수퍼바이저 에이전트 - 토론 진행 및 최종 의사결정"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from config import MAX_DEBATE_ROUNDS
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def _all_analyses(state: AgentState) -> str:
    return (
        f"[📊 시장 분석가]\n{state.get('market_analysis', '분석 없음')}\n\n"
        f"[📰 뉴스 분석가]\n{state.get('news_analysis', '분석 없음')}\n\n"
        f"[🔍 스크리닝 에이전트]\n{state.get('screening_analysis', '분석 없음')}\n\n"
        f"[📈 거래량 분석가]\n{state.get('volume_analysis', '분석 없음')}\n\n"
        f"[🏦 기관/외국인 분석가]\n{state.get('institutional_analysis', '분석 없음')}"
    )


def supervisor_node(state: AgentState) -> dict:
    round_num = state.get("debate_round", 0)
    debate_log = state.get("debate_log", [])

    log_agent("🎯 수퍼바이저", f"토론 라운드 {round_num + 1} 시작...")

    analyses = _all_analyses(state)

    if round_num == 0:
        prompt = (
            "당신은 한국 주식 투자팀의 수석 투자 전략가입니다.\n"
            "5명의 전문가 에이전트(시장분석, 뉴스, 스크리닝, 거래량, 기관/외국인)의 분석을 검토하고 토론을 이끕니다.\n\n"
            + analyses +
            "\n\n각 전문가의 의견을 종합하여 다음을 수행해주세요:\n"
            "1. 5개 에이전트 의견의 핵심 공통점과 차이점\n"
            "2. 에이전트 간 의견이 충돌하는 지점 (예: 뉴스는 긍정인데 기관은 매도)\n"
            "3. 추가 논의가 필요한 핵심 쟁점 2-3가지\n"
            "4. 1차 종합 투자 방향 (매수 우호/비우호/중립)\n\n"
            "이후 토론에서 각 에이전트가 반드시 답해야 할 질문을 에이전트별로 제시해주세요."
        )

    elif round_num < MAX_DEBATE_ROUNDS - 1:
        prev = "\n".join(debate_log[-4:]) if debate_log else ""
        prompt = (
            f"[이전 토론]\n{prev}\n\n"
            f"[전체 분석 자료]\n{analyses}\n\n"
            f"토론 라운드 {round_num + 1}입니다. 이전 토론을 바탕으로:\n"
            "1. 각 에이전트의 입장 변화 또는 고수 여부\n"
            "2. 아직 해소되지 않은 핵심 불확실성\n"
            "3. 데이터 간 상충되는 신호 (예: 거래량↑ 인데 기관 순매도)\n"
            "4. 컨센서스 수렴 정도 평가 (0-100%)\n\n"
            "컨센서스가 70% 이상이면 최종 결정 단계로 전환합니다.\n"
            "각 에이전트에게 추가로 확인할 사항을 구체적으로 요청해주세요."
        )

    else:
        all_log = "\n".join(debate_log) if debate_log else ""
        prompt = (
            f"[전체 토론 기록]\n{all_log}\n\n"
            f"[최종 분석 자료]\n{analyses}\n\n"
            "모든 토론을 종합하여 최종 투자 결정을 내려주세요:\n\n"
            "최종 결정 형식:\n"
            "1. 결정: [매수/매도/관망]\n"
            "2. 핵심 근거 (에이전트별 1줄 요약):\n"
            "   - 시장: ...\n"
            "   - 뉴스: ...\n"
            "   - 스크리닝: ...\n"
            "   - 거래량: ...\n"
            "   - 기관/외국인: ...\n"
            "3. 대상 종목: (매수/매도인 경우 종목코드와 종목명)\n"
            "4. 리스크 요인\n"
            "5. 신뢰도: [높음/보통/낮음]\n\n"
            "반드시 \"최종결정:\" 으로 시작하는 줄에 결정 내용을 명확히 표시해주세요."
        )

    llm = create_llm(temperature=0.5)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    opinion = response.content

    new_log = debate_log + [f"[수퍼바이저 라운드 {round_num + 1}]\n{opinion}"]

    is_last = round_num >= MAX_DEBATE_ROUNDS - 1
    consensus_kw = ["최종결정:", "컨센서스 달성", "의견 일치", "70% 이상"]
    consensus_reached = is_last or any(kw in opinion for kw in consensus_kw)

    log_agent("🎯 수퍼바이저", f"라운드 {round_num + 1} 완료. 컨센서스: {consensus_reached}")

    return {
        "supervisor_opinion": opinion,
        "debate_round": round_num + 1,
        "debate_log": new_log,
        "consensus_reached": consensus_reached,
        "messages": [AIMessage(content=f"[수퍼바이저 라운드 {round_num + 1}]: {opinion}", name="supervisor")],
    }


def debate_agent_node(state: AgentState) -> dict:
    """5개 전문가 에이전트가 각자의 분석 근거로 수퍼바이저 질문에 답변"""
    round_num = state.get("debate_round", 1)
    debate_log = state.get("debate_log", [])
    supervisor_opinion = state.get("supervisor_opinion", "")

    log_agent("💬 토론 에이전트들", f"라운드 {round_num} 토론 응답 중...")

    analyses = _all_analyses(state)

    prompt = (
        "다음은 한국 주식 투자 전문가 토론 세션입니다.\n"
        "수퍼바이저의 요청에 5명의 전문가가 각자의 분석 데이터를 근거로 입장을 밝힙니다.\n\n"
        f"[수퍼바이저 요청]\n{supervisor_opinion}\n\n"
        f"[각 에이전트의 분석 데이터]\n{analyses}\n\n"
        "5명의 전문가가 각자의 고유 분석 데이터를 근거로 답변합니다.\n"
        "다른 에이전트 의견에 동의/반론할 때는 구체적 데이터를 인용해주세요.\n\n"
        "형식 (각 50-100자):\n"
        "[📊 시장분석가]: (시장 데이터 기반 답변)\n"
        "[📰 뉴스분석가]: (뉴스/공시 데이터 기반 답변)\n"
        "[🔍 스크리닝에이전트]: (종목 스크리닝 데이터 기반 답변)\n"
        "[📈 거래량분석가]: (거래량 패턴 기반 답변)\n"
        "[🏦 기관/외국인분석가]: (기관·외국인 매매동향 기반 답변)"
    )

    llm = create_llm(temperature=0.6)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    debate_response = response.content

    new_log = debate_log + [f"[에이전트 토론 라운드 {round_num}]\n{debate_response}"]

    log_agent("💬 토론 에이전트들", "토론 응답 완료")

    return {
        "debate_log": new_log,
        "messages": [AIMessage(content=f"[에이전트 토론 라운드 {round_num}]: {debate_response}", name="debate_agents")],
    }


def make_final_decision(state: AgentState) -> dict:
    """최종 투자 결정 및 대상 종목 확정"""
    supervisor_opinion = state.get("supervisor_opinion", "")
    screened_stocks = state.get("screened_stocks", [])

    decision = "관망"
    if "매수" in supervisor_opinion:
        decision = "매수"
    elif "매도" in supervisor_opinion:
        decision = "매도"

    target_stocks = []
    if decision == "매수" and screened_stocks:
        target_stocks = screened_stocks[:3]

    log_agent("✅ 최종 결정", f"결정: {decision} | 대상 종목: {len(target_stocks)}개")

    return {
        "final_decision": decision,
        "target_stocks": target_stocks,
        "messages": [
            AIMessage(
                content=f"[최종 결정]: {decision} | 대상: {[s.get('name', '') for s in target_stocks]}",
                name="final_decision",
            )
        ],
    }
