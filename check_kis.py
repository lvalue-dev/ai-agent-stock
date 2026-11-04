"""한국투자 실데이터 점검 스크립트

  python check_kis.py            # REST 현재가 + 웹소켓 체결 10초 수신
  python check_kis.py 005930 000660 --seconds 20

.env 의 KIS_APP_KEY/SECRET, KIS_MARKET 을 그대로 써서
  1) REST 현재가(FHKST01010100)가 실제 값으로 오는지
  2) 웹소켓 접속키 발급 → 체결 구독 → 실제 틱이 들어오는지
를 눈으로 확인한다. 장외 시간엔 틱이 0건이어도 정상이다.
"""
import argparse
import logging
import sys
import time
from datetime import datetime

from config import KIS_MODE, KIS_MARKET, KIS_BASE_URL, KIS_WS_URL, KIS_APP_KEY
from tools.kis_api import get_stock_price, get_minute_candles
from tools.kis_websocket import KISWebSocketClient, TR_TRADE, market_session, KST


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", default=["005930", "000660"])
    ap.add_argument("--seconds", type=int, default=10)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if not KIS_APP_KEY:
        print("❌ KIS_APP_KEY 가 비어 있습니다 (.env 확인)")
        return 1
    print(f"모드 {KIS_MODE} · 시장 {KIS_MARKET} · REST {KIS_BASE_URL} · WS {KIS_WS_URL} · 지금 {market_session()} ({datetime.now(KST):%H:%M:%S} KST)\n")

    print("── 1) REST 현재가 ──")
    for code in args.codes:
        try:
            q = get_stock_price(code)
            print(f"  {q['name']}({code}) 현재가 {q['price']}원 전일比 {q['change_rate']}% 거래량 {q['volume']} [시장 {q.get('market')}]")
        except Exception as e:
            print(f"  {code} 조회 실패: {e}")

    print("\n── 2) REST 당일 1분봉 (최근 3개) ──")
    try:
        rows = get_minute_candles(args.codes[0], pages=1)
        for r in rows[-3:]:
            print(f"  {r['time'][:2]}:{r['time'][2:4]} 시 {r['open']} 고 {r['high']} 저 {r['low']} 종 {r['close']} 량 {r['volume']}")
        if not rows:
            print("  분봉 없음 (장 시작 전이면 정상)")
    except Exception as e:
        print(f"  분봉 조회 실패: {e}")

    print(f"\n── 3) 웹소켓 체결 ({TR_TRADE}) {args.seconds}초 수신 ──")
    ticks = []

    def on_tick(t):
        ticks.append(t)
        if len(ticks) <= 10:
            print(f"  {t.time[:2]}:{t.time[2:4]}:{t.time[4:6]} {t.code} {t.price:,}원 {t.volume}주 {t.side} 강도 {t.strength} [{t.session}]")

    client = KISWebSocketClient(on_tick=on_tick)
    for code in args.codes:
        client.subscribe(code)
    client.start()
    if not client.connected.wait(10):
        print("  ❌ 10초 안에 연결되지 않았습니다 (접속키 발급/방화벽 확인)")
        client.stop()
        return 1
    time.sleep(args.seconds)
    client.stop()
    print(f"\n  수신 {len(ticks)}건 · 통계 {client.stats}")
    if not ticks:
        print("  틱 0건: 장외 시간이거나, 프리마켓인데 NXT 비거래 종목이거나, 구독 응답 오류(위 로그 확인)일 수 있습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
