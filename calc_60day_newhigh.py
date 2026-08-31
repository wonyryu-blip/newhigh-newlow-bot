# -*- coding: utf-8 -*-
"""
60일(달력일) 신고가/신저가 계산 프로토타입

52주는 KIS "신고/신저근접종목 상위" API(near_new_highlow, FHPST01870000)로
바로 받을 수 있지만, 60일 기준은 그 API에 없기 때문에 이 스크립트처럼
"전종목 코드 확보 → 종목별 일자별 시세 조회 → 직접 비교" 방식으로 계산한다.

절차:
  1) KRX 종목마스터(kospi_code.mst / kosdaq_code.mst)를 내려받아 전체
     상장 종목 코드/종목명을 확보한다. (KIS 인증 없이 받는 정적 파일)
  2) 종목별로 "국내주식기간별시세(일봉)" API(FHKST03010100)를 호출해
     최근 65일(60일치를 넉넉히 담기 위한 여유분) 종가를 받아온다.
     한 번의 호출로 최대 100건까지 나오므로, 60일 구간은 호출 1회로
     충분하다(실제 테스트로 확인됨: 65일 조회 시 응답 44건).
  3) 오늘(가장 최근) 종가가 그 구간의 최고/최저와 같으면 "60일
     신고가/신저가 경신 종목"으로 판정한다.

주의:
  - 이 프로토타입은 동작 검증을 위해 소수 종목(SAMPLE_LIMIT)만 돈다.
    전종목(코스피 2,566 + 코스닥 1,824 = 총 4,390개, 2026-08-31 기준
    마스터파일 실측치)을 매일 아침 실행하려면 API 호출 속도 제한을
    고려한 쓰로틀링이 필요하다. KIS 공식 안내 기준 실전투자는 초당
    20건, 모의투자는 이보다 더 낮은 것으로 알려져 있음(정확한 수치는
    공식 문서로 재확인 권장). 전종목 기준 예상 소요시간:
      - 실전투자(초당 20건 가정): 4,390 / 20 ≈ 약 3.7분
      - 모의투자(초당 2건 가정):   4,390 / 2  ≈ 약 36.6분
    매일 아침 8시 전에 결과를 받아야 하므로, 이 소요시간을 감안해
    스케줄 시작 시각을 앞당겨야 한다(2단계에서 다룸).
"""

import os
import json
import time
import zipfile
import urllib.request
import ssl
import datetime

import pandas as pd
import requests

BASE_URL = "https://openapivts.koreainvestment.com:29443"  # 모의투자 도메인
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SAMPLE_LIMIT = 10          # 프로토타입 검증용: 코스피/코스닥 각각 이 개수만 조회
CALL_INTERVAL_SEC = 0.6    # 종목별 호출 사이 대기(모의투자 기준 여유있게)


# ---------------------------------------------------------------------------
# 1) 종목마스터 다운로드/파싱 (KIS 공식 샘플 코드 축약판)
# ---------------------------------------------------------------------------

def _download_mst(url, zip_path, mst_name):
    ssl._create_default_https_context = ssl._create_unverified_context
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(BASE_DIR)
    os.remove(zip_path)
    return os.path.join(BASE_DIR, mst_name)


def get_kospi_tickers():
    mst_path = os.path.join(BASE_DIR, "kospi_code.mst")
    if not os.path.exists(mst_path):
        mst_path = _download_mst(
            "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
            os.path.join(BASE_DIR, "kospi_code.zip"),
            "kospi_code.mst",
        )
    codes = []
    with open(mst_path, mode="r", encoding="cp949") as f:
        for row in f:
            rf1 = row[0: len(row) - 228]
            code = rf1[0:9].rstrip()
            name = rf1[21:].strip()
            codes.append((code, name, "KOSPI"))
    return codes


def get_kosdaq_tickers():
    mst_path = os.path.join(BASE_DIR, "kosdaq_code.mst")
    if not os.path.exists(mst_path):
        mst_path = _download_mst(
            "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
            os.path.join(BASE_DIR, "kosdaq_code.zip"),
            "kosdaq_code.mst",
        )
    codes = []
    with open(mst_path, mode="r", encoding="cp949") as f:
        for row in f:
            rf1 = row[0: len(row) - 222]
            code = rf1[0:9].rstrip()
            name = rf1[21:].strip()
            codes.append((code, name, "KOSDAQ"))
    return codes


