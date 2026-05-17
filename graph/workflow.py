"""LangGraph 멀티 에이전트 워크플로우 정의"""
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from agents import (
    market_analyst_node,
    news_analyst_node,
    stock_screener_node,
    supervisor_node,
    debate_agent_node,
    make_final_decision,
    trading_agent_node,
)
from config import MAX_DEBATE_ROUNDS


def should_continue_debate(state: AgentState) -> str:
    """토론 계속 여부 결정"""
    debate_round = state.get("debate_round", 0)
    consensus_reached = state.get("consensus_reached", False)

    if consensus_reached or debate_round >= MAX_DEBATE_ROUNDS:
        return "finalize"
    return "debate"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node("market_analyst", market_analyst_node)
    graph.add_node("news_analyst", news_analyst_node)
    graph.add_node("stock_screener", stock_screener_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("debate_agents", debate_agent_node)
    graph.add_node("finalize", make_final_decision)
    graph.add_node("trading_agent", trading_agent_node)

    # 시작점: 시장 분석
    graph.set_entry_point("market_analyst")

    # 순차 분석: 시장분석 → 뉴스분석 → 스크리닝
    graph.add_edge("market_analyst", "news_analyst")
    graph.add_edge("news_analyst", "stock_screener")

    # 스크리닝 완료 후 수퍼바이저 토론 시작
    graph.add_edge("stock_screener", "supervisor")

    # 수퍼바이저 → 토론 계속 or 최종화
    graph.add_conditional_edges(
        "supervisor",
        should_continue_debate,
        {
            "debate": "debate_agents",
            "finalize": "finalize",
        },
    )

    # 에이전트 토론 후 다시 수퍼바이저
    graph.add_edge("debate_agents", "supervisor")

    # 최종화 → 매매 에이전트 → 종료
    graph.add_edge("finalize", "trading_agent")
    graph.add_edge("trading_agent", END)

    return graph.compile()


def get_initial_state() -> AgentState:
    return {
        "messages": [],
        "market_analysis": "",
        "news_analysis": "",
        "screened_stocks": [],
        "screening_analysis": "",
        "debate_round": 0,
        "debate_log": [],
        "consensus_reached": False,
        "final_decision": "관망",
        "target_stocks": [],
        "supervisor_opinion": "",
        "trade_results": [],
    }
