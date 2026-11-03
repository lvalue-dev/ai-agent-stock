"""한국투자증권 KIS OpenAPI 래퍼"""
import time
import requests
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
from typing import Optional
from config import (
    KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO,
    KIS_ACCOUNT_PROD_CODE, KIS_BASE_URL, KIS_MODE, KIS_MARKET
)


class KISAuth:
    """KIS API 인증 토큰 관리"""
    _token: str = ""
    _expires_at: datetime = datetime.min

    @classmethod
    def get_token(cls) -> str:
        if datetime.now() < cls._expires_at and cls._token:
            return cls._token

        resp = requests.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        cls._token = data["access_token"]
        cls._expires_at = datetime.now() + timedelta(hours=23)
        return cls._token


def _headers(tr_id: str, custom_headers: Optional[dict] = None) -> dict:
    h = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {KISAuth.get_token()}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    if custom_headers:
        h.update(custom_headers)
    return h


def _quote(path: str, tr_id: str, params: dict, market: str = KIS_MARKET) -> dict:
    """시세 조회 공통. 통합(UN)/NXT 조회가 거부되면 KRX(J)로 한 번 더 시도한다.

    NXT 미신청 계좌나 NXT 비거래 종목은 rt_cd != 0 으로 돌아오므로 정규장 데이터로 폴백.
    """
    def call(mkt: str) -> dict:
        resp = requests.get(
            f"{KIS_BASE_URL}{path}",
            headers=_headers(tr_id),
            params={**params, "FID_COND_MRKT_DIV_CODE": mkt},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        data = call(market)
        if data.get("rt_cd", "0") == "0" and (data.get("output") or data.get("output2") or data.get("output1")):
            data["_market"] = market
            return data
        if market == "J":
            return data
    except requests.RequestException:
        if market == "J":
            raise
    data = call("J")
    data["_market"] = "J"
    return data


def get_market_index(market: str = "KOSPI") -> dict:
    """코스피/코스닥 지수 조회"""
    code_map = {"KOSPI": "0001", "KOSDAQ": "1001"}
    fid_input_iscd = code_map.get(market.upper(), "0001")

    resp = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-index-price",
        headers=_headers("FHPUP02100000"),
        params={"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": fid_input_iscd},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    output = data.get("output", {})
    return {
        "market": market,
        "index": output.get("bstp_nmix_prpr", "N/A"),
        "change": output.get("bstp_nmix_prdy_vrss", "N/A"),
        "change_rate": output.get("bstp_nmix_prdy_ctrt", "N/A"),
        "volume": output.get("acml_vol", "N/A"),
        "trade_amount": output.get("acml_tr_pbmn", "N/A"),
        "high": output.get("bstp_nmix_hgpr", "N/A"),
        "low": output.get("bstp_nmix_lwpr", "N/A"),
        "timestamp": datetime.now().isoformat(),
    }


def get_stock_price(stock_code: str) -> dict:
    """개별 종목 현재가 조회 (KIS_MARKET=UN 이면 프리/애프터마켓 NXT 체결가 포함)"""
    data = _quote(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        {"FID_INPUT_ISCD": stock_code},
    )
    output = data.get("output", {})
    return {
        "code": stock_code,
        "market": data.get("_market", "J"),
        "name": output.get("hts_kor_isnm", ""),
        "price": output.get("stck_prpr", "N/A"),
        "change": output.get("prdy_vrss", "N/A"),
        "change_rate": output.get("prdy_ctrt", "N/A"),
        "volume": output.get("acml_vol", "N/A"),
        "per": output.get("per", "N/A"),
        "pbr": output.get("pbr", "N/A"),
        "market_cap": output.get("hts_avls", "N/A"),
        "52w_high": output.get("w52_hgpr", "N/A"),
        "52w_low": output.get("w52_lwpr", "N/A"),
    }


def get_top_volume_stocks(market: str = "KOSPI", limit: int = 10) -> list[dict]:
    """거래량 상위 종목 조회"""
    market_code = "J" if market.upper() == "KOSPI" else "Q"
    resp = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/volume-rank",
        headers=_headers("FHPST01710000"),
        params={
            "FID_COND_MRKT_DIV_CODE": market_code,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    output = data.get("output", [])[:limit]
    return [
        {
            "rank": item.get("data_rank", ""),
            "code": item.get("mksc_shrn_iscd", ""),
            "name": item.get("hts_kor_isnm", ""),
            "price": item.get("stck_prpr", ""),
            "change_rate": item.get("prdy_ctrt", ""),
            "volume": item.get("acml_vol", ""),
            "volume_rate": item.get("vol_inrt", ""),
        }
        for item in output
    ]


def get_investor_trading(stock_code: str) -> dict:
    """종목별 투자자 매매동향 (기관/외국인/개인)"""
    try:
        data = _quote(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {"FID_INPUT_ISCD": stock_code},
        )
        output = data.get("output", {})
        if isinstance(output, list):   # 투자자 동향은 일자별 리스트로 오기도 함
            output = output[0] if output else {}
        return {
            "code": stock_code,
            "individual_net_buy": output.get("prsn_ntby_qty", "0"),
            "individual_net_amount": output.get("prsn_ntby_tr_pbmn", "0"),
            "foreign_net_buy": output.get("frgn_ntby_qty", "0"),
            "foreign_net_amount": output.get("frgn_ntby_tr_pbmn", "0"),
            "institution_net_buy": output.get("orgn_ntby_qty", "0"),
            "institution_net_amount": output.get("orgn_ntby_tr_pbmn", "0"),
            "trust_net_buy": output.get("trust_ntby_qty", "0"),
            "trust_net_amount": output.get("trust_ntby_tr_pbmn", "0"),
        }
    except Exception as e:
        return {"code": stock_code, "error": str(e)}


def get_daily_volume(stock_code: str, days: int = 10) -> list[dict]:
    """최근 N일 거래량 추이 조회"""
    try:
        data = _quote(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "FHKST03010100",
            {
                "FID_INPUT_ISCD": stock_code,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        output = (data.get("output2") or data.get("output") or [])[:days]
        return [
            {
                "date": item.get("stck_bsop_date", ""),
                "close": item.get("stck_clpr", ""),
                "volume": item.get("acml_vol", ""),
                "trade_amount": item.get("acml_tr_pbmn", ""),
                "change_rate": item.get("prdy_ctrt", ""),
            }
            for item in output
        ]
    except Exception:
        return []


def get_minute_candles(stock_code: str, pages: int = 4, end_time: str = "") -> list[dict]:
    """당일 1분봉 (FHKST03010200). 한 번에 30건씩 과거로 페이지. 결과는 시간 오름차순.

    KIS_MARKET=UN 이면 NXT 프리마켓/애프터마켓 분봉도 포함된다.
    """
    out: dict[str, dict] = {}
    hour = end_time or datetime.now(KST).strftime("%H%M%S")
    for _ in range(max(pages, 1)):
        data = _quote(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",
            {
                "FID_ETC_CLS_CODE": "",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_HOUR_1": hour,
                "FID_PW_DATA_INCU_YN": "Y",
            },
        )
        rows = data.get("output2") or []
        times = []
        for r in rows:
            t = str(r.get("stck_cntg_hour", ""))
            if len(t) < 4:
                continue
            times.append(t)
            out[t[:4]] = {
                "time": t,
                "open": _to_int(r.get("stck_oprc")),
                "high": _to_int(r.get("stck_hgpr")),
                "low": _to_int(r.get("stck_lwpr")),
                "close": _to_int(r.get("stck_prpr")),
                "volume": _to_int(r.get("cntg_vol")),
            }
        if not times:
            break
        earliest = min(times)
        if earliest <= "080000":
            break
        # 가장 이른 분의 1분 전부터 다시 조회
        hh, mm = int(earliest[:2]), int(earliest[2:4])
        prev = datetime(2000, 1, 1, hh, mm) - timedelta(minutes=1)
        hour = prev.strftime("%H%M%S")
        time.sleep(0.1)   # 초당 호출 제한 완화
    return [out[k] for k in sorted(out)]


def _to_int(v, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return default


def get_stock_news(stock_code: str, limit: int = 10) -> list[dict]:
    """종목 관련 뉴스 조회"""
    resp = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/news-title",
        headers=_headers("HHKST03900400"),
        params={"FID_INPUT_ISCD": stock_code, "FID_NEWS_OFER_ENTP_CODE": ""},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    output = data.get("output", [])[:limit]
    return [
        {
            "title": item.get("news_ttl", ""),
            "time": item.get("datas", ""),
            "office": item.get("news_ofer_entp_code", ""),
        }
        for item in output
    ]


def get_account_balance() -> dict:
    """계좌 잔고 조회"""
    params = {
        "CANO": KIS_ACCOUNT_NO,
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD_CODE,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    resp = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance",
        headers=_headers("TTTC8434R" if KIS_MODE == "real" else "VTTC8434R"),
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    output2 = data.get("output2", [{}])[0] if data.get("output2") else {}
    holdings = data.get("output1", [])
    return {
        "total_eval": output2.get("tot_evlu_amt", "0"),
        "purchase_amount": output2.get("pchs_amt_smtl_amt", "0"),
        "profit_loss": output2.get("evlu_pfls_smtl_amt", "0"),
        "available_cash": output2.get("nass_amt", "0"),
        "holdings": [
            {
                "code": h.get("pdno", ""),
                "name": h.get("prdt_name", ""),
                "quantity": h.get("hldg_qty", "0"),
                "avg_price": h.get("pchs_avg_pric", "0"),
                "current_price": h.get("prpr", "0"),
                "profit_rate": h.get("evlu_pfls_rt", "0"),
            }
            for h in holdings
        ],
    }


def place_order(
    stock_code: str,
    order_type: str,  # "buy" or "sell"
    quantity: int,
    price: int = 0,  # 0 = 시장가
) -> dict:
    """매수/매도 주문"""
    if order_type == "buy":
        tr_id = "TTTC0802U" if KIS_MODE == "real" else "VTTC0802U"
    else:
        tr_id = "TTTC0801U" if KIS_MODE == "real" else "VTTC0801U"

    order_dvsn = "01" if price == 0 else "00"  # 01=시장가, 00=지정가
    body = {
        "CANO": KIS_ACCOUNT_NO,
        "ACNT_PRDT_CD": KIS_ACCOUNT_PROD_CODE,
        "PDNO": stock_code,
        "ORD_DVSN": order_dvsn,
        "ORD_QTY": str(quantity),
        "ORD_UNPR": str(price),
    }
    resp = requests.post(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash",
        headers=_headers(tr_id),
        json=body,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "success": data.get("rt_cd") == "0",
        "message": data.get("msg1", ""),
        "order_no": data.get("output", {}).get("ODNO", ""),
        "stock_code": stock_code,
        "order_type": order_type,
        "quantity": quantity,
        "price": price if price > 0 else "시장가",
    }
