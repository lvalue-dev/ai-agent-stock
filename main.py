"""한국 주식 멀티 에이전트 시스템 - 메인 실행 파일

사용법
  python main.py                       # 1회 분석 (정기 모드)
  python main.py --realtime            # 웹소켓 실시간 감시 → 신호 발생 시 에이전트 실행
  python main.py --realtime --watch 005930,000660 --orderbook
  python main.py --realtime --dry-run  # 신호만 기록하고 에이전트는 실행하지 않음
"""
import argparse
import logging
import sys
from datetime import datetime

from graph.workflow import build_graph, get_initial_state
from utils.logger import print_separator, print_final_report
from utils.discord import send_report
from config import (
    KIS_APP_KEY, GOOGLE_API_KEY, GROQ_API_KEY, LLM_PROVIDER, KIS_MODE,
    AUTO_TRADE_ENABLED, MAX_DEBATE_ROUNDS, DISCORD_WEBHOOK_URL, KIS_MARKET,
    REALTIME_ORDERBOOK, REALTIME_TRIGGER_COOLDOWN_SEC, REALTIME_PRICE_SPIKE_PCT,
    REALTIME_VOLUME_SURGE_RATIO,
)


def validate_config() -> bool:
    errors = []
    if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        errors.append("GROQ_API_KEY 가 설정되지 않았습니다. https://console.groq.com 에서 발급 후 .env 에 입력해주세요.")
    elif LLM_PROVIDER == "gemini" and not GOOGLE_API_KEY:
        errors.append("GOOGLE_API_KEY 가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    if not KIS_APP_KEY:
        errors.append("KIS_APP_KEY 가 설정되지 않았습니다. .env 파일을 확인해주세요.")

    if errors:
        print("❌ 설정 오류:")
        for e in errors:
            print(f"  - {e}")
        print("\n💡 .env.example 파일을 복사하여 .env 파일을 만들고 API 키를 설정해주세요.")
        return False
    return True


def print_startup_info(realtime: bool = False):
    print_separator("한국 주식 멀티 에이전트 시스템")
    print(f"""
🤖 에이전트 구성:
  1. 📊 시장 분석 에이전트 - KOSPI/KOSDAQ 시장 흐름 분석
  2. 📰 뉴스 분석 에이전트 - 시장 뉴스 및 공시 분석
  3. 🔍 스크리닝 에이전트  - 투자 유망 종목 발굴
  4. 📈 거래량 에이전트    - 거래량 패턴·모멘텀
  5. 🏦 기관/외국인 에이전트 - 스마트머니 동향
  6. ⚡ 실시간 에이전트    - 웹소켓 체결/호가 신호 해석 (실시간 모드)
  7. 🎯 수퍼바이저 에이전트 - 토론 진행 및 최종 의사결정

⚙️  설정:
  - LLM: {LLM_PROVIDER.upper()} ({'Groq - llama-3.3-70b' if LLM_PROVIDER == 'groq' else 'Google Gemini 2.0 Flash'})
  - KIS 모드: {KIS_MODE.upper()} ({'실전 투자' if KIS_MODE == 'real' else '모의 투자'})
  - 시세 시장: {KIS_MARKET} ({ {'J': 'KRX 정규장만', 'NX': '넥스트레이드만', 'UN': 'KRX+NXT 통합 (프리마켓 08:00~ / 애프터마켓 ~20:00 포함)'}[KIS_MARKET] })
  - 자동 매매: {'활성화' if AUTO_TRADE_ENABLED else '비활성화 (시뮬레이션)'}
  - 최대 토론 라운드: {MAX_DEBATE_ROUNDS}회
  - 실행 모드: {'실시간 (웹소켓 트리거)' if realtime else '1회 분석'}
""")
    print_separator()


def run_pipeline(trigger_event: dict | None = None) -> dict | None:
    """에이전트 그래프를 1회 실행하고 최종 상태를 돌려준다."""
    app = build_graph()
    initial_state = get_initial_state(trigger_event=trigger_event)

    accumulated_state = dict(initial_state)
    ran = False
    for step in app.stream(initial_state, {"recursion_limit": 50}):
        for node_name, node_output in step.items():
            if node_name != "__end__":
                print(f"\n  ✓ '{node_name}' 완료")
                if isinstance(node_output, dict):
                    accumulated_state.update(node_output)
        ran = True

    if not ran:
        print("❌ 에이전트 실행 실패")
        return None

    print("\n")
    print_final_report(accumulated_state)
    if DISCORD_WEBHOOK_URL:
        print("\n📨 Discord로 보고서 전송 중...")
        if send_report(accumulated_state):
            print("  ✓ Discord 전송 완료")
    return accumulated_state


def run_once():
    print("\n🚀 멀티 에이전트 분석 시작...\n")
    run_pipeline()


def run_realtime(watch: list[str] | None, orderbook: bool, dry_run: bool):
    from realtime import RealtimeEngine, build_watchlist

    print("\n📡 감시 종목 구성 중...")
    watchlist = build_watchlist(watch)
    if not watchlist:
        print("❌ 감시 종목이 없습니다. --watch 또는 .env 의 WATCHLIST 를 확인해주세요.")
        sys.exit(1)
    print("  " + ", ".join(f"{w.get('name') or '?'}({w['code']})" for w in watchlist))
    print(f"\n  신호 기준: 5분 등락 ±{REALTIME_PRICE_SPIKE_PCT}% | 1분 거래량 {REALTIME_VOLUME_SURGE_RATIO}배"
          f" | 에이전트 재실행 간격 {REALTIME_TRIGGER_COOLDOWN_SEC}초")

    def on_trigger(event: dict):
        print_separator(f"⚡ 실시간 트리거 {event.get('at', '')} [{event.get('session', '')}]")
        for s in event.get("signals", []):
            print(f"  • [{s.get('label')}] {s.get('message')}")
        print("\n🚀 멀티 에이전트 분석 시작...\n")
        run_pipeline(trigger_event=event)

    engine = RealtimeEngine(
        watchlist,
        on_trigger=None if dry_run else on_trigger,
        orderbook=orderbook,
    )
    engine.start()
    print(f"\n✅ 실시간 감시 시작 ({datetime.now().strftime('%H:%M:%S')}). 종료: Ctrl+C\n"
          f"   스냅샷: {engine.snapshot_path} (대시보드 '실시간' 탭에서 확인)\n")
    engine.run_forever()
    print("\n👋 실시간 감시 종료")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="한국 주식 멀티 에이전트")
    parser.add_argument("--realtime", action="store_true", help="웹소켓 실시간 감시 모드")
    parser.add_argument("--watch", default="", help="감시 종목코드 (쉼표 구분). 생략 시 WATCHLIST 또는 거래량 상위 자동 선정")
    parser.add_argument("--orderbook", action="store_true", default=REALTIME_ORDERBOOK, help="호가(H0STASP0)도 구독")
    parser.add_argument("--dry-run", action="store_true", help="신호만 기록하고 에이전트는 실행하지 않음")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None):
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not validate_config():
        sys.exit(1)

    print_startup_info(realtime=args.realtime)

    if args.realtime:
        watch = [c.strip() for c in args.watch.split(",") if c.strip()] or None
        run_realtime(watch, orderbook=args.orderbook, dry_run=args.dry_run)
    else:
        run_once()


if __name__ == "__main__":
    run()
