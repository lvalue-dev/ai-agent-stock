"""실시간 엔진 - 웹소켓 → 틱 버퍼 → 신호 감지 → 에이전트 트리거

수신 스레드는 버퍼 적재와 규칙 평가만 하고, LLM 그래프 실행처럼 오래 걸리는 일은
별도 워커 스레드가 큐에서 꺼내 처리한다.
"""
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from config import (
    WATCHLIST, WATCHLIST_AUTO_LIMIT, REALTIME_MAX_SUBSCRIPTIONS, REALTIME_ORDERBOOK,
    REALTIME_TRIGGER_COOLDOWN_SEC, REALTIME_BATCH_WINDOW_SEC, REALTIME_SNAPSHOT_PATH,
    REALTIME_LIVE_DIR, REALTIME_BACKFILL_PAGES,
)
from tools.kis_websocket import KISWebSocketClient, Tick, OrderBook, market_session, TR_TRADE, KST
from config import KIS_MARKET
from realtime.buffer import TickBuffer
from realtime.signals import Signal, SignalDetector

log = logging.getLogger(__name__)

TriggerHandler = Callable[[dict], None]


def build_watchlist(codes: Optional[list[str]] = None, limit: Optional[int] = None) -> list[dict]:
    """감시 종목 목록 생성. 코드가 없으면 거래량 상위 종목을 자동 선정."""
    from tools.kis_api import get_top_volume_stocks, get_stock_price

    limit = limit or WATCHLIST_AUTO_LIMIT
    codes = codes or WATCHLIST
    result: list[dict] = []
    if codes:
        for code in codes:
            name = ""
            try:
                name = get_stock_price(code).get("name", "")
            except Exception as e:
                log.warning("%s 종목명 조회 실패: %s", code, e)
            result.append({"code": code, "name": name})
        return result

    seen = set()
    for market in ("KOSPI", "KOSDAQ"):
        try:
            for s in get_top_volume_stocks(market, limit=limit):
                code = s.get("code", "")
                if code and code not in seen:
                    seen.add(code)
                    result.append({"code": code, "name": s.get("name", ""), "market": market})
        except Exception as e:
            log.warning("%s 거래량 상위 조회 실패: %s", market, e)
    return result[:limit]


