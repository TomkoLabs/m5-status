import http.server
import json
from pathlib import Path
import runpy
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_polish import sample

s = runpy.run_path(str(Path(__file__).resolve().parents[1] / "m5-status"))


class Swap(unittest.TestCase):
    def test_valid_zero_allocated_and_invalid_readings(self):
        for raw, expected in (("total = 0.00M used = 0.00M free = 0.00M", "0.0%"),
                              ("total = 2.00G used = 512.00M free = 1.50G", "25.0%")):
            data = sample()
            data["swap"] = s["parse_swap"](raw)
            self.assertIn(expected, next(l for l in s["render_snapshot"](data).splitlines() if l.startswith("Swap")))
        for raw in ("", "total = -1M used = 0M free = 0M", "total = 0M used = 1M free = 0M",
                    "total = 1M used = 0M free = 2M", "total = nanM used = 0M free = 0M"):
            with self.subTest(raw=raw), self.assertRaises(s["CollectorError"]):
                s["parse_swap"](raw)
        for invalid in (None, "failed", {}, {"used": 1, "total": 0}, {"used": float("nan"), "total": 1}):
            data = sample(); data["swap"] = invalid
            row = next(l for l in s["render_snapshot"](data).splitlines() if l.startswith("Swap"))
            self.assertEqual(row, "Swap    N/A  unavailable")


class Models(unittest.TestCase):
    def test_loaded_empty_active_and_malformed(self):
        self.assertEqual(s["loaded_models"]({"status": "ok", "models_loaded": 0, "loaded_models": []}), ["oMLX: none"])
        self.assertEqual(s["loaded_models"]({"status": "ok", "models_loaded": 1, "loaded_models": ["checkpoint"]}), ["oMLX: checkpoint"])
        for doc in ({}, {"status": "ok", "models_loaded": 0, "loaded_models": None},
                    {"status": "ok", "models_loaded": 1, "loaded_models": []},
                    {"status": "ok", "models_loaded": 1, "loaded_models": [None]}):
            with self.assertRaises((ValueError, KeyError)):
                s["loaded_models"](doc)

    def test_inventory_changes_partial_and_missing_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); settings = {"model": {"model_dirs": [tmp, tmp]}}
            self.assertEqual(s["downloaded_models"](settings), ["oMLX: none"])
            model = root / "org" / "test-model"; model.mkdir(parents=True)
            (model / "config.json").write_text("{}")
            index = model / "model.safetensors.index.json"
            index.write_text(json.dumps({"weight_map": {"a": "one.safetensors", "b": "two.safetensors"}}))
            (model / "one.safetensors").write_bytes(b"test")
            self.assertEqual(s["downloaded_models"](settings), ["test-model (incomplete: 1 indexed files missing/empty)"])
            (model / "two.safetensors").write_bytes(b"test")
            self.assertEqual(s["downloaded_models"](settings), ["test-model (unverified)"])
            index.write_text("broken")
            self.assertEqual(s["downloaded_models"](settings), ["test-model (completeness unverified)"])
            model.rename(model.with_name("renamed"))
            self.assertIn("renamed", s["downloaded_models"](settings)[0])
            settings["model"]["model_dirs"].append(str(root / "missing"))
            self.assertIn("unavailable", s["downloaded_models"](settings)[-1])

    def test_index_paths_adapters_and_direct_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "config.json").write_text("{}")
            settings = {"model": {"model_dir": tmp}}
            self.assertEqual(len(s["downloaded_models"](settings)), 1)
            for name in ("../outside", "/outside", 1):
                (root / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": name}}))
                self.assertEqual(s["model_completeness"](root), "completeness unverified")
            (root / "adapter_config.json").write_text("{}")
            self.assertEqual(s["downloaded_models"](settings), ["oMLX: none"])

    def test_probe_failure_is_private_and_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(s["model_probe"]("loaded", tmp), ["oMLX: unavailable"])
            (base / "settings.json").write_text(json.dumps({"server": {"port": 8000}}))
            fn = s["model_probe"]
            with mock.patch.dict(fn.__globals__, query_loaded=mock.Mock(side_effect=[OSError("SECRET"), ["oMLX: none"]])):
                self.assertEqual(fn("loaded", tmp), ["oMLX: unavailable"])
                self.assertEqual(fn("loaded", tmp), ["oMLX: none"])

    def test_wall_timeout_and_independent_sources(self):
        commands = mock.Mock()
        commands.run.side_effect = [s["CollectorError"]("timeout"), b'["checkpoint"]']
        result = s["collect_models"](commands, "/example")
        self.assertEqual(result, {"loaded": ["oMLX: unavailable"], "downloaded": ["checkpoint"]})
        self.assertTrue(all(c.kwargs["timeout"] == 2 for c in commands.run.call_args_list))

    def test_read_only_http_auth_failure_redirect_and_timeout(self):
        state = {"mode": "ok", "paths": [], "auth": []}

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                state["paths"].append(self.path)
                state["auth"].append(self.headers.get("Authorization"))
                if state["mode"] == "slow":
                    time.sleep(1)
                code = {"ok": 200, "invalid": 200, "denied": 401, "redirect": 302, "slow": 200}[state["mode"]]
                self.send_response(code)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
                try:
                    self.wfile.write(b'{}' if state["mode"] == "invalid" else b'{"status":"ok","models_loaded":0,"loaded_models":[]}')
                except BrokenPipeError:
                    pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / "settings.json").write_text(json.dumps({"server": {"port": server.server_port}}))
                (base / "main-api-key").write_text("fixture-key")
                self.assertEqual(s["model_probe"]("loaded", tmp), ["oMLX: none"])
                for mode in ("invalid", "denied", "redirect", "slow"):
                    state["mode"] = mode
                    started = time.monotonic()
                    self.assertEqual(s["model_probe"]("loaded", tmp), ["oMLX: unavailable"])
                    self.assertLess(time.monotonic() - started, 1.5)
                self.assertEqual(state["paths"], ["/api/status"] * 5)
                self.assertEqual(state["auth"], ["Bearer fixture-key"] * 5)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_layout_order_width_controls_and_color(self):
        data = sample()
        data["models"] = {"loaded": ["oMLX: none"], "downloaded": ["x" * 150 + "\x1b[2J"]}
        for width in (32, 80, 100, 120):
            text = s["render_snapshot"](data, width)
            self.assertLess(text.index("LOADED MODEL"), text.index("DOWNLOADED MODELS"))
            self.assertLess(text.index("DOWNLOADED MODELS"), text.index("TOP PROCESSES"))
            self.assertTrue(all(len(l) <= width for l in text.splitlines()))
            self.assertNotIn("\x1b", text)


if __name__ == "__main__":
    unittest.main()
