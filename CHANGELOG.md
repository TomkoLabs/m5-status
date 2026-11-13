# Changelog

## 0.2.2 — 2026-11-12

- Show temperature and current/average GPU watts on the default row in GX10
  order, using the existing macmon sample; retain source/clock in details.
- Average valid GPU power samples from the last six refreshes, including missing
  refresh slots; independently omit invalid temperature or current power.
- Document field sources, validity bounds, startup behavior and averaging limits.

## 0.2.1 — 2026-11-12

- Use the shared cyan resource-row color for swap, preserving zero/allocated
  meters and unavailable/plain-output behavior.
- Add native 1/5/15-minute load averages to the CPU row; omit the suffix on a
  failed load read without interrupting CPU monitoring.
- Shorten the present/nonempty indexed-model annotation to `(unverified)`;
  retain inventory checks and document integrity/loadability limits.

## 0.2.0 — 2026-11-12

- Render valid zero allocated swap with an aligned, empty green 0.0% meter;
  preserve actual allocated usage and reject invalid readings. Retry failures.
- Add GX10-style loaded/downloaded model sections and process heading while
  retaining Mac GPU, pressure, file-backed memory and top CPU/RSS readings.
- Query oMLX status and configured local inventory passively each refresh with
  independent hard timeouts, private authentication and explicit uncertainty.
- Cover swap states, model states/filesystem changes, HTTP failures/redirects,
  timeouts and terminal formatting in Linux/macOS regression tests.

- Clarify source-directory setup and obtaining Python on a fresh Mac.
- Add Linux synthetic-test and syntax-check CI for Python 3.9 and 3.15.

## 0.1.0 — 2026-10-09

First tagged release.

- Compact resource meters and process table; expanded `--details` diagnostics.
- Optional automatic root-free macmon GPU residency and clock sampling, with
  validated fields and a clearly labeled native driver fallback.
- Width-aware ASCII layout and restrained terminal colors respecting NO_COLOR.
- `--version`, MIT license, generic atomic installer with preservation and
  repeatable installation, and concise user/metric documentation.
- Retained native CPU, non-file RAM estimate, kernel pressure, swap, shared
  APFS capacity, default 10-second refresh, and bounded collector cleanup.
