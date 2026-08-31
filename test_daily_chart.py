# -*- coding: utf-8 -*-
import json, os, datetime
import requests

BASE_URL = "https://openapi.koreainvestment.com:9443"

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

today = datetime.date.today()
start = today - datetime.timedelta(days=65)

url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
headers = {
    "content-type": "application/json; charset=utf-8",
    "authorization": f"Bearer {token}",
    "appkey": env["KIS_APP_KEY"],
    "appsecret": env["KIS_APP_SECRET"],
    "tr_id": "FHKST03010100",
    "custtype": "P",
}
params = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": "005930",
    "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
    "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
    "FID_PERIOD_DIV_CODE": "D",
    "FID_ORG_ADJ_PRC": "1",
}
res = requests.get(url, headers=headers, params=params, timeout=10)
data = res.json()
with open("raw_daily_chart_samsung.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("status", res.status_code, "rt_cd", data.get("rt_cd"), "msg", data.get("msg1"))
print("output2 rows:", len(data.get("output2", [])))
