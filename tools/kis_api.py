"""한국투자증권 KIS OpenAPI 래퍼"""
import requests
from datetime import datetime, timedelta
from typing import Optional
from config import (
    KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO,
    KIS_ACCOUNT_PROD_CODE, KIS_BASE_URL, KIS_MODE
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
    """개별 종목 현재가 조회"""
    resp = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
        headers=_headers("FHKST01010100"),
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    output = data.get("output", {})
    return {
        "code": stock_code,
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


def get_stock_news(stock_code: str) -> list[dict]:
    """종목 관련 뉴스 조회"""
    resp = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/news-title",
        headers=_headers("HHKST03900400"),
        params={"FID_INPUT_ISCD": stock_code, "FID_NEWS_OFER_ENTP_CODE": ""},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    output = data.get("output", [])[:5]
    return [
        {
            "title": item.get("news_ttl", ""),
            "time": item.get("datas", ""),
            "code": item.get("news_id", ""),
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
