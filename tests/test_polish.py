import datetime
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
s = runpy.run_path(str(ROOT / "m5-status"))
installer = runpy.run_path(str(ROOT / "install.py"))
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def sample():
    gib = 1024 ** 3
    return dict(static=dict(chip="Apple example", cpu="8", gpu="10", os="version", model="model"),
        host="example.local", timestamp="2026-01-01 00:00:00 UTC", uptime=3600, once=False, interval=10,
        cpu=25, load=(1, 2, 3), total=64 * gib,
        vm={"non_file_estimate":24 * gib,"Anonymous pages":18 * gib,"Pages wired down":4 * gib,
            "Pages occupied by compressor":2 * gib,"File-backed pages":20 * gib,"Pages free":20 * gib,
            "Pages purgeable":512 * 1024 ** 2,"Pages stored in compressor":4 * gib,"page_size":16384},
        swap={"used":32 * 1024 ** 2,"total":gib}, pressure="normal",
        disks=[("/generic/data",500*gib,250*gib,250*gib,True)],labels={"/generic/data":"SSD"},
        processes=[(i,"worker-with-a-very-long-process-name",10,1024**2) for i in range(1,6)]+[(99,"inference-server",0,12*gib)],
        gpu={"percent":8,"source":"macmon active","mhz":608,"max_mhz":1620}, gpu_notes=[],collection=.8,errors=[])


class Formatting(unittest.TestCase):
    def test_compact_groups_resources_and_preserves_inference(self):
        text=s["render_snapshot"](sample(),120)
        offsets=[text.index(label) for label in ("CPU     [","GPU     [","RAM~    [","SSD     [","Swap    [")]
        self.assertEqual(offsets,sorted(offsets))
        self.assertIn("37.5%",text)
        self.assertIn("24.00 / 64 GiB",text)
        self.assertIn("3.1%",text)
        self.assertIn("inference-server",text)
        for hidden in ("Collection:","VM page:","GPU temperature:","shared APFS", "/generic/data"):
            self.assertNotIn(hidden,text)

    def test_details_keeps_diagnostics(self):
        text=s["render_snapshot"](sample(),80,True)
        for visible in ("Collection:","VM page:","GPU temperature:","shared APFS", "/generic/data", "Non-file estimate"):
            self.assertIn(visible,text)

    def test_width_ascii_and_color(self):
        data=sample();data["host"]="example-"+"x"*150
        for width in (32,40,60,80,100,120):
            for details in (False,True):
                plain=s["render_snapshot"](data,width,details)
                self.assertTrue(all(len(line)<=width for line in plain.splitlines()),(width,details))
                self.assertNotIn("\x1b",plain)
                self.assertTrue(plain.isascii())
                colored=s["render_snapshot"](data,width,details,True)
                self.assertEqual(re.sub(r"\x1b\[[0-9;]*m","",colored),plain)

    def test_unavailable_has_no_meter_and_zero_swap_has_no_percent(self):
        data=sample();data["gpu"]={"percent":None,"source":"unavailable"};data["swap"]={"used":0,"total":0}
        text=s["render_snapshot"](data,120)
        gpu=next(line for line in text.splitlines() if line.startswith("GPU"))
        swap=next(line for line in text.splitlines() if line.startswith("Swap"))
        self.assertNotIn("[",gpu);self.assertNotIn("%",gpu)
        self.assertNotIn("[",swap);self.assertNotIn("%",swap);self.assertIn("not allocated",swap)

    def test_once_and_version_arguments(self):
        for args in (["--version"],["--help"]):
            output=subprocess.check_output([sys.executable,str(ROOT/"m5-status")]+args,text=True)
            self.assertNotIn("\x1b",output)
            self.assertIn(s["VERSION"] if args==["--version"] else "--details",output)
        data=sample();data["once"]=True
        self.assertIn("| Once |",s["render_snapshot"](data))

    def test_storage_identity_not_protocol_assumption(self):
        for info,label in (({"SolidState":True,"BusProtocol":"unusual"},"SSD"),({"SolidState":False},"Disk"),({},"Storage")):
            self.assertEqual(s["storage_label"](info),label)

    def test_small_swap_retains_useful_precision(self):
        data=sample();data["swap"]["used"]=4.81*1024**2
        text=s["render_snapshot"](data,120)
        self.assertIn("4.81 MiB / 1.00 GiB",text)
        self.assertIn("0.5%",text)


