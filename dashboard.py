"""한국 주식 멀티 에이전트 대시보드"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from graph.workflow import build_graph, get_initial_state
from config import LLM_PROVIDER, KIS_MODE, MAX_DEBATE_ROUNDS, DISCORD_WEBHOOK_URL
from utils.discord import send_report

st.set_page_config(
    page_title="한국 주식 멀티 에이전트",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
body { background-color: #0f172a; }
.stApp { background-color: #0f172a; }
[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; }
[data-testid="stMetricLabel"] { font-size: 0.8rem; color: #94a3b8; }
.stTabs [data-baseweb="tab"] { font-size: 0.9rem; }
.agent-step { padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; display: inline-block; margin: 2px; }
.step-done { background: #14532d; color: #4ade80; }
.step-pending { background: #1e293b; color: #64748b; }
.step-running { background: #1e3a5f; color: #60a5fa; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
</style>
""", unsafe_allow_html=True)

# ── 사이드바 ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 시스템 설정")
    st.divider()
    c1, c2 = st.columns(2)
    c1.metric("LLM", LLM_PROVIDER.upper())
    c2.metric("KIS", "실전" if KIS_MODE == "real" else "모의")
    c1.metric("토론", f"{MAX_DEBATE_ROUNDS}R")
    c2.metric("매매", "시뮬")
    st.divider()
    st.caption("에이전트 파이프라인")
    for e, n, d in [
        ("📊", "시장 분석", "KOSPI/KOSDAQ 지수"),
        ("📰", "뉴스 분석", "Google News RSS"),
        ("🔍", "스크리닝", "유망 종목 발굴"),
        ("📈", "거래량", "패턴·모멘텀"),
        ("🏦", "기관/외국인", "스마트머니 동향"),
        ("🎯", "수퍼바이저", "5자 토론·결정"),
    ]:
        st.markdown(f"{e} **{n}** — _{d}_")
    st.divider()
    st.caption("Discord: " + ("✅ 연동됨" if DISCORD_WEBHOOK_URL else "미설정"))

# ── 세션 초기화 ──────────────────────────────────────────────────────
for k, v in [("results", None), ("messages", []), ("ran_at", None), ("agent_done", set())]:
    if k not in st.session_state:
        st.session_state[k] = v

AGENT_META = {
    "market_analyst":      ("📊", "시장 분석"),
    "news_analyst":        ("📰", "뉴스 분석"),
    "stock_screener":      ("🔍", "스크리닝"),
    "volume_agent":        ("📈", "거래량 분석"),
    "institutional_agent": ("🏦", "기관/외국인"),
    "supervisor":          ("🎯", "수퍼바이저"),
    "debate_agents":       ("💬", "토론"),
    "finalize":            ("✅", "최종 결정"),
}

PIPELINE = ["market_analyst", "news_analyst", "stock_screener",
            "volume_agent", "institutional_agent", "supervisor", "finalize"]


def _node_content(node_name: str, state: dict) -> str:
    mapping = {
        "market_analyst": "market_analysis",
        "news_analyst": "news_analysis",
        "stock_screener": "screening_analysis",
        "volume_agent": "volume_analysis",
        "institutional_agent": "institutional_analysis",
        "supervisor": "supervisor_opinion",
    }
    if node_name in mapping:
        return state.get(mapping[node_name], "")
    if node_name == "debate_agents":
        log = state.get("debate_log", [])
        return log[-1] if log else ""
    if node_name == "finalize":
        d = state.get("final_decision", "관망")
        t = state.get("target_stocks", [])
        names = " | ".join(f"{s.get('name','')}({s.get('code','')})" for s in t)
        return f"**최종 결정: {d}**" + (f"\n대상: {names}" if names else "")
    return ""


