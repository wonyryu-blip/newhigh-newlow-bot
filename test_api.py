# -*- coding: utf-8 -*-
"""
KIS Developers "국내주식 신고/신저근접종목 상위" API 실제 호출 검증용 스크립트

목적:
  - 이 API가 코스피+코스닥 전체를 커버하는지 확인
  - 응답에 "기간"(60일/52주 등)을 유추할 수 있는 필드가 있는지 원본 JSON 전체 확인
  - fid_prc_cls_code=0(신고근접)/1(신저근접) 각각 정상 동작하는지 확인

실행 방법:
  1) pip install requests
  2) 이 파일과 같은 폴더에 .env 파일이 있는지 확인 (KIS_APP_KEY, KIS_APP_SECRET)
  3) python test_api.py
  4) 콘솔에 출력되는 내용을 통째로 복사해서 알려주세요.

주의:
  - 조회(읽기 전용) API만 호출합니다. 주문/매매는 절대 하지 않습니다.
  - 이 .env의 앱키는 모의투자용이므로 모의투자 도메인
    (openapivts.koreainvestment.com:29443)을 사용합니다.
  - 순위분석(신고/신저근접종목) 같은 일부 API는 모의투자 환경에서
    아예 지원되지 않을 수도 있습니다. 이 스크립트를 돌려보면 그
    지원 여부 자체도 함께 확인됩니다(오류 응답이 나오면 미지원
    가능성이 큼).
"""

import os
import json
import requests

BASE_URL = "https://openapivts.koreainvestment.com:29443"  # 모의투자 도메인


def load_env(path=".env"):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def get_token(app_key, app_secret, cache_path="token_cache.json"):
    # 토큰 발급은 1분에 1회 제한이 있어서, 하루 유효한 토큰을 파일로
    # 캐시해두고 재사용한다.
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        print("=== 캐시된 토큰 재사용 ===")
        return cached["access_token"]

    url = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    res = requests.post(url, json=body, timeout=10)
    print("=== 토큰 발급 응답 ===")
    print(res.status_code, res.text)
    res.raise_for_status()
    data = res.json()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data["access_token"]


def call_near_new_highlow(token, app_key, app_secret, fid_input_iscd, fid_prc_cls_code, label):
    url = f"{BASE_URL}/uapi/domestic-stock/v1/ranking/near-new-highlow"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHPST01870000",
        "custtype": "P",
    }
    params = {
        "fid_aply_rang_vol": "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20187",
        "fid_div_cls_code": "0",
        "fid_input_cnt_1": "0",
        "fid_input_cnt_2": "100",
        "fid_prc_cls_code": fid_prc_cls_code,   # 0:신고근접, 1:신저근접
        "fid_input_iscd": fid_input_iscd,       # 0000/0001/1001
        "fid_trgt_cls_code": "0",
        "fid_trgt_exls_cls_code": "0",
        "fid_aply_rang_prc_1": "0",
        "fid_aply_rang_prc_2": "1000000",
    }
    res = requests.get(url, headers=headers, params=params, timeout=10)
    print(f"\n=== [{label}] 응답 (iscd={fid_input_iscd}, prc_cls={fid_prc_cls_code}) ===")
    print("status:", res.status_code)
    try:
        data = res.json()
    except Exception:
        print(res.text)
        return

    output = data.get("output", [])
    print("총 rt_cd:", data.get("rt_cd"), "msg:", data.get("msg1"))
    print("응답 종목 수:", len(output))
    if output:
        print("--- 첫 번째 종목의 전체 필드(키/값) ---")
        for k, v in output[0].items():
            print(f"  {k}: {v}")
        print("--- 상위 5개 종목 요약(종목명/현재가/신고가/신저가) ---")
        for row in output[:5]:
            print(
                row.get("hts_kor_isnm"),
                "| 현재가:", row.get("stck_prpr"),
                "| 신최고가:", row.get("new_hgpr"),
                "| 고가근접비율:", row.get("hprc_near_rate"),
                "| 신최저가:", row.get("new_lwpr"),
                "| 저가근접비율:", row.get("lwpr_near_rate"),
            )


def dump_raw_json(token, app_key, app_secret, fid_input_iscd, fid_prc_cls_code, out_path):
    url = f"{BASE_URL}/uapi/domestic-stock/v1/ranking/near-new-highlow"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHPST01870000",
        "custtype": "P",
    }
    params = {
        "fid_aply_rang_vol": "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20187",
        "fid_div_cls_code": "0",
        "fid_input_cnt_1": "0",
        "fid_input_cnt_2": "100",
        "fid_prc_cls_code": fid_prc_cls_code,
        "fid_input_iscd": fid_input_iscd,
        "fid_trgt_cls_code": "0",
        "fid_trgt_exls_cls_code": "0",
        "fid_aply_rang_prc_1": "0",
        "fid_aply_rang_prc_2": "1000000",
    }
    res = requests.get(url, headers=headers, params=params, timeout=10)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res.json(), f, ensure_ascii=False, indent=2)
    print(f"저장됨: {out_path}")


def main():
    env = load_env()
    app_key = env["KIS_APP_KEY"]
    app_secret = env["KIS_APP_SECRET"]

    token = get_token(app_key, app_secret)

    # 1) 전체(0000)로 조회했을 때 코스피+코스닥이 다 섞여 나오는지 확인
    call_near_new_highlow(token, app_key, app_secret, "0000", "0", "신고근접-전체")
    call_near_new_highlow(token, app_key, app_secret, "0000", "1", "신저근접-전체")

    # 2) 코스피(0001)만, 코스닥(1001)만 따로 조회했을 때와 비교
    call_near_new_highlow(token, app_key, app_secret, "0001", "0", "신고근접-코스피")
    call_near_new_highlow(token, app_key, app_secret, "1001", "0", "신고근접-코스닥")

    # 3) 한글 깨짐 없이 분석하기 위해 원본 JSON을 UTF-8 파일로 저장
    dump_raw_json(token, app_key, app_secret, "0000", "0", "raw_new_high_all.json")
    dump_raw_json(token, app_key, app_secret, "0000", "1", "raw_new_low_all.json")
    dump_raw_json(token, app_key, app_secret, "0001", "0", "raw_new_high_kospi.json")
    dump_raw_json(token, app_key, app_secret, "1001", "0", "raw_new_high_kosdaq.json")


if __name__ == "__main__":
    main()
