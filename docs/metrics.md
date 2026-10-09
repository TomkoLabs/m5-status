# Metrics and collectors

## CPU and processes

Overall CPU uses a 250ms non-idle delta of Mach HOST_CPU_LOAD_INFO ticks,
normalized across all CPUs. Load averages in details are native 1/5/15-minute
values, not percentages. The compact process table combines the top three CPU
and top three RSS consumers; details uses five of each, deduplicating PIDs.
Idle, memory-heavy inference processes stay visible. Names are basenames of
`ps comm`; full command lines are never requested. Native process CPU accounting
has a different time window and can exceed 100% with multiple cores. RSS excludes
swapped/compressed pages and can include shared pages; it is not exact unique
ownership or complete unified GPU memory.

## Unified memory

Physical RAM comes from `hw.memsize`; page size comes from `vm_stat`. RAM~ is
resident anonymous pages + wired pages + pages physically occupied by the
compressor. It is a non-file residency estimate, rather than Activity Monitor
Memory Used or App Memory. Other kernel/driver accounting can be omitted.
Native `top` can include file-backed residency in its broader used-memory figure.
Neither total minus free nor process RSS is labeled application/model allocation.

File-backed includes cached and mapped files, not all immediately reclaimable.
Purgeable overlaps other categories and is not added to free/cache/inactive pages
as exact available memory. Details separates physical compressor footprint from
original logical pages stored compressed; neither is counted twice.

Pressure uses the private sysctl `kern.memorystatus_vm_pressure_level`: userspace
constants 1 normal, 2 warning, 4 critical; others remain unknown. It is not inferred
from free memory. See Apple's [pressure implementation](https://github.com/apple-oss-distributions/xnu/blob/xnu-10063.101.15/bsd/kern/kern_memorystatus_notify.c)
and [VM statistics definitions](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/vm_statistics.h).
Swap uses `vm.swapusage` and its binary units. The denominator is currently
allocated capacity, which can grow; it is not a fixed maximum. Zero allocation
has no percentage denominator. Swap percentage alone does not classify pressure.

## Storage

The internal Data filesystem and mounted local volumes under `/Volumes` are
selected at startup; `--disk PATH` adds a local filesystem. Restart after mount
changes. Network filesystems are not monitored. Static native disk identity is
cached: SolidState=true is SSD, false is Disk, unknown is Storage. Interface type
is not inferred from APFS or a marketing name.

APFS volumes, including boot snapshots, are grouped by the container identity in
`diskutil apfs list -plist`. Total is the capacity ceiling, free is unallocated
container space, and used is their difference, including other volumes/snapshots/
metadata. A shared container appears once. Purgeable space is not added to free;
quotas or reservations can constrain an individual volume further. Other local
filesystems use `df -Pk`. Paths and shared-capacity explanations appear in details.

## GPU

Automatic macmon sampling uses `macmon pipe -s 1 -i 250 --soc-info` as a finite,
root-free subprocess. AGX metadata must expose one aggregate GPUPH residency
channel; unsupported/multiple channels fall back. The tested Ultra exposes one,
and idle/brief GPU activity validation demonstrated changing counters. We use
macmon's aggregate `gpu_active_ratio`, not a sum of per-device percentages.

Active residency measures the part of the interval in active frequency states.
Frequency-scaled activity weights those states by frequency relative to the
highest advertised DVFS frequency; neither is a direct measure of throughput.
The clock is averaged over active residency, so it is not an instantaneous clock
sensor. The maximum is the highest advertised supported DVFS state. See the
[pinned sampler implementation](https://github.com/vladkens/macmon/blob/v0.8.2/src_lib/metrics.rs)
and [upstream metric notes](https://github.com/vladkens/macmon#metrics).

Require explicit finite ratios and a fresh timezone-aware timestamp. Missing,
malformed, out-of-range or stale primary fields disable that sampler for the run
and fall back to native AGX Device Utilization %. This fallback is labeled
`driver snapshot`; its window is undocumented and it may be stale. Multiple
unaggregated devices are unavailable rather than summed. Neither unavailable
source nor missing optional fields become zero. Zero active residency from a
supported fresh source is valid idle activity.

Details can show positive valid GPU temperature and estimated power; zero/null
sensor values can represent unavailable private counters and are withheld. Only
GPU power is consumed from macmon. macOS 27 can leave named CPU/ANE energy counters
visible but frozen; no such fields are treated as measurements here. Private APIs
can change with macOS/chip versions, so future compatibility is unverified.

Explicit `--gpu` additionally attempts native `powermetrics gpu_power`, 250ms,
one sample. A valid native active-residency sample takes precedence; permission
failure preserves automatic macmon/driver monitoring and is explained in details.
The command never launches sudo. Elevated execution remains untested; the
unprivileged failure and synthetic parsing are tested. No calibrated power
accuracy or dedicated VRAM total is claimed.

## Timing, output and failures

Static hardware/disk identity is cached. Each external collector has a three-second
timeout. Samplers are finite processes, and their groups are killed/reaped on
Ctrl+C, TERM, HUP or timeout. No polling daemon or background service is installed.
Refresh timing includes collection: if a frame exceeds the requested interval,
the next begins after collection. Optional failures are disabled for the run to
avoid repeated failed calls; restart to retry. Core failures remain visible and
make `--once` exit 1. Argument errors exit 2; INT exits 130, TERM 143, HUP 129.

Output wraps intentionally to the terminal width, never relying on terminal
wrapping. Long process names are shortened. ASCII is used throughout. Color and
screen clearing are only for looping output to a usable TTY. NO_COLOR disables
color; `--once`, redirection and TERM=dumb disable all terminal escapes.
