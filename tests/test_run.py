"""启动参数与地址提示测试；uvicorn 被替换，不会真的监听局域网。"""

import io
import os
import socket
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from server import run


class LauncherTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"HOMEBOT_ACCESS_CODE": "", "HOMEBOT_MOTOR": "mock", "HOMEBOT_CAMERA": "opencv", "HOMEBOT_INVERT_LEFT": "0", "HOMEBOT_INVERT_RIGHT": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        server = patch.object(run.uvicorn, "run")
        self.server = server.start()
        self.addCleanup(server.stop)
        addresses = patch.object(run, "lan_addresses", return_value=["192.168.1.20"])
        self.addresses = addresses.start()
        self.addCleanup(addresses.stop)

    def launch(self, args):
        with redirect_stdout(io.StringIO()) as output:
            run.main(args)
        return output.getvalue()

    def test_defaults_are_local_single_process_and_ignore_proxy_headers(self):
        output = self.launch([])
        self.assertEqual(os.environ["HOMEBOT_CAMERA"], "opencv")
        self.server.assert_called_once_with("server.main:app", host="127.0.0.1", port=8000, workers=1, reload=False, proxy_headers=False)
        self.assertIn("http://localhost:8000", output)
        self.assertIn("python -m server.run --lan", output)
        self.assertNotIn("访问码：", output)
        self.addresses.assert_not_called()

    def test_lan_generates_access_code_before_starting_server(self):
        observed_codes = []
        self.server.side_effect = lambda *args, **kwargs: observed_codes.append(os.environ["HOMEBOT_ACCESS_CODE"])
        with patch.object(run.secrets, "token_urlsafe", return_value="generated-code") as generate:
            output = self.launch(["--lan"])
        generate.assert_called_once_with(12)
        self.assertEqual(observed_codes, ["generated-code"])
        self.server.assert_called_once_with("server.main:app", host="0.0.0.0", port=8000, workers=1, reload=False, proxy_headers=False)
        self.assertIn("http://192.168.1.20:8000", output)
        self.assertIn("用户名：homebot", output)
        self.assertIn("访问码：generated-code", output)
        self.assertIn("HTTP 不加密", output)

    def test_existing_code_is_reused_for_lan(self):
        os.environ["HOMEBOT_ACCESS_CODE"] = "user-configured-code"
        with patch.object(run.secrets, "token_urlsafe") as generate:
            output = self.launch(["--lan", "--port", "9000"])
        generate.assert_not_called()
        self.assertEqual(os.environ["HOMEBOT_ACCESS_CODE"], "user-configured-code")
        self.assertIn("访问码：user-configured-code", output)
        self.assertIn("http://localhost:9000", output)
        self.assertIn("http://192.168.1.20:9000", output)
        self.assertEqual(self.server.call_args.kwargs["port"], 9000)

    def test_configured_local_code_is_also_explained(self):
        os.environ["HOMEBOT_ACCESS_CODE"] = "local-code"
        output = self.launch([])
        self.assertIn("用户名：homebot", output)
        self.assertIn("访问码：local-code", output)
        self.assertEqual(self.server.call_args.kwargs["host"], "127.0.0.1")

    def test_missing_environment_variable_generates_lan_code(self):
        os.environ.pop("HOMEBOT_ACCESS_CODE")
        with patch.object(run.secrets, "token_urlsafe", return_value="new-code"):
            self.launch(["--lan"])
        self.assertEqual(os.environ["HOMEBOT_ACCESS_CODE"], "new-code")

    def test_no_detected_address_has_manual_wifi_hint(self):
        self.addresses.return_value = []
        output = self.launch(["--lan", "--port", "9000"])
        self.assertIn("Wi-Fi", output)
        self.assertIn("IPv4", output)
        self.assertIn("http://<电脑 Wi-Fi IPv4>:9000", output)
        self.assertIn("未自动识别", output)

    def test_invalid_port_or_unknown_flags_do_not_start_server(self):
        for args in (["--port", "0"], ["--port", "65536"], ["--port", "-1"], ["--port", "no"], ["--reload"], ["--workers", "2"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                run.main(args)
            self.assertEqual(error.exception.code, 2)
        self.server.assert_not_called()

    def test_real_mode_requires_an_explicit_flag_even_with_old_environment(self):
        for mode in ("tb6612", "drv8833", "drv8833-dual"):
            with self.subTest(mode=mode):
                os.environ["HOMEBOT_MOTOR"] = mode
                output = self.launch([])
                self.assertEqual(os.environ["HOMEBOT_MOTOR"], "mock")
                self.assertIn("虚拟电机", output)

    def test_explicit_real_modes_select_single_motor_without_reload(self):
        for mode in ("tb6612", "drv8833"):
            with self.subTest(mode=mode):
                output = self.launch(["--motor", mode, "--lan"])
                self.assertEqual(os.environ["HOMEBOT_MOTOR"], mode)
                self.assertIn(f"{mode.upper()} 单电机", output)
                self.assertIn("40%", output)
                self.assertFalse(self.server.call_args.kwargs["reload"])
                self.assertEqual(self.server.call_args.kwargs["workers"], 1)

    def test_help_does_not_construct_controllers_or_start_server(self):
        with patch("server.tb6612.TB6612MotorController") as tb6612, patch("server.drv8833.DRV8833MotorController") as drv8833:
            for mode in ("tb6612", "drv8833"):
                with self.subTest(mode=mode), redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
                    run.main(["--motor", mode, "--help"])
                self.assertEqual(error.exception.code, 0)
                self.assertIn("drv8833", output.getvalue())
            tb6612.assert_not_called()
            drv8833.assert_not_called()
        self.server.assert_not_called()

    def test_unknown_motor_is_rejected_without_opening_server(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run.main(["--motor", "unknown"])
        self.server.assert_not_called()

    def test_dual_mode_passes_each_calibration_flag_before_server_start(self):
        for flags, left, right in (([], "0", "0"), (["--invert-left"], "1", "0"), (["--invert-right"], "0", "1"), (["--invert-left", "--invert-right"], "1", "1")):
            with self.subTest(flags=flags):
                observed = []
                self.server.side_effect = lambda *a, **k: observed.append((os.environ["HOMEBOT_MOTOR"], os.environ["HOMEBOT_INVERT_LEFT"], os.environ["HOMEBOT_INVERT_RIGHT"]))
                output = self.launch(["--motor", "drv8833-dual", "--lan", *flags])
                self.assertEqual(observed, [("drv8833-dual", left, right)])
                self.assertIn("v0.7", output)
                self.assertIn("30%", output)
                self.assertIn("GPIO23", output)
                self.assertEqual(self.server.call_args.kwargs["workers"], 1)
                self.assertFalse(self.server.call_args.kwargs["reload"])

    def test_calibration_flags_cannot_silently_apply_to_another_mode(self):
        for mode in ("mock", "tb6612", "drv8833"):
            for flag in ("--invert-left", "--invert-right"):
                with self.subTest(mode=mode, flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    run.main(["--motor", mode, flag])
        self.server.assert_not_called()

    def test_old_calibration_environment_is_not_reused_by_launcher(self):
        os.environ.update(HOMEBOT_INVERT_LEFT="1", HOMEBOT_INVERT_RIGHT="1")
        self.launch(["--motor", "drv8833-dual"])
        self.assertEqual(os.environ["HOMEBOT_INVERT_LEFT"], "0")
        self.assertEqual(os.environ["HOMEBOT_INVERT_RIGHT"], "0")

    def test_port_boundaries_are_valid(self):
        self.assertEqual(run.port_number("1"), 1)
        self.assertEqual(run.port_number("65535"), 65535)

    def test_camera_flag_is_passed_before_server_import(self):
        observed = []
        self.server.side_effect = lambda *args, **kwargs: observed.append(os.environ["HOMEBOT_CAMERA"])
        output = self.launch(["--camera", "picamera2", "--lan"])
        self.assertEqual(observed, ["picamera2"])
        self.assertIn("摄像头后端：picamera2", output)
        self.assertEqual(os.environ["HOMEBOT_MOTOR"], "mock")

    def test_camera_environment_and_flag_override(self):
        os.environ["HOMEBOT_CAMERA"] = "picamera2"
        self.launch([])
        self.assertEqual(os.environ["HOMEBOT_CAMERA"], "picamera2")
        self.launch(["--camera", "opencv"])
        self.assertEqual(os.environ["HOMEBOT_CAMERA"], "opencv")

    def test_invalid_camera_flag_or_environment_prevents_launch(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.launch(["--camera", "typo"])
        os.environ["HOMEBOT_CAMERA"] = "typo"
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.launch([])
        self.server.assert_not_called()


class AddressTests(unittest.TestCase):
    def test_addresses_are_deduplicated_and_loopback_is_excluded(self):
        values = ("127.0.0.1", "192.168.1.20", "192.168.1.20", "10.0.0.2", "0.0.0.0", "224.0.0.1", "invalid")
        entries = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 0)) for value in values]
        with patch.object(run.socket, "gethostname", return_value="my-computer"), patch.object(run.socket, "getaddrinfo", return_value=entries) as resolve:
            self.assertEqual(run.lan_addresses(), ["10.0.0.2", "192.168.1.20"])
        resolve.assert_called_once_with("my-computer", None, socket.AF_INET, socket.SOCK_STREAM)

    def test_lookup_failure_is_safe_to_ignore(self):
        with patch.object(run.socket, "getaddrinfo", side_effect=OSError("no address")):
            self.assertEqual(run.lan_addresses(), [])


if __name__ == "__main__":
    unittest.main()
