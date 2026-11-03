"""한국 주식 멀티 에이전트 대시보드"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from graph.workflow import build_graph, get_initial_state
from config import LLM_PROVIDER, KIS_MODE, MAX_DEBATE_ROUNDS, DISCORD_WEBHOOK_URL, REALTIME_SNAPSHOT_PATH, KIS_APP_KEY
from tools.kis_websocket import market_session, KST
import streamlit.components.v1 as components
import inspect
import json
import os
import threading
import time
import traceback
from utils.discord import send_report

st.set_page_config(
    page_title="한국 주식 멀티 에이전트",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",  # 모바일에서는 접힘 (펼치면 화면 전체를 가림)
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
@media (max-width: 640px) { h1 { font-size: 1.4rem !important; } h2 { font-size: 1.15rem !important; } }
/* ── 실시간 시세판 ── */
.lb-head { display:flex; justify-content:space-between; align-items:center; font-size:.85rem; color:#94a3b8; margin:2px 0 6px; }
.lb-head b { color:#e2e8f0; }
.lb { width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
.lb th { color:#64748b; font-weight:500; font-size:11px; text-align:right; padding:4px 6px; border-bottom:1px solid #1e293b; }
.lb th:first-child, .lb td:first-child { text-align:left; }
.lb td { padding:6px 6px; border-bottom:1px solid #111827; text-align:right; white-space:nowrap; }
.lb tr.sel td { background:#1e293b; }
.lb .nm { font-weight:600; color:#e2e8f0; }
.lb .cd { font-size:10px; color:#64748b; margin-left:4px; }
.lb .px { font-weight:700; font-size:14px; }
.up { color:#ff5252; } .dn { color:#448aff; } .fl { color:#cbd5e1; }
.vb { color:#ff8a80; } .vs { color:#82b1ff; }
@keyframes flashUp { 0% { background:#ff525266; } 100% { background:transparent; } }
@keyframes flashDn { 0% { background:#448aff66; } 100% { background:transparent; } }
.fu { animation: flashUp .9s ease-out; } .fd { animation: flashDn .9s ease-out; }
.spark { vertical-align:middle; }
.lb-detail { background:#0b1220; border:1px solid #1e293b; border-radius:12px; padding:12px 14px; margin-top:8px; }
.lb-detail .big { font-size:28px; font-weight:800; }
.lb-detail .sub { color:#94a3b8; font-size:12px; }
.ob { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0; font-size:13px; }
.ob div { background:#111827; border-radius:8px; padding:6px 10px; }
.tape { width:100%; font-size:12px; border-collapse:collapse; }
.tape td { padding:2px 6px; text-align:right; color:#cbd5e1; }
.tape td:first-child { text-align:left; color:#64748b; }
@media (max-width: 640px) { .lb .hide-m { display:none; } .lb { font-size:12px; } .lb .px { font-size:13px; } }
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
        ("⚡", "실시간", "웹소켓 체결·호가 신호"),
        ("🎯", "수퍼바이저", "토론·결정"),
    ]:
        st.markdown(f"{e} **{n}** — _{d}_")
    st.divider()
    st.caption("Discord: " + ("✅ 연동됨" if DISCORD_WEBHOOK_URL else "미설정"))

# ── 세션 초기화 ──────────────────────────────────────────────────────
for k, v in [("results", None), ("messages", []), ("ran_at", None), ("agent_done", set()), ("run_error", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

AGENT_META = {
    "market_analyst":      ("📊", "시장 분석"),
    "news_analyst":        ("📰", "뉴스 분석"),
    "stock_screener":      ("🔍", "스크리닝"),
    "volume_agent":        ("📈", "거래량 분석"),
    "institutional_agent": ("🏦", "기관/외국인"),
    "realtime_agent":      ("⚡", "실시간"),
    "supervisor":          ("🎯", "수퍼바이저"),
    "debate_agents":       ("💬", "토론"),
    "finalize":            ("✅", "최종 결정"),
}

PIPELINE = ["market_analyst", "news_analyst", "stock_screener",
            "volume_agent", "institutional_agent", "realtime_agent", "supervisor", "finalize"]


def _node_content(node_name: str, state: dict) -> str:
    mapping = {
        "market_analyst": "market_analysis",
        "news_analyst": "news_analysis",
        "stock_screener": "screening_analysis",
        "volume_agent": "volume_analysis",
        "institutional_agent": "institutional_analysis",
        "realtime_agent": "realtime_analysis",
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


# ── 차트 공통 설정 (모바일 터치 대응) ──────────────────────────────────
# Plotly 의 드래그 확대/이동은 Streamlit·Plotly 버전과 터치 브라우저에 따라
# 박스 확대로 동작하는 경우가 있어 아예 끈다. 드래그는 페이지 스크롤로만 쓰이고,
# 막대가 많을 때는 구간 선택(알약 버튼)으로 넘겨 본다.
CHART_PAGE_SIZE = 10
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "scrollZoom": False,
    "doubleClick": False,
    "responsive": True,
}
_PLOTLY_HAS_WIDTH = "width" in inspect.signature(st.plotly_chart).parameters


def _render_chart(fig: go.Figure, key: str, page_size: int = CHART_PAGE_SIZE) -> None:
    """모든 차트에 동일한 터치 동작을 적용해 그린다.

    - 드래그/휠/더블클릭 확대 전부 비활성화 (양 축 고정)
    - 범주가 page_size 보다 많으면 구간 선택 버튼으로 이동, '전체' 로 한눈에 보기
    """
    horizontal = bool(fig.data) and all(getattr(tr, "orientation", None) == "h" for tr in fig.data)
    cat_attr = "y" if horizontal else "x"
    n = max((len(getattr(tr, cat_attr, None) or []) for tr in fig.data), default=0)

    fig.update_layout(
        dragmode=False,
        hovermode="y unified" if horizontal else "x unified",
        hoverlabel=dict(font_size=12),
    )
    fig.update_xaxes(fixedrange=True, automargin=True)
    fig.update_yaxes(fixedrange=True, automargin=True)

    if n > page_size:
        pages = [(i, min(i + page_size, n)) for i in range(0, n, page_size)]
        labels = [f"{a + 1}–{b}" for a, b in pages] + ["전체"]
        k = f"chart_{key}_page"
        if hasattr(st, "pills"):   # Streamlit ≥ 1.40. 한 줄 알약 버튼이라 모바일에서도 가로로 유지됨
            choice = st.pills("구간", labels, default=labels[0], key=k, label_visibility="collapsed")
        else:
            choice = st.radio("구간", labels, horizontal=True, key=k, label_visibility="collapsed")
        if choice not in labels:   # pills 는 선택 해제가 가능 → 첫 구간으로
            choice = labels[0]
        if choice != "전체":
            a, b = pages[labels.index(choice)]
            rng = [a - 0.5, b - 0.5]
            if horizontal:
                fig.update_yaxes(range=rng)
            else:
                fig.update_xaxes(range=rng)
        elif not horizontal:
            fig.update_xaxes(tickangle=-90, tickfont=dict(size=10))  # 전체 보기 땐 이름이 겹치므로 세로로
    elif n > 8 and not horizontal:
        fig.update_xaxes(tickangle=-90, tickfont=dict(size=10))

    # Streamlit 1.4x 는 width= 인자가 없어 use_container_width 로 대체 (구버전 호환)
    if _PLOTLY_HAS_WIDTH:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)
    else:
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=key)


# ── 메인 헤더 ────────────────────────────────────────────────────────
st.markdown("# 📈 한국 주식 멀티 에이전트 대시보드")

col_btn, col_ts = st.columns([1, 5])
with col_btn:
    run_clicked = st.button("🚀 분석 시작", type="primary", use_container_width=True)
with col_ts:
    if st.session_state.ran_at:
        st.caption(f"마지막 분석: {st.session_state.ran_at}")

# ── 실시간 감시 현황 ──────────────────────────────────────────────────
# 장이 열린 시간(프리마켓 08:00 ~ 애프터마켓 20:00)에는 대시보드가 직접 KIS 웹소켓 엔진을 띄워
# 1초마다 자동 갱신한다 (주식창처럼 현재가 깜빡임·체결 테이프·스파크라인). `python main.py --realtime` 이 따로 돌아 스냅샷 파일을 쓰고 있으면
# (같은 앱키로 웹소켓을 두 번 열지 않도록) 그 파일을 읽어 보여준다. 장외에는 마지막 스냅샷만 표시.
LIVE_REFRESH_SEC = 1
SNAPSHOT_FRESH_SEC = 15


def _load_realtime_snapshot() -> dict | None:
    try:
        if os.path.exists(REALTIME_SNAPSHOT_PATH):
            with open(REALTIME_SNAPSHOT_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None


def _snapshot_is_fresh() -> bool:
    try:
        return time.time() - os.path.getmtime(REALTIME_SNAPSHOT_PATH) < SNAPSHOT_FRESH_SEC
    except OSError:
        return False


@st.cache_resource(show_spinner=False)
def _analysis_lock() -> threading.Lock:
    """대시보드 수동 분석과 엔진 트리거 분석이 동시에 LLM 을 두드리지 않도록 (무료 티어 한도 보호)"""
    return threading.Lock()


@st.cache_resource(show_spinner="📡 KIS 웹소켓 연결 중...")
def _get_engine():
    """서버 프로세스당 하나만 띄우는 실시간 엔진. 신호가 오면 에이전트 파이프라인을 백그라운드로 실행."""
    from realtime import RealtimeEngine, build_watchlist
    from main import run_pipeline

    results: list[dict] = []
    lock = _analysis_lock()

    def on_trigger(event: dict) -> None:
        if not lock.acquire(blocking=False):
            print("⏭️  다른 분석이 진행 중이라 실시간 트리거 분석을 건너뜁니다:", event.get("summary", ""))
            return
        try:
            state = run_pipeline(trigger_event=event)
        finally:
            lock.release()
        if state:
            state["_triggered_at"] = event.get("at", "")
            results.append(state)
            del results[:-5]

    watchlist = build_watchlist()
    if not watchlist:
        raise RuntimeError("감시 종목을 가져오지 못했습니다 (KIS REST 거래량 순위 조회 실패 또는 WATCHLIST 비어 있음)")
    engine = RealtimeEngine(watchlist, on_trigger=on_trigger, snapshot_path=None)
    engine.trigger_results = results
    engine.start()
    return engine


def _live_status() -> tuple[dict | None, str]:
    """(상태 dict, 소스) 소스: engine | file | stale | none"""
    session = market_session()
    if _snapshot_is_fresh() and "live_engine" not in st.session_state:
        return _load_realtime_snapshot(), "file"
    if session != "장외" and KIS_APP_KEY:
        try:
            engine = _get_engine()
            st.session_state["live_engine"] = True
            return engine.status(), "engine"
        except Exception as e:  # 접속키 발급 실패, 감시 종목 조회 실패 등
            _get_engine.clear()
            st.error(f"웹소켓 엔진 시작 실패: {e}")
    rt = _load_realtime_snapshot()
    return rt, ("stale" if rt else "none")


def _spark_svg(values: list, w: int = 96, h: int = 28, stroke: float = 1.5) -> str:
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(f"{i * (w - 2) / (n - 1) + 1:.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}" for i, v in enumerate(vals))
    color = "#ff5252" if vals[-1] > vals[0] else ("#448aff" if vals[-1] < vals[0] else "#94a3b8")
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{color}" stroke-width="{stroke}" points="{pts}"/></svg>')


def _cls(v: float) -> str:
    return "up" if v > 0 else ("dn" if v < 0 else "fl")


def _fmt_vol(v) -> str:
    v = _safe_int(v)
    return f"{v / 10000:.1f}만" if v >= 10000 else f"{v:,}"


def _render_live_board(rt: dict, source: str) -> None:
    """실제 주식창처럼: 현재가 깜빡임, 체결 테이프, 스파크라인, 1호가"""
    session = rt.get("session") or market_session()
    stats = rt.get("stats", {})
    src_label = {"engine": "대시보드 내장 소켓", "file": "main.py --realtime", "stale": "마지막 스냅샷", "none": ""}[source]
    icon = {"정규장": "🟢", "프리마켓": "🟠", "애프터마켓": "🟣"}.get(session, "🟡" if "동시호가" in session else "⚫")
    conn = "연결" if rt.get("connected") else "끊김"
    st.markdown(
        f'<div class="lb-head"><span>{icon} <b>{session}</b> · {conn} · {src_label}</span>'
        f'<span>체결 <b>{stats.get("ticks", 0):,}</b> · 신호 <b>{len(rt.get("signals", []))}</b> · {(rt.get("updated_at") or "")[11:19]}</span></div>',
        unsafe_allow_html=True,
    )

    rows = rt.get("snapshot", [])
    if not rows:
        if rt.get("connected"):
            st.info("소켓 연결됨. 체결이 들어오면 바로 표시됩니다. 프리마켓은 NXT 거래 종목만 체결이 발생합니다.")
        else:
            st.caption("아직 수신된 체결이 없습니다.")
        return

    # 정렬: 관심순(감시 목록 순서) / 등락률 / 거래량비
    order_key = "lb_sort"
    sort = st.pills("정렬", ["관심순", "등락률", "거래량비", "5분변동"], default="관심순", key=order_key,
                    label_visibility="collapsed") if hasattr(st, "pills") else "관심순"
    if sort == "등락률":
        rows = sorted(rows, key=lambda r: _safe_float(r.get("change_rate")), reverse=True)
    elif sort == "거래량비":
        rows = sorted(rows, key=lambda r: _safe_float(r.get("vol_ratio_1m")), reverse=True)
    elif sort == "5분변동":
        rows = sorted(rows, key=lambda r: abs(_safe_float(r.get("pct_5m"))), reverse=True)
    else:
        idx = {w.get("code"): i for i, w in enumerate(rt.get("watchlist", []))}
        rows = sorted(rows, key=lambda r: idx.get(r.get("code"), 999))

    codes = [r["code"] for r in rows]
    sel = st.session_state.get("lb_sel")
    if sel not in codes:
        sel = codes[0]
    # 직전 렌더 가격과 비교해 틱 방향 깜빡임
    prev_map = st.session_state.setdefault("lb_prev", {})
    html = ['<table class="lb"><thead><tr><th>종목</th><th>현재가</th><th>등락</th><th>체결</th>'
            '<th class="hide-m">강도</th><th class="hide-m">량비</th><th>추이</th></tr></thead><tbody>']
    for r in rows:
        code, price = r["code"], _safe_int(r.get("price"))
        prev = prev_map.get(code, price)
        flash = "fu" if price > prev else ("fd" if price < prev else "")
        prev_map[code] = price
        cr = _safe_float(r.get("change_rate"))
        side = r.get("last_side", "")
        vcls = "vb" if side == "buy" else ("vs" if side == "sell" else "")
        html.append(
            f'<tr class="{"sel" if code == sel else ""}">'
            f'<td><span class="nm">{r.get("name", "")}</span><span class="cd">{code}</span>'
            f'<div class="sub" style="font-size:10px;color:#64748b">{r.get("time", "")[:2]}:{r.get("time", "")[2:4]}:{r.get("time", "")[4:6]}</div></td>'
            f'<td class="px {_cls(cr)} {flash}">{price:,}</td>'
            f'<td class="{_cls(cr)}">{cr:+.2f}%<div style="font-size:10px">{_safe_int(r.get("change")):+,}</div></td>'
            f'<td class="{vcls}">{_fmt_vol(r.get("last_volume"))}<div style="font-size:10px;color:#64748b">{_fmt_vol(r.get("acc_volume"))}</div></td>'
            f'<td class="hide-m">{_safe_float(r.get("strength")):.0f}</td>'
            f'<td class="hide-m">{_safe_float(r.get("vol_ratio_1m")):.1f}x</td>'
            f'<td>{_spark_svg(r.get("spark", []))}</td></tr>'
        )
    html.append("</tbody></table>")
    st.markdown("".join(html), unsafe_allow_html=True)

    # 상세: 종목 선택 → 1호가 · 체결 테이프 · 30분 추이
    names = {r["code"]: f"{r.get('name', '')}" for r in rows}
    if hasattr(st, "pills"):
        picked = st.pills("종목", codes, format_func=lambda c: names.get(c, c), default=sel, key="lb_pick",
                          label_visibility="collapsed")
        if picked in codes:
            sel = picked
    st.session_state["lb_sel"] = sel
    r = next((x for x in rows if x["code"] == sel), rows[0])
    cr = _safe_float(r.get("change_rate"))
    tape_rows = "".join(
        f'<tr><td>{t.get("time", "")[:2]}:{t.get("time", "")[2:4]}:{t.get("time", "")[4:6]}</td>'
        f'<td class="{"up" if t.get("side") == "buy" else ("dn" if t.get("side") == "sell" else "fl")}">{_safe_int(t.get("price")):,}</td>'
        f'<td class="{"vb" if t.get("side") == "buy" else ("vs" if t.get("side") == "sell" else "")}">{_fmt_vol(t.get("volume"))}</td></tr>'
        for t in r.get("tape", [])
    )
    st.markdown(
        f'<div class="lb-detail">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px">'
        f'<div><span class="nm" style="font-size:16px;font-weight:700">{r.get("name", "")}</span> <span class="cd">{sel}</span>'
        f'<div class="big {_cls(cr)}">{_safe_int(r.get("price")):,}</div>'
        f'<div class="{_cls(cr)}">{_safe_int(r.get("change")):+,} ({cr:+.2f}%)</div>'
        f'<div class="sub">고 {_safe_int(r.get("high")):,} · 저 {_safe_int(r.get("low")):,} · 시 {_safe_int(r.get("open")):,} · 누적 {_fmt_vol(r.get("acc_volume"))}</div></div>'
        f'<div>{_spark_svg(r.get("spark", []), w=220, h=64, stroke=2)}<div class="sub" style="text-align:right">최근 30분</div></div></div>'
        f'<div class="ob"><div><span class="sub">매도 1호가</span><br><b class="dn">{_safe_int(r.get("ask1")):,}</b></div>'
        f'<div><span class="sub">매수 1호가</span><br><b class="up">{_safe_int(r.get("bid1")):,}</b></div>'
        f'<div><span class="sub">체결강도</span><br><b>{_safe_float(r.get("strength")):.0f}</b> <span class="sub">5분 매수비중 {_safe_float(r.get("buy_ratio_5m")):.0f}%</span></div>'
        f'<div><span class="sub">호가 잔량비(매수/매도)</span><br><b>{_safe_float(r.get("imbalance")):.2f}</b> <span class="sub">1분 거래량 {_safe_float(r.get("vol_ratio_1m")):.1f}x</span></div></div>'
        f'<div class="sub" style="margin-top:4px">체결 테이프</div><table class="tape">{tape_rows}</table></div>',
        unsafe_allow_html=True,
    )

    sigs = rt.get("signals", [])
    if sigs:
        st.markdown("**최근 신호**")
        for sg in sigs[:8]:
            t = datetime.fromtimestamp(sg.get("at", 0)).strftime("%H:%M:%S") if sg.get("at") else ""
            st.markdown(f"- `{t}` **{sg.get('label', '')}** — {sg.get('message', '')}")


def _render_trigger_results() -> None:
    """대시보드 내장 엔진이 실행한 에이전트 분석 결과 (최근 5건)"""
    if "live_engine" not in st.session_state:
        return
    engine = _get_engine()
    results = getattr(engine, "trigger_results", [])
    if not results:
        return
    st.markdown("**⚡ 실시간 트리거 분석 (최근)**")
    for i, res in enumerate(reversed(results)):
        ev = res.get("trigger_event", {}) or {}
        cols = st.columns([5, 1])
        cols[0].markdown(f"- `{res.get('_triggered_at','')}` **{res.get('final_decision','')}** — {ev.get('summary','')[:120]}")
        if cols[1].button("보기", key=f"trig_view_{i}"):
            st.session_state.results = res
            st.session_state.ran_at = res.get("_triggered_at", "")
            st.session_state.messages = [
                {"avatar": AGENT_META.get(n, ("🤖", n))[0], "name": AGENT_META.get(n, ("🤖", n))[1],
                 "content": _node_content(n, res), "node": n}
                for n in PIPELINE if _node_content(n, res)
            ]
            st.rerun(scope="app")   # fragment 안이므로 앱 전체를 다시 그린다


_CHART_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "live_chart.html")


@st.cache_data(show_spinner=False)
def _live_chart_html() -> str:
    """터치 네이티브 캔들 차트 (TradingView Lightweight Charts 로컬 번들). iframe 안에서 1초마다 /app/static/live/ 피드를 읽는다."""
    with open(_CHART_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _render_live_chart() -> None:
    components.html(_live_chart_html(), height=560, scrolling=False)


def _live_section_body() -> None:
    rt, source = _live_status()
    if not rt:
        st.caption(
            "장이 열리면(평일 08:00~20:00) 자동으로 웹소켓에 연결됩니다. "
            + ("" if KIS_APP_KEY else "KIS_APP_KEY 가 설정되어 있지 않습니다.")
        )
        return
    _render_live_board(rt, source)
    _render_trigger_results()


# 장이 열린 시간에만 자동 갱신 (fragment 는 이 부분만 다시 그린다)
# 분석 실행 중에는 자동 갱신을 멈춘다. 일부 Streamlit 버전은 fragment 자동 재실행이 진행 중인 메인 실행을 끊는다.
_live_refresh = None if run_clicked else (LIVE_REFRESH_SEC if market_session() != "장외" else None)
if hasattr(st, "fragment"):
    _live_section = st.fragment(run_every=_live_refresh)(_live_section_body)
else:
    _live_section = _live_section_body

with st.expander("⚡ 실시간 시세", expanded=market_session() != "장외" and not run_clicked):
    # 차트는 fragment 밖에서 한 번만 그려 iframe 이 유지되고, 안에서 스스로 1초마다 피드를 읽어 갱신한다
    _render_live_chart()
    if run_clicked:
        st.caption("분석이 끝날 때까지 시세 목록 자동 갱신을 잠시 멈춥니다. 차트는 계속 갱신됩니다.")
    else:
        _live_section()

# ── 실행 ──────────────────────────────────────────────────────────────
if run_clicked:
    st.session_state.messages = []
    st.session_state.results = None
    st.session_state.agent_done = set()
    st.session_state.run_error = None

    import utils.llm as _llm_mod

    # 파이프라인 진행 표시
    pipeline_placeholder = st.empty()
    progress = st.progress(0, text="분석 준비 중...")
    status_line = st.empty()
    chat_placeholder = st.empty()

    total_est = MAX_DEBATE_ROUNDS * 2 + len(PIPELINE)
    step_n = 0
    started = time.time()
    current_label = "준비"

    def _elapsed() -> str:
        return f"{int(time.time() - started) // 60}분 {int(time.time() - started) % 60}초"

    def _set_status(msg: str) -> None:
        status_line.caption(f"⏱ {_elapsed()} 경과 · {msg}")

    _llm_mod.RETRY_LISTENER = lambda msg: _set_status(f"'{current_label}' 단계 · {msg}")

    lock = _analysis_lock()
    waited = 0
    while not lock.acquire(blocking=False):
        if waited == 0:
            _set_status("실시간 트리거 분석이 진행 중입니다. 끝나면 이어서 시작합니다…")
        time.sleep(1)
        waited += 1
        if waited > 900:
            st.error("다른 분석이 15분 넘게 끝나지 않아 중단했습니다. 잠시 후 다시 시도해주세요.")
            st.stop()

    accumulated: dict = {}
    try:
        app = build_graph()
        initial_state = get_initial_state()
        accumulated = dict(initial_state)
        _set_status("시장 데이터 수집 및 첫 에이전트 호출 중…")

        for step in app.stream(initial_state, {"recursion_limit": 50}):
            for node_name, node_output in step.items():
                if node_name == "__end__" or not isinstance(node_output, dict):
                    continue
                accumulated.update(node_output)
                emoji, label = AGENT_META.get(node_name, ("🤖", node_name))
                current_label = label
                content = _node_content(node_name, accumulated)
                st.session_state.messages.append(
                    {"avatar": emoji, "name": label, "content": content, "node": node_name}
                )
                st.session_state.agent_done.add(node_name)
                step_n += 1
                progress.progress(min(step_n / total_est, 0.95), text=f"'{label}' 완료 · 다음 단계 진행 중...")
                _set_status(f"'{label}' 완료")

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

        progress.progress(1.0, text=f"✅ 분석 완료! ({_elapsed()})")
        st.session_state.results = accumulated
        st.session_state.ran_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        if DISCORD_WEBHOOK_URL:
            if send_report(accumulated):
                st.toast("Discord 전송 완료!", icon="📨")
    except Exception as e:
        # 어떤 단계에서 왜 실패했는지 남기고, 완료된 단계의 결과는 보존
        st.session_state.run_error = {
            "label": current_label, "elapsed": _elapsed(), "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(), "partial": accumulated,
        }
    finally:
        _llm_mod.RETRY_LISTENER = None
        lock.release()
    st.rerun()

if st.session_state.get("run_error"):
    err = st.session_state.run_error
    st.error(f"분석이 '{err['label']}' 단계에서 중단됐습니다 ({err['elapsed']} 경과): {err['error']}")
    with st.expander("오류 상세"):
        st.code(err["trace"])
    partial = err.get("partial") or {}
    done = [AGENT_META.get(n, ("🤖", n))[1] for n in PIPELINE if _node_content(n, partial)]
    if done:
        st.caption("완료된 단계: " + ", ".join(done))
        with st.expander("완료된 단계 결과 보기"):
            for n in PIPELINE:
                c = _node_content(n, partial)
                if c:
                    e, lbl = AGENT_META.get(n, ("🤖", n))
                    with st.chat_message(lbl, avatar=e):
                        st.markdown(c)

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
            _render_chart(fig, key="top_volume")
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
            _render_chart(fig, key="inst_vs_frgn")
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
            _render_chart(fig, key="screened_change")

    st.divider()

    # ── 탭 섹션 ──────────────────────────────────────────────────────
    tabs = st.tabs([
        "💬 에이전트 대화",
        "📊 시장 분석",
        "📰 뉴스 분석",
        "🔍 스크리닝",
        "📈 거래량",
        "🏦 기관/외국인",
        "⚡ 실시간",
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
                _render_chart(fig2, key="vol_rate")
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
                _render_chart(fig3, key="inst_net")
        with col_b:
            st.markdown(state.get("institutional_analysis", "데이터 없음"))

    with tabs[6]:
        st.subheader("⚡ 실시간 분석 결과")
        event = state.get("trigger_event", {}) or {}
        if event.get("summary"):
            st.info(f"트리거 ({event.get('at','')}): {event['summary']}")
        rt_text = state.get("realtime_analysis", "")
        if rt_text:
            st.markdown(rt_text)
        else:
            st.info("정기 분석에서는 실시간 데이터가 없습니다. `python main.py --realtime` 로 트리거된 분석에서 채워집니다.")

    with tabs[7]:
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
        ("🏦", "기관/외국인"), ("➡️", ""), ("⚡", "실시간"), ("➡️", ""), ("🎯", "토론"), ("➡️", ""), ("✅", "결정"),
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
