#!/usr/bin/env python3
import os
import re
import sys
import requests

CHANNEL = "changfengchannel"  # ← 改这里
KV_FILE = "sub.txt"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def log(msg):
    print(f"[{__import__('datetime').datetime.now().isoformat()}] {msg}")

def fetch_telegram_web():
    url = f"https://t.me/s/{CHANNEL}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://t.me/",
        "Cache-Control": "no-cache",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        log(f"t.me/s/ status: {r.status_code}, length: {len(r.text)}")
        if "tgme_channel_history" in r.text or "tgme_widget_message" in r.text:
            msgs = re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>', r.text)
            log(f"Extracted {len(msgs)} messages from web")
            for m in msgs:
                text = re.sub(r'<[^>]+>', '', m).replace('&nbsp;', ' ').strip()
                urls = re.findall(r'https?://[^\s<>"]+', text)
                for u in urls:
                    if "nodebuf.com" in u and "/download" in u:
                        return u
        else:
            log("t.me/s/ returned contact/restricted page, skipping")
    except Exception as e:
        log(f"t.me/s/ error: {e}")
    return None

def fetch_bot_api():
    if not BOT_TOKEN:
        log("BOT_TOKEN not set, skipping Bot API")
        return None
    
    me = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=15).json()
    if not me.get("ok"):
        log(f"Bot API auth failed: {me}")
        return None
    log(f"Bot OK: @{me['result']['username']}")
    
    chat = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
        params={"chat_id": f"@{CHANNEL}"},
        timeout=15
    ).json()
    
    if chat.get("ok"):
        log(f"getChat OK: {chat['result'].get('title', 'unknown')}")
        pinned = chat["result"].get("pinned_message", {})
        text = pinned.get("text") or pinned.get("caption") or ""
        log(f"Pinned message length: {len(text)}")
        
        urls = re.findall(r'https?://[^\s<>"]+', text)
        log(f"URLs in pinned: {urls}")
        
        for u in urls:
            if "nodebuf.com" in u and "/download" in u:
                return u
    else:
        log(f"getChat failed: {chat}")
        log("Trying getUpdates...")
        
        updates = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"limit": 100},
            timeout=15
        ).json()
        
        if updates.get("ok"):
            log(f"Got {len(updates['result'])} updates")
            for upd in reversed(updates["result"]):
                msg = upd.get("channel_post")
                if msg and msg.get("chat", {}).get("username") == CHANNEL:
                    text = msg.get("text") or msg.get("caption") or ""
                    for u in re.findall(r'https?://[^\s<>"]+', text):
                        if "nodebuf.com" in u and "/download" in u:
                            log(f"Found URL in update: {u}")
                            return u
        else:
            log(f"getUpdates failed: {updates}")
    
    return None

def download_sub(url):
    log(f"Downloading: {url}")
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://t.me/",
    }, timeout=30)
