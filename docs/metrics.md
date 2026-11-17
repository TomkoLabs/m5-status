# Metrics and collectors

## CPU and processes

Overall CPU uses a 250ms non-idle delta of Mach HOST_CPU_LOAD_INFO ticks,
normalized across all CPUs. Load averages on the CPU row and in details are native
`os.getloadavg()` 1/5/15-minute values, not percentages. The CPU suffix uses
`load: 3.39 3.29 3.27` formatting. If the read raises `OSError`, the suffix is
omitted, details says unavailable, and the CPU reading remains usable.
The compact process table combines the top three CPU
and top three RSS consumers; details uses five of each, deduplicating PIDs.
Idle, memory-heavy inference processes stay visible. Names are basenames of
`ps comm`; full command lines are never requested. Native process CPU accounting
has a different time window and can exceed 100% with multiple cores. RSS excludes
swapped/compressed pages and can include shared pages; it is not exact unique
ownership or complete unified GPU memory.

## Unified memory

Physical RAM comes from `hw.memsize`; page size comes from `vm_stat`. RAM is
resident anonymous pages + wired pages + pages physically occupied by the
compressor. It is a non-file residency estimate, rather than Activity Monitor
Memory Used or App Memory. Other kernel/driver accounting can be omitted.
Native `top` can include file-backed residency in its broader used-memory figure.
Neither total minus free nor process RSS is labeled application/model allocation.

The dashboard uses the plain `RAM` label for every state. The former tilde was
an intentional estimate marker introduced with the compact renderer, not a
fallback marker or a calculation defect. The calculation is unchanged:

```text
used bytes = vm_stat page size * (Anonymous pages + Pages wired down
                                 + Pages occupied by compressor)
percentage = 100 * used bytes / sysctl hw.memsize
```

The sum excludes file-backed pages (shown separately), free pages, and swapped-out
data. It does not add inactive or purgeable categories, which can overlap other
counts, nor the logical `Pages stored in compressor` value: the compressor's
physical footprint is already included. It is not exact total system allocation,
Activity Monitor Memory Used/App Memory, or dedicated GPU/model memory.

There is no RAM fallback collector. Failed or malformed `vm_stat` output renders
`RAM N/A collector failed`, records the existing core error, and retries at the
next refresh. A failed reading is never substituted with zero, process RSS or
total-minus-free. Details explicitly calls the successful reading `RAM estimate`.

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
has no percentage denominator: a successful zero-used/zero-total sample uses an
empty 0.0% meter with the shared cyan resource-row styling as an idle display
convention. Allocated swap uses the actual
used/total percentage. Missing, nonfinite, negative or impossible readings remain
unavailable and are retried next frame. Swap percentage alone does not classify pressure.

## Storage

The internal Data filesystem and mounted local volumes under `/Volumes` are
selected at startup, except the dedicated external mount below; `--disk PATH`
adds a local filesystem. Restart after other mount changes. Network filesystems are not monitored. Static native disk identity is
cached: SolidState=true is SSD, false is Disk, unknown is Storage. Interface type
is not inferred from APFS or a marketing name.

APFS volumes, including boot snapshots, are grouped by the container identity in
`diskutil apfs list -plist`. Total is the capacity ceiling, free is unallocated
container space, and used is their difference, including other volumes/snapshots/
metadata. A shared container appears once. Purgeable space is not added to free;
quotas or reservations can constrain an individual volume further. Other local
filesystems use `df -Pk`. Paths and shared-capacity explanations appear in details.

The dedicated **SSDe** row follows the primary SSD row and uses a separate
`df -Pk /Volumes/External-Drive` lookup every frame, bounded by the existing
three-second command timeout. Accept exactly one local device row whose returned
mount point is exactly `/Volumes/External-Drive`, with positive capacity and
nonnegative used/free counts no greater than capacity. Checking directory
existence alone is insufficient: after unmount, a leftover directory can report
the startup filesystem. A mismatched mount, failed command or invalid result
renders `SSDe N/A unavailable` without failing the internal disk row or `--once`.
Failures are not sticky; the next refresh retries, and reconnects may change the
device ID. This path and its subdirectories are excluded from the startup-selected
disk group, including `--disk` arguments under that path.

SSDe uses the volume's total, Used and Available fields directly (1024-byte
blocks), with percent = Used / total. It reuses SSD's binary GiB formatting and
cyan bar. Unlike general APFS container accounting above, SSDe does not compute
used = total - available. APFS metadata, shared capacity and reservations can
leave Used + Available below total; near-empty volumes can round to 0.00 GiB used
and 0.0%. Details labels this as `df volume accounting`. No file-tree scan, cached
device identity, mount/unmount action or drive write is performed.

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

The default GPU row shows utilization, then `temp: N C`, then
`power: A.AA W avg / N.NN W now`, separated by ` | ` when both sensor readings
are valid. Temperature comes from the same macmon sample's `temp.gpu_temp_avg`,
rounded to a whole degree (Python nearest, ties to even). Watts come directly from
`gpu_power`; `all_power` and `sys_power` are never substituted or added.

`now` is the latest sample. `avg` is the arithmetic mean of valid wattages in the
last six dashboard refreshes, including the current refresh; startup uses the
samples available so far. Every refresh advances the bounded in-memory window,
even if its power reading is missing/invalid. Invalid samples are excluded from
the mean, never replaced with zero. No history persists across runs; `--once`
therefore has equal average/current values. This is an average of periodic 250ms
samples, not continuous energy measurement or a time-weighted average.

Existing sensor validity bounds remain: finite numeric temperature 1–150 C and
power 0.000001–1000 W, excluding booleans. Zero/null values can represent
unsupported private counters and are withheld. Temperature and power render
independently; invalid current power hides both average/current power text rather
than showing stale readings. Invalid temperature does not suppress valid power.
No additional sampler invocation is made. Source/clock and sensor diagnostics
remain in details. With `--gpu`, native utilization may take precedence, but the
compact temperature and power window still use macmon only; native power remains
a separately sourced details reading. Only GPU power is consumed from macmon. macOS 27 can leave named CPU/ANE energy counters
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
the next begins after collection. Optional GPU/pressure failures are disabled for the run to
avoid repeated failed calls; restart to retry. Core failures remain visible and
make `--once` exit 1. Argument errors exit 2; INT exits 130, TERM 143, HUP 129.

Output wraps intentionally to the terminal width, never relying on terminal
wrapping. Long process names are shortened. ASCII is used throughout. Color and
screen clearing are only for looping output to a usable TTY. NO_COLOR disables
color; `--once`, redirection and TERM=dumb disable all terminal escapes.

## Models

See the [model information contract](../README.md#model-information) for sources,
authentication, filesystem scope and completeness limitations. Loaded and downloaded
lookups are independent, read-only and freshly collected each frame, each with a
two-second subprocess deadline. A 0.75-second HTTP socket timeout is also enforced.
They never use process memory as evidence of a loaded model, and never equate catalog
entries or supported context profiles with loaded physical checkpoints. Unlike
sticky optional GPU failures, model lookup failures retry on every refresh.
Model lookup failures appear in their own sections without failing otherwise valid
core metrics or `--once`. Swap collector failures do fail `--once`.
