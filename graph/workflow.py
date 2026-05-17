"""LangGraph 멀티 에이전트 워크플로우 정의"""
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from agents import (
    market_analyst_node,
    news_analyst_node,
    stock_screener_node,
    volume_agent_node,
    institutional_agent_node,
    supervisor_node,
    debate_agent_node,
    make_final_decision,
)
from config import MAX_DEBATE_ROUNDS


def should_continue_debate(state: AgentState) -> str:
    debate_round = state.get("debate_round", 0)
    consensus_reached = state.get("consensus_reached", False)
    if consensus_reached or debate_round >= MAX_DEBATE_ROUNDS:
        return "finalize"
    return "debate"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("market_analyst", market_analyst_node)
    graph.add_node("news_analyst", news_analyst_node)
    graph.add_node("stock_screener", stock_screener_node)
    graph.add_node("volume_agent", volume_agent_node)
    graph.add_node("institutional_agent", institutional_agent_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("debate_agents", debate_agent_node)
    graph.add_node("finalize", make_final_decision)

    graph.set_entry_point("market_analyst")

    graph.add_edge("market_analyst", "news_analyst")
    graph.add_edge("news_analyst", "stock_screener")
    graph.add_edge("stock_screener", "volume_agent")
    graph.add_edge("volume_agent", "institutional_agent")
    graph.add_edge("institutional_agent", "supervisor")

    graph.add_conditional_edges(
        "supervisor",
        should_continue_debate,
        {"debate": "debate_agents", "finalize": "finalize"},
    )

    graph.add_edge("debate_agents", "supervisor")
    graph.add_edge("finalize", END)

    return graph.compile()


def get_initial_state() -> AgentState:
    return {
        "messages": [],
        "market_analysis": "",
        "news_analysis": "",
        "screened_stocks": [],
        "screening_analysis": "",
        "volume_analysis": "",
        "institutional_analysis": "",
        "volume_stocks_raw": [],
        "institutional_stocks_raw": [],
        "debate_round": 0,
        "debate_log": [],
        "consensus_reached": False,
        "final_decision": "관망",
        "target_stocks": [],
        "supervisor_opinion": "",
    }
