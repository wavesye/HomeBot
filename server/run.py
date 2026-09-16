"""python -m server.run [--lan] [--port 8000]：本机或同 Wi-Fi 启动。"""

import argparse
import ipaddress
import os
import secrets
import socket

import uvicorn


def port_number(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("端口必须是 1 到 65535 的整数。") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须是 1 到 65535 的整数。")
    return port


def lan_addresses():
    """用本机主机名找 IPv4 候选地址；无法识别时由终端给出手动查询提示。"""
    try:
        entries = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    addresses = set()
    for entry in entries:
        value = entry[4][0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if not (address.is_loopback or address.is_unspecified or address.is_multicast):
            addresses.add(value)
    return sorted(addresses)


def main(argv=None):
    parser = argparse.ArgumentParser(description="启动 Homebot；默认仅本机访问，--lan 允许同 Wi-Fi 的手机访问。")
    parser.add_argument("--lan", action="store_true", help="允许局域网访问，并在未设置访问码时自动生成。")
    parser.add_argument("--port", type=port_number, default=8000, help="HTTP 端口（默认 8000）。")
    args = parser.parse_args(argv)

    access_code = os.environ.get("HOMEBOT_ACCESS_CODE", "")
    if args.lan and not access_code:
        access_code = secrets.token_urlsafe(12)
        os.environ["HOMEBOT_ACCESS_CODE"] = access_code

    print(f"Homebot v0.5 · 虚拟电机\n本机：http://localhost:{args.port}", flush=True)
    if args.lan:
        addresses = lan_addresses()
        for address in addresses:
            print(f"手机地址（候选）：http://{address}:{args.port}", flush=True)
        print("手机与电脑需连接同一 Wi-Fi；若地址不可用，请查看电脑 Wi-Fi 设置中的 IPv4 地址。", flush=True)
        if not addresses:
            print(f"未自动识别局域网地址：手机打开 http://<电脑 Wi-Fi IPv4>:{args.port}", flush=True)
        print("仅用于可信局域网：HTTP 不加密访问码，请勿暴露到公网。", flush=True)
    else:
        print("仅允许本机访问；手机访问请使用 python -m server.run --lan。", flush=True)
    if access_code:
        print(f"用户名：homebot\n访问码：{access_code}", flush=True)

    # 运动状态只存在当前进程，必须单进程；不要信任客户端提供的代理头。
    uvicorn.run(
        "server.main:app", host="0.0.0.0" if args.lan else "127.0.0.1",
        port=args.port, workers=1, reload=False, proxy_headers=False,
    )


if __name__ == "__main__":
    main()