# ---------------------------------------------------------------------------
# 2) 인증
# ---------------------------------------------------------------------------

def load_env(path=os.path.join(BASE_DIR, ".env")):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def get_token(app_key, app_secret, cache_path=os.path.join(BASE_DIR, "token_cache.json")):
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)["access_token"]
    res = requests.post(
        f"{BASE_URL}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
        timeout=10,
    )
    res.raise_for_status()
    data = res.json()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data["access_token"]


# ---------------------------------------------------------------------------
# 3) 종목별 60일(달력일) 종가 이력 조회 + 신고가/신저가 판정
# ---------------------------------------------------------------------------

def fetch_daily_closes(token, app_key, app_secret, code, days=65):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days)
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST03010100",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }
    res = requests.get(url, headers=headers, params=params, timeout=10)
    data = res.json()
    if data.get("rt_cd") != "0":
        return None, data.get("msg1")
    rows = data.get("output2", [])
    # 종가가 "0"인 행(비영업일/데이터없음)은 제외
    closes = [(r["stck_bsop_date"], int(r["stck_clpr"])) for r in rows if r.get("stck_clpr") not in (None, "", "0")]
    closes.sort(key=lambda x: x[0])  # 날짜 오름차순
    return closes, None


def judge_new_high_low(closes):
    """closes: [(date, close), ...] 날짜 오름차순. 가장 최근 종가가
    이 구간의 최고/최저와 같으면 신고가/신저가로 판정."""
    if not closes:
        return None
    latest_date, latest_close = closes[-1]
    max_close = max(c for _, c in closes)
    min_close = min(c for _, c in closes)
    is_new_high = latest_close >= max_close
    is_new_low = latest_close <= min_close
    return {
        "latest_date": latest_date,
        "latest_close": latest_close,
        "period_high": max_close,
        "period_low": min_close,
        "is_new_high": is_new_high,
        "is_new_low": is_new_low,
        "days_count": len(closes),
    }


# ---------------------------------------------------------------------------
# 4) 실행 (프로토타입: 표본 종목만)
# ---------------------------------------------------------------------------

def main():
    env = load_env()
    token = get_token(env["KIS_APP_KEY"], env["KIS_APP_SECRET"])

    print("=== 종목마스터 다운로드 ===")
    kospi = get_kospi_tickers()
    kosdaq = get_kosdaq_tickers()
    print(f"코스피 {len(kospi)}종목, 코스닥 {len(kosdaq)}종목 (전체 마스터 기준)")

    sample = kospi[:SAMPLE_LIMIT] + kosdaq[:SAMPLE_LIMIT]
    print(f"프로토타입 검증용으로 {len(sample)}종목만 조회합니다 (SAMPLE_LIMIT={SAMPLE_LIMIT})")

    new_high_list = []
    new_low_list = []

    for code, name, market in sample:
        closes, err = fetch_daily_closes(token, env["KIS_APP_KEY"], env["KIS_APP_SECRET"], code)
        if err:
            print(f"  [skip] {market} {code} {name}: {err}")
            time.sleep(CALL_INTERVAL_SEC)
            continue
        result = judge_new_high_low(closes)
        if result is None:
            print(f"  [skip] {market} {code} {name}: 데이터 없음")
            time.sleep(CALL_INTERVAL_SEC)
            continue
        tag = []
        if result["is_new_high"]:
            tag.append("60일 신고가")
            new_high_list.append((market, code, name, result))
        if result["is_new_low"]:
            tag.append("60일 신저가")
            new_low_list.append((market, code, name, result))
        print(
            f"  {market} {code} {name}: 최근종가={result['latest_close']} "
            f"구간최고={result['period_high']} 구간최저={result['period_low']} "
            f"({result['days_count']}거래일) {' / '.join(tag) if tag else ''}"
        )
        time.sleep(CALL_INTERVAL_SEC)

    print("\n=== 60일 신고가 종목 ===")
    for market, code, name, r in new_high_list:
        print(f"  {market} {code} {name}  종가 {r['latest_close']}")

    print("\n=== 60일 신저가 종목 ===")
    for market, code, name, r in new_low_list:
        print(f"  {market} {code} {name}  종가 {r['latest_close']}")


if __name__ == "__main__":
    main()
