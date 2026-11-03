"""실시간 틱 버퍼 - 종목별 최근 체결/호가를 메모리에 유지하고 요약 지표를 계산"""
import calendar
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

from tools.kis_websocket import Tick, OrderBook, KST


def kst_minute_ts(hhmm: str, day: Optional[datetime] = None) -> int:
    """오늘(KST) HHMM 을 '벽시계 시각을 UTC 로 간주한' 유닉스 초로. 차트 라이브러리가 KST 라벨을 그대로 찍게 한다."""
    d = day or datetime.now(KST)
    naive = datetime(d.year, d.month, d.day, int(hhmm[:2]), int(hhmm[2:4]))
    return calendar.timegm(naive.timetuple())


class TickBuffer:
    def __init__(self, window_sec: int = 1800, max_ticks: int = 5000):
        self.window_sec = window_sec
        self.max_ticks = max_ticks
        self._ticks: dict[str, deque[Tick]] = {}
        self._candles: dict[str, dict[str, list]] = {}   # code -> {HHMM: [o, h, l, c, v]}
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
            self._update_candle(tick)

    def _update_candle(self, tick: Tick) -> None:
        key = tick.time[:4] if len(tick.time) >= 4 and tick.time[:4].isdigit() else ""
        if not key or tick.price <= 0:
            return
        cd = self._candles.setdefault(tick.code, {})
        c = cd.get(key)
        if c is None:
            cd[key] = [tick.price, tick.price, tick.price, tick.price, tick.volume]
        else:
            c[1] = max(c[1], tick.price)
            c[2] = min(c[2], tick.price)
            c[3] = tick.price
            c[4] += tick.volume

    def backfill_candles(self, code: str, rows: list[dict]) -> int:
        """REST 분봉으로 과거 구간 채우기. rows: {time: HHMM[SS], open, high, low, close, volume}
        틱으로 만든 분봉이 이미 있고 거래량이 더 크면(더 완전하면) 유지한다."""
        n = 0
        with self._lock:
            cd = self._candles.setdefault(code, {})
            for r in rows:
                key = str(r.get("time", ""))[:4]
                if len(key) < 4 or not key.isdigit():
                    continue
                cur = cd.get(key)
                if cur is None or cur[4] < int(r.get("volume", 0)):
                    cd[key] = [int(r["open"]), int(r["high"]), int(r["low"]), int(r["close"]), int(r.get("volume", 0))]
                    n += 1
            self._candles[code] = dict(sorted(cd.items()))
        return n

    def candles(self, code: str, last: Optional[int] = None) -> list[dict]:
        """1분봉 (시간 오름차순). last=n 이면 최근 n 개만."""
        with self._lock:
            cd = self._candles.get(code, {})
            keys = sorted(cd)
            if last:
                keys = keys[-last:]
            return [
                {"time": kst_minute_ts(k), "hhmm": k, "open": cd[k][0], "high": cd[k][1],
                 "low": cd[k][2], "close": cd[k][3], "volume": cd[k][4]}
                for k in keys
            ]

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

    def tape(self, code: str, n: int = 10) -> list[dict]:
        """최근 체결 n건 (주식창 체결 테이프용, 최신이 앞)"""
        with self._lock:
            dq = self._ticks.get(code)
            if not dq:
                return []
            recent = list(dq)[-n:]
        return [
            {"time": t.time, "price": t.price, "volume": t.volume, "side": t.side}
            for t in reversed(recent)
        ]

    def sparkline(self, code: str, points: int = 60, seconds: int = 1800, now: Optional[float] = None) -> list[int]:
        """최근 seconds 구간을 points 개 버킷으로 나눠 버킷별 마지막 체결가 (빈 버킷은 직전 값)"""
        now = now if now is not None else time.time()
        ticks = self.ticks(code, seconds=seconds, now=now)
        if not ticks:
            return []
        start = now - seconds
        bucket = seconds / points
        out: list[Optional[int]] = [None] * points
        for t in ticks:
            idx = min(int((t.received_at - start) / bucket), points - 1)
            if idx >= 0:
                out[idx] = t.price
        # 앞쪽 빈 버킷은 첫 체결가로, 중간 빈 버킷은 직전 값으로 채운다
        first = next((v for v in out if v is not None), ticks[0].price)
        filled, prev = [], first
        for v in out:
            prev = v if v is not None else prev
            filled.append(prev)
        return filled

    def summary(self, code: str, now: Optional[float] = None) -> Optional[dict]:
        """신호 감지와 LLM 프롬프트에 쓰는 종목 요약"""
        now = now if now is not None else time.time()
        all_ticks = self.ticks(code, now=now)
        if not all_ticks:
            return None
        last = all_ticks[-1]
        prev = all_ticks[-2] if len(all_ticks) > 1 else last
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
            "prev_price": prev.price,          # 직전 체결가 (틱 방향 표시용)
            "last_volume": last.volume,
            "last_side": last.side,
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
            "spark": self.sparkline(code, seconds=int(max(60, min(self.window_sec, span_sec))), now=now),  # 데이터가 쌓인 만큼만
            "tape": self.tape(code, 8),
        }

    def snapshot(self, codes: Optional[list[str]] = None, limit: int = 20, now: Optional[float] = None) -> list[dict]:
        """전 종목 요약을 5분 변동 폭 기준으로 정렬"""
        codes = codes if codes is not None else self.codes()
        rows = [s for c in codes if (s := self.summary(c, now=now))]
        rows.sort(key=lambda r: (abs(r["pct_5m"]), r["vol_ratio_1m"]), reverse=True)
        return rows[:limit]
