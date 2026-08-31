# -*- coding: utf-8 -*-
"""
텔레그램 chat_id 확인용 헬퍼 스크립트

사용법:
  1) 텔레그램 앱에서 @BotFather 와 대화 -> /newbot -> 봇 이름/username 설정
     -> 발급받은 토큰을 .env에 TELEGRAM_BOT_TOKEN=... 으로 추가
  2) 텔레그램 앱에서 방금 만든 봇을 검색해 대화창을 열고 아무 메시지나
     (예: "hi") 전송
  3) 이 스크립트 실행: python get_telegram_chat_id.py
  4) 출력되는 chat_id 값을 .env에 TELEGRAM_CHAT_ID=... 로 추가
"""
import os
import requests


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


def main():
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("먼저 .env에 TELEGRAM_BOT_TOKEN=<봇토큰> 을 추가하세요.")
        return

    res = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    data = res.json()

    if not data.get("ok"):
        print("오류:", data)
        return

    results = data.get("result", [])
    if not results:
        print("아직 메시지가 없습니다. 텔레그램 앱에서 봇에게 먼저 메시지를 보낸 뒤 다시 실행하세요.")
        return

    print("=== 감지된 대화(chat) 목록 ===")
    seen = set()
    for item in results:
        msg = item.get("message") or item.get("channel_post")
        if not msg:
            continue
        chat = msg["chat"]
        cid = chat["id"]
        if cid in seen:
            continue
        seen.add(cid)
        name = chat.get("username") or chat.get("first_name") or chat.get("title")
        print(f"  chat_id = {cid}   (이름: {name}, 유형: {chat.get('type')})")

    print("\n위 chat_id 값을 .env에 TELEGRAM_CHAT_ID=<값> 으로 추가하세요.")


if __name__ == "__main__":
    main()
