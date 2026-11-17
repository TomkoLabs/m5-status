import argparse
from pathlib import Path
import re
import runpy
import unittest
from unittest import mock

from test_polish import sample

s = runpy.run_path(str(Path(__file__).resolve().parents[1] / "m5-status"))
MOUNT = s["EXTERNAL_MOUNT"]


def df(mount=MOUNT, device="disk5s1", total=976557744, used=864, free=976354588):
    return ("Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            "/dev/{} {} {} {} 1% {}\n".format(device,total,used,free,mount)).encode()


class ExternalStorage(unittest.TestCase):
    def test_volume_accounting_and_row_placement_color_width(self):
        commands=mock.Mock();commands.run.return_value=df()
        external=s["external_storage"](commands)
        self.assertEqual(external,(MOUNT,976557744*1024,864*1024,976354588*1024,False))
        commands.run.assert_called_once_with(["/bin/df","-Pk",MOUNT])
        data=sample();data["external_disk"]=external
        text=s["render_snapshot"](data,120)
        lines=text.splitlines();i=next(i for i,l in enumerate(lines) if l.startswith("SSD "))
        self.assertEqual(lines[i+1],"SSDe    [------------------------]   0.0%  0.00 / 931.32 GiB (931.12 GiB free)")
        self.assertTrue(lines[i+2].startswith("Swap "))
        self.assertNotIn("SSD2",text)
        for width in (32,60,80,100,120):
            plain=s["render_snapshot"](data,width)
            colored=s["render_snapshot"](data,width,color=True)
            self.assertIn("\x1b[36mSSDe",colored)
            self.assertEqual(re.sub(r"\x1b\[[0-9;]*m","",colored),plain)
            self.assertTrue(all(len(line)<=width for line in plain.splitlines()))

    def test_leftover_directory_wrong_mount_and_unavailable(self):
        commands=mock.Mock()
        for raw in (df("/"),df("/System/Volumes/Data"),df(MOUNT+"-other"),b"bad",df()+df()):
            commands.run.return_value=raw
            self.assertIsNone(s["external_storage"](commands))
        data=sample();data["external_disk"]=None
        self.assertIn("SSD     [",s["render_snapshot"](data,120))
        self.assertIn("SSDe    N/A  unavailable",s["render_snapshot"](data,120))

    def test_retry_after_missing_path_timeout_and_reconnect_new_device(self):
        commands=mock.Mock()
        commands.run.side_effect=[s["CollectorError"]("missing path"),df("/"),
                                  s["CollectorError"]("timeout"),df(device="disk9s1"),df(device="disk12s1")]
        for _ in range(3):self.assertIsNone(s["external_storage"](commands))
        for _ in range(2):self.assertEqual(s["external_storage"](commands)[0],MOUNT)
        self.assertEqual(commands.run.call_count,5)

    def test_invalid_capacity_does_not_become_zero(self):
        commands=mock.Mock()
        for fields in ({"total":0},{"used":-1},{"free":-1},{"used":9999999999},
                       {"free":9999999999},{"used":"nan"}):
            commands.run.return_value=df(**fields)
            self.assertIsNone(s["external_storage"](commands))

    def test_external_paths_not_cached_in_general_disk_group(self):
        monitor_type=s["Monitor"]
        values={"hw.memsize":"1024", "hw.ncpu":"8", "hw.model":"test",
                "machdep.cpu.brand_string":"Apple test", "kern.boottime":"sec = 1",
                "kern.osproductversion":"test"}
        def text(_self,argv):
            if argv[0]=="/usr/sbin/sysctl":return values[argv[-1]]
            return df().decode()
        with mock.patch.dict(monitor_type.__init__.__globals__,CPU=mock.Mock()), \
                mock.patch.object(monitor_type,"text",text), \
                mock.patch.object(monitor_type,"optional",return_value={}):
            monitor=monitor_type(mock.Mock(),argparse.Namespace(disk=[MOUNT,MOUNT+"/Models"]))
        self.assertTrue(monitor.disk_paths)
        self.assertFalse(any(p.startswith(MOUNT) for p in monitor.disk_paths))


if __name__=="__main__":unittest.main()