def _safe_float(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", ""))
    except Exception:
        return default


def _safe_int(v, default=0) -> int:
    try:
        return int(str(v).replace(",", ""))
    except Exception:
        return default

# ── 메인 헤더 ────────────────────────────────────────────────────────
st.markdown("# 📈 한국 주식 멀티 에이전트 대시보드")

col_btn, col_ts = st.columns([1, 5])
with col_btn:
    run_clicked = st.button("🚀 분석 시작", type="primary", use_container_width=True)
with col_ts:
    if st.session_state.ran_at:
        st.caption(f"마지막 분석: {st.session_state.ran_at}")

# ── 실행 ──────────────────────────────────────────────────────────────
if run_clicked:
    st.session_state.messages = []
    st.session_state.results = None
    st.session_state.agent_done = set()

    app = build_graph()
    initial_state = get_initial_state()
    accumulated = dict(initial_state)

    # 파이프라인 진행 표시
    pipeline_placeholder = st.empty()
    progress = st.progress(0, text="분석 준비 중...")
    chat_placeholder = st.empty()

    total_est = MAX_DEBATE_ROUNDS * 2 + len(PIPELINE)
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
            st.session_state.agent_done.add(node_name)
            step_n += 1
            progress.progress(min(step_n / total_est, 0.95), text=f"'{label}' 처리 중...")

            # 파이프라인 상태 표시
            with pipeline_placeholder.container():
                cols = st.columns(len(PIPELINE))
                for i, node in enumerate(PIPELINE):
                    e, lbl = AGENT_META.get(node, ("🤖", node))
                    if node in st.session_state.agent_done:
                        cols[i].markdown(f"<div class='agent-step step-done'>{e} {lbl} ✓</div>", unsafe_allow_html=True)
                    elif node == node_name:
                        cols[i].markdown(f"<div class='agent-step step-running'>{e} {lbl} ...</div>", unsafe_allow_html=True)
                    else:
                        cols[i].markdown(f"<div class='agent-step step-pending'>{e} {lbl}</div>", unsafe_allow_html=True)

            # 채팅 업데이트
            with chat_placeholder.container():
                for m in st.session_state.messages[-6:]:  # 최근 6개만 실시간 표시
                    with st.chat_message(m["name"], avatar=m["avatar"]):
                        st.markdown(m["content"][:600] + ("..." if len(m["content"]) > 600 else ""))

    progress.progress(1.0, text="✅ 분석 완료!")
    st.session_state.results = accumulated
    st.session_state.ran_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if DISCORD_WEBHOOK_URL:
        if send_report(accumulated):
            st.toast("Discord 전송 완료!", icon="📨")
    st.rerun()

# ── 결과 대시보드 ─────────────────────────────────────────────────────
if st.session_state.results:
    state = st.session_state.results
    decision = state.get("final_decision", "관망")
    target_stocks = state.get("target_stocks", [])
    volume_raw = state.get("volume_stocks_raw", [])
    inst_raw = state.get("institutional_stocks_raw", [])
    screened = state.get("screened_stocks", [])

    # ── 파이프라인 완료 표시 ─────────────────────────────────────────
    cols = st.columns(len(PIPELINE))
    for i, node in enumerate(PIPELINE):
        e, lbl = AGENT_META.get(node, ("🤖", node))
        cols[i].markdown(f"<div class='agent-step step-done'>{e} {lbl} ✓</div>", unsafe_allow_html=True)

    st.divider()

    # ── 최종 결정 배너 ───────────────────────────────────────────────
    decision_cfg = {
        "매수": ("🟢", "매수 (BUY)", "success"),
        "매도": ("🔴", "매도 (SELL)", "error"),
        "관망": ("⚪", "관망 (HOLD)", "info"),
    }
    icon, dlabel, dtype = decision_cfg.get(decision, ("⚪", decision, "info"))

    banner_cols = st.columns([3, 1, 1, 1, 1])
    with banner_cols[0]:
        getattr(st, dtype)(f"## {icon} 최종 결정: {dlabel}")
    banner_cols[1].metric("대상 종목", len(target_stocks))
    banner_cols[2].metric("토론 라운드", f"{state.get('debate_round', 0)}R")
    banner_cols[3].metric("컨센서스", "달성 ✓" if state.get("consensus_reached") else "미달성")
    banner_cols[4].metric("분석 종목", len(screened))

    # ── 대상 종목 카드 ────────────────────────────────────────────────
    if target_stocks:
        st.subheader("🎯 선정 종목")
        scols = st.columns(min(len(target_stocks), 4))
        for i, s in enumerate(target_stocks):
            cr = _safe_float(s.get("change_rate", 0))
            with scols[i % 4]:
                st.metric(
                    label=f"{s.get('name', '')} ({s.get('code', '')})",
                    value=f"{s.get('price', 'N/A')}원",
                    delta=f"{cr:+.2f}%" if cr else None,
                )

    st.divider()

    # ── 차트 섹션 (2열) ───────────────────────────────────────────────
    chart_left, chart_right = st.columns(2)

    with chart_left:
        st.subheader("📈 거래량 상위 종목")
        if volume_raw:
            top_vol = sorted(
                volume_raw, key=lambda x: _safe_int(x.get("volume", 0)), reverse=True
            )[:15]
            names = [f"{s.get('name', '')[:6]}\n({s.get('market','')[:1]})" for s in top_vol]
            volumes = [_safe_int(s.get("volume", 0)) for s in top_vol]
            changes = [_safe_float(s.get("change_rate", 0)) for s in top_vol]
            colors = ["#ef4444" if c < 0 else "#22c55e" for c in changes]

            fig = go.Figure(go.Bar(
                x=volumes,
                y=names,
                orientation="h",
                marker_color=colors,
                text=[f"{c:+.1f}%" for c in changes],
                textposition="outside",
                hovertemplate="%{y}<br>거래량: %{x:,}<br>등락: %{text}<extra></extra>",
            ))
            fig.update_layout(
                height=420,
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.8)",
                xaxis_title="거래량",
                margin=dict(l=10, r=60, t=20, b=10),
                font=dict(size=11),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("거래량 데이터 없음")

    with chart_right:
        st.subheader("🏦 투자자별 순매수 동향")
        if inst_raw:
            top_inst = inst_raw[:10]
            labels = [s.get("name", "")[:6] for s in top_inst]
            inst_vals = [_safe_int(s.get("institution_net_buy", 0)) for s in top_inst]
            frgn_vals = [_safe_int(s.get("foreign_net_buy", 0)) for s in top_inst]
            indv_vals = [_safe_int(s.get("individual_net_buy", 0)) for s in top_inst]

            fig = go.Figure(data=[
                go.Bar(name="기관", x=labels, y=inst_vals, marker_color="#6366f1"),
                go.Bar(name="외국인", x=labels, y=frgn_vals, marker_color="#f59e0b"),
                go.Bar(name="개인", x=labels, y=indv_vals, marker_color="#64748b"),
            ])
            fig.update_layout(
                barmode="group",
                height=420,
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.8)",
                yaxis_title="순매수 (주)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=10, r=10, t=30, b=10),
                font=dict(size=11),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("기관/외국인 데이터 없음")

    # ── 스크리닝 종목 등락률 차트 ────────────────────────────────────
    if screened:
        st.subheader("🔍 스크리닝 종목 등락률")
        screened_valid = [s for s in screened if s.get("name") and s.get("change_rate")]
        if screened_valid:
            names_s = [s.get("name", "")[:8] for s in screened_valid]
            changes_s = [_safe_float(s.get("change_rate", 0)) for s in screened_valid]
            colors_s = ["#ef4444" if c < 0 else "#22c55e" for c in changes_s]

            fig = go.Figure(go.Bar(
                x=names_s,
                y=changes_s,
                marker_color=colors_s,
                text=[f"{c:+.2f}%" for c in changes_s],
                textposition="outside",
                hovertemplate="%{x}<br>등락률: %{y:+.2f}%<extra></extra>",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#475569", line_width=1)
            fig.update_layout(
                height=280,
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.8)",
                yaxis_title="등락률 (%)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(size=12),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── 탭 섹션 ──────────────────────────────────────────────────────
    tabs = st.tabs([
        "💬 에이전트 대화",
        "📊 시장 분석",
        "📰 뉴스 분석",
        "🔍 스크리닝",
        "📈 거래량",
        "🏦 기관/외국인",
        "🗣️ 토론 기록",
    ])

    with tabs[0]:
        st.subheader("에이전트 대화 전체 기록")
        for m in st.session_state.messages:
            with st.chat_message(m["name"], avatar=m["avatar"]):
                st.markdown(m["content"])

    with tabs[1]:
        st.subheader("📊 시장 분석 결과")
        st.markdown(state.get("market_analysis", "데이터 없음"))

    with tabs[2]:
        st.subheader("📰 뉴스 분석 결과")
        content = state.get("news_analysis", "")
        if content:
            st.markdown(content)
        else:
            st.info("뉴스 분석 데이터 없음")

    with tabs[3]:
        st.subheader("🔍 종목 스크리닝 결과")
        col_a, col_b = st.columns([2, 3])
        with col_a:
            if screened:
                for s in screened:
                    cr = _safe_float(s.get("change_rate", 0))
                    st.metric(
                        f"{s.get('name','')} ({s.get('code','')})",
                        f"{s.get('price','N/A')}원",
                        delta=f"{cr:+.2f}%" if cr else None,
                    )
        with col_b:
            st.markdown(state.get("screening_analysis", "데이터 없음"))

    with tabs[4]:
        st.subheader("📈 거래량 분석 결과")
        col_a, col_b = st.columns([3, 2])
        with col_a:
            if volume_raw:
                # 거래량 증감률 차트
                top10 = sorted(volume_raw, key=lambda x: abs(_safe_float(x.get("volume_rate", 0))), reverse=True)[:12]
                n = [s.get("name", "")[:6] for s in top10]
                vr = [_safe_float(s.get("volume_rate", 0)) for s in top10]
                fig2 = go.Figure(go.Bar(
                    x=n, y=vr,
                    marker_color=["#22c55e" if v > 0 else "#ef4444" for v in vr],
                    text=[f"{v:+.0f}%" for v in vr],
                    textposition="outside",
                ))
                fig2.add_hline(y=0, line_dash="dash", line_color="#475569")
                fig2.update_layout(
                    title="거래량 증감률 상위",
                    height=320, template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,23,42,0.8)",
                    yaxis_title="거래량 증감률 (%)",
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig2, use_container_width=True)
        with col_b:
            st.markdown(state.get("volume_analysis", "데이터 없음"))

    with tabs[5]:
        st.subheader("🏦 기관/외국인 분석 결과")
        col_a, col_b = st.columns([3, 2])
        with col_a:
            if inst_raw:
                # 기관 순매수 상위 차트
                top_inst8 = sorted(inst_raw, key=lambda x: _safe_int(x.get("institution_net_buy", 0)), reverse=True)[:10]
                lbs = [s.get("name", "")[:6] for s in top_inst8]
                iv = [_safe_int(s.get("institution_net_buy", 0)) for s in top_inst8]
                fv = [_safe_int(s.get("foreign_net_buy", 0)) for s in top_inst8]

                fig3 = go.Figure(data=[
                    go.Bar(name="기관 순매수", x=lbs, y=iv, marker_color="#6366f1"),
                    go.Bar(name="외국인 순매수", x=lbs, y=fv, marker_color="#f59e0b"),
                ])
                fig3.update_layout(
                    barmode="group", title="기관·외국인 순매수 상위",
                    height=320, template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,23,42,0.8)",
                    yaxis_title="순매수 (주)",
                    margin=dict(l=10, r=10, t=40, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                )
                st.plotly_chart(fig3, use_container_width=True)
        with col_b:
            st.markdown(state.get("institutional_analysis", "데이터 없음"))

    with tabs[6]:
        st.subheader("🗣️ 에이전트 토론 기록")
        debate_log = state.get("debate_log", [])
        if debate_log:
            for entry in debate_log:
                avatar = "🎯" if "수퍼바이저" in entry else "💬"
                name = "수퍼바이저" if "수퍼바이저" in entry else "토론"
                with st.chat_message(name, avatar=avatar):
                    st.markdown(entry)
        else:
            st.info("토론 기록 없음")

else:
    # ── 초기 안내 화면 ────────────────────────────────────────────────
    st.info("👆 '분석 시작' 버튼을 눌러 멀티 에이전트 분석을 시작하세요.")
    st.divider()
    st.subheader("분석 파이프라인")
    flow = [
        ("📊", "시장분석"), ("➡️", ""), ("📰", "뉴스\n(Google)"), ("➡️", ""),
        ("🔍", "스크리닝"), ("➡️", ""), ("📈", "거래량"), ("➡️", ""),
        ("🏦", "기관/외국인"), ("➡️", ""), ("🎯", "5자 토론"), ("➡️", ""), ("✅", "결정"),
    ]
    cols = st.columns(len(flow))
    for i, (e, l) in enumerate(flow):
        with cols[i]:
            if e == "➡️":
                st.markdown("<div style='text-align:center;font-size:20px;padding-top:20px'>➡️</div>", unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<div style='text-align:center;background:#1e293b;border-radius:12px;padding:12px 4px'>"
                    f"<div style='font-size:28px'>{e}</div>"
                    f"<div style='font-size:11px;color:#94a3b8;margin-top:4px'>{l}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
