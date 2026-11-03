# 한국 주식 멀티 에이전트 시스템

한국투자증권(KIS) OpenAPI 데이터와 LangGraph 멀티 에이전트로 시장을 분석하고,
실시간 웹소켓 체결/호가 신호가 발생하면 에이전트 분석을 자동으로 실행합니다.

## 구성

```
tools/kis_api.py        KIS REST 래퍼 (현재가, 지수, 거래량 상위, 투자자 동향, 잔고, 주문)
tools/kis_websocket.py  KIS 실시간 웹소켓 클라이언트 (체결가 H0STCNT0, 호가 H0STASP0)
realtime/buffer.py      종목별 틱 버퍼와 요약 지표 (1분/5분 변동, 거래량비, 체결강도, 호가 불균형)
realtime/signals.py     규칙 기반 신호 감지 (급등/급락, 거래량 급증, 체결강도, 호가 불균형, 전일 대비 거래량)
realtime/engine.py      웹소켓 → 버퍼 → 신호 → 에이전트 트리거, 대시보드용 스냅샷 기록
agents/                 시장·뉴스·스크리닝·거래량·기관/외국인·실시간·수퍼바이저 에이전트
graph/workflow.py       LangGraph 워크플로우
main.py                 실행 진입점 (1회 분석 / 실시간 모드)
dashboard.py            Streamlit 대시보드
```

에이전트 흐름:
시장 분석 → 뉴스 → 스크리닝 → 거래량 → 기관/외국인 → **실시간** → 수퍼바이저 토론 → 최종 결정

## 설정

```bash
pip install -r requirements.txt
cp .env.example .env     # KIS 앱키, LLM 키 입력
```

## 실행

```bash
# 1회 분석 (기존 방식)
python main.py

# 실시간 감시: 거래량 상위 종목을 자동 구독, 신호 발생 시 에이전트 실행
python main.py --realtime

# 종목 지정 + 호가 구독
python main.py --realtime --watch 005930,000660 --orderbook

# 신호만 기록 (LLM 호출 없음)
python main.py --realtime --dry-run

# 대시보드: 장이 열린 시간(평일 08:00~20:00)엔 스스로 KIS 웹소켓에 연결해 2초마다 자동 갱신
#           (main.py --realtime 이 따로 돌고 있으면 그 스냅샷을 읽어 같은 앱키로 소켓을 두 번 열지 않음)
streamlit run dashboard.py
```

## 프리마켓 / 애프터마켓

기본값 `KIS_MARKET=UN` 은 한국투자 KRX+넥스트레이드(NXT) 통합 시세를 씁니다.
REST 현재가·투자자동향·일별시세는 시장구분 `UN`, 웹소켓은 `H0UNCNT0`(체결)·`H0UNASP0`(호가)로 구독하므로
NXT 프리마켓(08:00~08:50)과 애프터마켓(15:40~20:00) 체결이 실시간으로 들어옵니다.
NXT 를 신청하지 않은 계좌나 NXT 비거래 종목은 자동으로 KRX(`J`) 조회로 폴백합니다.
틱·신호·스냅샷에는 `session` 라벨(프리마켓/동시호가/정규장/애프터마켓)이 붙습니다.

## 실시간 동작

1. `/oauth2/Approval` 로 웹소켓 접속키를 받고 `ws://ops.koreainvestment.com:21000` 에 연결합니다.
   (모의투자는 `:31000`)
2. 감시 종목의 체결가(통합 H0UNCNT0, KRX 전용이면 H0STCNT0)를 구독합니다. `--orderbook` 이면 호가도 구독합니다.
   KIS 세션당 등록 한도가 있어 기본 40건까지만 구독합니다.
3. 수신 틱은 `TickBuffer` 에 쌓이고, 틱마다 `SignalDetector` 가 규칙을 평가합니다.
4. 신호는 `REALTIME_BATCH_WINDOW_SEC` 동안 묶여 하나의 트리거 이벤트가 되고,
   `REALTIME_TRIGGER_COOLDOWN_SEC` 간격으로만 에이전트 그래프를 실행합니다.
5. 트리거 이벤트는 그래프 상태의 `trigger_event` 로 들어가 스크리닝 에이전트가 해당 종목을
   우선 분석하고, 실시간 에이전트가 신호를 해석한 뒤 수퍼바이저 토론에 반영됩니다.
6. 결과는 콘솔과 Discord(설정 시)로 전송되고, 스냅샷은 `data/realtime_snapshot.json` 에 5초마다 기록됩니다.
7. 대시보드 내장 엔진이 트리거한 분석은 "실시간 감시 현황" 아래 목록에서 "보기"로 불러올 수 있습니다.

연결이 끊기면 지수 백오프로 재접속하고 구독을 복구합니다. 90초간 수신이 없으면 재접속합니다.

## 테스트

```bash
pip install pytest
python -m pytest tests -q
```
