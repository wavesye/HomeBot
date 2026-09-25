"""直接调用 ASGI 应用验证访问保护，不连接网络或真实硬件。"""

import base64
import json
import os
import unittest
from unittest.mock import Mock, patch

from server import main
from server.access import AccessMiddleware


def basic(code="test-access-code", username="homebot"):
    return "Basic " + base64.b64encode(f"{username}:{code}".encode()).decode()


async def request(method, path, payload=None, *, headers=None, client=("192.168.1.10", 1234)):
    body = b"" if payload is None else json.dumps(payload).encode()
    responses = []
    request_headers = {"host": "192.168.1.20:8000", "content-type": "application/json"}
    request_headers.update(headers or {})

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        responses.append(message)

    await main.app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "",
        "headers": [(name.encode(), value.encode("latin-1")) for name, value in request_headers.items()],
        "client": client, "server": ("192.168.1.20", 8000),
    }, receive, send)
    start = next(message for message in responses if message["type"] == "http.response.start")
    response_headers = {name.decode(): value.decode() for name, value in start["headers"]}
    data = b"".join(message.get("body", b"") for message in responses if message["type"] == "http.response.body")
    return start["status"], response_headers, data


class AccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"HOMEBOT_ACCESS_CODE": "test-access-code"})
        environment.start()
        self.addCleanup(environment.stop)
        self.motor = Mock()
        self.camera = Mock()
        self.camera.get_frame.return_value = b"test-jpeg"
        for name, value in (("motor", self.motor), ("camera", self.camera)):
            patcher = patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        main.reset_status(main.MockMotorController())

    def assert_security_headers(self, headers):
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["content-security-policy"], "frame-ancestors 'none'")
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertNotIn("access-control-allow-origin", headers)

    async def test_all_routes_require_authentication_without_touching_hardware(self):
        for method, path in (
            ("GET", "/"), ("GET", "/static/index.html"), ("GET", "/static/app.js"),
            ("GET", "/static/style.css"), ("GET", "/docs"), ("GET", "/redoc"),
            ("GET", "/docs/oauth2-redirect"), ("GET", "/openapi.json"),
            ("GET", "/api/status"), ("POST", "/api/move"), ("POST", "/api/heartbeat"),
            ("POST", "/api/camera/start"), ("GET", "/api/camera/frame"),
            ("POST", "/api/camera/stop"), ("GET", "/missing"),
        ):
            with self.subTest(path=path):
                code, headers, _ = await request(method, path)
                self.assertEqual(code, 401)
                self.assertEqual(headers["www-authenticate"], 'Basic realm="Homebot", charset="UTF-8"')
                self.assert_security_headers(headers)
        self.assertEqual(self.motor.mock_calls, [])
        self.assertEqual(self.camera.mock_calls, [])

    async def test_wrong_or_malformed_credentials_are_rejected(self):
        for value in (
            basic("wrong"), basic(username="other"), "Bearer token", "Basic !!!",
            "Basic " + base64.b64encode(b"homebot").decode(), "Basic \xff", "",
        ):
            with self.subTest(value=value):
                code, _, _ = await request("POST", "/api/camera/start", headers={"authorization": value})
                self.assertEqual(code, 401)
        self.camera.start.assert_not_called()

    async def test_correct_credentials_allow_html_static_docs_and_status(self):
        for path in ("/", "/static/app.js", "/static/style.css", "/docs", "/openapi.json", "/api/status"):
            with self.subTest(path=path):
                code, headers, _ = await request("GET", path, headers={"authorization": basic()})
                self.assertEqual(code, 200)
                self.assert_security_headers(headers)
        self.assertEqual(self.camera.mock_calls, [])
        self.assertEqual(self.motor.mock_calls, [])

    async def test_correct_credentials_allow_camera_and_movement(self):
        headers = {"authorization": basic()}
        code, _, _ = await request("POST", "/api/move", {"direction": "left", "speed": 0.4}, headers=headers)
        self.assertEqual(code, 200)
        self.motor.turn_left.assert_called_once_with(0.4)
        code, _, _ = await request("POST", "/api/camera/start", headers=headers)
        self.assertEqual(code, 200)
        self.camera.start.assert_called_once_with()
        code, response_headers, data = await request("GET", "/api/camera/frame", headers=headers)
        self.assertEqual(code, 200)
        self.assertEqual(data, b"test-jpeg")
        self.assert_security_headers(response_headers)

    async def test_configured_code_is_required_even_on_loopback(self):
        code, _, _ = await request("GET", "/api/status", client=("127.0.0.1", 1234), headers={"host": "localhost:8000"})
        self.assertEqual(code, 401)

    async def test_utf8_and_colon_in_access_code(self):
        os.environ["HOMEBOT_ACCESS_CODE"] = "测试:code"
        code, _, _ = await request("GET", "/api/status", headers={"authorization": basic("测试:code")})
        self.assertEqual(code, 200)

    async def test_without_code_only_real_loopback_can_connect(self):
        os.environ.pop("HOMEBOT_ACCESS_CODE")
        for address, host in (("127.0.0.1", "localhost:8000"), ("127.0.0.2", "127.0.0.2:8000"), ("::1", "[::1]:8000")):
            with self.subTest(address=address):
                code, headers, _ = await request("GET", "/api/status", client=(address, 1234), headers={"host": host})
                self.assertEqual(code, 200)
                self.assert_security_headers(headers)
        for client in (("192.168.1.10", 1234), ("8.8.8.8", 1234), ("invalid", 1234), ("localhost", 1234), None):
            with self.subTest(client=client):
                code, headers, data = await request("POST", "/api/camera/start", client=client)
                self.assertEqual(code, 503)
                self.assertIn("python -m server.run --lan", json.loads(data)["detail"])
                self.assert_security_headers(headers)
        self.camera.start.assert_not_called()

    async def test_empty_code_also_refuses_remote_access(self):
        os.environ["HOMEBOT_ACCESS_CODE"] = ""
        code, _, _ = await request("GET", "/")
        self.assertEqual(code, 503)

    async def test_forwarded_headers_cannot_impersonate_loopback(self):
        os.environ["HOMEBOT_ACCESS_CODE"] = ""
        code, _, _ = await request("POST", "/api/camera/start", headers={
            "host": "localhost:8000", "x-forwarded-for": "127.0.0.1",
            "forwarded": "for=127.0.0.1;host=localhost:8000", "x-real-ip": "127.0.0.1",
        })
        self.assertEqual(code, 503)
        self.camera.start.assert_not_called()

    async def test_unprotected_local_mode_rejects_rebinding_host(self):
        os.environ["HOMEBOT_ACCESS_CODE"] = ""
        for host in ("evil.example:8000", "localhost.evil:8000", "user@localhost:8000", "localhost:invalid"):
            with self.subTest(host=host):
                code, _, _ = await request("GET", "/", client=("127.0.0.1", 1234), headers={"host": host})
                self.assertEqual(code, 403)

    async def test_cross_origin_requests_are_rejected_before_hardware(self):
        for origin in (
            "http://evil.example", "null", "https://192.168.1.20:8000", "http://192.168.1.20:9000",
            "http://192.168.1.20:8000/path", "http://user@192.168.1.20:8000", "http://[bad",
        ):
            with self.subTest(origin=origin):
                code, headers, _ = await request("POST", "/api/camera/start", headers={"authorization": basic(), "origin": origin})
                self.assertEqual(code, 403)
                self.assert_security_headers(headers)
        self.camera.start.assert_not_called()

    async def test_cross_site_metadata_rejects_posts_without_origin(self):
        for site in ("cross-site", "same-site"):
            code, _, _ = await request("POST", "/api/move", {"direction": "forward", "speed": 1}, headers={
                "authorization": basic(), "sec-fetch-site": site,
            })
            self.assertEqual(code, 403)
        self.assertEqual(self.motor.mock_calls, [])

    async def test_same_origin_and_cli_requests_are_allowed(self):
        for extra in ({}, {"origin": "http://192.168.1.20:8000", "sec-fetch-site": "same-origin"}, {"sec-fetch-site": "none"}):
            code, _, _ = await request("POST", "/api/camera/start", headers={"authorization": basic(), **extra})
            self.assertEqual(code, 200)
        self.assertEqual(self.camera.start.call_count, 3)

    async def test_origin_comparison_normalizes_default_port_and_host_case(self):
        code, _, _ = await request("POST", "/api/camera/start", headers={
            "authorization": basic(), "host": "LOCALHOST:80", "origin": "http://localhost",
        })
        self.assertEqual(code, 200)

    async def test_explicit_zero_port_is_not_treated_as_default_port(self):
        code, _, _ = await request("POST", "/api/camera/start", headers={
            "authorization": basic(), "host": "localhost:80", "origin": "http://localhost:0",
        })
        self.assertEqual(code, 403)
        self.camera.start.assert_not_called()

    async def test_cross_origin_preflight_and_null_get_are_not_allowed(self):
        for method, origin in (("OPTIONS", "http://evil.example"), ("GET", "null")):
            code, headers, _ = await request(method, "/api/status", headers={"authorization": basic(), "origin": origin})
            self.assertEqual(code, 403)
            self.assertNotIn("access-control-allow-origin", headers)

    async def test_security_headers_cover_not_found_and_validation_errors(self):
        for method, path, expected in (("GET", "/missing", 404), ("POST", "/api/move", 422)):
            code, headers, _ = await request(method, path, headers={"authorization": basic()})
            self.assertEqual(code, expected)
            self.assert_security_headers(headers)

    async def test_non_http_scope_passes_through(self):
        seen = []

        async def downstream(scope, receive, send):
            seen.append(scope)

        scope = {"type": "lifespan"}
        await AccessMiddleware(downstream)(scope, None, None)
        self.assertEqual(seen, [scope])


if __name__ == "__main__":
    unittest.main()