class GPU(unittest.TestCase):
    def document(self,**extra):
        d={"timestamp":NOW.isoformat(),"gpu_active_ratio":.5,"gpu_scaled_ratio":.25,"gpu_freq_mhz":800,
           "soc":{"gpu_freqs":[0,400,800,1600]},"temp":{"gpu_temp_avg":0},"gpu_power":0}
        d.update(extra);return json.dumps(d)

    def test_active_semantics_and_clock(self):
        d=s["parse_macmon"](self.document(),NOW)
        self.assertEqual(d["percent"],50);self.assertEqual(d["scaled"],25)
        self.assertEqual((d["mhz"],d["max_mhz"]),(800,1600))
        self.assertNotIn("temperature",d);self.assertNotIn("power",d)

    def test_supported_idle_zero_and_invalid_primary_fields(self):
        self.assertEqual(s["parse_macmon"](self.document(gpu_active_ratio=0,gpu_freq_mhz=0),NOW)["percent"],0)
        for value in (None,True,-1,1.5,float("nan"),"0.2"):
            with self.subTest(value=value),self.assertRaises(s["CollectorError"]):
                s["parse_macmon"](self.document(gpu_active_ratio=value),NOW)
        d=json.loads(self.document());del d["gpu_active_ratio"]
        with self.assertRaises(s["CollectorError"]):s["parse_macmon"](json.dumps(d),NOW)

    def test_stale_malformed_and_unsupported_clock(self):
        for text in ("garbage",self.document(timestamp="2020-01-01T00:00:00+00:00"),self.document(timestamp="2026-01-01T00:00:00")):
            with self.assertRaises(s["CollectorError"]):s["parse_macmon"](text,NOW)
        d=s["parse_macmon"](self.document(gpu_freq_mhz=99999),NOW)
        self.assertNotIn("mhz",d)

    def test_aggregate_channel_and_fallback_without_summing(self):
        channel=int.from_bytes(b"GPUPH","big")
        device={"IOReportLegend":[{"IOReportSubGroupName":"GPU Performance States","IOReportChannels":[[channel,1]]}],
                "PerformanceStatistics":{"Device Utilization %":15}}
        self.assertTrue(s["has_gpu_channel"]([device]))
        self.assertFalse(s["has_gpu_channel"]([device,device]))
        driver=s["driver_gpu"]([device])
        self.assertEqual(s["choose_gpu"]("invalid",driver)["source"],"driver snapshot")
        self.assertIsNone(s["choose_gpu"](None,None)["percent"])
        with self.assertRaises(s["CollectorError"]):s["driver_gpu"]([device,device])


class Installation(unittest.TestCase):
    def test_preservation_repeatability_atomic_mode_and_failure(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=root/"source";target=root/"bin/command"
            source.write_bytes(b"first source")
            backup,digest=installer["install"](source,target);self.assertIsNone(backup)
            self.assertEqual(target.stat().st_mode&0o777,0o755)
            again,_=installer["install"](source,target);self.assertIsNone(again)
            source.write_bytes(b"second source")
            backup,_=installer["install"](source,target)
            self.assertEqual(backup.read_bytes(),b"first source")
            self.assertEqual(target.read_bytes(),b"second source")
            source.write_bytes(b"third source")
            with mock.patch.dict(installer["install"].__globals__,os=mock.Mock(wraps=os)):
                installer["install"].__globals__["os"].replace.side_effect=OSError("simulated replacement failure")
                with self.assertRaises(OSError):installer["install"](source,target)
            self.assertEqual(target.read_bytes(),b"second source")
            self.assertEqual(list(target.parent.glob(".m5-status.*")),[])

    def test_symlink_preserved_without_modifying_referent(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=root/"source";referent=root/"other";target=root/"command"
            source.write_bytes(b"new");referent.write_bytes(b"old");target.symlink_to(referent)
            backup,_=installer["install"](source,target)
            self.assertTrue(backup.is_symlink());self.assertFalse(target.is_symlink())
            self.assertEqual(referent.read_bytes(),b"old")


if __name__=="__main__":unittest.main()
