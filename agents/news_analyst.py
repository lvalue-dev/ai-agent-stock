"""뉴스/공시 분석 에이전트 - Google News RSS 기반"""
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.news_api import get_market_news, get_stock_news, get_theme_news
from tools.kis_api import get_top_volume_stocks
from utils.llm import create_llm, invoke_with_retry
from utils.logger import log_agent


def news_analyst_node(state: AgentState) -> dict:
    log_agent("📰 뉴스 분석 에이전트", "Google News에서 뉴스 수집 중...")

    market_context = state.get("market_analysis", "")
    screened_stocks = state.get("screened_stocks", [])

    # 1) 시장 전체 뉴스
    market_news = get_market_news(limit=15)

    # 2) 거래량 상위 종목 뉴스
    kospi_top = get_top_volume_stocks("KOSPI", limit=5)
    kosdaq_top = get_top_volume_stocks("KOSDAQ", limit=5)
    candidate_names = {s.get("name", ""): s for s in screened_stocks if s.get("name")}
    for s in kospi_top + kosdaq_top:
        name = s.get("name", "")
        if name and name not in candidate_names and len(candidate_names) < 10:
            candidate_names[name] = s

    stock_news_data = []
    for name, info in list(candidate_names.items())[:8]:
        news = get_stock_news(name, limit=5)
        if news:
            stock_news_data.append({
                "name": name,
                "code": info.get("code", ""),
                "market": info.get("market", ""),
                "news": news,
            })

    # 3) 주요 테마 뉴스
    themes = ["반도체", "AI 인공지능", "2차전지 배터리", "바이오"]
    theme_news_data = []
    for theme in themes:
        items = get_theme_news(theme, limit=3)
        if items:
            theme_news_data.append({"theme": theme, "news": items})

    market_text = _fmt_list(market_news)
    stock_text = _fmt_stock_news(stock_news_data)
    theme_text = _fmt_theme_news(theme_news_data)

    prompt = (
        "당신은 한국 주식시장 전문 뉴스 분석 애널리스트입니다.\n"
        "Google News에서 수집한 최신 뉴스를 심층 분석합니다.\n\n"
        f"[시장 분석 컨텍스트]\n{market_context}\n\n"
        f"[시장 전체 뉴스 ({len(market_news)}건)]\n{market_text}\n\n"
        f"[종목별 뉴스 ({len(stock_news_data)}개 종목)]\n{stock_text}\n\n"
        f"[테마별 뉴스]\n{theme_text}\n\n"
        "다음 항목을 분석해주세요:\n\n"
        "1. 핵심 호재 뉴스\n"
        "   - 실적·계약·신사업·수출 등 긍정 신호 종목 [종목코드 종목명]\n\n"
        "2. 핵심 악재 뉴스\n"
        "   - 실적부진·소송·규제·리콜 등 부정 신호 종목 [종목코드 종목명]\n\n"
        "3. 섹터/테마 분석\n"
        "   - 어느 테마에 뉴스가 집중되는지, 섹터 순환 신호\n\n"
        "4. 뉴스 모멘텀 TOP 3 종목 (이유 포함)\n\n"
        "5. 전체 뉴스 기반 시장 센티멘트\n"
        "   - 긍정/중립/부정 판단 및 근거\n"
        "   - 시장 지수 방향과의 일치 여부"
    )

    llm = create_llm(temperature=0.3)
    response = invoke_with_retry(llm, [HumanMessage(content=prompt)])
    analysis = response.content

    log_agent("📰 뉴스 분석 에이전트", f"분석 완료:\n{analysis}")

    return {
        "news_analysis": analysis,
        "messages": [AIMessage(content=f"[뉴스 분석가]: {analysis}", name="news_analyst")],
    }


def _fmt_list(items: list[dict]) -> str:
    if not items:
        return "뉴스 없음"
    return "\n".join(
        f"  [{i+1}] {n['title']}  ({n['source']}, {n['time'][:16]})"
        for i, n in enumerate(items)
    )


def _fmt_stock_news(data: list[dict]) -> str:
    if not data:
        return "뉴스 없음"
    lines = []
    for item in data:
        lines.append(f"\n▶ {item['name']}({item['code']})")
        for n in item["news"]:
            lines.append(f"   · {n['title']}  [{n['source']}]")
            if n.get("summary"):
                lines.append(f"     {n['summary'][:120]}")
    return "\n".join(lines)


def _fmt_theme_news(data: list[dict]) -> str:
    if not data:
        return "테마 뉴스 없음"
    lines = []
    for item in data:
        lines.append(f"\n[{item['theme']}]")
        for n in item["news"]:
            lines.append(f"   · {n['title']}  [{n['source']}]")
    return "\n".join(lines)
