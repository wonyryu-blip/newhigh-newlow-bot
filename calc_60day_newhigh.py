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

BASE_URL = "https://openapi.koreainvestment.com:9443"  # 실전투자 도메인
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SAMPLE_LIMIT = 10          # 프로토타입 검증용: 코스피/코스닥 각각 이 개수만 조회
CALL_INTERVAL_SEC = 0.6    # 종목별 호출 사이 대기(모의투자 기준 여유있게)


# ---------------------------------------------------------------------------
# 1) 종목마스터 다운로드/파싱 (KIS 공식 샘플 코드 기반)
#
#    실제 마스터파일을 뜯어본 결과(2026-08-31 기준):
#      - 그룹코드/증권그룹구분코드 == 'ST' 인 것만 남기면 ETF(EF)/ETN(EN)/
#        파생결합증권(BC)/리츠(RT)/외국주권(FS)/예탁증서(DR) 등이 전부
#        빠지고 "주권(株券)"만 남는다. ELW는 이 마스터파일 자체에 아예
#        포함되어 있지 않아(별도 파일) 추가 필터 없이 자동으로 제외된다.
#      - 우선주는 '우선주'/'우선주구분코드' 컬럼이 0이 아닌 행이므로
#        ==0 인 것만 남기면 보통주만 남는다(코스피 916개 중 805개,
#        "삼성전자우" 같은 종목들이 제외됨).
#      - 스팩(기업인수목적회사)은 코스닥에만 있고(코스피는 전부 N),
#        '기업인수목적회사여부' == 'N' 인 것만 남기면 제외된다.
#    최종: 코스피 805종목 + 코스닥 1,730종목 = 총 2,535종목(순수 보통주)
# ---------------------------------------------------------------------------

def _download_mst(url, zip_path, mst_name):
    mst_path = os.path.join(BASE_DIR, mst_name)
    if os.path.exists(mst_path):
        return mst_path
    ssl._create_default_https_context = ssl._create_unverified_context
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(BASE_DIR)
    os.remove(zip_path)
    return mst_path


def get_kospi_tickers():
    mst_path = _download_mst(
        "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
        os.path.join(BASE_DIR, "kospi_code.zip"),
        "kospi_code.mst",
    )

    tmp1 = os.path.join(BASE_DIR, "_kospi_part1.tmp")
    tmp2 = os.path.join(BASE_DIR, "_kospi_part2.tmp")
    with open(tmp1, "w", encoding="utf-8") as wf1, open(tmp2, "w", encoding="utf-8") as wf2:
        with open(mst_path, mode="r", encoding="cp949") as f:
            for row in f:
                rf1 = row[0:len(row) - 228]
                wf1.write(rf1[0:9].rstrip() + "," + rf1[21:].strip() + "\n")
                wf2.write(row[-228:])

    df1 = pd.read_csv(tmp1, header=None, names=["단축코드", "한글명"], encoding="utf-8")

    # KIS 공식 kis_kospi_code_mst.py의 field_specs/part2_columns 그대로 사용
    field_specs = [2, 1, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                   1, 1, 1, 1, 1, 1, 9, 5, 5, 1, 1, 1, 2, 1, 1, 1, 2, 2, 2, 3, 1, 3, 12, 12, 8,
                   15, 21, 2, 7, 1, 1, 1, 1, 1, 9, 9, 9, 5, 9, 8, 9, 3, 1, 1, 1]
    part2_columns = ["그룹코드", "시가총액규모", "지수업종대분류", "지수업종중분류", "지수업종소분류",
                      "제조업", "저유동성", "지배구조지수종목", "KOSPI200섹터업종", "KOSPI100",
                      "KOSPI50", "KRX", "ETP", "ELW발행", "KRX100", "KRX자동차", "KRX반도체",
                      "KRX바이오", "KRX은행", "SPAC", "KRX에너지화학", "KRX철강", "단기과열",
                      "KRX미디어통신", "KRX건설", "Non1", "KRX증권", "KRX선박", "KRX섹터_보험",
                      "KRX섹터_운송", "SRI", "기준가", "매매수량단위", "시간외수량단위", "거래정지",
                      "정리매매", "관리종목", "시장경고", "경고예고", "불성실공시", "우회상장",
                      "락구분", "액면변경", "증자구분", "증거금비율", "신용가능", "신용기간",
                      "전일거래량", "액면가", "상장일자", "상장주수", "자본금", "결산월", "공모가",
                      "우선주", "공매도과열", "이상급등", "KRX300", "KOSPI", "매출액", "영업이익",
                      "경상이익", "당기순이익", "ROE", "기준년월", "시가총액", "그룹사코드",
                      "회사신용한도초과", "담보대출가능", "대주가능"]
    df2 = pd.read_fwf(tmp2, widths=field_specs, names=part2_columns)
    df = pd.merge(df1, df2, how="outer", left_index=True, right_index=True)
    os.remove(tmp1)
    os.remove(tmp2)

    pure = df[(df["그룹코드"] == "ST") & (df["우선주"] == 0)]
    return [(row["단축코드"], row["한글명"], "KOSPI") for _, row in pure.iterrows()]


