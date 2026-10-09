"""Synthetic fixtures only: no machine captures or deployment configuration."""

import argparse
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "m5-status"
status = runpy.run_path(str(SOURCE))


class Parsing(unittest.TestCase):
    def test_interval(self):
        for valid in ("10", "0.5", "86400"):
            self.assertGreater(status["interval"](valid), 0)
        for invalid in ("0", "-2", "nan", "inf", "1e3", "86401", ".5", "1.", "garbage"):
            with self.subTest(invalid=invalid), self.assertRaises(argparse.ArgumentTypeError):
                status["interval"](invalid)

    def test_cpu_machine_semantics_and_counter_wrap(self):
        self.assertEqual(status["cpu_delta"]([10, 5, 80, 5], [25, 10, 155, 10]), 25)
        self.assertEqual(status["cpu_delta"]([0xffffffff, 0, 0, 0], [1, 0, 2, 0]), 50)
        with self.assertRaises(status["CollectorError"]):
            status["cpu_delta"]([0] * 4, [0] * 4)

    def test_memory_pages_and_overlapping_categories(self):
        template = '''Mach Virtual Memory Statistics: (page size of {page} bytes)
Pages free: 100.
Anonymous pages: 20.
Pages wired down: 30.
Pages occupied by compressor: 5.
Pages stored in compressor: 15.
File-backed pages: 80.
Pages purgeable: 10.
Pages inactive: 70.
'''
        for page in (4096, 16384):
            vm = status["parse_vm"](template.format(page=page))
            self.assertEqual(vm["non_file_estimate"], 55 * page)
            self.assertEqual(vm["Pages stored in compressor"], 15 * page)
            self.assertEqual(vm["Pages occupied by compressor"], 5 * page)
        with self.assertRaises(status["CollectorError"]):
            status["parse_vm"]("unrecognized output")

    def test_swap_units_and_kernel_pressure_constants(self):
        swap = status["parse_swap"]("total = 2.00G used = 12.50M free = 2035.50M")
        self.assertEqual(swap["used"], 12.5 * 1024 ** 2)
        self.assertEqual(swap["total"], 2 * 1024 ** 3)
        for value, label in ((1, "normal"), (2, "warning"), (4, "critical"), (0, "unknown (0)")):
            self.assertEqual(status["pressure_label"](value), label)

    def test_apfs_shared_capacity_snapshot_and_external(self):
        df = status["parse_df"]('''Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/disk9s1s1 1000 10 100 10% /
/dev/disk9s5 1000 700 100 88% /System/Volumes/Data
/dev/disk8s1 200 70 130 35% /Volumes/Model Store
''')
        apfs = {"Containers": [{"ContainerReference": "disk9", "CapacityCeiling": 1000000,
                                "CapacityFree": 100000, "Volumes": [
                                    {"DeviceIdentifier": "disk9s1"}, {"DeviceIdentifier": "disk9s5"}]}]}
        rows = status["storage_rows"](df, apfs)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1:5], (1000000, 900000, 100000, True))
        self.assertEqual(rows[1][0], "/Volumes/Model Store")
        self.assertEqual(rows[1][1:5], (200 * 1024, 70 * 1024, 130 * 1024, False))

    def test_idle_memory_consumer_and_short_names(self):
        text = "\n".join("{} 50.0 1 /generic/cpu-worker".format(i) for i in range(1, 8))
        text += "\n99 0.0 100000 inference-server"
        rows = status["busiest"](status["parse_processes"](text))
        self.assertIn(99, [r[0] for r in rows])
        self.assertEqual(len({r[0] for r in rows}), len(rows))
        self.assertEqual(status["parse_processes"]("9 2.0 10 /generic/short-name")[0][1], "short-name")

    def test_gpu_snapshot_validation_and_power_fields(self):
        snapshot = status["driver_gpu"]([{"PerformanceStatistics": {
            "Device Utilization %": 12, "Renderer Utilization %": 8, "Tiler Utilization %": 4}}])
        self.assertEqual(snapshot["percent"], 12)
        with self.assertRaises(status["CollectorError"]):
            status["driver_gpu"]([{"PerformanceStatistics": {"Device Utilization %": -1}}])
        self.assertEqual(status["parse_native_gpu"]("GPU active residency: 9.0%\nGPU Power: 2500 mW")["power"], 2.5)
        with self.assertRaises(status["CollectorError"]):
            status["parse_native_gpu"]("unsupported sampler")

    def test_terminal_controls(self):
        self.assertEqual(status["clean"]("name\x1b[2J\n"), "name?[2J?")

    def test_malformed_native_plist_is_a_collector_failure(self):
        for invalid in (b"garbage", b"<?xml version='1.0'?><plist><dict>broken"):
            with self.assertRaises(status["CollectorError"]):
                status["native_plist"](invalid)

    def test_optional_failure_disables_repeated_sampling(self):
        monitor = object.__new__(status["Monitor"])
        monitor.optional_failures = {}
        calls = []
        def restricted():
            calls.append(True)
            raise status["CollectorError"]("powermetrics requires root")
        for _ in range(3):
            self.assertEqual(monitor.optional("GPU", restricted), "N/A (powermetrics requires root)")
        self.assertEqual(len(calls), 1)


class Cleanup(unittest.TestCase):
    def test_timeout_reaps_collector(self):
        commands = status["Commands"]()
        started = time.monotonic()
        with self.assertRaises(status["CollectorError"]):
            commands.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
        self.assertIsNone(commands.child)
        self.assertLess(time.monotonic() - started, 2)

    def test_interrupt_kills_collector_process_group(self):
        # Exercise the same signal/unwind path while a sampling child is running.
        program = '''import os, runpy, signal, sys
s = runpy.run_path(sys.argv[1])
def stop(signum, frame):
    raise SystemExit(128 + signum)
signal.signal(signal.SIGINT, stop)
c = s['Commands']()
try:
    c.run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=30)
finally:
    c.close()
'''
        process = subprocess.Popen([sys.executable, "-c", program, str(SOURCE)], start_new_session=True)
        child = None
        try:
            for _ in range(50):
                result = subprocess.run(["pgrep", "-P", str(process.pid)], capture_output=True, text=True)
                if result.returncode == 0:
                    child = int(result.stdout.strip().splitlines()[0])
                    break
                time.sleep(0.02)
            self.assertIsNotNone(child)
            process.send_signal(signal.SIGINT)
            self.assertEqual(process.wait(timeout=2), 130)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


if __name__ == "__main__":
    unittest.main()
