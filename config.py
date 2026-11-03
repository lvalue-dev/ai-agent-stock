import os
from dotenv import load_dotenv

load_dotenv()

# LLM 제공자 설정 (groq 또는 gemini)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

# Groq API (무료 티어: 14,400 req/day, 30 RPM - https://console.groq.com)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Google Gemini API (무료 티어: 1,500 req/day, 15 RPM)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"

# 한국투자증권 API
KIS_MODE = os.getenv("KIS_MODE", "real")  # real or virtual
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_ACCOUNT_PROD_CODE = os.getenv("KIS_ACCOUNT_PROD_CODE", "01")

KIS_BASE_URL = (
    "https://openapi.koreainvestment.com:9443"
    if KIS_MODE == "real"
    else "https://openapivts.koreainvestment.com:29443"
)

# 시세 조회 시장 구분: J=KRX 정규장만, NX=넥스트레이드만, UN=KRX+NXT 통합 (프리/애프터마켓 포함)
KIS_MARKET = os.getenv("KIS_MARKET", "UN").upper()
if KIS_MARKET not in ("J", "NX", "UN"):
    KIS_MARKET = "UN"

# 에이전트 설정
MAX_DEBATE_ROUNDS = int(os.getenv("MAX_DEBATE_ROUNDS", "3"))
AUTO_TRADE_ENABLED = os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"
MAX_TRADE_AMOUNT = int(os.getenv("MAX_TRADE_AMOUNT", "100000"))

# Discord Webhook
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 분석 대상 시장
TARGET_MARKETS = ["KOSPI", "KOSDAQ"]

# ── 실시간 (KIS WebSocket) 설정 ──────────────────────────────────────
KIS_WS_URL = (
    "ws://ops.koreainvestment.com:21000"
    if KIS_MODE == "real"
    else "ws://ops.koreainvestment.com:31000"
)

# 감시 종목 (쉼표 구분 종목코드). 비워두면 거래량 상위 종목을 자동 선정
WATCHLIST = [c.strip() for c in os.getenv("WATCHLIST", "").split(",") if c.strip()]
WATCHLIST_AUTO_LIMIT = int(os.getenv("WATCHLIST_AUTO_LIMIT", "20"))

# KIS 웹소켓은 세션당 등록 가능한 건수 제한이 있음 (실전 41건)
REALTIME_MAX_SUBSCRIPTIONS = int(os.getenv("REALTIME_MAX_SUBSCRIPTIONS", "40"))
REALTIME_ORDERBOOK = os.getenv("REALTIME_ORDERBOOK", "false").lower() == "true"

# 신호 감지 임계값
REALTIME_PRICE_SPIKE_PCT = float(os.getenv("REALTIME_PRICE_SPIKE_PCT", "2.0"))     # N분 내 등락률 (%)
REALTIME_PRICE_WINDOW_SEC = int(os.getenv("REALTIME_PRICE_WINDOW_SEC", "300"))     # 등락률 측정 구간 (초)
REALTIME_VOLUME_SURGE_RATIO = float(os.getenv("REALTIME_VOLUME_SURGE_RATIO", "3.0"))  # 1분 거래량 / 평균 1분 거래량
REALTIME_STRENGTH_THRESHOLD = float(os.getenv("REALTIME_STRENGTH_THRESHOLD", "150"))  # 체결강도
REALTIME_IMBALANCE_RATIO = float(os.getenv("REALTIME_IMBALANCE_RATIO", "2.5"))     # 호가 잔량 비율
REALTIME_SIGNAL_COOLDOWN_SEC = int(os.getenv("REALTIME_SIGNAL_COOLDOWN_SEC", "600"))  # 같은 종목·신호 재발생 억제
REALTIME_TRIGGER_COOLDOWN_SEC = int(os.getenv("REALTIME_TRIGGER_COOLDOWN_SEC", "900"))  # 에이전트 재실행 최소 간격
REALTIME_BATCH_WINDOW_SEC = float(os.getenv("REALTIME_BATCH_WINDOW_SEC", "3"))     # 신호 묶음 대기 시간

# 대시보드용 스냅샷 파일
REALTIME_SNAPSHOT_PATH = os.getenv("REALTIME_SNAPSHOT_PATH", "data/realtime_snapshot.json")
# 실시간 차트 피드 디렉터리 (Streamlit 정적 서빙 /app/static/live/ 로 노출). 비우면 기록 안 함
REALTIME_LIVE_DIR = os.getenv("REALTIME_LIVE_DIR", "static/live")
# 엔진 시작 시 당일 분봉 과거 구간 채우기 (30분 × 페이지 수, 0이면 생략)
REALTIME_BACKFILL_PAGES = int(os.getenv("REALTIME_BACKFILL_PAGES", "4"))
