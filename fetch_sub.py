#!/usr/bin/env python3
import os
import re
import sys
import base64
import requests

CHANNEL = "changfengchannel"
KV_FILE = "sub.txt"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


def log(msg):
    print(f"[{__import__('datetime').datetime.now().isoformat()}] {msg}")


def clean_html(raw):
    text = raw.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    text = re.sub(r'<[^>]+>', '', text).replace('&nbsp;', ' ').replace('&#39;', "'")
    return text.strip()


def extract_urls(text):
    urls = []
    for line in text.split('\n'):
        line = line.strip()
        found = re.findall(r'https?://[a-zA-Z0-9\-\._~:/?#[\]@!$&\'()*+,;=%]+', line)
        for u in found:
            u = re.sub(r'[：。，！？、；""''（）【】]+$', '', u)
            if u.startswith('http'):
                urls.append(u)
    return urls


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

            # 策略1：优先找包含 Base64 / 通用订阅 的消息
            for m in msgs:
                text = clean_html(m)
                if 'base64' in text.lower() or '通用订阅' in text:
                    urls = extract_urls(text)
                    log(f"Base64 message URLs: {urls}")
                    for u in urls:
                        if "nodebuf.com" in u and "/download" in u:
                            log(f"Found Base64 sub URL: {u}")
                            return u

            # 策略2：兜底，任意 nodebuf download 链接
            for m in msgs:
                text = clean_html(m)
                urls = extract_urls(text)
                for u in urls:
                    if "nodebuf.com" in u and "/download" in u:
                        log(f"Found fallback URL: {u}")
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

        # 优先找 Base64 链接
        if 'base64' in text.lower() or '通用订阅' in text:
            urls = extract_urls(text)
            log(f"Base64 URLs in pinned: {urls}")
            for u in urls:
                if "nodebuf.com" in u and "/download" in u:
                    log(f"Found Base64 URL: {u}")
                    return u

        # 兜底
        urls = extract_urls(text)
        for u in urls:
            if "nodebuf.com" in u and "/download" in u:
                return u
    else:
        log(f"getChat failed: {chat}")

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
                    if 'base64' in text.lower() or '通用订阅' in text:
                        for u in extract_urls(text):
                            if "nodebuf.com" in u and "/download" in u:
                                log(f"Found Base64 URL in update: {u}")
                                return u
                    for u in extract_urls(text):
                        if "nodebuf.com" in u and "/download" in u:
                            return u
        else:
            log(f"getUpdates failed: {updates}")

    return None


def download_and_decode(url):
    log(f"Downloading: {url}")
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://t.me/",
    }, timeout=30)
    r.raise_for_status()
    raw = r.text.strip()
    log(f"Downloaded {len(raw)} bytes")

    if len(raw) < 50:
        raise ValueError("Content too short")

    # 如果内容已经是明文节点（不是 base64），直接返回
    if '://' in raw[:500] and not raw.startswith('mixed-port:'):
        log("Content is already plain text nodes, no decoding needed")
        return raw

    # 尝试 base64 解码
    try:
        padded = raw + '=' * (4 - len(raw) % 4) if len(raw) % 4 else raw
        decoded = base64.b64decode(padded).decode('utf-8')
        log(f"Base64 decoded: {len(decoded)} bytes")

        # 验证解码结果是否像订阅内容
        if '://' in decoded[:500] or decoded.strip().startswith('{'):
            return decoded
        else:
            log("WARNING: Decoded content does not look like subscription, returning raw")
            return raw
    except Exception as e:
        log(f"Base64 decode failed: {e}, returning raw content")
        return raw


def main():
    log("=== Start Fetch ===")
    sub_url = fetch_telegram_web()
    if not sub_url:
        sub_url = fetch_bot_api()
    if not sub_url:
        log("FAILED: No subscription URL found")
        sys.exit(1)

    content = download_and_decode(sub_url)
    with open(KV_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    log(f"SUCCESS: Saved decoded content to {KV_FILE} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
