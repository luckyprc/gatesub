# scripts/fetch.py 替换版 —— 聚合多个免费节点源

import base64
import requests
import time
import os

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 公开免费节点订阅源（base64 编码的混合订阅）
SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub3.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v",
]

SUPPORTED = ("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hysteria://", "hy2://", "tuic://")

def fetch_nodes_from_url(url: str) -> list[str]:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        text = resp.text.strip()

        # 尝试 base64 解码
        try:
            decoded = base64.b64decode(text + "==").decode("utf-8", errors="ignore")
            text = decoded
        except Exception:
            pass

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return [l for l in lines if l.startswith(SUPPORTED)]
    except Exception as e:
        print(f"  ⚠️  Failed {url}: {e}")
        return []

def deduplicate(nodes: list[str]) -> list[str]:
    seen = set()
    result = []
    for n in nodes:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result

def main():
    all_nodes = []
    for url in SOURCES:
        print(f"📡 Fetching: {url}")
        nodes = fetch_nodes_from_url(url)
        print(f"   Got {len(nodes)} nodes")
        all_nodes.extend(nodes)

    all_nodes = deduplicate(all_nodes)
    print(f"\n✅ Total unique nodes: {len(all_nodes)}")

    # 统计协议分布
    for proto in SUPPORTED:
        count = sum(1 for n in all_nodes if n.startswith(proto))
        if count:
            print(f"   {proto:<12} {count}")

    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    # 输出 base64 订阅（V2rayNG / Hiddify 通用）
    content = "\n".join(all_nodes)
    b64 = base64.b64encode(content.encode()).decode()
    with open(f"{OUTPUT_DIR}/base64.txt", "w") as f:
        f.write(b64)

    # 输出明文（调试用）
    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        f.write(f"# Generated: {ts}  Total: {len(all_nodes)}\n")
        f.write(content)

    print(f"\n📁 Output written to {OUTPUT_DIR}/")

if __name__ == "__main__":
    main()
