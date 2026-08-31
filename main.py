# -*- coding: utf-8 -*-
"""
코스피·코스닥 60일/52주(달력일) 신고가·신저가 스크리닝 + 텔레그램 전송

매일 아침 GitHub Actions에서 이 스크립트 하나를 실행하는 것을 목표로 함.
필요한 환경변수(로컬 테스트 시 .env 파일, GitHub Actions에서는 repo secrets):
  KIS_APP_KEY, KIS_APP_SECRET               - 한국투자증권 실전투자 앱키
                                               (시세 조회 전용, 주문 코드 없음)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID       - 텔레그램 봇 토큰/chat_id
                                               (미설정 시 콘솔에만 출력)
  SAMPLE_LIMIT (선택)                        - 종목 수를 제한해 빠르게
                                               테스트하고 싶을 때 설정
                                               (예: 20). 미설정 시 전체 실행.

대상 종목: 코스피·코스닥 "순수 보통주"만(우선주/스팩/ETF/ETN/ELW 제외).
  기준 및 실측 근거는 method.txt 참고. 60일/52주 계산 결과 모두 이
  종목코드 집합으로 교차 필터링해 두 기준의 대상 종목을 완전히
  일치시킴(52주 API 자체의 제외 옵션은 한 번에 한 카테고리만 가능해서
  불완전하므로, 이렇게 교차 필터링으로 보완함).
"""

import os
import sys
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

# 실전투자 API 호출 제한(공식 안내 초당 20건)에 여유를 둔 호출 간격
CALL_INTERVAL_SEC = 0.08


# ---------------------------------------------------------------------------
# 환경변수 로딩: GitHub Actions에서는 os.environ, 로컬 테스트는 .env 파일
# ---------------------------------------------------------------------------

def load_env():
    env = dict(os.environ)
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


# ---------------------------------------------------------------------------
# 종목마스터 다운로드/파싱 → 순수 보통주만 필터링
# (실측 근거: method.txt 참고. 코스피 805 + 코스닥 1,730 = 2,535종목)
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
# KIS 인증 + 공통 헤더
# ---------------------------------------------------------------------------

def get_token(app_key, app_secret):
    res = requests.post(
        f"{BASE_URL}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
        timeout=10,
    )
    res.raise_for_status()
    return res.json()["access_token"]


def kis_headers(token, app_key, app_secret, tr_id, tr_cont=""):
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "tr_cont": tr_cont,
    }


# ---------------------------------------------------------------------------
# 52주(서버 기준) 신고가/신저가 — 근접비율 0.00% = 실제 경신 종목
# ---------------------------------------------------------------------------

def fetch_near_new_highlow(token, app_key, app_secret, fid_prc_cls_code, max_pages=30):
    url = f"{BASE_URL}/uapi/domestic-stock/v1/ranking/near-new-highlow"
    params = {
        "fid_aply_rang_vol": "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20187",
        "fid_div_cls_code": "0",
        "fid_input_cnt_1": "0",
        "fid_input_cnt_2": "0",       # 괴리율 0~0 => 정확히 신고/신저에 닿은 종목만
        "fid_prc_cls_code": fid_prc_cls_code,
        "fid_input_iscd": "0000",     # 코스피+코스닥 전체
        "fid_trgt_cls_code": "0",
        "fid_trgt_exls_cls_code": "0",
        "fid_aply_rang_prc_1": "0",
        "fid_aply_rang_prc_2": "1000000",
    }
    all_rows = []
    tr_cont = ""
    for _ in range(max_pages):
        headers = kis_headers(token, app_key, app_secret, "FHPST01870000", tr_cont)
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
        all_rows.extend(data.get("output", []))
        # KIS 관례: 응답 헤더의 tr_cont == "M" 이면 다음 페이지 있음
        if res.headers.get("tr_cont") != "M":
            break
        tr_cont = "N"
        time.sleep(CALL_INTERVAL_SEC)
    return all_rows


def get_52week_events(token, app_key, app_secret, pure_codes):
    """returns (new_high_rows, new_low_rows), 순수 보통주로만 교차 필터링됨"""
    high_rows = fetch_near_new_highlow(token, app_key, app_secret, "0")
    low_rows = fetch_near_new_highlow(token, app_key, app_secret, "1")

    new_high = [
        r for r in high_rows
        if r.get("mksc_shrn_iscd") in pure_codes and float(r.get("hprc_near_rate", "1") or 1) == 0.0
    ]
    new_low = [
        r for r in low_rows
        if r.get("mksc_shrn_iscd") in pure_codes and float(r.get("lwpr_near_rate", "1") or 1) == 0.0
    ]
    return new_high, new_low


# ---------------------------------------------------------------------------
# 60일(달력일) 신고가/신저가 — 종목별 일자별 시세로 직접 계산
# ---------------------------------------------------------------------------

