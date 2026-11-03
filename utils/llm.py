"""LLM 팩토리 - Groq/Gemini 공통 인터페이스 + 429 자동 재시도"""
import time
from langchain_core.language_models.chat_models import BaseChatModel
from config import (
    LLM_PROVIDER,
    GROQ_API_KEY, GROQ_MODEL,
    GOOGLE_API_KEY, GEMINI_MODEL,
)


def create_llm(temperature: float = 0.3) -> BaseChatModel:
    if LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=GROQ_MODEL,
            groq_api_key=GROQ_API_KEY,
            temperature=temperature,
        )
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=temperature,
        )


# 재시도 대기 상황을 UI 등에 알리고 싶을 때 설정 (message: str) -> None
RETRY_LISTENER = None


def _notify(message: str) -> None:
    print(f"  ⏳ {message}")
    if RETRY_LISTENER:
        try:
            RETRY_LISTENER(message)
        except Exception:
            pass


def invoke_with_retry(llm: BaseChatModel, messages: list, max_retries: int = 4) -> any:
    """429/503 오류 시 지수 백오프로 재시도"""
    delay = 30
    for attempt in range(max_retries):
        try:
            return llm.invoke(messages)
        except Exception as e:
            err = str(e)
            is_rate_limit = "429" in err or "RESOURCE_EXHAUSTED" in err or "rate_limit" in err.lower()
            is_unavailable = "503" in err or "UNAVAILABLE" in err
            if (is_rate_limit or is_unavailable) and attempt < max_retries - 1:
                _notify(f"LLM API 한도 초과({'429' if is_rate_limit else '503'}), {delay}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise
