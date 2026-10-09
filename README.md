# m5-status

**Your Mac at a glance, over SSH.** CPU, GPU, unified RAM, storage, swap and a
short process table refresh every 10 seconds. No daemon or Python packages.
MIT licensed.

## Quick start

Run these commands from the extracted source or checkout directory containing
`m5-status` and `install.py`. If Python is missing, see
[requirements and installation](#requirements-and-installation) first.

```sh
python3 --version                 # requires 3.9 or later
python3 install.py
m5-status                         # Ctrl+C exits
m5-status 2                       # refresh every 2 seconds
m5-status --once                   # one plain snapshot
m5-status --details                # expanded diagnostics
m5-status --version
```

For enhanced root-free GPU readings, optionally install
[macmon](https://github.com/vladkens/macmon) using an existing Homebrew setup:
`brew install macmon`. It is detected automatically; normal monitoring needs
no sudo. Core metrics work without it.

## Requirements and installation

macOS, Python 3.9 or later, and native macOS tools are required. Python is not
assumed to be present on every stock Mac. Check availability in Terminal:

```sh
python3 --version
```

If the command is missing or reports a version older than 3.9, download a current
stable **macOS universal2 installer** from the official
[Python downloads page](https://www.python.org/downloads/macos/). Open the `.pkg`
and follow its installer; then open a new Terminal window and repeat the check.
Use a currently supported Python release for a fresh installation; 3.9 is the
minimum compatibility target. See Python's
[macOS installation guide](https://docs.python.org/3/using/mac.html).
No pip packages are required. See [tested scope](#metrics-and-tested-scope).

From a downloaded release or checkout, run `python3 install.py`. This installs
only the executable into `~/.local/bin`, atomically, and verifies its checksum.
A changed prior executable is preserved as `m5-status.backup.UTC-TIMESTAMP` in
that directory. Identical reinstallation does not create another backup.
Use `python3 install.py --bin-dir /your/bin` for another destination.

Ensure the destination is on your login PATH. For zsh, if needed, add this to
`~/.zprofile`, then start a fresh SSH session:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Update the checkout with `git pull --ff-only` (or download a new release), then
repeat installation. Remove with `rm "$HOME/.local/bin/m5-status"`. Review
saved backups before deleting them. No automatic updater or service is created.

## Usage

```text
m5-status [seconds] [--once] [--details] [--gpu] [--disk PATH]
m5-status --help
m5-status --version
```

- `seconds`: positive decimal interval, default 10, maximum 86400.
- `--once`: one snapshot, always free of terminal escapes.
- `--details`: detailed accounting, GPU fields, paths and collector status.
- `--gpu`: explicitly add native powermetrics sampling; this requires root.
  It never invokes sudo itself and preserves normal readings if restricted.
- `--disk PATH`: also monitor the local filesystem containing an existing
  path; repeatable. Shared APFS containers appear once.

```sh
m5-status --once > snapshot.txt
m5-status --details --once
m5-status --disk /path/to/models
ssh -t user@example.invalid 'exec "$HOME/.local/bin/m5-status"'
```

Illustrative compact output, with invented values and a generic host:

```text
M5 Ultra | 30 CPU / 64 GPU cores | Refresh 10s | Uptime 2d 1h 4m
example.local | 2026-01-01 12:00:00 UTC

CPU     [######------------------]  25.0%
GPU     [##----------------------]   8.0%  macmon active | 608 / 1620 MHz
RAM~    [#########---------------]  37.5%  24.00 / 64 GiB
SSD     [############------------]  50.0%  250.00 / 500 GiB (250.00 GiB free)
Swap    [#-----------------------]   3.1%  32.00 MiB / 1.00 GiB

Pressure: normal | File-backed: 20.00 GiB

Processes (top CPU + RSS)
    PID  PROCESS                       CPU%       RSS
    123  inference-server               18.0  12.00 GiB
```

Lines adapt to terminal width, with intentional continuation lines when needed.
Output is ASCII. Colors are limited to interactive looping terminals and respect
`NO_COLOR`. Redirected output, `--once`, and `TERM=dumb` have no escapes.

## Enhanced GPU monitoring

When available, macmon supplies a bounded 250ms **active residency** sample and
average active clock / highest advertised DVFS clock. This is activity time,
not percentage of peak throughput. It uses private macOS APIs and needs no root.
Only a single verified aggregate residency channel is accepted; device percentages
are never summed. Missing, invalid or stale samples fall back to a labeled
**driver snapshot**, whose sampling window is unknown and may be stale. If
neither source works, the GPU row says unavailable and has no meter.

`--details` includes available frequency-scaled activity, temperature and estimated
power. Unsupported zero/null sensor fields are omitted from compact output.
macOS updates can change private counters; an advertised field is not proof
that it works on every chip. CPU/ANE power from macmon is not used.

For optional native GPU sampling in an administrator-controlled terminal:

```sh
sudo "$HOME/.local/bin/m5-status" --gpu --details
```

Elevated powermetrics execution is unverified; its unprivileged permission behavior
is tested. No sudoers changes or privileged background service are needed.
See [metric and collector details](docs/metrics.md).

## Metrics and tested scope

CPU 100% means the whole machine is busy; process CPU 100% means one core.
**RAM~** estimates non-file residency: anonymous pages + wired pages + physical
compressor footprint. It is not Activity Monitor App Memory or exact total
allocation. Unified CPU/GPU memory has one detected physical capacity; process
RSS is not total model/GPU allocation. File-backed and purgeable categories
can overlap and are not an exact available-memory total.

Memory pressure is the kernel status, not a free-memory percentage. Swap is
used / **currently allocated** capacity; that capacity can change. Zero
allocation has no percentage meter. APFS storage shows container used/free
capacity once, including shared volumes and snapshots. Disk type labels come
from native identity metadata; NVMe is not assumed.

Tested on Apple M5 Ultra, macOS 27.0 (arm64), Apple Python 3.9.6 and optional
macmon 0.8.2. Other hardware/macOS versions and stock Macs without Python are
untested. Linux is used for synthetic regression tests only.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile m5-status install.py
```

The [GitHub Actions workflow](.github/workflows/ci.yml) runs these synthetic
regressions and syntax checks on Linux with Python 3.9 and 3.15. It does not
exercise native macOS collectors or GPU hardware.

Tests use synthetic data, including formatting, sampler failures, accounting,
installer preservation and process cleanup. Native verification also covers
SSH login, refresh timing, terminal/plain output, idle/active GPU observations,
native metric comparisons and installed/source hashes. See [CHANGELOG](CHANGELOG.md)
and [MIT license](LICENSE).