def fetch_daily_closes(token, app_key, app_secret, code, days=65):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days)
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = kis_headers(token, app_key, app_secret, "FHKST03010100")
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
    closes = [(r["stck_bsop_date"], int(r["stck_clpr"])) for r in rows if r.get("stck_clpr") not in (None, "", "0")]
    closes.sort(key=lambda x: x[0])
    return closes, None


def judge_new_high_low(closes):
    if not closes:
        return None
    latest_date, latest_close = closes[-1]
    max_close = max(c for _, c in closes)
    min_close = min(c for _, c in closes)
    return {
        "latest_date": latest_date,
        "latest_close": latest_close,
        "period_high": max_close,
        "period_low": min_close,
        "is_new_high": latest_close >= max_close,
        "is_new_low": latest_close <= min_close,
    }


def get_60day_events(token, app_key, app_secret, universe):
    new_high, new_low = [], []
    for code, name, market in universe:
        closes, err = fetch_daily_closes(token, app_key, app_secret, code)
        time.sleep(CALL_INTERVAL_SEC)
        if err or not closes:
            continue
        r = judge_new_high_low(closes)
        if r is None:
            continue
        if r["is_new_high"]:
            new_high.append((market, code, name, r))
        if r["is_new_low"]:
            new_low.append((market, code, name, r))
    return new_high, new_low


# ---------------------------------------------------------------------------
# 메시지 포맷 + 텔레그램 전송
# ---------------------------------------------------------------------------

def fmt_52w_line(row):
    return f"  {row.get('hts_kor_isnm')}({row.get('mksc_shrn_iscd')})  {row.get('stck_prpr')}원"


def fmt_60d_line(item):
    market, code, name, r = item
    return f"  [{market}] {name}({code})  {r['latest_close']}원"


def build_message(today_str, high52, low52, high60, low60):
    lines = [f"📈 {today_str} 국내증시 신고가/신저가 스크리닝 (전일 종가 기준)", ""]

    lines.append(f"[52주 신고가] {len(high52)}종목")
    lines += [fmt_52w_line(r) for r in high52[:50]] or ["  없음"]
    if len(high52) > 50:
        lines.append(f"  ...외 {len(high52) - 50}종목")
    lines.append("")

    lines.append(f"[52주 신저가] {len(low52)}종목")
    lines += [fmt_52w_line(r) for r in low52[:50]] or ["  없음"]
    if len(low52) > 50:
        lines.append(f"  ...외 {len(low52) - 50}종목")
    lines.append("")

    lines.append(f"[60일 신고가] {len(high60)}종목")
    lines += [fmt_60d_line(r) for r in high60[:50]] or ["  없음"]
    if len(high60) > 50:
        lines.append(f"  ...외 {len(high60) - 50}종목")
    lines.append("")

    lines.append(f"[60일 신저가] {len(low60)}종목")
    lines += [fmt_60d_line(r) for r in low60[:50]] or ["  없음"]
    if len(low60) > 50:
        lines.append(f"  ...외 {len(low60) - 50}종목")

    return "\n".join(lines)


def send_telegram(token, chat_id, text):
    if not token or not chat_id:
        print("[텔레그램 미설정 - 콘솔 출력]\n")
        print(text)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # 텔레그램 메시지 4096자 제한 → 여유있게 3500자 단위로 분할 전송
    for i in range(0, len(text), 3500):
        chunk = text[i:i + 3500]
        res = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=10)
        if res.status_code != 200:
            print("텔레그램 전송 실패:", res.status_code, res.text)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    env = load_env()
    app_key = env["KIS_APP_KEY"]
    app_secret = env["KIS_APP_SECRET"]
    telegram_token = env.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = env.get("TELEGRAM_CHAT_ID")
    sample_limit = int(env.get("SAMPLE_LIMIT", "0") or "0")

    print("=== 1) 순수 보통주 종목마스터 준비 ===")
    kospi = get_kospi_tickers()
    kosdaq = get_kosdaq_tickers()
    universe = kospi + kosdaq
    if sample_limit:
        universe = kospi[:sample_limit] + kosdaq[:sample_limit]
    pure_codes = {code for code, _, _ in (kospi + kosdaq)}
    print(f"코스피 {len(kospi)}종목 + 코스닥 {len(kosdaq)}종목 (필터 후), 이번 실행 대상 {len(universe)}종목")

    print("=== 2) 인증 ===")
    token = get_token(app_key, app_secret)

    print("=== 3) 52주 신고가/신저가 조회 ===")
    high52, low52 = get_52week_events(token, app_key, app_secret, pure_codes)
    print(f"52주 신고가 {len(high52)}종목, 52주 신저가 {len(low52)}종목")

    print("=== 4) 60일 신고가/신저가 계산 ===")
    high60, low60 = get_60day_events(token, app_key, app_secret, universe)
    print(f"60일 신고가 {len(high60)}종목, 60일 신저가 {len(low60)}종목")

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    message = build_message(today_str, high52, low52, high60, low60)

    print("=== 5) 텔레그램 전송 ===")
    send_telegram(telegram_token, telegram_chat_id, message)


if __name__ == "__main__":
    sys.exit(main())
