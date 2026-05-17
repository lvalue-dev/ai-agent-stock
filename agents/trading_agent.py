"""매매 실행 에이전트 - 최종 결정에 따른 주문 실행"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from graph.state import AgentState
from tools.kis_api import get_account_balance, get_stock_price, place_order
from config import GOOGLE_API_KEY, GEMINI_MODEL, AUTO_TRADE_ENABLED, MAX_TRADE_AMOUNT
from utils.logger import log_agent


def trading_agent_node(state: AgentState) -> dict:
    final_decision = state.get("final_decision", "관망")
    target_stocks = state.get("target_stocks", [])

    log_agent("💹 매매 에이전트", f"최종 결정: {final_decision}")

    if final_decision == "관망" or not target_stocks:
        log_agent("💹 매매 에이전트", "관망 결정 - 매매 없음")
        return {
            "trade_results": [],
            "messages": [AIMessage(content="[매매 에이전트]: 관망 결정으로 매매를 실행하지 않습니다.", name="trading_agent")],
        }

    try:
        balance = get_account_balance()
        available_cash = int(balance.get("available_cash", "0").replace(",", ""))
        holdings = balance.get("holdings", [])
    except Exception as e:
        log_agent("💹 매매 에이전트", f"계좌 조회 실패: {e}")
        available_cash = 0
        holdings = []

    trade_results = []

    if final_decision == "매수":
        trade_results = _execute_buy(target_stocks, available_cash)
    elif final_decision == "매도":
        trade_results = _execute_sell(holdings)

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.2,
    )

    result_text = _format_trade_results(trade_results)
    prompt = f"""다음 매매 실행 결과를 간결하게 요약해주세요:

결정: {final_decision}
실행 결과: {result_text}

투자자에게 전달할 매매 실행 요약 (100자 이내):"""

    response = llm.invoke([HumanMessage(content=prompt)])
    summary = response.content

    log_agent("💹 매매 에이전트", f"매매 완료:\n{summary}")

    return {
        "trade_results": trade_results,
        "messages": [AIMessage(content=f"[매매 에이전트]: {summary}", name="trading_agent")],
    }


def _execute_buy(target_stocks: list[dict], available_cash: int) -> list[dict]:
    results = []
    if not AUTO_TRADE_ENABLED:
        for stock in target_stocks:
            results.append({
                "mode": "simulation",
                "action": "매수",
                "code": stock.get("code", ""),
                "name": stock.get("name", ""),
                "message": "AUTO_TRADE_ENABLED=false 로 실제 매매 미실행 (시뮬레이션)",
            })
        return results

    per_stock_budget = min(MAX_TRADE_AMOUNT, available_cash // max(len(target_stocks), 1))

    for stock in target_stocks:
        code = stock.get("code", "")
        if not code:
            continue
        try:
            price_info = get_stock_price(code)
            current_price = int(price_info.get("price", "0").replace(",", ""))
            if current_price <= 0:
                continue
            quantity = per_stock_budget // current_price
            if quantity < 1:
                continue
            result = place_order(code, "buy", quantity, 0)  # 시장가 매수
            result["name"] = stock.get("name", "")
            results.append(result)
        except Exception as e:
            results.append({
                "success": False,
                "code": code,
                "name": stock.get("name", ""),
                "message": str(e),
            })
    return results


def _execute_sell(holdings: list[dict]) -> list[dict]:
    results = []
    if not AUTO_TRADE_ENABLED:
        for h in holdings:
            results.append({
                "mode": "simulation",
                "action": "매도",
                "code": h.get("code", ""),
                "name": h.get("name", ""),
                "message": "AUTO_TRADE_ENABLED=false 로 실제 매매 미실행 (시뮬레이션)",
            })
        return results

    for holding in holdings:
        code = holding.get("code", "")
        qty = int(holding.get("quantity", "0").replace(",", ""))
        if not code or qty < 1:
            continue
        try:
            result = place_order(code, "sell", qty, 0)  # 시장가 매도
            result["name"] = holding.get("name", "")
            results.append(result)
        except Exception as e:
            results.append({
                "success": False,
                "code": code,
                "name": holding.get("name", ""),
                "message": str(e),
            })
    return results


def _format_trade_results(results: list[dict]) -> str:
    if not results:
        return "실행된 거래 없음"
    lines = []
    for r in results:
        mode = r.get("mode", "")
        if mode == "simulation":
            lines.append(f"  [시뮬레이션] {r.get('action', '')} {r.get('name', '')}({r.get('code', '')})")
        else:
            status = "성공" if r.get("success") else "실패"
            lines.append(
                f"  [{status}] {r.get('order_type', '')} {r.get('name', '')}({r.get('stock_code', '')}) "
                f"{r.get('quantity', '')}주 - {r.get('message', '')}"
            )
    return "\n".join(lines)
