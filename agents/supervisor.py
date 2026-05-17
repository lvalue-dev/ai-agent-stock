"""수퍼바이저 에이전트 - 토론 진행 및 최종 의사결정"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from config import GOOGLE_API_KEY, GEMINI_MODEL, MAX_DEBATE_ROUNDS
from utils.logger import log_agent


def supervisor_node(state: AgentState) -> dict:
    round_num = state.get("debate_round", 0)
    debate_log = state.get("debate_log", [])

    log_agent("🎯 수퍼바이저", f"토론 라운드 {round_num + 1} 시작...")

    market_analysis = state.get("market_analysis", "")
    news_analysis = state.get("news_analysis", "")
    screening_analysis = state.get("screening_analysis", "")

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.5,
    )

    if round_num == 0:
        prompt = f"""당신은 한국 주식 투자팀의 수석 투자 전략가입니다.
각 전문가 에이전트의 분석을 검토하고 토론을 이끌어 최선의 투자 결정을 내립니다.

[시장 분석가 의견]
{market_analysis}

[뉴스 분석가 의견]
{news_analysis}

[종목 스크리닝 에이전트 의견]
{screening_analysis}

각 전문가의 의견을 종합하여 다음을 수행해주세요:
1. 세 에이전트 의견의 핵심 공통점과 차이점 파악
2. 현재 쟁점이 되는 부분 (의견이 충돌하거나 불확실한 부분)
3. 추가로 검토가 필요한 사항
4. 1차 종합 의견 (매수 우호/비우호/중립)

이후 토론에서 각 에이전트가 반드시 답해야 할 핵심 질문을 2-3개 제시해주세요."""

    elif round_num < MAX_DEBATE_ROUNDS - 1:
        prev_debate = "\n".join(debate_log[-3:]) if debate_log else ""
        prompt = f"""[이전 토론 내용]
{prev_debate}

[시장 분석]
{market_analysis}

[뉴스 분석]
{news_analysis}

[스크리닝 결과]
{screening_analysis}

토론 라운드 {round_num + 1}입니다. 이전 토론을 바탕으로:
1. 제기된 쟁점들이 충분히 논의되었는지 평가
2. 아직 해소되지 않은 불확실성
3. 컨센서스 형성 여부 판단
4. 추가 토론이 필요한 핵심 포인트

현재 의견 수렴 정도를 0-100%로 표현하고, 컨센서스가 70% 이상이면 최종 결정으로 넘어갑니다."""

    else:
        all_debate = "\n".join(debate_log) if debate_log else ""
        prompt = f"""[전체 토론 기록]
{all_debate}

[최종 분석 자료]
시장분석: {market_analysis}
뉴스분석: {news_analysis}
종목스크리닝: {screening_analysis}

모든 토론을 종합하여 최종 투자 결정을 내려주세요:

최종 결정 형식:
1. 결정: [매수/매도/관망]
2. 근거: (핵심 이유 3가지)
3. 대상 종목: (매수/매도인 경우 종목코드와 종목명)
4. 리스크: (주요 리스크 요인)
5. 신뢰도: [높음/보통/낮음]

반드시 "최종결정:" 으로 시작하는 줄에 결정 내용을 명확히 표시해주세요."""

    response = llm.invoke([HumanMessage(content=prompt)])
    opinion = response.content

    new_debate_log = debate_log + [f"[수퍼바이저 라운드 {round_num + 1}]: {opinion}"]

    is_last_round = round_num >= MAX_DEBATE_ROUNDS - 1
    consensus_keywords = ["최종결정:", "컨센서스 달성", "의견 일치", "70% 이상"]
    consensus_reached = is_last_round or any(kw in opinion for kw in consensus_keywords)

    log_agent("🎯 수퍼바이저", f"라운드 {round_num + 1} 완료. 컨센서스: {consensus_reached}")

    return {
        "supervisor_opinion": opinion,
        "debate_round": round_num + 1,
        "debate_log": new_debate_log,
        "consensus_reached": consensus_reached,
        "messages": [AIMessage(content=f"[수퍼바이저 라운드 {round_num + 1}]: {opinion}", name="supervisor")],
    }


def debate_agent_node(state: AgentState) -> dict:
    """토론 라운드에서 각 전문가 에이전트가 수퍼바이저 질문에 답변"""
    round_num = state.get("debate_round", 1)
    debate_log = state.get("debate_log", [])
    supervisor_opinion = state.get("supervisor_opinion", "")

    log_agent("💬 토론 에이전트들", f"라운드 {round_num} 토론 응답 중...")

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.6,
    )

    market_analysis = state.get("market_analysis", "")
    news_analysis = state.get("news_analysis", "")
    screening_analysis = state.get("screening_analysis", "")

    prompt = f"""다음은 투자 전문가 토론 세션입니다.
수퍼바이저의 질문에 각 전문가 에이전트가 입장을 밝힙니다.

[수퍼바이저 질문/요청]
{supervisor_opinion}

[보유 분석 자료]
- 시장 분석: {market_analysis}
- 뉴스 분석: {news_analysis}
- 스크리닝: {screening_analysis}

세 전문가(시장분석가, 뉴스분석가, 스크리닝 에이전트)의 입장을 각각 대변하여:
1. 수퍼바이저 질문에 대한 각자의 답변
2. 다른 에이전트 의견에 대한 동의/반론
3. 자신의 분석 관점에서 보완해야 할 점

형식:
[시장분석가]: (답변)
[뉴스분석가]: (답변)
[스크리닝에이전트]: (답변)

각 답변은 50-100자 이내로 간결하게 작성해주세요."""

    response = llm.invoke([HumanMessage(content=prompt)])
    debate_response = response.content

    new_debate_log = debate_log + [f"[에이전트 토론 라운드 {round_num}]: {debate_response}"]

    log_agent("💬 토론 에이전트들", "토론 응답 완료")

    return {
        "debate_log": new_debate_log,
        "messages": [AIMessage(content=f"[에이전트 토론]: {debate_response}", name="debate_agents")],
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
