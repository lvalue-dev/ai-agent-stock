"""실시간 모듈 단위 테스트 - 네트워크 없이 파서/버퍼/신호/엔진 검증"""
import json
import time

import pytest

from tools.kis_websocket import (
    TR_TRADE, TR_ORDERBOOK, TRADE_FIELDS, ORDERBOOK_FIELDS,
    parse_message, build_subscribe_message, KISWebSocketClient, Tick,
)
from realtime.buffer import TickBuffer
from realtime.signals import SignalDetector
from realtime.engine import RealtimeEngine


# ── 헬퍼 ───────────────────────────────────────────────────────────
def _trade_payload(**over) -> str:
    base = {name: "0" for name in TRADE_FIELDS}
    base.update({
        "MKSC_SHRN_ISCD": "005930", "STCK_CNTG_HOUR": "093015", "STCK_PRPR": "71000",
        "PRDY_VRSS_SIGN": "2", "PRDY_VRSS": "500", "PRDY_CTRT": "0.71",
        "STCK_OPRC": "70500", "STCK_HGPR": "71200", "STCK_LWPR": "70300",
        "ASKP1": "71100", "BIDP1": "71000", "CNTG_VOL": "150", "ACML_VOL": "1234567",
        "ACML_TR_PBMN": "87654321000", "CTTR": "120.5", "CCLD_DVSN": "1", "SHNU_RATE": "55.2",
        "PRDY_SMNS_HOUR_ACML_VOL_RATE": "140.0", "TOTAL_ASKP_RSQN": "10000", "TOTAL_BIDP_RSQN": "12000",
        "TRHT_YN": "N",
    })
    base.update(over)
    return "^".join(base[n] for n in TRADE_FIELDS)


def _tick(code="005930", price=71000, volume=100, side="buy", strength=100.0, at=0.0, **over) -> Tick:
    kw = dict(
        code=code, time="093000", price=price, change=0, change_rate=0.0, open=price, high=price, low=price,
        ask1=price + 100, bid1=price, volume=volume, acc_volume=0, acc_amount=0, strength=strength, side=side,
        buy_ratio=50.0, prev_day_vol_rate=0.0, same_time_vol_rate=0.0, ask_rsqn1=0, bid_rsqn1=0,
        total_ask_rsqn=1000, total_bid_rsqn=1000, halted=False, received_at=at,
    )
    kw.update(over)
    return Tick(**kw)


# ── 파서 ───────────────────────────────────────────────────────────
def test_parse_single_trade():
    tr_id, recs = parse_message(f"0|{TR_TRADE}|001|{_trade_payload()}")
    assert tr_id == TR_TRADE and len(recs) == 1
    t = recs[0]
    assert t.code == "005930" and t.price == 71000 and t.change == 500
    assert t.side == "buy" and t.strength == 120.5 and t.volume == 150
    assert t.same_time_vol_rate == 140.0 and t.total_bid_rsqn == 12000


def test_parse_multiple_records_and_sign():
    payload = _trade_payload() + "^" + _trade_payload(MKSC_SHRN_ISCD="000660", PRDY_VRSS_SIGN="5", PRDY_VRSS="300", CCLD_DVSN="5")
    tr_id, recs = parse_message(f"0|{TR_TRADE}|002|{payload}")
    assert [r.code for r in recs] == ["005930", "000660"]
    assert recs[1].change == -300 and recs[1].side == "sell"


def test_parse_orderbook():
    fields = {n: "0" for n in ORDERBOOK_FIELDS}
    fields.update({"MKSC_SHRN_ISCD": "005930", "BSOP_HOUR": "093000", "ASKP1": "71100", "BIDP1": "71000",
                   "ASKP_RSQN1": "500", "BIDP_RSQN1": "1500", "TOTAL_ASKP_RSQN": "4000", "TOTAL_BIDP_RSQN": "10000"})
    payload = "^".join(fields[n] for n in ORDERBOOK_FIELDS)
    tr_id, recs = parse_message(f"0|{TR_ORDERBOOK}|001|{payload}")
    book = recs[0]
    assert tr_id == TR_ORDERBOOK and book.asks[0] == (71100, 500) and book.bids[0] == (71000, 1500)
    assert book.imbalance == pytest.approx(2.5)


def test_parse_rejects_encrypted_and_unknown():
    with pytest.raises(ValueError):
        parse_message(f"1|H0STCNI0|001|abc")
    assert parse_message("0|H0XXXX|001|a^b") == ("H0XXXX", [])


def test_subscribe_message_shape():
    msg = json.loads(build_subscribe_message("key", TR_TRADE, "005930"))
    assert msg["header"]["approval_key"] == "key" and msg["header"]["tr_type"] == "1"
    assert msg["body"]["input"] == {"tr_id": TR_TRADE, "tr_key": "005930"}
    assert json.loads(build_subscribe_message("key", TR_TRADE, "005930", subscribe=False))["header"]["tr_type"] == "2"


# ── 클라이언트 디스패치 ───────────────────────────────────────────
def test_client_dispatch_and_pingpong():
    ticks, sent = [], []
    client = KISWebSocketClient(on_tick=ticks.append, approval_key_provider=lambda: "k")
    client._send = sent.append
    client.handle_message(f"0|{TR_TRADE}|001|{_trade_payload()}")
    assert len(ticks) == 1 and client.stats["ticks"] == 1
    ping = json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20260101"}})
    client.handle_message(ping)
    assert sent == [ping]
    client.handle_message(json.dumps({"header": {"tr_id": TR_TRADE, "tr_key": "005930"}, "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"}}))


