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


# ── 통합(KRX+NXT) 스트림 / 장 구분 ───────────────────────────────────
def test_parse_unified_trade_with_extra_trailing_fields():
    from tools.kis_websocket import TRADE_TR_IDS, MARKET_TR_IDS
    assert MARKET_TR_IDS["UN"] == ("H0UNCNT0", "H0UNASP0") and "H0UNCNT0" in TRADE_TR_IDS
    # 통합 스트림은 필드가 더 붙을 수 있다 → 레코드 2건 + 각 2개 추가 필드
    rec = _trade_payload(STCK_CNTG_HOUR="081512") + "^X^Y"
    rec2 = _trade_payload(MKSC_SHRN_ISCD="000660", STCK_CNTG_HOUR="081513") + "^X^Y"
    tr_id, recs = parse_message(f"0|H0UNCNT0|002|{rec}^{rec2}")
    assert tr_id == "H0UNCNT0" and [r.code for r in recs] == ["005930", "000660"]
    assert recs[0].price == 71000 and recs[0].session == "프리마켓"
    assert recs[0].to_dict()["session"] == "프리마켓"


def test_market_session_labels():
    from tools.kis_websocket import market_session
    assert market_session("080000") == "프리마켓"
    assert market_session("084959") == "프리마켓"
    assert market_session("085500") == "동시호가"
    assert market_session("093000") == "정규장"
    assert market_session("153500") == "장마감 동시호가"
    assert market_session("170000") == "애프터마켓"
    assert market_session("195959") == "애프터마켓"
    assert market_session("200000") == "장외"
    assert market_session("073000") == "장외"


def test_signal_message_carries_session():
    det = SignalDetector(price_spike_pct=2.0, cooldown_sec=0, min_history_sec=0)
    sig = det.evaluate(_summary(pct_5m=3.0, session="프리마켓"), now=1000)[0]
    assert sig.message.startswith("[프리마켓]") and sig.data["session"] == "프리마켓"
    sig2 = det.evaluate(_summary(code="000660", pct_5m=3.0, session="정규장"), now=1000)[0]
    assert not sig2.message.startswith("[") and sig2.data["session"] == "정규장"


def test_client_dispatches_unified_trade():
    ticks = []
    client = KISWebSocketClient(on_tick=ticks.append, approval_key_provider=lambda: "k")
    client.handle_message(f"0|H0UNCNT0|001|{_trade_payload()}")
    assert len(ticks) == 1 and ticks[0].code == "005930"


def test_buffer_tape_and_sparkline():
    buf = TickBuffer(window_sec=1800)
    t0 = 5_000_000.0
    for i in range(10):
        buf.add(_tick(price=70000 + i * 10, volume=i + 1, at=t0 + i * 60, side="buy" if i % 2 else "sell"))
    now = t0 + 9 * 60
    tape = buf.tape("005930", 3)
    assert [t["price"] for t in tape] == [70090, 70080, 70070] and tape[0]["side"] == "buy"
    spark = buf.sparkline("005930", points=30, seconds=600, now=now)
    assert len(spark) == 30 and spark[-1] == 70090 and spark[0] >= 70000 and all(isinstance(v, int) for v in spark)
    assert spark == sorted(spark)   # 단조 증가 데이터는 스파크라인도 증가
    s = buf.summary("005930", now=now)
    assert s["prev_price"] == 70080 and s["last_volume"] == 10 and len(s["tape"]) == 8 and len(s["spark"]) == 60


def test_buffer_candles_and_backfill():
    from realtime.buffer import kst_minute_ts
    buf = TickBuffer()
    for t, px, v in [("090001", 100, 5), ("090030", 110, 5), ("090059", 105, 5), ("090100", 106, 7)]:
        buf.add(_tick(price=px, volume=v, time=t, at=1.0))
    c = buf.candles("005930")
    assert [x["hhmm"] for x in c] == ["0900", "0901"]
    assert c[0]["open"] == 100 and c[0]["high"] == 110 and c[0]["low"] == 100 and c[0]["close"] == 105 and c[0]["volume"] == 15
    assert c[1]["time"] - c[0]["time"] == 60 and c[0]["time"] == kst_minute_ts("0900")
    # 백필: 없는 분은 추가, 있는 분은 거래량이 더 클 때만 교체
    n = buf.backfill_candles("005930", [
        {"time": "085900", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 3},
        {"time": "090000", "open": 100, "high": 112, "low": 99, "close": 105, "volume": 40},
        {"time": "090100", "open": 106, "high": 106, "low": 106, "close": 106, "volume": 1},
    ])
    assert n == 2
    c = buf.candles("005930")
    assert [x["hhmm"] for x in c] == ["0859", "0900", "0901"] and c[1]["high"] == 112 and c[2]["volume"] == 7
    assert buf.candles("005930", last=1)[0]["hhmm"] == "0901"


def test_engine_live_feed_shape(tmp_path):
    engine = RealtimeEngine(watchlist=[{"code": "005930", "name": "삼성전자"}, {"code": "000660", "name": "SK하이닉스"}],
                            client=FakeClient(), snapshot_path=None, live_dir=str(tmp_path / "live"), backfill_pages=0)
    engine.handle_tick(_tick(price=70000, volume=10, time="091000", at=time.time()))
    engine.write_live(full=True)
    feed = json.loads((tmp_path / "live" / "live.json").read_text(encoding="utf-8"))
    assert [q["code"] for q in feed["quotes"]] == ["005930", "000660"]
    q = feed["quotes"][0]
    assert q["price"] == 70000 and q["last"]["hhmm"] == "0910" and q["prev"] is None
    assert feed["quotes"][1]["last"] is None and feed["quotes"][1]["name"] == "SK하이닉스"
    full = json.loads((tmp_path / "live" / "candles" / "005930.json").read_text(encoding="utf-8"))
    assert full["candles"][0]["close"] == 70000
