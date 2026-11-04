"""한국투자증권 KIS 실시간 WebSocket 클라이언트

체결가 / 호가 tr_id 는 시장 구분(KIS_MARKET)에 따라 고른다.
  J  (KRX 정규장)      : H0STCNT0 / H0STASP0
  NX (넥스트레이드)     : H0NXCNT0 / H0NXASP0
  UN (KRX+NXT 통합)    : H0UNCNT0 / H0UNASP0  ← 프리마켓(08:00~)·애프터마켓(~20:00) 포함

메시지 형식
  데이터:   "0|H0STCNT0|001|필드1^필드2^..."   (첫 글자 0=평문, 1=암호화)
  제어:     JSON (구독 응답, PINGPONG)
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

KST = timezone(timedelta(hours=9))

import requests
import websocket

from config import (
    KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL, KIS_WS_URL, KIS_MARKET,
    REALTIME_MAX_SUBSCRIPTIONS,
)

log = logging.getLogger(__name__)

MARKET_TR_IDS = {
    "J":  ("H0STCNT0", "H0STASP0"),
    "NX": ("H0NXCNT0", "H0NXASP0"),
    "UN": ("H0UNCNT0", "H0UNASP0"),
}
TRADE_TR_IDS = {v[0] for v in MARKET_TR_IDS.values()}
ORDERBOOK_TR_IDS = {v[1] for v in MARKET_TR_IDS.values()}
TR_TRADE, TR_ORDERBOOK = MARKET_TR_IDS.get(KIS_MARKET, MARKET_TR_IDS["UN"])

# KIS 문서 순서 그대로 (H0STCNT0, 46개 필드)
TRADE_FIELDS = [
    "MKSC_SHRN_ISCD", "STCK_CNTG_HOUR", "STCK_PRPR", "PRDY_VRSS_SIGN", "PRDY_VRSS",
    "PRDY_CTRT", "WGHN_AVRG_STCK_PRC", "STCK_OPRC", "STCK_HGPR", "STCK_LWPR",
    "ASKP1", "BIDP1", "CNTG_VOL", "ACML_VOL", "ACML_TR_PBMN",
    "SELN_CNTG_CSNU", "SHNU_CNTG_CSNU", "NTBY_CNTG_CSNU", "CTTR", "SELN_CNTG_SMTN",
    "SHNU_CNTG_SMTN", "CCLD_DVSN", "SHNU_RATE", "PRDY_VOL_VRSS_ACML_VOL_RATE", "OPRC_HOUR",
    "OPRC_VRSS_PRPR_SIGN", "OPRC_VRSS_PRPR", "HGPR_HOUR", "HGPR_VRSS_PRPR_SIGN", "HGPR_VRSS_PRPR",
    "LWPR_HOUR", "LWPR_VRSS_PRPR_SIGN", "LWPR_VRSS_PRPR", "BSOP_DATE", "NEW_MKOP_CLS_CODE",
    "TRHT_YN", "ASKP_RSQN1", "BIDP_RSQN1", "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN",
    "VOL_TNRT", "PRDY_SMNS_HOUR_ACML_VOL", "PRDY_SMNS_HOUR_ACML_VOL_RATE", "HOUR_CLS_CODE",
    "MRKT_TRTM_CLS_CODE", "VI_STND_PRC",
]

# H0STASP0, 59개 필드
ORDERBOOK_FIELDS = (
    ["MKSC_SHRN_ISCD", "BSOP_HOUR", "HOUR_CLS_CODE"]
    + [f"ASKP{i}" for i in range(1, 11)]
    + [f"BIDP{i}" for i in range(1, 11)]
    + [f"ASKP_RSQN{i}" for i in range(1, 11)]
    + [f"BIDP_RSQN{i}" for i in range(1, 11)]
    + [
        "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN", "OVTM_TOTAL_ASKP_RSQN", "OVTM_TOTAL_BIDP_RSQN",
        "ANTC_CNPR", "ANTC_CNQN", "ANTC_VOL", "ANTC_CNTG_VRSS", "ANTC_CNTG_VRSS_SIGN",
        "ANTC_CNTG_PRDY_CTRT", "ACML_VOL", "TOTAL_ASKP_RSQN_ICDC", "TOTAL_BIDP_RSQN_ICDC",
        "OVTM_TOTAL_ASKP_ICDC", "OVTM_TOTAL_BIDP_ICDC", "STCK_DEAL_CLS_CODE",
    ]
)

def _field_names(tr_id: str) -> Optional[list[str]]:
    if tr_id in TRADE_TR_IDS:
        return TRADE_FIELDS
    if tr_id in ORDERBOOK_TR_IDS:
        return ORDERBOOK_FIELDS
    return None


def _int(v: str, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return default


def _float(v: str, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return default


@dataclass
class Tick:
    """실시간 체결 1건"""
    code: str
    time: str                 # HHMMSS
    price: int
    change: int               # 전일 대비 (부호 반영)
    change_rate: float        # 전일 대비율 (%)
    open: int
    high: int
    low: int
    ask1: int
    bid1: int
    volume: int               # 이번 체결 수량
    acc_volume: int           # 누적 거래량
    acc_amount: int           # 누적 거래대금
    strength: float           # 체결강도
    side: str                 # buy / sell / other
    buy_ratio: float          # 매수비율 (%)
    prev_day_vol_rate: float  # 전일 거래량 대비 누적 거래량 (%)
    same_time_vol_rate: float # 전일 동시간 누적 거래량 대비 (%)
    ask_rsqn1: int
    bid_rsqn1: int
    total_ask_rsqn: int
    total_bid_rsqn: int
    halted: bool = False
    received_at: float = field(default_factory=time.time)

    @property
    def session(self) -> str:
        return market_session(self.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["session"] = self.session
        return d


# ── 장 구분 ─────────────────────────────────────────────────────────
SESSIONS = [
    # (시작 HHMM, 끝 HHMM, 라벨)
    (800, 850, "프리마켓"),        # NXT 프리마켓
    (850, 900, "동시호가"),        # KRX 장전 동시호가 (NXT 는 08:50 종료)
    (900, 1530, "정규장"),
    (1530, 1540, "장마감 동시호가"),
    (1540, 1600, "애프터마켓"),     # NXT 애프터마켓 (15:40~20:00) + KRX 시간외 종가(15:40~16:00)
    (1600, 1800, "애프터마켓"),     # KRX 시간외 단일가 (16:00~18:00) 와 겹침
    (1800, 2000, "애프터마켓"),
]


def market_session(hhmmss: str = "", now: Optional[datetime] = None) -> str:
    """체결 시각(HHMMSS) 또는 현재 KST 기준 장 구분 라벨"""
    if hhmmss and len(hhmmss) >= 4 and hhmmss[:4].isdigit():
        hhmm = int(hhmmss[:4])
    else:
        now = now or datetime.now(KST)
        hhmm = now.hour * 100 + now.minute
    for start, end, label in SESSIONS:
        if start <= hhmm < end:
            return label
    return "장외"


@dataclass
class OrderBook:
    """실시간 호가 1건"""
    code: str
    time: str
    asks: list[tuple[int, int]]   # [(가격, 잔량)] 1~10호가
    bids: list[tuple[int, int]]
    total_ask_rsqn: int
    total_bid_rsqn: int
    expected_price: int
    expected_volume: int
    acc_volume: int
    received_at: float = field(default_factory=time.time)

    @property
    def imbalance(self) -> float:
        """매수잔량 / 매도잔량 (>1 매수 우위)"""
        if self.total_ask_rsqn <= 0:
            return 0.0
        return self.total_bid_rsqn / self.total_ask_rsqn

    def to_dict(self) -> dict:
        d = asdict(self)
        d["imbalance"] = round(self.imbalance, 3)
        return d


def _sign(sign_code: str) -> int:
    # 1:상한 2:상승 3:보합 4:하한 5:하락
    return -1 if sign_code in ("4", "5") else 1


def parse_trade_record(fields: dict[str, str]) -> Tick:
    side_code = fields.get("CCLD_DVSN", "")
    side = {"1": "buy", "5": "sell"}.get(side_code, "other")
    return Tick(
        code=fields.get("MKSC_SHRN_ISCD", ""),
        time=fields.get("STCK_CNTG_HOUR", ""),
        price=_int(fields.get("STCK_PRPR")),
        change=_sign(fields.get("PRDY_VRSS_SIGN", "")) * abs(_int(fields.get("PRDY_VRSS"))),
        change_rate=_float(fields.get("PRDY_CTRT")),
        open=_int(fields.get("STCK_OPRC")),
        high=_int(fields.get("STCK_HGPR")),
        low=_int(fields.get("STCK_LWPR")),
        ask1=_int(fields.get("ASKP1")),
        bid1=_int(fields.get("BIDP1")),
        volume=_int(fields.get("CNTG_VOL")),
        acc_volume=_int(fields.get("ACML_VOL")),
        acc_amount=_int(fields.get("ACML_TR_PBMN")),
        strength=_float(fields.get("CTTR")),
        side=side,
        buy_ratio=_float(fields.get("SHNU_RATE")),
        prev_day_vol_rate=_float(fields.get("PRDY_VOL_VRSS_ACML_VOL_RATE")),
        same_time_vol_rate=_float(fields.get("PRDY_SMNS_HOUR_ACML_VOL_RATE")),
        ask_rsqn1=_int(fields.get("ASKP_RSQN1")),
        bid_rsqn1=_int(fields.get("BIDP_RSQN1")),
        total_ask_rsqn=_int(fields.get("TOTAL_ASKP_RSQN")),
        total_bid_rsqn=_int(fields.get("TOTAL_BIDP_RSQN")),
        halted=fields.get("TRHT_YN", "N") == "Y",
    )


def parse_orderbook_record(fields: dict[str, str]) -> OrderBook:
    asks = [(_int(fields.get(f"ASKP{i}")), _int(fields.get(f"ASKP_RSQN{i}"))) for i in range(1, 11)]
    bids = [(_int(fields.get(f"BIDP{i}")), _int(fields.get(f"BIDP_RSQN{i}"))) for i in range(1, 11)]
    return OrderBook(
        code=fields.get("MKSC_SHRN_ISCD", ""),
        time=fields.get("BSOP_HOUR", ""),
        asks=asks,
        bids=bids,
        total_ask_rsqn=_int(fields.get("TOTAL_ASKP_RSQN")),
        total_bid_rsqn=_int(fields.get("TOTAL_BIDP_RSQN")),
        expected_price=_int(fields.get("ANTC_CNPR")),
        expected_volume=_int(fields.get("ANTC_VOL")),
        acc_volume=_int(fields.get("ACML_VOL")),
    )


def parse_message(raw: str) -> tuple[str, list]:
    """KIS 데이터 메시지 파싱.

    Returns: (tr_id, [Tick | OrderBook, ...]) — 알 수 없는 tr_id 면 (tr_id, [])
    한 메시지에 여러 레코드가 ^ 로 이어 붙어 올 수 있어 필드 수 단위로 자른다.
    """
    parts = raw.split("|", 3)
    if len(parts) < 4:
        raise ValueError(f"잘못된 메시지 형식: {raw[:80]}")
    encrypted, tr_id, count_str, payload = parts
    if encrypted == "1":
        # 체결가/호가는 평문. 암호화 데이터(체결통보 등)는 이 클라이언트 범위 밖
        raise ValueError(f"암호화된 메시지는 지원하지 않습니다: {tr_id}")

    names = _field_names(tr_id)
    if not names:
        return tr_id, []

    values = payload.split("^")
    count = max(_int(count_str, 1), 1)
    # 통합/NXT 스트림은 필드가 뒤에 더 붙을 수 있으므로 레코드 길이는 실제 값 수로 계산
    n_fields = max(len(values) // count, 1)
    records = []
    for i in range(count):
        chunk = values[i * n_fields:(i + 1) * n_fields]
        if len(chunk) < 3:
            break
        fields = dict(zip(names, chunk))
        if tr_id in TRADE_TR_IDS:
            records.append(parse_trade_record(fields))
        else:
            records.append(parse_orderbook_record(fields))
    return tr_id, records


def get_approval_key() -> str:
    """웹소켓 접속키 발급 (REST 토큰과 별개)"""
    resp = requests.post(
        f"{KIS_BASE_URL}/oauth2/Approval",
        headers={"Content-Type": "application/json; charset=utf-8"},
        json={
            "grant_type": "client_credentials",
            "appkey": KIS_APP_KEY,
            "secretkey": KIS_APP_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    key = resp.json().get("approval_key", "")
    if not key:
        raise RuntimeError(f"approval_key 발급 실패: {resp.text[:200]}")
    return key


def build_subscribe_message(approval_key: str, tr_id: str, code: str, subscribe: bool = True) -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "1" if subscribe else "2",
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": code}},
    })


class KISWebSocketClient:
    """재접속·재구독을 처리하는 KIS 실시간 클라이언트.

    on_tick(Tick), on_orderbook(OrderBook) 콜백은 수신 스레드에서 호출되므로
    오래 걸리는 작업은 콜백 안에서 하지 말고 큐로 넘긴다.
    """

    def __init__(
        self,
        on_tick: Callable[[Tick], None],
        on_orderbook: Optional[Callable[[OrderBook], None]] = None,
        url: str = KIS_WS_URL,
        max_subscriptions: int = REALTIME_MAX_SUBSCRIPTIONS,
        approval_key_provider: Callable[[], str] = get_approval_key,
        watchdog_sec: int = 90,
    ):
        self.url = url
        self.on_tick = on_tick
        self.on_orderbook = on_orderbook
        self.max_subscriptions = max_subscriptions
        self._approval_key_provider = approval_key_provider
        self._approval_key = ""
        self._subs: dict[tuple[str, str], bool] = {}   # (tr_id, code) -> True
        self._lock = threading.Lock()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.connected = threading.Event()
        self._last_msg_at = 0.0
        self._watchdog_sec = watchdog_sec
        self.stats = {"ticks": 0, "orderbooks": 0, "reconnects": 0, "errors": 0}
        self.last_event = "아직 연결 시도 전"   # 진단용: 마지막 연결/구독/오류 메시지
        self.last_tick_at = 0.0

    # ── 구독 관리 ───────────────────────────────────────────────────
    def subscribe(self, code: str, orderbook: bool = False) -> bool:
        keys = [(TR_TRADE, code)] + ([(TR_ORDERBOOK, code)] if orderbook else [])
        with self._lock:
            new = [k for k in keys if k not in self._subs]
            if len(self._subs) + len(new) > self.max_subscriptions:
                log.warning("구독 한도(%d) 초과로 %s 건너뜀", self.max_subscriptions, code)
                return False
            for k in new:
                self._subs[k] = True
        if self.connected.is_set():
            for tr_id, c in new:
                self._send(build_subscribe_message(self._approval_key, tr_id, c, True))
        return True

    def unsubscribe(self, code: str) -> None:
        with self._lock:
            keys = [k for k in self._subs if k[1] == code]
            for k in keys:
                del self._subs[k]
        if self.connected.is_set():
            for tr_id, c in keys:
                self._send(build_subscribe_message(self._approval_key, tr_id, c, False))

    @property
    def subscriptions(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._subs)

    # ── 수명 주기 ───────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="kis-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                self._approval_key = self._approval_key_provider()
                self._ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                watchdog = threading.Thread(target=self._watchdog, daemon=True)
                watchdog.start()
                self._ws.run_forever(ping_interval=0)
                backoff = 1
            except Exception as e:
                self.stats["errors"] += 1
                self.last_event = f"연결 실패: {e}"
                log.error("웹소켓 루프 오류: %s", e)
            finally:
                self.connected.clear()
            if self._stop.is_set():
                break
            self.stats["reconnects"] += 1
            log.info("%d초 후 재접속...", backoff)
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 60)

    def _watchdog(self) -> None:
        """일정 시간 메시지가 없으면 연결을 끊어 재접속을 유도"""
        ws = self._ws
        while not self._stop.is_set() and ws is self._ws:
            self._stop.wait(10)
            if self.connected.is_set() and time.time() - self._last_msg_at > self._watchdog_sec:
                log.warning("%d초간 수신 없음, 재접속", self._watchdog_sec)
                try:
                    ws.close()
                except Exception:
                    pass
                return

    # ── 콜백 ───────────────────────────────────────────────────────
    def _on_open(self, ws) -> None:
        log.info("KIS 웹소켓 연결됨: %s", self.url)
        self._last_msg_at = time.time()
        self.last_event = f"연결됨 ({time.strftime('%H:%M:%S')}) · 구독 {len(self.subscriptions)}건 요청"
        self.connected.set()
        for tr_id, code in self.subscriptions:
            self._send(build_subscribe_message(self._approval_key, tr_id, code, True))
            time.sleep(0.05)  # 등록 요청 폭주 방지

    def _on_message(self, ws, message: str) -> None:
        self._last_msg_at = time.time()
        try:
            self.handle_message(message)
        except Exception as e:
            self.stats["errors"] += 1
            log.debug("메시지 처리 오류: %s | %s", e, message[:120])

    def handle_message(self, message: str) -> None:
        """테스트 가능하도록 분리한 메시지 디스패치"""
        if message and message[0] in ("0", "1"):
            tr_id, records = parse_message(message)
            for rec in records:
                if tr_id in TRADE_TR_IDS:
                    self.stats["ticks"] += 1
                    self.last_tick_at = time.time()
                    self.on_tick(rec)
                elif tr_id in ORDERBOOK_TR_IDS and self.on_orderbook:
                    self.stats["orderbooks"] += 1
                    self.on_orderbook(rec)
            return

        data = json.loads(message)
        header = data.get("header", {})
        tr_id = header.get("tr_id", "")
        if tr_id == "PINGPONG":
            self._send(message)   # 받은 그대로 되돌려 보내면 연결 유지
            return
        body = data.get("body", {})
        rt_cd = body.get("rt_cd")
        msg = body.get("msg1", "")
        if rt_cd not in (None, "0"):
            self.last_event = f"구독 오류 [{tr_id} {header.get('tr_key', '')}]: {msg}"
            log.warning("구독 응답 오류 [%s %s]: %s", tr_id, header.get("tr_key", ""), msg)
        else:
            self.last_event = f"구독 응답 [{tr_id} {header.get('tr_key', '')}]: {msg}"
            log.info("구독 응답 [%s %s]: %s", tr_id, header.get("tr_key", ""), msg)

    def _on_error(self, ws, error) -> None:
        self.stats["errors"] += 1
        self.last_event = f"웹소켓 오류: {error}"
        log.error("웹소켓 오류: %s", error)

    def _on_close(self, ws, status_code, msg) -> None:
        self.connected.clear()
        self.last_event = f"웹소켓 종료 ({status_code} {msg})"
        log.info("웹소켓 종료 (%s %s)", status_code, msg)

    def _send(self, payload: str) -> None:
        try:
            if self._ws:
                self._ws.send(payload)
        except Exception as e:
            log.error("전송 실패: %s", e)
