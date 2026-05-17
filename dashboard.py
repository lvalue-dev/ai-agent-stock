"""한국 주식 멀티 에이전트 Streamlit 대시보드"""
import streamlit as st
from datetime import datetime
from graph.workflow import build_graph, get_initial_state
from config import (
    LLM_PROVIDER, KIS_MODE, AUTO_TRADE_ENABLED,
    MAX_DEBATE_ROUNDS, DISCORD_WEBHOOK_URL,
)
from utils.discord import send_report

st.set_page_config(
    page_title="한국 주식 멀티 에이전트",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.4rem; }
.stTabs [data-baseweb="tab"] { font-size: 0.95rem; }
</style>
""", unsafe_allow_html=True)

# ── 사이드바 ────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 시스템 설정")
    st.divider()

    c1, c2 = st.columns(2)
    c1.metric("LLM", LLM_PROVIDER.upper())
    c2.metric("KIS", "실전" if KIS_MODE == "real" else "모의")
    c1.metric("토론", f"{MAX_DEBATE_ROUNDS}R")
    c2.metric("자동매매", "ON" if AUTO_TRADE_ENABLED else "OFF")

    st.divider()
    st.caption("에이전트 파이프라인")
    for emoji, name, desc in [
        ("📊", "시장 분석", "KOSPI/KOSDAQ 흐름"),
        ("📰", "뉴스 분석", "뉴스/공시 심층 분석"),
        ("🔍", "스크리닝", "유망 종목 발굴"),
        ("📈", "거래량 분석", "거래량 패턴/모멘텀"),
        ("🏦", "기관/외국인", "스마트머니 동향"),
        ("🎯", "수퍼바이저", "5자 토론 진행/결정"),
        ("💹", "매매 실행", "주문 처리"),
    ]:
        st.markdown(f"{emoji} **{name}** — _{desc}_")

    st.divider()
    if DISCORD_WEBHOOK_URL:
        st.success("Discord 연동 활성화")
    else:
        st.caption("Discord 미연동 (.env 설정)")

# ── 메인 ────────────────────────────────────────────────────────────
st.title("📈 한국 주식 멀티 에이전트 대시보드")

# 세션 초기화
for key, default in [("results", None), ("messages", []), ("ran_at", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── 에이전트 메타 ────────────────────────────────────────────────────
AGENT_META = {
    "market_analyst":      ("📊", "시장 분석 에이전트"),
    "news_analyst":        ("📰", "뉴스 분석 에이전트"),
    "stock_screener":      ("🔍", "스크리닝 에이전트"),
    "volume_agent":        ("📈", "거래량 분석 에이전트"),
    "institutional_agent": ("🏦", "기관/외국인 분석 에이전트"),
    "supervisor":          ("🎯", "수퍼바이저"),
    "debate_agents":       ("💬", "토론 에이전트"),
    "finalize":            ("✅", "최종 결정"),
    "trading_agent":       ("💹", "매매 실행 에이전트"),
}


def _node_content(node_name: str, state: dict) -> str:
    if node_name == "market_analyst":
        return state.get("market_analysis", "")
    if node_name == "news_analyst":
        return state.get("news_analysis", "")
    if node_name == "stock_screener":
        return state.get("screening_analysis", "")
    if node_name == "volume_agent":
        return state.get("volume_analysis", "")
    if node_name == "institutional_agent":
        return state.get("institutional_analysis", "")
    if node_name == "supervisor":
        return state.get("supervisor_opinion", "")
    if node_name == "debate_agents":
        log = state.get("debate_log", [])
        return log[-1] if log else ""
    if node_name == "finalize":
        decision = state.get("final_decision", "관망")
        targets = state.get("target_stocks", [])
        names = " | ".join(f"{t.get('name','')}({t.get('code','')})" for t in targets)
        return f"**최종 결정: {decision}**" + (f"\n대상: {names}" if names else "")
    if node_name == "trading_agent":
        results = state.get("trade_results", [])
        if not results:
            return "관망 결정 — 매매 없음"
        lines = []
        for r in results:
            if r.get("mode") == "simulation":
                lines.append(f"[시뮬레이션] {r.get('action','')} {r.get('name','')}({r.get('code','')})")
            else:
                ok = "✅" if r.get("success") else "❌"
                lines.append(f"{ok} {r.get('name','')} {r.get('quantity','')}주")
        return "\n".join(lines)
    return ""


# ── 실행 버튼 ────────────────────────────────────────────────────────
col_btn, col_info = st.columns([1, 5])
with col_btn:
    run_clicked = st.button("🚀 분석 시작", type="primary", use_container_width=True)
with col_info:
    if st.session_state.ran_at:
        st.caption(f"마지막 분석: {st.session_state.ran_at}")

if run_clicked:
    st.session_state.messages = []
    st.session_state.results = None

    app = build_graph()
    initial_state = get_initial_state()
    accumulated = dict(initial_state)

    progress = st.progress(0, text="분석 시작...")
    chat_placeholder = st.empty()
    total_est = MAX_DEBATE_ROUNDS * 2 + 5
    step_n = 0

    for step in app.stream(initial_state, {"recursion_limit": 50}):
        for node_name, node_output in step.items():
            if node_name == "__end__" or not isinstance(node_output, dict):
                continue

            accumulated.update(node_output)
            emoji, label = AGENT_META.get(node_name, ("🤖", node_name))
            content = _node_content(node_name, accumulated)

            st.session_state.messages.append(
                {"avatar": emoji, "name": label, "content": content, "node": node_name}
            )
            step_n += 1
            progress.progress(min(step_n / total_est, 0.95), text=f"'{label}' 처리 중...")

            with chat_placeholder.container():
                for m in st.session_state.messages:
                    with st.chat_message(m["name"], avatar=m["avatar"]):
                        st.markdown(m["content"])

    progress.progress(1.0, text="✅ 분석 완료!")
    st.session_state.results = accumulated
    st.session_state.ran_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if DISCORD_WEBHOOK_URL:
        if send_report(accumulated):
            st.toast("Discord로 보고서를 전송했습니다!", icon="📨")

    st.rerun()

# ── 결과 표시 ────────────────────────────────────────────────────────
if st.session_state.results:
    state = st.session_state.results
    decision = state.get("final_decision", "관망")
    target_stocks = state.get("target_stocks", [])
    debate_log = state.get("debate_log", [])

    st.divider()

    # 최종 결정 배너
    decision_cfg = {
        "매수": ("🟢", "매수 (BUY)", st.success),
        "매도": ("🔴", "매도 (SELL)", st.error),
        "관망": ("⚪", "관망 (HOLD)", st.info),
    }
    icon, label, banner_fn = decision_cfg.get(decision, ("⚪", decision, st.info))

    m1, m2, m3, m4 = st.columns([3, 1, 1, 1])
    with m1:
        banner_fn(f"## {icon} 최종 결정: {label}")
    m2.metric("대상 종목", len(target_stocks))
    m3.metric("토론 라운드", f"{state.get('debate_round', 0)}회")
    m4.metric("컨센서스", "달성" if state.get("consensus_reached") else "미달성")

    # 대상 종목 카드
    if target_stocks:
        st.subheader("🎯 대상 종목")
        cols = st.columns(min(len(target_stocks), 4))
        for i, stock in enumerate(target_stocks):
            with cols[i % 4]:
                st.metric(
                    label=f"{stock.get('name', '')} ({stock.get('code', '')})",
                    value=f"{stock.get('price', 'N/A')}원",
                )

    st.divider()

    # 탭
    tab_chat, tab_market, tab_news, tab_screen, tab_volume, tab_inst, tab_debate, tab_trade = st.tabs([
        "💬 에이전트 대화",
        "📊 시장 분석",
        "📰 뉴스 분석",
        "🔍 종목 스크리닝",
        "📈 거래량 분석",
        "🏦 기관/외국인",
        "🗣️ 토론 기록",
        "💹 매매 결과",
    ])

    with tab_chat:
        st.subheader("실시간 에이전트 대화 전체 기록")
        if st.session_state.messages:
            for m in st.session_state.messages:
                with st.chat_message(m["name"], avatar=m["avatar"]):
                    st.markdown(m["content"])
        else:
            st.info("대화 기록 없음")

    with tab_market:
        st.subheader("📊 시장 분석")
        content = state.get("market_analysis", "")
        st.markdown(content if content else "데이터 없음")

    with tab_news:
        st.subheader("📰 뉴스 분석")
        content = state.get("news_analysis", "")
        st.markdown(content if content else "데이터 없음")

    with tab_screen:
        st.subheader("🔍 종목 스크리닝")
        content = state.get("screening_analysis", "")
        st.markdown(content if content else "데이터 없음")

    with tab_volume:
        st.subheader("📈 거래량 분석")
        content = state.get("volume_analysis", "")
        st.markdown(content if content else "데이터 없음")

    with tab_inst:
        st.subheader("🏦 기관/외국인 투자자 분석")
        content = state.get("institutional_analysis", "")
        st.markdown(content if content else "데이터 없음")

    with tab_debate:
        st.subheader("🗣️ 토론 전체 기록")
        if debate_log:
            for entry in debate_log:
                if "수퍼바이저" in entry:
                    with st.chat_message("수퍼바이저", avatar="🎯"):
                        st.markdown(entry)
                else:
                    with st.chat_message("토론", avatar="💬"):
                        st.markdown(entry)
        else:
            st.info("토론 기록 없음")

    with tab_trade:
        st.subheader("💹 매매 실행 결과")
        trade_results = state.get("trade_results", [])
        if trade_results:
            for r in trade_results:
                if r.get("mode") == "simulation":
                    st.info(
                        f"[시뮬레이션] {r.get('action','')} "
                        f"**{r.get('name','')}** ({r.get('code','')})"
                    )
                elif r.get("success"):
                    st.success(f"✅ 주문 성공: **{r.get('name','')}** {r.get('quantity','')}주")
                else:
                    st.error(f"❌ 주문 실패: {r.get('name','')} — {r.get('message','')}")
        else:
            st.info("관망 결정으로 매매가 실행되지 않았습니다.")

else:
    # 초기 안내 화면
    st.info("👆 '분석 시작' 버튼을 눌러 멀티 에이전트 분석을 시작하세요.")
    st.divider()
    st.subheader("분석 흐름")

    flow_cols = st.columns(13)
    flow = [
        ("📊", "시장분석"), ("➡️", ""), ("📰", "뉴스분석"), ("➡️", ""),
        ("🔍", "스크리닝"), ("➡️", ""), ("📈", "거래량"), ("➡️", ""),
        ("🏦", "기관/외국인"), ("➡️", ""), ("🎯", "토론"), ("➡️", ""), ("💹", "매매"),
    ]
    for i, (e, l) in enumerate(flow):
        with flow_cols[i]:
            if e == "➡️":
                st.markdown(
                    "<div style='text-align:center;font-size:24px;padding-top:18px'>➡️</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:36px'>{e}</div>"
                    f"<div style='font-size:12px;margin-top:4px'>{l}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
