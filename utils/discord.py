"""Discord Webhook으로 분석 결과 전송"""
import requests
from datetime import datetime
from config import DISCORD_WEBHOOK_URL


def send_report(state: dict) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    final_decision = state.get("final_decision", "N/A")
    target_stocks = state.get("target_stocks", [])
    trade_results = state.get("trade_results", [])

    decision_color = {"매수": 0x2ECC71, "매도": 0xE74C3C}.get(final_decision, 0x95A5A6)

    targets_text = (
        "\n".join(f"• {t.get('name', '')}({t.get('code', '')}) {t.get('price', '')}원" for t in target_stocks)
        if target_stocks else "없음"
    )

    trade_text = _format_trade_results(trade_results)
    market_analysis = _truncate(state.get("market_analysis", "N/A"), 500)
    news_analysis = _truncate(state.get("news_analysis", "N/A"), 500)
    screening_analysis = _truncate(state.get("screening_analysis", "N/A"), 500)

    payload = {
        "username": "주식 분석 에이전트",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2910/2910791.png",
        "embeds": [
            {
                "title": f"📊 한국 주식 멀티 에이전트 분석 보고서",
                "description": f"분석 시각: {now}",
                "color": decision_color,
                "fields": [
                    {"name": "✅ 최종 결정", "value": f"**{final_decision}**", "inline": True},
                    {"name": "🎯 대상 종목", "value": targets_text, "inline": True},
                    {"name": "📊 시장 분석", "value": market_analysis, "inline": False},
                    {"name": "📰 뉴스 분석", "value": news_analysis, "inline": False},
                    {"name": "🔍 종목 스크리닝", "value": screening_analysis, "inline": False},
                    {"name": "💹 매매 실행 결과", "value": trade_text, "inline": False},
                ],
                "footer": {"text": "한국 주식 멀티 에이전트 시스템"},
            }
        ],
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  ⚠️  Discord 전송 실패: {e}")
        return False


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _format_trade_results(results: list[dict]) -> str:
    if not results:
        return "매매 없음 (관망)"
    lines = []
    for r in results:
        if r.get("mode") == "simulation":
            lines.append(f"[시뮬레이션] {r.get('action', '')} {r.get('name', '')}({r.get('code', '')})")
        else:
            status = "성공" if r.get("success") else "실패"
            lines.append(f"[{status}] {r.get('name', '')}({r.get('stock_code', '')}) {r.get('quantity', '')}주")
    return "\n".join(lines)
