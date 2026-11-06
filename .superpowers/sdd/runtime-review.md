# Runtime / API / frontend integration review

Scope: the runtime requirements in `p0-brief.md`, `.superpowers/sdd/runtime-review.diff`, and the current versions of `core.py`, `run_guard.py`, `managed_process.py`, `server.py`, `scripts/project_config.py`, frontend integration and focused tests. The current versions include fixes made during this review. `preflight.py` and `result_validation.py` behavior are expressly excluded from this round. No implementation files, engine sources or real input data were changed by the reviewer; no engine runs or commits were performed.

## Final verdicts

- **Spec compliance: approved for this reviewed scope.** No remaining Critical or Important finding identified after the two independently reproduced defects below were corrected. The result-validation and preflight reviews remain separate gates.
- **Code quality: approved for this reviewed scope.** Reservation is centralized, nested operations reuse an owner token, stale releases are rejected, and session records deep-copy their context and response objects. Windows process ownership starts before executable code is resumed. Finalization, stop retries and teardown preserve the lease until tree exit has been confirmed.
- **Remaining severity:** 0 Critical, 0 Important. Two Important findings discovered during this review were fixed and independently reprobed.

## Corrected Important findings and evidence

### R1. The task-binding query could migrate configuration while a run held the lease — fixed

The reviewed initial `Api.task_binding` called `ProjectStore.binding` without a read-only option. Its query path still entered `_locked()` and `_read()` with persistence enabled. This bypassed the otherwise correct read-only handling in `core.load_env` and `scan_projects`.

An isolated Python probe retained an active `RuntimeGuard` lease, redirected `core.ENV_FILE` to a temporary legacy env and replaced only task resolution with a fixture. Before the call, the directory contained `local-win.env`; after `Api.task_binding({})`, it additionally contained `local-win.env.profiles.bak`, `project-profiles.json` and `project-profiles.json.lock`. The API returned `binding: null` while `busy` remained true. This violated the requirement that queries stay read-only while runtime inputs are reserved.

The current fix is at `server.py:223–224` and `scripts/project_config.py:248–257`: query callers explicitly use `read_only=True`, the store uses only its in-memory lock and `_read(persist=False)`, and a value supplied to a read-only binding call is rejected. `core.py:59–61` and `:90–91` also use read-only queries unconditionally, avoiding a busy-check/persist race.

**Independent reprobe after the fix:** directory contents remained exactly `['local-win.env']`; response remained `{'binding': None}`; the guard remained busy. Probe exited 0. The parent additionally reports its updated runtime API regression passed; that existing suite was not rerun by this reviewer.

### R2. A missing session after service restart left a permanent frontend launch lock — fixed

The initial console polling branch returned on every `r.error` without clearing `S.pollTimer`. After restarting the service, the old session no longer existed but `/runtime_state` correctly reported idle. `doRun` and `toolkit` still rejected all operations because their local `S.pollTimer` remained set.

An isolated Node VM probe initialized `attachConsole(31, ...)`, returned `{error:'会话不存在'}` from output and `{busy:false,phase:'idle'}` from runtime_state, then called `doRun`. Actual state was `busy:false`, `sid:31`, one active polling timer and zero `/api/run` requests, with the message `平台已有任务，请等待结束或取消`.

The current API emits stable `SESSION_NOT_FOUND` codes from `Runner.output` (`core.py:961`) and `session_results` (`core.py:1073–1075`). `app.js:1296–1306` handles that terminal condition by clearing the old polling timer and sid, removing only a matching result-session association, marking the old outcome unconfirmed and asking for authoritative runtime state. Other errors retain the existing retry behavior. Restoration still attaches to a different active sid through `applyRuntimeState(..., true)`.

**Independent reprobe after the fix:** `busy:false`, `sid:0`, `resultSid:0`, `pollTimer:null`, zero active timers, and an explicit runtime_state request. Probe exited 0. The newly added regression in `tests/test_runtime_ui.cjs:78–87` also checks a subsequent launch using sid 32; the parent reports that test passed, and it was not rerun by this reviewer.

## Reviewed requirements and concrete evidence

| Requirement | Evidence in current implementation |
| --- | --- |
| Reserve before preflight/config persistence | `runtime_operation` wraps project operations from outside (`server.py:41–56`); `run`, `toolkit`, render, cleanup, config, bindings, XML and CSV writers carry it. Build reservation precedes `prepare_build` and `ProjectStore.save` (`server.py:520–533`). `start_lishuttle` also reserves around inspection and baseline capture. |
| Busy is authoritative across clients | Foreign operations receive a `RuntimeBusy` response with public owner metadata; `Handler._json` maps its code to HTTP 409. The lease token is excluded from `RuntimeGuard.snapshot`. No new write route bypass was found after R1. |
| Reads/log/stop remain available | Runtime state, output, stop and sid results bypass project mutation reservations. State/setup and build-status implicit writes attempt a lease and defer their write when busy. Environment, profile paths and task-binding queries now always read without persistence. |
| No release while any managed child lives | `ManagedProcess` creates a Windows job with kill-on-close, creates the root suspended, assigns it to the job, then resumes it (`managed_process.py:15–27`, `:82–86`). `wait` waits for both root exit and job active count zero (`:92–119`). The monitor retains the lease across retrying wait errors and result finalization. |
| Cancellation and exceptions | `Runner.stop` marks cancellation and terminates the entire job; failed termination returns the session to a retryable running state without releasing its lease (`core.py:967–982`). Spawn/reader/finalizer errors have cleanup or conservative outcomes. The added close-error handling only releases after tree exit has already been confirmed (`core.py:932–943`). |
| Shutdown waits for finalization | `done_event` is set after session finalization and lease release. `shutdown` retries stops and waits for every captured active session's event (`core.py:984–996`); it does not return immediately after issuing a kill. The focused lifecycle tests include close-error and shutdown-finalization scenarios. |
| Fixed run identity and result context | `Runner.start` deep-copies context; `output` and `session_results` deep-copy responses. The launch context includes the inspected configuration and project environment. sid results use the saved session and no current-project lookup; directory browsing always has `associated=False, verdict='unconfirmed'`. |
| UI reflects backend status | Periodic runtime state disables protected writes and restores another active sid. Launches have a local pending guard. Run and results badges use the structured verdict; process exit, artifacts and business are shown separately. Unknown/partial/no-update/cancelled outcomes do not receive the success class. R2 handles a lost session without fabricating success. |

## Verification and limits

The reviewer read the existing runtime API, lifecycle, guard, run-session and frontend tests and did not rerun their already reported suites. Two new scenario probes were executed before fixes; both were independently repeated after the relevant code changed and yielded the corrected states above. They used temporary configuration or an in-memory DOM, not real project inputs. The reviewer also inspected the parent's current close-error, shutdown and read-only-query changes and the associated focused regressions.

This conclusion concerns the single running service, as required. It does not establish coordination with independent CLI processes or validate algorithm execution, preflight semantics, artifact correctness, or numerical output accuracy. No claim of a real-data engine acceptance run is made.
