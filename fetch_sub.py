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
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
    return text.strip()


def extract_urls(text):
    urls = []
    for line in text.split('\n'):
        line = line.strip()
        found = re.findall(r'https?://[a-zA-Z0-9\-\._~:/?#[\]@!$&\'()*+,;=%]+', line)
        for u in found:
            u = re.sub(r'[：。，！？、；""''（）【】]+$', '', u)
            if u.startswith('http') and 'nodebuf.com' in u and '/download' in u:
                urls.append(u)
    return urls


def find_base64_url(messages):
    """只找包含 base64 / 通用订阅 关键词的消息里的下载链接"""
    for msg in messages:
        text = msg if isinstance(msg, str) else clean_html(msg)
        if 'base64' in text.lower() or '通用订阅' in text:
            urls = extract_urls(text)
            if urls:
                log(f"Found base64 keyword, URLs: {urls}")
                return urls[0]
    return None


def download(url):
    log(f"Downloading: {url}")
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://t.me/",
    }, timeout=30)
    r.raise_for_status()
    return r.text.strip()


def decode(content):
    raw = content.strip()
    
    # 如果已经是明文节点，直接返回
    if any(proto in raw[:1000] for proto in ['vmess://', 'vless://', 'trojan://', 'ss://', 'ssr://', 'hysteria2://', 'hy2://']):
        log("Content is already plain text nodes")
        return raw
    
    # 如果是 base64（单行、长字符串、无空格、符合 base64 字符集）
    if '\n' not in raw and len(raw) > 100 and re.match(r'^[A-Za-z0-9+/=]+$', raw):
        try:
            padded = raw + '=' * (4 - len(raw) % 4) if len(raw) % 4 else raw
            decoded = base64.b64decode(padded).decode('utf-8')
            if any(proto in decoded[:1000] for proto in ['vmess://', 'vless://', 'trojan://', 'ss://']):
                log(f"Base64 decoded: {len(decoded)} bytes")
                return decoded
        except Exception as e:
            log(f"Base64 decode failed: {e}")
    
    # 兜底：如果内容里有 vmess:// 等但被包裹在其他文本中
    lines = raw.split('\n')
    nodes = [l for l in lines if '://' in l and any(p in l for p in ['vmess://', 'vless://', 'trojan://', 'ss://'])]
    if nodes:
        log(f"Extracted {len(nodes)} node lines from raw text")
        return '\n'.join(nodes)
    
    raise ValueError("Downloaded content is not valid subscription (neither base64 nor plain nodes)")


def fetch_web():
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
        if "tgme_channel_history" not in r.text and "tgme_widget_message" not in r.text:
            log("t.me/s/ returned contact/restricted page")
            return None
        
        msgs = re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>', r.text)
        log(f"Extracted {len(msgs)} messages")
        return find_base64_url(msgs)
    except Exception as e:
        log(f"t.me/s/ error: {e}")
    return None


def fetch_bot():
    if not BOT_TOKEN:
        log("BOT_TOKEN not set")
        return None
    
    try:
        me = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=15).json()
        if not me.get("ok"):
            log(f"Bot auth failed: {me}")
            return None
        log(f"Bot OK: @{me['result']['username']}")
        
        chat = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
            params={"chat_id": f"@{CHANNEL}"},
            timeout=15
        ).json()
        
        if not chat.get("ok"):
            log(f"getChat failed: {chat}")
            return None
        
        pinned = chat["result"].get("pinned_message", {})
        text = pinned.get("text") or pinned.get("caption") or ""
        log(f"Pinned message length: {len(text)}")
        
        url = find_base64_url([text])
        if url:
            return url
        
        # 如果置顶没有，尝试最近更新
        updates = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"limit": 50},
            timeout=15
        ).json()
        
        if updates.get("ok"):
            for upd in reversed(updates["result"]):
                msg = upd.get("channel_post")
                if msg and msg.get("chat", {}).get("username") == CHANNEL:
                    text = msg.get("text") or msg.get("caption") or ""
                    url = find_base64_url([text])
                    if url:
                        return url
    except Exception as e:
        log(f"Bot API error: {e}")
    return None


def main():
    log("=== Start Fetch ===")
    
    sub_url = fetch_web()
    if not sub_url:
        sub_url = fetch_bot()
    
    if not sub_url:
        log("FAILED: No base64 subscription URL found")
        sys.exit(1)
    
    raw = download(sub_url)
    plain = decode(raw)
    
    with open(KV_FILE, "w", encoding="utf-8") as f:
        f.write(plain)
    
    log(f"SUCCESS: Saved plain nodes to {KV_FILE} ({len(plain)} bytes)")


if __name__ == "__main__":
    main()
