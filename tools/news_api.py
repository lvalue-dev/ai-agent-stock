"""Google News RSS 기반 뉴스 수집 - API 키 불필요"""
import re
from urllib.parse import quote
import feedparser


def get_news(query: str, limit: int = 10) -> list[dict]:
    """Google News RSS에서 뉴스 수집"""
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:limit]:
            title = entry.get("title", "")
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0].strip(), parts[1].strip()
            results.append({
                "title": title,
                "source": source or entry.get("source", {}).get("title", ""),
                "time": entry.get("published", ""),
                "summary": _clean(entry.get("summary", "")),
            })
        return results
    except Exception:
        return []


def get_market_news(limit: int = 20) -> list[dict]:
    """KOSPI·KOSDAQ 시장 전체 뉴스"""
    return get_news("코스피 코스닥 증시 주식시장", limit)


def get_stock_news(stock_name: str, limit: int = 8) -> list[dict]:
    """종목명으로 뉴스 검색"""
    return get_news(f"{stock_name} 주가 주식", limit)


def get_theme_news(theme: str, limit: int = 8) -> list[dict]:
    """테마별 뉴스 (반도체, AI, 2차전지 등)"""
    return get_news(f"{theme} 주식 투자", limit)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:400].strip()
