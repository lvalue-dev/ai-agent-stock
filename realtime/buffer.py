"""실시간 틱 버퍼 - 종목별 최근 체결/호가를 메모리에 유지하고 요약 지표를 계산"""
import threading
import time
from collections import deque
from typing import Optional

from tools.kis_websocket import Tick, OrderBook


class TickBuffer:
    def __init__(self, window_sec: int = 1800, max_ticks: int = 5000):
        self.window_sec = window_sec
        self.max_ticks = max_ticks
        self._ticks: dict[str, deque[Tick]] = {}
        self._books: dict[str, OrderBook] = {}
        self._names: dict[str, str] = {}
        self._first_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    # ── 입력 ────────────────────────────────────────────────────────
    def set_name(self, code: str, name: str) -> None:
        if name:
            self._names[code] = name

    def add(self, tick: Tick) -> None:
        with self._lock:
            dq = self._ticks.get(tick.code)
            if dq is None:
                dq = deque(maxlen=self.max_ticks)
                self._ticks[tick.code] = dq
                self._first_seen[tick.code] = tick.received_at
            dq.append(tick)
            self._evict(dq, tick.received_at)

    def add_orderbook(self, book: OrderBook) -> None:
        with self._lock:
            self._books[book.code] = book

    def _evict(self, dq: deque, now: float) -> None:
        cutoff = now - self.window_sec
        while dq and dq[0].received_at < cutoff:
            dq.popleft()

    # ── 조회 ────────────────────────────────────────────────────────
    def codes(self) -> list[str]:
        with self._lock:
            return list(self._ticks)

    def name(self, code: str) -> str:
        return self._names.get(code, "")

    def last(self, code: str) -> Optional[Tick]:
        with self._lock:
            dq = self._ticks.get(code)
            return dq[-1] if dq else None

    def orderbook(self, code: str) -> Optional[OrderBook]:
        return self._books.get(code)

    def ticks(self, code: str, seconds: Optional[float] = None, now: Optional[float] = None) -> list[Tick]:
        with self._lock:
            dq = self._ticks.get(code)
            if not dq:
                return []
            if seconds is None:
                return list(dq)
            now = now if now is not None else time.time()
            cutoff = now - seconds
            return [t for t in dq if t.received_at >= cutoff]

    def summary(self, code: str, now: Optional[float] = None) -> Optional[dict]:
        """신호 감지와 LLM 프롬프트에 쓰는 종목 요약"""
        now = now if now is not None else time.time()
        all_ticks = self.ticks(code, now=now)
        if not all_ticks:
            return None
        last = all_ticks[-1]
        t1m = [t for t in all_ticks if t.received_at >= now - 60]
        t5m = [t for t in all_ticks if t.received_at >= now - 300]

        span_sec = max(now - self._first_seen.get(code, all_ticks[0].received_at), 1.0)
        span_sec = min(span_sec, self.window_sec)
        total_vol = sum(t.volume for t in all_ticks)
        avg_vol_per_min = total_vol / (span_sec / 60.0)

        vol_1m = sum(t.volume for t in t1m)
        vol_5m = sum(t.volume for t in t5m)
        buy_5m = sum(t.volume for t in t5m if t.side == "buy")
        sell_5m = sum(t.volume for t in t5m if t.side == "sell")
        buy_ratio_5m = (buy_5m / (buy_5m + sell_5m) * 100) if (buy_5m + sell_5m) else 0.0

        def pct_change(ticks: list[Tick]) -> float:
            if len(ticks) < 2 or ticks[0].price <= 0:
                return 0.0
            return (ticks[-1].price - ticks[0].price) / ticks[0].price * 100

        book = self._books.get(code)
        imbalance = book.imbalance if book else (
            (last.total_bid_rsqn / last.total_ask_rsqn) if last.total_ask_rsqn > 0 else 0.0
        )

        return {
            "code": code,
            "name": self._names.get(code, ""),
            "time": last.time,
            "session": last.session,
            "price": last.price,
            "change": last.change,
            "change_rate": last.change_rate,          # 전일 대비 (%)
            "open": last.open,
            "high": last.high,
            "low": last.low,
            "high_5m": max(t.price for t in t5m) if t5m else last.price,
            "low_5m": min(t.price for t in t5m) if t5m else last.price,
            "pct_1m": round(pct_change(t1m), 2),
            "pct_5m": round(pct_change(t5m), 2),
            "pct_window": round(pct_change(all_ticks), 2),
            "vol_1m": vol_1m,
            "vol_5m": vol_5m,
            "avg_vol_per_min": round(avg_vol_per_min, 1),
            "vol_ratio_1m": round(vol_1m / avg_vol_per_min, 2) if avg_vol_per_min > 0 else 0.0,
            "acc_volume": last.acc_volume,
            "acc_amount": last.acc_amount,
            "strength": last.strength,
            "buy_ratio_5m": round(buy_ratio_5m, 1),
            "same_time_vol_rate": last.same_time_vol_rate,
            "prev_day_vol_rate": last.prev_day_vol_rate,
            "ask1": last.ask1,
            "bid1": last.bid1,
            "imbalance": round(imbalance, 2),
            "tick_count_1m": len(t1m),
            "data_span_sec": int(span_sec),
            "halted": last.halted,
        }

    def snapshot(self, codes: Optional[list[str]] = None, limit: int = 20, now: Optional[float] = None) -> list[dict]:
        """전 종목 요약을 5분 변동 폭 기준으로 정렬"""
        codes = codes if codes is not None else self.codes()
        rows = [s for c in codes if (s := self.summary(c, now=now))]
        rows.sort(key=lambda r: (abs(r["pct_5m"]), r["vol_ratio_1m"]), reverse=True)
        return rows[:limit]
