"""실시간 신호 감지 - 틱 요약에서 규칙 기반으로 이벤트를 뽑아낸다"""
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from config import (
    REALTIME_PRICE_SPIKE_PCT, REALTIME_PRICE_WINDOW_SEC, REALTIME_VOLUME_SURGE_RATIO,
    REALTIME_STRENGTH_THRESHOLD, REALTIME_IMBALANCE_RATIO, REALTIME_SIGNAL_COOLDOWN_SEC,
)


@dataclass
class Signal:
    kind: str          # price_spike / price_drop / volume_surge / strength / bid_imbalance / ask_imbalance / day_volume
    label: str         # 사람이 읽는 이름
    code: str
    name: str
    score: float       # 신호 강도 (클수록 중요)
    message: str
    data: dict = field(default_factory=dict)
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class SignalDetector:
    def __init__(
        self,
        price_spike_pct: float = REALTIME_PRICE_SPIKE_PCT,
        price_window_sec: int = REALTIME_PRICE_WINDOW_SEC,
        volume_surge_ratio: float = REALTIME_VOLUME_SURGE_RATIO,
        strength_threshold: float = REALTIME_STRENGTH_THRESHOLD,
        imbalance_ratio: float = REALTIME_IMBALANCE_RATIO,
        cooldown_sec: int = REALTIME_SIGNAL_COOLDOWN_SEC,
        min_history_sec: int = 300,
    ):
        self.price_spike_pct = price_spike_pct
        self.price_window_sec = price_window_sec
        self.volume_surge_ratio = volume_surge_ratio
        self.strength_threshold = strength_threshold
        self.imbalance_ratio = imbalance_ratio
        self.cooldown_sec = cooldown_sec
        self.min_history_sec = min_history_sec
        self._last_fired: dict[tuple[str, str], float] = {}

    def _ready(self, code: str, kind: str, now: float) -> bool:
        last = self._last_fired.get((code, kind))
        return last is None or now - last >= self.cooldown_sec

    def _fire(self, code: str, kind: str, now: float) -> None:
        self._last_fired[(code, kind)] = now

    def evaluate(self, summary: dict, now: Optional[float] = None) -> list[Signal]:
        now = now if now is not None else time.time()
        if not summary or summary.get("halted"):
            return []
        code, name = summary["code"], summary.get("name", "")
        out: list[Signal] = []

        def emit(kind: str, label: str, score: float, message: str, **data) -> None:
            if self._ready(code, kind, now):
                self._fire(code, kind, now)
                out.append(Signal(kind, label, code, name, round(score, 2), message, data, now))

        # 1) 단기 급등/급락 (5분 변동)
        pct = summary.get("pct_5m", 0.0)
        if abs(pct) >= self.price_spike_pct:
            if pct > 0:
                emit("price_spike", "단기 급등", abs(pct) / self.price_spike_pct,
                     f"{name}({code}) {self.price_window_sec // 60}분 내 {pct:+.2f}% 급등, 현재가 {summary['price']:,}원",
                     pct_5m=pct, price=summary["price"])
            else:
                emit("price_drop", "단기 급락", abs(pct) / self.price_spike_pct,
                     f"{name}({code}) {self.price_window_sec // 60}분 내 {pct:+.2f}% 급락, 현재가 {summary['price']:,}원",
                     pct_5m=pct, price=summary["price"])

        # 2) 거래량 급증 (1분 거래량 vs 평균 1분 거래량). 기준치가 쌓일 때까지 대기
        ratio = summary.get("vol_ratio_1m", 0.0)
        if summary.get("data_span_sec", 0) >= self.min_history_sec and ratio >= self.volume_surge_ratio:
            emit("volume_surge", "거래량 급증", ratio / self.volume_surge_ratio,
                 f"{name}({code}) 1분 거래량 {summary['vol_1m']:,}주, 평균 대비 {ratio:.1f}배",
                 vol_ratio_1m=ratio, vol_1m=summary["vol_1m"], pct_1m=summary.get("pct_1m", 0.0))

        # 3) 체결강도 강세 + 상승 동반
        strength = summary.get("strength", 0.0)
        if strength >= self.strength_threshold and summary.get("pct_5m", 0.0) > 0:
            emit("strength", "체결강도 강세", strength / self.strength_threshold,
                 f"{name}({code}) 체결강도 {strength:.0f}, 5분 매수비율 {summary.get('buy_ratio_5m', 0):.0f}%",
                 strength=strength, buy_ratio_5m=summary.get("buy_ratio_5m", 0.0))

        # 4) 호가 잔량 불균형
        imb = summary.get("imbalance", 0.0)
        if imb >= self.imbalance_ratio:
            emit("bid_imbalance", "매수 호가 우위", imb / self.imbalance_ratio,
                 f"{name}({code}) 매수잔량/매도잔량 {imb:.1f}배", imbalance=imb)
        elif 0 < imb <= 1 / self.imbalance_ratio:
            emit("ask_imbalance", "매도 호가 우위", (1 / imb) / self.imbalance_ratio,
                 f"{name}({code}) 매도잔량/매수잔량 {1 / imb:.1f}배", imbalance=imb)

        # 5) 전일 동시간 대비 누적 거래량 폭증
        day_rate = summary.get("same_time_vol_rate", 0.0)
        if day_rate >= 300:
            emit("day_volume", "전일 대비 거래량 폭증", day_rate / 300,
                 f"{name}({code}) 전일 동시간 대비 누적 거래량 {day_rate:.0f}%",
                 same_time_vol_rate=day_rate)

        return out