class RealtimeEngine:
    def __init__(
        self,
        watchlist: list[dict],
        on_trigger: Optional[TriggerHandler] = None,
        orderbook: bool = REALTIME_ORDERBOOK,
        buffer: Optional[TickBuffer] = None,
        detector: Optional[SignalDetector] = None,
        client: Optional[KISWebSocketClient] = None,
        trigger_cooldown_sec: int = REALTIME_TRIGGER_COOLDOWN_SEC,
        batch_window_sec: float = REALTIME_BATCH_WINDOW_SEC,
        snapshot_path: Optional[str] = REALTIME_SNAPSHOT_PATH,
        snapshot_interval_sec: float = 1.0,
        max_subscriptions: int = REALTIME_MAX_SUBSCRIPTIONS,
        live_dir: Optional[str] = REALTIME_LIVE_DIR,
        backfill_pages: int = REALTIME_BACKFILL_PAGES,
    ):
        self.watchlist = watchlist
        self.on_trigger = on_trigger
        self.orderbook = orderbook
        self.buffer = buffer or TickBuffer()
        self.detector = detector or SignalDetector()
        self.client = client or KISWebSocketClient(
            on_tick=self.handle_tick, on_orderbook=self.handle_orderbook,
            max_subscriptions=max_subscriptions,
        )
        self.trigger_cooldown_sec = trigger_cooldown_sec
        self.batch_window_sec = batch_window_sec
        self.snapshot_path = snapshot_path
        self.snapshot_interval_sec = snapshot_interval_sec
        self.live_dir = live_dir
        self.backfill_pages = backfill_pages
        self.backfilled: set[str] = set()
        self.last_error = ""          # 피드/스냅샷 기록 실패 등 진단용
        self.live_writes = 0

        self._queue: queue.Queue[Signal] = queue.Queue()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._snapshot_thread: Optional[threading.Thread] = None
        self._last_trigger_at = 0.0
        self.recent_signals: list[Signal] = []
        self.trigger_count = 0
        self.started_at: Optional[float] = None

        for item in watchlist:
            self.buffer.set_name(item["code"], item.get("name", ""))

    # ── 수명 주기 ───────────────────────────────────────────────────
    def start(self) -> None:
        self.started_at = time.time()
        self._stop.clear()
        subscribed = 0
        per_code = 2 if self.orderbook else 1
        for item in self.watchlist:
            if (subscribed + per_code) > self.client.max_subscriptions:
                log.warning("구독 한도 도달, %d 종목만 감시", subscribed // per_code)
                break
            if self.client.subscribe(item["code"], orderbook=self.orderbook):
                subscribed += per_code
        self.client.start()
        self._worker = threading.Thread(target=self._worker_loop, name="rt-worker", daemon=True)
        self._worker.start()
        if self.snapshot_path or self.live_dir:
            self._snapshot_thread = threading.Thread(target=self._snapshot_loop, name="rt-snapshot", daemon=True)
            self._snapshot_thread.start()
        if self.backfill_pages > 0:
            threading.Thread(target=self._backfill_loop, name="rt-backfill", daemon=True).start()
        log.info("실시간 엔진 시작: %d 종목 감시 (호가 %s)", subscribed // per_code, "포함" if self.orderbook else "제외")

    def stop(self) -> None:
        self._stop.set()
        self.client.stop()
        if self._worker:
            self._worker.join(timeout=5)
        self.write_snapshot()
        self.write_live(full=True)

    def run_forever(self) -> None:
        """Ctrl+C 까지 대기"""
        try:
            while not self._stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    # ── 수신 콜백 (웹소켓 스레드) ──────────────────────────────────
    def handle_tick(self, tick: Tick) -> None:
        self.buffer.add(tick)
        summary = self.buffer.summary(tick.code, now=tick.received_at)
        for sig in self.detector.evaluate(summary, now=tick.received_at):
            log.info("⚡ 신호: %s", sig.message)
            self._queue.put(sig)

    def handle_orderbook(self, book: OrderBook) -> None:
        self.buffer.add_orderbook(book)

    # ── 워커 (트리거 스레드) ───────────────────────────────────────
    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            batch = [first]
            deadline = time.time() + self.batch_window_sec
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            self._record(batch)
            if not self.on_trigger:
                continue
            now = time.time()
            if now - self._last_trigger_at < self.trigger_cooldown_sec:
                log.info("트리거 쿨다운 중 (%d초 남음), 신호 %d건은 기록만",
                         int(self.trigger_cooldown_sec - (now - self._last_trigger_at)), len(batch))
                continue
            self._last_trigger_at = now
            self.trigger_count += 1
            event = self.build_event(batch)
            try:
                self.on_trigger(event)
            except Exception as e:
                log.exception("트리거 핸들러 오류: %s", e)

    def _record(self, signals: list[Signal]) -> None:
        self.recent_signals.extend(signals)
        self.recent_signals = self.recent_signals[-100:]

    def build_event(self, signals: list[Signal]) -> dict:
        """에이전트 그래프에 넘길 트리거 이벤트"""
        signals = sorted(signals, key=lambda s: s.score, reverse=True)
        codes: list[str] = []
        for s in signals:
            if s.code not in codes:
                codes.append(s.code)
        return {
            "at": datetime.now(KST).isoformat(timespec="seconds"),
            "session": market_session(),
            "signals": [s.to_dict() for s in signals],
            "codes": codes,
            "stocks": [{"code": c, "name": self.buffer.name(c)} for c in codes],
            "summary": "; ".join(s.message for s in signals[:5]),
            "snapshot": self.buffer.snapshot(limit=15),
            "focus": [self.buffer.summary(c) for c in codes[:5]],
        }

    # ── 스냅샷 (대시보드용) ────────────────────────────────────────
    def status(self) -> dict:
        return {
            "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "started_at": datetime.fromtimestamp(self.started_at, KST).isoformat(timespec="seconds") if self.started_at else None,
            "connected": self.client.connected.is_set(),
            "market": KIS_MARKET,
            "tr_id": TR_TRADE,
            "session": market_session(),
            "watchlist": self.watchlist,
            "stats": dict(self.client.stats),
            "trigger_count": self.trigger_count,
            "diag": self.diagnostics(),
            "last_trigger_at": datetime.fromtimestamp(self._last_trigger_at, KST).isoformat(timespec="seconds") if self._last_trigger_at else None,
            "snapshot": self.buffer.snapshot(limit=50),
            "signals": [s.to_dict() for s in self.recent_signals[-30:]][::-1],
        }

    def diagnostics(self) -> dict:
        """대시보드 진단 패널용"""
        c = self.client
        last_tick = getattr(c, "last_tick_at", 0.0)
        return {
            "connected": c.connected.is_set(),
            "last_event": getattr(c, "last_event", ""),
            "ticks": c.stats.get("ticks", 0),
            "last_tick_age_sec": int(time.time() - last_tick) if last_tick else None,
            "subscriptions": len(getattr(c, "subscriptions", []) or []),
            "watchlist": len(self.watchlist),
            "backfilled": len(self.backfilled),
            "live_dir": os.path.abspath(self.live_dir) if self.live_dir else None,
            "live_writes": self.live_writes,
            "last_error": self.last_error,
            "trigger_count": self.trigger_count,
            "uptime_sec": int(time.time() - self.started_at) if self.started_at else 0,
        }

    def write_snapshot(self) -> None:
        if not self.snapshot_path:
            return
        try:
            os.makedirs(os.path.dirname(self.snapshot_path) or ".", exist_ok=True)
            tmp = self.snapshot_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.status(), f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.snapshot_path)
        except Exception as e:
            self.last_error = f"스냅샷 저장 실패 ({self.snapshot_path}): {e}"
            log.warning(self.last_error)

    def _snapshot_loop(self) -> None:
        n = 0
        while not self._stop.is_set():
            self.write_snapshot()
            self.write_live(full=(n % 5 == 0))
            n += 1
            self._stop.wait(self.snapshot_interval_sec)

    # ── 차트 피드 (대시보드 차트 컴포넌트가 1초마다 읽음) ──────────────
    def live_feed(self) -> dict:
        quotes = []
        for item in self.watchlist:
            code = item["code"]
            summ = self.buffer.summary(code)
            last2 = self.buffer.candles(code, last=2)
            q = {"code": code, "name": item.get("name", "") or self.buffer.name(code)}
            if summ:
                q.update({k: summ.get(k) for k in (
                    "price", "change", "change_rate", "open", "high", "low", "acc_volume", "acc_amount",
                    "strength", "last_volume", "last_side", "time", "session", "ask1", "bid1",
                    "vol_ratio_1m", "pct_5m", "buy_ratio_5m",
                )})
            q["last"] = last2[-1] if last2 else None
            q["prev"] = last2[-2] if len(last2) > 1 else None
            q["backfilled"] = code in self.backfilled
            quotes.append(q)
        return {
            "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "session": market_session(),
            "connected": self.client.connected.is_set(),
            "market": KIS_MARKET,
            "quotes": quotes,
        }

    def write_live(self, full: bool = False) -> None:
        """static/live/live.json (매초) + static/live/candles/<code>.json (5초마다)"""
        if not self.live_dir:
            return
        try:
            os.makedirs(os.path.join(self.live_dir, "candles"), exist_ok=True)
            self._atomic_json(os.path.join(self.live_dir, "live.json"), self.live_feed())
            if full:
                for item in self.watchlist:
                    code = item["code"]
                    self._atomic_json(
                        os.path.join(self.live_dir, "candles", f"{code}.json"),
                        {"code": code, "name": item.get("name", ""), "candles": self.buffer.candles(code)},
                    )
            self.live_writes += 1
        except Exception as e:
            self.last_error = f"피드 저장 실패 ({self.live_dir}): {e}"
            log.warning(self.last_error)

    @staticmethod
    def _atomic_json(path: str, obj) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)

    # ── 당일 분봉 백필 (REST, 백그라운드) ───────────────────────────────
    def _backfill_loop(self) -> None:
        from tools.kis_api import get_minute_candles
        for item in self.watchlist:
            if self._stop.is_set():
                return
            code = item["code"]
            try:
                rows = get_minute_candles(code, pages=self.backfill_pages)
                n = self.buffer.backfill_candles(code, rows)
                self.backfilled.add(code)
                log.info("분봉 백필 %s: %d건", code, n)
            except Exception as e:
                log.warning("분봉 백필 실패 %s: %s", code, e)
            self._stop.wait(0.15)
        self.write_live(full=True)
