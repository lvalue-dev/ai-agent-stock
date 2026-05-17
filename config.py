import os
from dotenv import load_dotenv

load_dotenv()

# Google Gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"  # 무료 티어: 15 RPM, 1M TPM/day

# 한국투자증권 API
KIS_MODE = os.getenv("KIS_MODE", "virtual")  # real or virtual
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_ACCOUNT_PROD_CODE = os.getenv("KIS_ACCOUNT_PROD_CODE", "01")

KIS_BASE_URL = (
    "https://openapi.koreainvestment.com:9443"
    if KIS_MODE == "real"
    else "https://openapivts.koreainvestment.com:29443"
)

# 에이전트 설정
MAX_DEBATE_ROUNDS = int(os.getenv("MAX_DEBATE_ROUNDS", "3"))
AUTO_TRADE_ENABLED = os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"
MAX_TRADE_AMOUNT = int(os.getenv("MAX_TRADE_AMOUNT", "100000"))

# 분석 대상 시장
TARGET_MARKETS = ["KOSPI", "KOSDAQ"]
