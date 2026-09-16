"""统一保护网页、静态资源和 API；HTTP Basic 仅适合可信局域网。"""

import base64
import binascii
import ipaddress
import os
import secrets
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse


def is_loopback(address):
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def parse_origin(value):
    """端口缺省时按 HTTP/HTTPS 的默认值比较，拒绝 null 和非法来源。"""
    try:
        url = urlsplit(value)
        if (
            url.scheme not in ("http", "https") or not url.hostname
            or url.username is not None or url.password is not None
            or url.path or url.query or url.fragment
        ):
            return None
        port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
        return url.scheme, url.hostname.lower(), port
    except ValueError:
        return None


def valid_credentials(authorization, access_code):
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    username, separator, password = decoded.partition(b":")
    username_ok = secrets.compare_digest(username, b"homebot")
    password_ok = secrets.compare_digest(password, access_code.encode("utf-8"))
    return bool(separator) and username_ok and password_ok


class AccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["Content-Security-Policy"] = "frame-ancestors 'none'"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        async def reject(code, detail, headers=None):
            await JSONResponse({"detail": detail}, status_code=code, headers=headers)(scope, receive, secure_send)

        headers = Headers(scope=scope)
        access_code = os.environ.get("HOMEBOT_ACCESS_CODE", "")
        if access_code:
            if not valid_credentials(headers.get("authorization", ""), access_code):
                await reject(401, "请输入用户名 homebot 和终端显示的访问码。", {
                    "WWW-Authenticate": 'Basic realm="Homebot", charset="UTF-8"',
                })
                return
        else:
            # 只检查 ASGI 对端，不相信 X-Forwarded-For；启动器也禁用代理头处理。
            peer = scope.get("client")
            if not peer or not is_loopback(peer[0]):
                await reject(503, "远程访问需要访问码，请在电脑终端运行 python -m server.run --lan。")
                return
            # 防止恶意域名解析到本机后，用自定义 Host 访问无密码的本机模式。
            host = headers.get("host")
            host_origin = parse_origin(f"{scope.get('scheme', 'http')}://{host}") if host else None
            if host and (not host_origin or not (host_origin[1] == "localhost" or is_loopback(host_origin[1]))):
                await reject(403, "本机模式请通过 localhost 或回环 IP 访问。")
                return

        origin = headers.get("origin")
        if origin is not None:
            host = headers.get("host")
            expected_origin = parse_origin(f"{scope.get('scheme', 'http')}://{host}") if host else None
            if expected_origin is None or parse_origin(origin) != expected_origin:
                await reject(403, "不允许其他网站发起请求，请直接打开 Homebot 页面。")
                return
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            fetch_site = headers.get("sec-fetch-site", "").lower()
            if fetch_site not in ("", "none", "same-origin"):
                await reject(403, "不允许跨站控制，请直接打开 Homebot 页面。")
                return

        await self.app(scope, receive, secure_send)
