"""에이전트 실행 로깅 유틸리티"""
from datetime import datetime
try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    _color = True
except ImportError:
    _color = False


def log_agent(agent_name: str, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    if _color:
        print(f"{Fore.CYAN}[{timestamp}]{Style.RESET_ALL} {Fore.YELLOW}{agent_name}{Style.RESET_ALL}: {message}")
    else:
        print(f"[{timestamp}] {agent_name}: {message}")


def print_separator(title: str = "") -> None:
    line = "=" * 60
    if title:
        padding = (60 - len(title) - 2) // 2
        line = "=" * padding + f" {title} " + "=" * padding
    if _color:
        print(f"{Fore.GREEN}{line}{Style.RESET_ALL}")
    else:
        print(line)


def print_final_report(state: dict) -> None:
    print_separator("최종 분석 보고서")
    print(f"\n{'='*60}")
    print("📊 시장 분석")
    print("-" * 40)
    print(state.get("market_analysis", "N/A"))

    print(f"\n{'='*60}")
    print("📰 뉴스 분석")
    print("-" * 40)
    print(state.get("news_analysis", "N/A"))

    print(f"\n{'='*60}")
    print("🔍 종목 스크리닝")
    print("-" * 40)
    print(state.get("screening_analysis", "N/A"))

    print(f"\n{'='*60}")
    print("💬 토론 기록")
    print("-" * 40)
    for entry in state.get("debate_log", []):
        print(f"\n{entry}")

    print(f"\n{'='*60}")
    print("✅ 최종 결정")
    print("-" * 40)
    print(f"결정: {state.get('final_decision', 'N/A')}")
    targets = state.get("target_stocks", [])
    if targets:
        print("대상 종목:")
        for t in targets:
            print(f"  - {t.get('name', '')}({t.get('code', '')}) {t.get('price', '')}원")

    print(f"\n{'='*60}")
    print("💹 매매 실행 결과")
    print("-" * 40)
    results = state.get("trade_results", [])
    if results:
        for r in results:
            if r.get("mode") == "simulation":
                print(f"  [시뮬레이션] {r.get('action', '')} {r.get('name', '')}({r.get('code', '')})")
            else:
                print(f"  {r}")
    else:
        print("  매매 없음 (관망)")
    print("=" * 60)
