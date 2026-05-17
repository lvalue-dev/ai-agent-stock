"""한국 주식 멀티 에이전트 시스템 - 메인 실행 파일"""
import sys
from graph.workflow import build_graph, get_initial_state
from utils.logger import print_separator, print_final_report
from config import KIS_APP_KEY, GOOGLE_API_KEY, GROQ_API_KEY, LLM_PROVIDER, KIS_MODE, AUTO_TRADE_ENABLED, MAX_DEBATE_ROUNDS


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


def print_startup_info():
    print_separator("한국 주식 멀티 에이전트 시스템")
    print(f"""
🤖 에이전트 구성:
  1. 📊 시장 분석 에이전트 - KOSPI/KOSDAQ 시장 흐름 분석
  2. 📰 뉴스 분석 에이전트 - 시장 뉴스 및 공시 분석
  3. 🔍 스크리닝 에이전트  - 투자 유망 종목 발굴
  4. 🎯 수퍼바이저 에이전트 - 토론 진행 및 최종 의사결정
  5. 💹 매매 실행 에이전트  - 주문 실행

⚙️  설정:
  - LLM: {LLM_PROVIDER.upper()} ({'Groq - llama-3.3-70b' if LLM_PROVIDER == 'groq' else 'Google Gemini 2.0 Flash'})
  - KIS 모드: {KIS_MODE.upper()} ({'실전 투자' if KIS_MODE == 'real' else '모의 투자'})
  - 자동 매매: {'활성화' if AUTO_TRADE_ENABLED else '비활성화 (시뮬레이션)'}
  - 최대 토론 라운드: {MAX_DEBATE_ROUNDS}회
""")
    print_separator()


def run():
    if not validate_config():
        sys.exit(1)

    print_startup_info()

    print("\n🚀 멀티 에이전트 분석 시작...\n")

    # 워크플로우 그래프 빌드
    app = build_graph()
    initial_state = get_initial_state()

    # 스트리밍으로 진행 상황 출력하면서 전체 상태 누적
    accumulated_state = dict(initial_state)
    ran = False
    for step in app.stream(initial_state, {"recursion_limit": 50}):
        for node_name, node_output in step.items():
            if node_name != "__end__":
                print(f"\n  ✓ '{node_name}' 완료")
                if isinstance(node_output, dict):
                    accumulated_state.update(node_output)
        ran = True

    if ran:
        print("\n")
        print_final_report(accumulated_state)
    else:
        print("❌ 에이전트 실행 실패")


if __name__ == "__main__":
    run()
