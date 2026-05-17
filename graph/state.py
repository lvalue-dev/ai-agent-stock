"""LangGraph 공유 상태 정의"""
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # 대화 메시지 히스토리 (add_messages로 누적)
    messages: Annotated[list[BaseMessage], add_messages]

    # 각 에이전트 분석 결과
    market_analysis: str        # 시장 분석 에이전트 결과
    news_analysis: str          # 뉴스 분석 에이전트 결과
    screened_stocks: list[dict] # 스크리닝된 종목 목록
    screening_analysis: str     # 스크리닝 에이전트 의견

    # 토론 관리
    debate_round: int           # 현재 토론 라운드
    debate_log: list[str]       # 토론 기록
    consensus_reached: bool     # 컨센서스 달성 여부

    # 최종 판단
    final_decision: str         # 매수/매도/관망
    target_stocks: list[dict]   # 최종 선택 종목
    supervisor_opinion: str     # 수퍼바이저 최종 의견

    # 매매 결과
    trade_results: list[dict]   # 실행된 주문 결과
