# -*- coding: utf-8 -*-
import json, time
import requests

BASE_URL = "https://openapivts.koreainvestment.com:29443"

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

env = load_env()
with open("token_cache.json", encoding="utf-8") as f:
    token = json.load(f)["access_token"]

codes = ["005930", "000660", "035420", "051910", "005380", "006400", "035720", "105560"]

url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
headers = {
    "content-type": "application/json; charset=utf-8",
    "authorization": f"Bearer {token}",
    "appkey": env["KIS_APP_KEY"],
    "appsecret": env["KIS_APP_SECRET"],
    "tr_id": "FHKST03010100",
    "custtype": "P",
}

t0 = time.time()
for code in codes:
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": "20260701",
        "FID_INPUT_DATE_2": "20260831",
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }
    t1 = time.time()
    res = requests.get(url, headers=headers, params=params, timeout=10)
    data = res.json()
    elapsed = time.time() - t1
    print(code, "status", res.status_code, "rt_cd", data.get("rt_cd"), "msg", data.get("msg1"), f"{elapsed:.2f}s")

print("total elapsed:", time.time() - t0)
