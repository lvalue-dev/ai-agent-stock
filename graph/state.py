"""LangGraph 공유 상태 정의"""
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # 대화 메시지 히스토리 (add_messages로 누적)
    messages: Annotated[list[BaseMessage], add_messages]

    # 각 에이전트 분석 결과 (텍스트)
    market_analysis: str
    news_analysis: str
    screened_stocks: list[dict]
    screening_analysis: str
    volume_analysis: str
    institutional_analysis: str

    # 차트용 raw 데이터
    volume_stocks_raw: list[dict]       # 거래량 상위 종목 raw (차트용)
    institutional_stocks_raw: list[dict] # 투자자별 순매수 raw (차트용)

    # 토론 관리
    debate_round: int
    debate_log: list[str]
    consensus_reached: bool

    # 실시간 (웹소켓 트리거 모드에서만 채워짐)
    trigger_event: dict              # 트리거 이벤트 {at, signals, codes, stocks, summary, snapshot, focus}
    realtime_snapshot: list[dict]    # 종목별 실시간 요약 (TickBuffer.snapshot)
    realtime_analysis: str

    # 최종 판단
    final_decision: str
    target_stocks: list[dict]
    supervisor_opinion: str
    trade_results: list[dict]