def test_client_subscription_limit():
    client = KISWebSocketClient(on_tick=lambda t: None, max_subscriptions=3, approval_key_provider=lambda: "k")
    assert client.subscribe("000001", orderbook=True)   # 2건
    assert client.subscribe("000002")                   # 3건
    assert not client.subscribe("000003")               # 한도 초과
    assert len(client.subscriptions) == 3
    client.unsubscribe("000001")
    assert len(client.subscriptions) == 1


# ── 버퍼 ───────────────────────────────────────────────────────────
def test_buffer_summary_metrics():
    buf = TickBuffer(window_sec=1800)
    buf.set_name("005930", "삼성전자")
    t0 = 1_000_000.0
    # 10분간 분당 100주 꾸준히 체결, 가격 70000
    for i in range(600):
        buf.add(_tick(price=70000, volume=10, at=t0 + i, side="buy" if i % 2 else "sell"))
    # 마지막 1분 급등 + 거래량 폭증
    for i in range(60):
        buf.add(_tick(price=70000 + i * 30, volume=100, at=t0 + 600 + i, side="buy", strength=180))
    now = t0 + 660
    s = buf.summary("005930", now=now)
    assert s["name"] == "삼성전자" and s["price"] == 70000 + 59 * 30
    assert s["pct_5m"] > 2.0 and s["pct_1m"] > 2.0
    assert s["vol_1m"] == 6000 and s["vol_ratio_1m"] > 3
    assert s["buy_ratio_5m"] > 50 and s["strength"] == 180
    assert s["data_span_sec"] == 660


def test_buffer_evicts_old_ticks():
    buf = TickBuffer(window_sec=60)
    buf.add(_tick(at=0.0))
    buf.add(_tick(at=100.0))
    assert len(buf.ticks("005930")) == 1


# ── 신호 ───────────────────────────────────────────────────────────
def _summary(**over) -> dict:
    base = dict(code="005930", name="삼성전자", price=70000, pct_1m=0.0, pct_5m=0.0, vol_1m=100,
                vol_ratio_1m=1.0, avg_vol_per_min=100, strength=100.0, buy_ratio_5m=50.0, imbalance=1.0,
                same_time_vol_rate=100.0, data_span_sec=600, halted=False)
    base.update(over)
    return base


def test_detector_rules():
    det = SignalDetector(price_spike_pct=2.0, volume_surge_ratio=3.0, strength_threshold=150,
                         imbalance_ratio=2.5, cooldown_sec=600, min_history_sec=300)
    kinds = {s.kind for s in det.evaluate(_summary(pct_5m=2.5, vol_ratio_1m=4.0, strength=160, imbalance=3.0, same_time_vol_rate=350), now=1000)}
    assert kinds == {"price_spike", "volume_surge", "strength", "bid_imbalance", "day_volume"}
    assert {s.kind for s in det.evaluate(_summary(code="000660", pct_5m=-3.0, imbalance=0.2), now=1000)} == {"price_drop", "ask_imbalance"}


def test_detector_cooldown_and_history_guard():
    det = SignalDetector(price_spike_pct=2.0, cooldown_sec=600, min_history_sec=300)
    assert [s.kind for s in det.evaluate(_summary(pct_5m=3.0), now=1000)] == ["price_spike"]
    assert det.evaluate(_summary(pct_5m=3.0), now=1100) == []          # 쿨다운
    assert [s.kind for s in det.evaluate(_summary(pct_5m=3.0), now=1700)] == ["price_spike"]
    assert det.evaluate(_summary(vol_ratio_1m=10.0, data_span_sec=60), now=2000) == []  # 기준치 부족
    assert det.evaluate(_summary(pct_5m=5.0, halted=True), now=3000) == []


# ── 엔진 ───────────────────────────────────────────────────────────
class FakeClient:
    def __init__(self):
        self.max_subscriptions = 40
        self.subs = []
        self.stats = {"ticks": 0}
        import threading
        self.connected = threading.Event()

    def subscribe(self, code, orderbook=False):
        self.subs.append((code, orderbook)); return True

    def start(self): self.connected.set()
    def stop(self): self.connected.clear()


def test_engine_triggers_once_per_cooldown(tmp_path):
    events = []
    engine = RealtimeEngine(
        watchlist=[{"code": "005930", "name": "삼성전자"}],
        on_trigger=events.append,
        client=FakeClient(),
        detector=SignalDetector(price_spike_pct=1.0, cooldown_sec=0, min_history_sec=0),
        trigger_cooldown_sec=600,
        batch_window_sec=0.1,
        snapshot_path=str(tmp_path / "snap.json"),
        snapshot_interval_sec=0.2,
    )
    engine.start()
    assert engine.client.subs == [("005930", False)]
    now = time.time()
    engine.handle_tick(_tick(price=70000, at=now - 100))
    engine.handle_tick(_tick(price=72000, at=now))     # +2.86% → 신호
    engine.handle_tick(_tick(price=72500, at=now + 1)) # 같은 배치에 묶임
    deadline = time.time() + 3
    while not events and time.time() < deadline:
        time.sleep(0.05)
    assert len(events) == 1
    ev = events[0]
    assert ev["codes"] == ["005930"] and ev["stocks"][0]["name"] == "삼성전자"
    assert ev["signals"][0]["kind"] == "price_spike" and ev["focus"][0]["price"] == 72500
    assert "급등" in ev["summary"]

    # 쿨다운 안의 추가 신호는 기록만 되고 트리거되지 않음
    engine.handle_tick(_tick(price=75000, at=now + 2))
    time.sleep(0.4)
    assert len(events) == 1 and len(engine.recent_signals) >= 2

    time.sleep(0.3)
    engine.stop()
    snap = json.loads((tmp_path / "snap.json").read_text(encoding="utf-8"))
    assert snap["trigger_count"] == 1 and snap["snapshot"][0]["code"] == "005930"
    assert snap["signals"][0]["kind"] == "price_spike"
