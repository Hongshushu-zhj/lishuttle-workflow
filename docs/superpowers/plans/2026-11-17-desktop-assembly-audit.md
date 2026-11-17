# Desktop assembly and workflow reliability implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the confirmed desktop assembly startup hang and verified defects in the configuration-to-results workflow; deliver an independently verified offline patch release.

**Architecture:** Preserve the existing authenticated desktop service, resource leases, recoverable assembly transactions and receipt verification. Isolate every noninteractive child from lifecycle input, bound renderer failures, and exercise actual desktop control pipes and API routes with disposable projects.

**Tech Stack:** Electron, Vue, Python standard library, Windows MSVC/CMake/Ninja, unittest and Node test runner.

## Global constraints

- Work only in `D:/workspace/LAB/lushuttle-workflow-destop`, branch `codex/desktop-app`; preserve the Web checkout and user engine/data.
- Reproduce each confirmed bug before its production fix. Keep legacy receipt verification, rollback, authentication and task ownership intact.
- Tests use isolated user data, Chinese/spaced paths and a disposable executable; no real LiShuttle calculation.
- Do not terminate the user's pending assembly until safely handling its recovery is understood.

## Tasks

- [x] Extend `tests/test_assembly_transactions.py` with regression tests for independent renderer input, bounded waiting and timeout diagnostics; run `python -B -m unittest discover -s tests -p test_assembly_transactions.py -v` and confirm the intended failures.
- [x] Repair `core.run_render` with a managed renderer supplying `stdin=subprocess.DEVNULL`, bounded process-tree cleanup, shutdown cancellation, a finite subprocess timeout, and failed-generation output for timeouts so `Api.render` rolls back its transaction. Re-run the receipt and assembly transaction tests.
- [x] Audit process lifecycle/stop and frontend state independently. Implement only confirmed workflow defects, each with a failing regression and passing correction.
- [x] Expand `tests/desktop_packaged_toolkit.py` to use the real supervisor, service, API, assembly, parameters, preflight, execution, logs/history/results, with the control pipe continuously open. Confirm legacy assembly fails and the correction succeeds.
- [x] Run complete Python, Web/desktop and Vue checks and type checking; verify the production UI during packaging. Review changes, update version/release/acceptance records, commit the verified patch.
- [ ] Build an offline installer in its own version directory. Run package verification, desktop smoke, the full API workflow against final packaged resources, and verify checksums and clean source revision before delivery.
