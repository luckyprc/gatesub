#!/usr/bin/env python3
"""
VPN Gate → 多格式订阅转换器
输出：
  output/clash.yaml        Clash/Hiddify Meta 格式
  output/base64.txt        V2rayNG / 通用 Base64 订阅
  output/singbox.json      SingBox outbounds
  output/nodes.txt         明文节点列表（调试用）
"""

import base64
import csv
import io
import json
import os
import re
import time
import requests
import yaml

# ── 配置 ────────────────────────────────────────────────────────────────────
VPN_GATE_URL  = "https://www.vpngate.net/api/iphone/"
TOP_N         = 20          # 保留节点数
MIN_SPEED_BPS = 1_000_000   # 最低下行速度 1 Mbps
MAX_PING_MS   = 200         # 最大延迟
PREFER_COUNTRIES = ["JP", "KR", "US", "SG", "HK", "TW", "CA", "DE"]
OUTPUT_DIR    = "output"
# ────────────────────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_csv() -> list[dict]:
    """抓取 VPN Gate CSV，跳过首行注释"""
    resp = requests.get(VPN_GATE_URL, timeout=30)
    resp.raise_for_status()
    text = resp.text

    # 去掉首行 "*vpn_servers" 注释
    lines = [l for l in text.splitlines() if not l.startswith("*")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    return list(reader)


def score_node(row: dict) -> float:
    """综合评分：速度权重 60%，延迟权重 30%，优选国家权重 10%"""
    try:
        speed = float(row.get("Speed", 0))
        ping  = float(row.get("Ping", 9999))
    except ValueError:
        return -1

    if speed < MIN_SPEED_BPS or ping > MAX_PING_MS:
        return -1

    speed_score   = min(speed / 10_000_000, 1.0)          # 归一化到 10 Mbps
    ping_score    = max(0, 1 - ping / MAX_PING_MS)
    country_score = 1.0 if row.get("CountryShort", "") in PREFER_COUNTRIES else 0.0

    return speed_score * 0.6 + ping_score * 0.3 + country_score * 0.1


def decode_ovpn(row: dict) -> str | None:
    """从 base64 字段解码 OpenVPN config"""
    raw = row.get("OpenVPN_ConfigData_Base64", "").strip()
    if not raw:
        return None
    try:
        return base64.b64decode(raw).decode("utf-8", errors="ignore")
    except Exception:
        return None


def parse_ovpn(config: str, row: dict) -> dict | None:
    """
    从 OpenVPN config 提取连接参数，转为统一 node dict
    VPN Gate 节点均为 TCP/UDP OpenVPN，无法直接转 vmess/vless，
    这里生成 OpenVPN URI（兼容 Hiddify）以及 Clash 的 OpenVPN proxy 块
    """
    host = row.get("HostName", "").strip() or row.get("IP", "").strip()
    country = row.get("CountryShort", "XX")
    speed_mb = round(float(row.get("Speed", 0)) / 1_000_000, 1)
    ping = row.get("Ping", "?")

    # 提取端口（优先 TCP）
    port = 1194
    proto = "tcp"
    for line in config.splitlines():
        m = re.match(r"^remote\s+\S+\s+(\d+)\s*(tcp|udp)?", line, re.I)
        if m:
            port = int(m.group(1))
            if m.group(2):
                proto = m.group(2).lower()
            break

    # 提取 CA cert（用于 Clash）
    ca_match = re.search(r"<ca>(.*?)</ca>", config, re.S)
    ca = ca_match.group(1).strip() if ca_match else ""

    name = f"[{country}] {host}:{port} {speed_mb}M {ping}ms"

    return {
        "name": name,
        "host": host,
        "port": port,
        "proto": proto,
        "ca": ca,
        "country": country,
        "speed": speed_mb,
        "ping": ping,
        "ovpn_config": config,
    }


# ── 格式转换器 ────────────────────────────────────────────────────────────────

def to_clash_proxy(node: dict) -> dict:
    """Clash Meta / Hiddify Meta OpenVPN proxy block"""
    proxy = {
        "name": node["name"],
        "type": "wireguard",   # placeholder；Clash Meta 暂不原生支持 OpenVPN
        # 实际请使用 Hiddify 的 openvpn type（见下方注释）
    }
    # Hiddify Meta 扩展支持 openvpn type：
    proxy = {
        "name": node["name"],
        "type": "openvpn",
        "server": node["host"],
        "port": node["port"],
        "proto": node["proto"],
        "ca": node["ca"],
        "cipher": "AES-256-GCM",
        "auth": "SHA512",
        "tls": True,
    }
    return proxy


def build_clash_yaml(nodes: list[dict]) -> str:
    data = {
        "proxies": [to_clash_proxy(n) for n in nodes],
        "proxy-groups": [
            {
                "name": "VPNGate",
                "type": "url-test",
                "proxies": [n["name"] for n in nodes],
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
            }
        ],
        "rules": ["MATCH,VPNGate"],
    }
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


def build_base64_sub(nodes: list[dict]) -> str:
    """
    V2rayNG / 通用订阅：每行一个 ovpn:// URI（base64 包装整段配置）
    格式：ovpn://<base64(config)>#<name>
    """
    lines = []
    for n in nodes:
        cfg_b64 = base64.b64encode(n["ovpn_config"].encode()).decode()
        uri = f"ovpn://{cfg_b64}#{n['name']}"
        lines.append(uri)
    all_text = "\n".join(lines)
    return base64.b64encode(all_text.encode()).decode()


def build_singbox(nodes: list[dict]) -> str:
    outbounds = []
    for n in nodes:
        outbounds.append({
            "type": "openvpn",
            "tag": n["name"],
            "server": n["host"],
            "server_port": n["port"],
            "transport": n["proto"],
            "tls": {"enabled": True, "ca": n["ca"]},
        })
    # selector outbound
    outbounds.insert(0, {
        "type": "selector",
        "tag": "VPNGate",
        "outbounds": [n["name"] for n in nodes],
    })
    return json.dumps({"outbounds": outbounds}, ensure_ascii=False, indent=2)


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    print("📡 Fetching VPN Gate CSV …")
    rows = fetch_csv()
    print(f"   Total rows: {len(rows)}")

    # 评分 & 过滤
    scored = [(score_node(r), r) for r in rows]
    scored = [(s, r) for s, r in scored if s >= 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_rows = [r for _, r in scored[:TOP_N * 3]]   # 多取几个，防解码失败

    # 解码 & 解析
    nodes = []
    for row in top_rows:
        config = decode_ovpn(row)
        if not config:
            continue
        node = parse_ovpn(config, row)
        if node:
            nodes.append(node)
        if len(nodes) >= TOP_N:
            break

    print(f"   Selected nodes: {len(nodes)}")

    if not nodes:
        print("⚠️  No valid nodes found, keeping previous output.")
        return

    # 写文件
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    with open(f"{OUTPUT_DIR}/clash.yaml", "w", encoding="utf-8") as f:
        f.write(f"# Generated: {ts}\n")
        f.write(build_clash_yaml(nodes))

    with open(f"{OUTPUT_DIR}/base64.txt", "w", encoding="utf-8") as f:
        f.write(build_base64_sub(nodes))

    with open(f"{OUTPUT_DIR}/singbox.json", "w", encoding="utf-8") as f:
        f.write(build_singbox(nodes))

    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        f.write(f"# Generated: {ts}\n")
        for n in nodes:
            f.write(f"{n['name']}\n")

    print("✅ Done!")
    for fname in ["clash.yaml", "base64.txt", "singbox.json", "nodes.txt"]:
        size = os.path.getsize(f"{OUTPUT_DIR}/{fname}")
        print(f"   {fname}: {size} bytes")


if __name__ == "__main__":
    main()
