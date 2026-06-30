#!/usr/bin/env python3
import os
import re
import sys
import requests

CHANNEL = "changfeng2021"
KV_FILE = "sub.txt"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def log(msg):
    print(f"[{__import__('datetime').datetime.now().isoformat()}] {msg}")

def fetch_telegram_web():
    """尝试直接抓取 t.me/s/（大概率失败，但值得一试）"""
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
            # 提取消息文本
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
    """通过 Bot API 获取频道置顶消息"""
    if not BOT_TOKEN:
        log("BOT_TOKEN not set, skipping Bot API")
        return None
    
    # 1. 验证 Bot
    me = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=15).json()
    if not me.get("ok"):
        log(f"Bot API auth failed: {me}")
        return None
    log(f"Bot OK: @{me['result']['username']}")
    
    # 2. 获取频道信息（公开频道无需加入）
    chat = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
        params={"chat_id": f"@{CHANNEL}"},
        timeout=15
    ).json()
    
    if not chat.get("ok"):
        log(f"getChat failed: {chat}")
        return None
    
    # 3. 提取置顶消息
    pinned = chat["result"].get("pinned_message", {})
    text = pinned.get("text") or pinned.get("caption") or ""
    log(f"Pinned message length: {len(text)}")
    
    urls = re.findall(r'https?://[^\s<>"]+', text)
    log(f"URLs in pinned: {urls}")
    
    for u in urls:
        if "nodebuf.com" in u and "/download" in u:
            return u
    
    # 4. 如果置顶没有，尝试 getUpdates（需 Bot 在频道内或频道有公开更新）
    log("No URL in pinned, trying getUpdates...")
    updates = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params={"limit": 50},
        timeout=15
    ).json()
    
    if updates.get("ok"):
        for upd in reversed(updates["result"]):
            msg = upd.get("channel_post", {})
            if msg.get("chat", {}).get("username") == CHANNEL:
                text = msg.get("text") or msg.get("caption") or ""
                for u in re.findall(r'https?://[^\s<>"]+', text):
                    if "nodebuf.com" in u and "/download" in u:
                        log(f"Found URL in update: {u}")
                        return u
    return None

def download_sub(url):
    """下载订阅内容"""
    log(f"Downloading: {url}")
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://t.me/",
    }, timeout=30)
    r.raise_for_status()
    content = r.text
    log(f"Downloaded {len(content)} bytes")
    if len(content) < 50:
        raise ValueError("Content too short")
    return content

def main():
    log("=== Start Fetch ===")
    
    # 策略1: t.me/s/
    sub_url = fetch_telegram_web()
    
    # 策略2: Bot API
    if not sub_url:
        sub_url = fetch_bot_api()
    
    if not sub_url:
        log("FAILED: No subscription URL found")
        sys.exit(1)
    
    # 下载并保存
    content = download_sub(sub_url)
    with open(KV_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    
    log(f"SUCCESS: Saved to {KV_FILE}")

if __name__ == "__main__":
    main()