def get_kosdaq_tickers():
    mst_path = _download_mst(
        "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
        os.path.join(BASE_DIR, "kosdaq_code.zip"),
        "kosdaq_code.mst",
    )

    tmp1 = os.path.join(BASE_DIR, "_kosdaq_part1.tmp")
    tmp2 = os.path.join(BASE_DIR, "_kosdaq_part2.tmp")
    with open(tmp1, "w", encoding="utf-8") as wf1, open(tmp2, "w", encoding="utf-8") as wf2:
        with open(mst_path, mode="r", encoding="cp949") as f:
            for row in f:
                rf1 = row[0:len(row) - 222]
                wf1.write(rf1[0:9].rstrip() + "," + rf1[21:].strip() + "\n")
                wf2.write(row[-222:])

    df1 = pd.read_csv(tmp1, header=None, names=["단축코드", "한글종목명"], encoding="utf-8")

    # KIS 공식 kis_kosdaq_code_mst.py의 field_specs/part2_columns 그대로 사용(64개)
    field_specs = [2, 1,
                   4, 4, 4, 1, 1,
                   1, 1, 1, 1, 1,
                   1, 1, 1, 1, 1,
                   1, 1, 1, 1, 1,
                   1, 1, 1, 1, 9,
                   5, 5, 1, 1, 1,
                   2, 1, 1, 1, 2,
                   2, 2, 3, 1, 3,
                   12, 12, 8, 15, 21,
                   2, 7, 1, 1, 1,
                   1, 9, 9, 9, 5,
                   9, 8, 9, 3, 1,
                   1, 1
                   ]
    part2_columns = ["증권그룹구분코드", "시가총액규모구분코드유가", "지수업종대분류코드",
                      "지수업종중분류코드", "지수업종소분류코드", "벤처기업여부", "저유동성종목여부",
                      "KRX종목여부", "ETP상품구분코드", "KRX100종목여부", "KRX자동차여부",
                      "KRX반도체여부", "KRX바이오여부", "KRX은행여부", "기업인수목적회사여부",
                      "KRX에너지화학여부", "KRX철강여부", "단기과열종목구분코드", "KRX미디어통신여부",
                      "KRX건설여부", "투자주의환기종목여부", "KRX증권구분", "KRX선박구분",
                      "KRX섹터보험여부", "KRX섹터운송여부", "KOSDAQ150지수여부", "주식기준가",
                      "정규시장매매수량단위", "시간외시장매매수량단위", "거래정지여부", "정리매매여부",
                      "관리종목여부", "시장경고구분코드", "시장경고위험예고여부", "불성실공시여부",
                      "우회상장여부", "락구분코드", "액면가변경구분코드", "증자구분코드", "증거금비율",
                      "신용주문가능여부", "신용기간", "전일거래량", "주식액면가", "주식상장일자",
                      "상장주수", "자본금", "결산월", "공모가격", "우선주구분코드", "공매도과열종목여부",
                      "이상급등종목여부", "KRX300종목여부", "매출액", "영업이익", "경상이익",
                      "당기순이익", "ROE", "기준년월", "전일기준시가총액", "그룹사코드",
                      "회사신용한도초과여부", "담보대출가능여부", "대주가능여부"]
    df2 = pd.read_fwf(tmp2, widths=field_specs, names=part2_columns)
    df = pd.merge(df1, df2, how="outer", left_index=True, right_index=True)
    os.remove(tmp1)
    os.remove(tmp2)

    pure = df[
        (df["증권그룹구분코드"] == "ST")
        & (df["우선주구분코드"] == 0)
        & (df["기업인수목적회사여부"] == "N")
    ]
    return [(row["단축코드"], row["한글종목명"], "KOSDAQ") for _, row in pure.iterrows()]


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
