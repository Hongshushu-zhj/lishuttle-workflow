# Desktop runtime and readability improvements

Approved by user on 2026-11-17; execute in `D:\workspace\LAB\lushuttle-workflow-destop`, branch `codex/desktop-app`. Base: `125c5f3`.

## Global constraints

- Windows 10/11 x64, offline installation, bundled Python 3.13.17; no system Python dependency for the desktop app.
- DLL selection is a root directory such as `ThirdPart/Dll`; the selected CMake build type resolves `Debug` or `Release` inside that root. RelWithDebInfo and MinSizeRel use Release.
- Old paths ending in Debug/Release migrate to their parent root without losing external custom roots. The resolved DLL_SRC remains available for legacy scripts. Missing matching directories never silently select the other build type.
- Existing task XML, models, antennas, business data, and unknown Bin files are preserved. DLL replacement is a separate explicit action with backup and rollback, under existing runtime resource locks.
- Task logs are actual stdout/stderr. Stream partial flushed output, preserve complete verification evidence and old history, reconnect without missing/duplicating events, and do not block process capture on slow clients.
- Existing desktop cookie/Host/Origin authentication, process tree cancellation and exit ownership remain enforced.
- User requests larger, heavier readable typography. Use at least 14px for normal text/controls and 13px for logs/secondary information; avoid shrinking small-screen text to fit. Prefer reflow/scroll and preserve usable actions.
- No edits to original web checkout or external engine/business data. Use temporary fixtures for tasks/tests.

## Task 1 — DLL root resolution and dependency preparation

- [ ] Add DLL_ROOT persisted project setting and backward-compatible derivation of DLL_SRC from root and selected build type.
- [ ] Normalize old relative/absolute paths, slash/case and restore project-local root on project switches. Unknown nonconventional legacy source remains explicitly usable rather than blindly appending a mode.
- [ ] Apply one backend resolver to preset preview/application/build; preserve manual root drafts and revision checks. Frontend selects root and shows resolved effective source/build mode.
- [ ] Add read-only same/missing/different DLL comparison and a distinct sync action, using existing FileTransaction backup/rollback. Only DLL files are updated; no deletions or XML/config/model/antenna overwrites. Keep existing fill-missing assembly semantics.
- [ ] Test standard/custom root, Debug/Release and equivalent Release modes, missing subdir, migration, root drafts, project isolation, sync byte equality and rollback/locks.

## Task 2 — Bundled Python validation

- [ ] Replace all four batch where checks with one shared interpreter validator. Honor explicit LISHUTTLE_PYTHON; only fall back to bare python when absent. Execute lightweight imports; report actual interpreter failure without hiding it.
- [ ] Update package allowlists for the new helper, and expose read-only runtime path/version/status in environment diagnostics where feasible.
- [ ] Test absolute interpreter, Chinese/spaces, no Python on PATH, invalid explicit interpreter and normal CLI fallback; exercise four real batch entrypoints with isolated fixtures.

## Task 3 — Live output, durable replay and complete export

- [ ] Binary chunk capture and incremental decoding preserve partial output, CR/CRLF, split multibyte characters and EOF tail. Keep GBK compatibility and explicit UTF-8 encoding support; record encoding, do not guess each chunk.
- [ ] Isolate event journal/replay and parsing in focused modules. Publish ordered persisted sid/sequence events, maintain bounded stream cache, leave complete legacy line archive and finalizer evidence intact.
- [ ] Add same-origin authenticated SSE stream with heartbeat, cursor replay/deduplication, final sequence, bounded writes and stop/shutdown wakeup. Keep old output pagination/history compatibility.
- [ ] Vue subscribes per fixed sid/generation, displays partial lines, handles CR/ANSI safely as text, batches renders and bounds display. Reconnect resumes exact event sequence; legacy history falls back to line pages.
- [ ] Add trusted streaming export to avoid frontend full aggregation and 16 MiB text IPC ceiling; legacy logs remain exportable.
- [ ] Test flushed half-line before exit, Chinese split chunks, progress/ANSI, EOF, reconnect/deduplication, old sid race, slow client, cancel, shutdown with live stream and >16 MiB export.

## Task 4 — Typography, integration and delivery

- [ ] Introduce coherent font/line-height/weight tokens, raise body/control/log sizes and contrast throughout breakpoints. Reflow compact screens rather than shrinking text.
- [ ] Review all task diffs, resolve blocking findings, run Python/Node/Vue suites and production build.
- [ ] Verify packaged offline runtime with no system Python and real batch prechecks using temporary fixture projects; test actual browser stream and responsive typography.
- [ ] Bump patch version, update usage/release notes, commit reviewed implementation and build stable installer with package verification, hashes and packaged smoke evidence.

## Progress

Implementation starts after baseline checks; task evidence is recorded in `.superpowers/sdd/2026-11-17/`.
