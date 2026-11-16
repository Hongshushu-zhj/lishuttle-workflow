# LiShuttle Desktop Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement and review these tasks. Track every task in .superpowers/sdd/progress.md.

**Goal:** Deliver the approved Windows desktop design with an offline application package, complete existing workflow and portable resource discovery.

**Architecture:** Electron owns native UI and a supervised bundled Python service. Vue renders the desktop workspace; existing Python domain operations and workflow state retain business correctness.

**Tech Stack:** Electron / electron-builder, Vue 3 / TypeScript / Vite / Element Plus, Python 3.13 embedded runtime.

## Global Constraints

- Work only in D:\workspace\LAB\lushuttle-workflow-destop, codex/desktop-app; preserve source Web checkout.
- Installation resources are read-only; mutable desktop data uses LISHUTTLE_DATA_DIR under LOCALAPPDATA and remains separate for dev/stable.
- Windows 10/11 x64; offline installed execution without Python/Node in PATH; engine/data chosen from local content, no author path assumptions.
- Existing Web APIs remain compatible; resource locks, snapshots, revisions, sid, result validation, backups and unknown outcomes retain existing semantics.
- No actual engine execution, destructive cleanup or data import on the user's projects during development. Use temporary fixtures; real acceptance is explicitly recorded separately.
- Desktop HTTP binds loopback port zero with session authentication and exact Host/Origin checks. Credentials travel through pipes, never URLs/CLI/logs.
- All source, tests and build tooling must be reproducible from tracked files; no personal data in package.

## Shared interfaces

Python entry reads one JSON bootstrap line from stdin before importing core: {data_dir, static_dir, resource_root, session_secret, cookie_name}. It emits {type:'ready',origin:'http://127.0.0.1:<port>'} as a stdout line; command lines {type:'shutdown'} / {type:'activity',request_id} return acknowledgements. EOF shuts down owned processes. desktop_supervisor.py may wrap the service process while preserving this protocol.

The Python entry composes original server.ROUTES with desktop_features.ROUTES; additions use /api/<name> and the same JSON conventions. API errors include error/code; private routes never appear in ordinary Web server.

Preload exposes window.desktop: pickDirectory({title,defaultPath}) => string|null; pickFile({title,defaultPath,extensions}) => string|null; saveText({suggestedName,text}) => {saved:boolean,path?:string}; openPath(path) => void; info() => {version,channel,dataDir,resourceRoot}; setDirty(boolean) => void. No arbitrary fs/command/electron APIs.

Vue uses existing API request revision fields _project, _revision, _machine_revision. New discovery API: POST discover_start {roots:string[],max_depth?:number,max_entries?:number} => {id}; GET discover_status?id= => {id,status,visited,results:[{kind,path,label,evidence,values?}],skipped,limited}; POST discover_cancel {id}. Preferences GET desktop_preferences / POST desktop_preferences {values}; GET desktop_info. Legacy config import POST legacy_import_preview {source_root} / legacy_import_apply {source_root,token}; settings persist only through this isolated entry. Unknown POST outcome is never auto-retried.

### Task 1: Portable Python runtime paths and supervised desktop service

**Files:** scripts/runtime_paths.py; platform/backend/{core.py,server.py,desktop_entry.py,desktop_supervisor.py}; scripts/project_config.py and local batch loaders; tests/test_desktop_{paths,service,supervisor}.py.

**Interfaces:** resolve resource/data roots and env/projects/jobs/runs/snapshots/maintenance paths with existing defaults outside desktop. Desktop entry consumes shared bootstrap protocol and adds desktop_features.ROUTES if present.

- [ ] Write focused failing temporary-directory tests for path isolation, bundled interpreter propagation, service auth/static containment, random port startup and graceful shutdown/EOF.
- [ ] Run tests and confirm meaningful failures.
- [ ] Implement paths, adapt mutable locations, preserve CLI/Web defaults and config snapshot semantics. Explicit interpreter LISHUTTLE_PYTHON replaces implicit python in batch invocation.
- [ ] Implement isolated desktop HTTP handler and lifecycle protocol without rewriting domain API methods; Content-Length/body limits, cookie/Host/Origin/CSP and safe static resolution.
- [ ] Supervise service with Windows Job ownership and stdin lifetime; shutdown waits Runner/archives; propagate owned activity and no global process-name killing.
- [ ] Run focused tests plus all existing Python tests; review diff.

### Task 2: Vue desktop workspace and full workflow migration

**Files:** desktop-ui/** only (including package.json, tests); no platform/backend or desktop/ edits.

**Interfaces:** consumes shared API and window.desktop; old workflow-state.js may be imported as pure logic through a bridge. Desktop UI production dist is static_dir.

- [ ] Write failing controller tests for revisions/old responses, XML modes, editor dirty state and pinned sid.
- [ ] Implement a professional light workspace, blue sidebar, current project context, six stage navigation, persistent log drawer, settings/history/help and empty/loading/error states.
- [ ] Implement project/machine config/detection, build reuse/doctor/build, discovery/manual path onboarding.
- [ ] Implement three XML modes, task/map/CSV/region/function choice, adaptation preview/token, assembly/source-target report, bindings and advanced maintenance.
- [ ] Implement XML categorized auto-save and defaults/read-only semantics; CSV explicit save/discard/column changes with version/format/source guards; indoor controls.
- [ ] Implement preflight/run/cancel, fixed sid log pagination/export, tiered results/history/current file matching, and native paths.
- [ ] Implement legacy preview/import and settings; update API context safely and display unknown writes for manual reconciliation.
- [ ] Run typecheck/build/controller checks; capture responsive UI evidence in integration.

### Task 3: Electron shell, runtime acquisition and offline packaging

**Files:** desktop/**; package.json/package-lock.json; electron-builder.yml; scripts/{desktop-build,prepare-python,package-verify,desktop-smoke}.cjs; third-party notices.

**Interfaces:** consumes shared Python protocol and exposes exact window.desktop contract. Use package name lishuttle-workflow-desktop, product LiShuttle Workflow (Dev channel separate), version 0.1.0; desktop-ui build output under desktop-ui/dist.

- [ ] Write failing Node tests for paths/security/backend protocol/package verification with temporary files.
- [ ] Implement main/preload/native IPC, sandbox/contextIsolation, trusted frame validation, isolated session cookie, random-origin validation and single instance.
- [ ] Implement close dirty/busy handling, owned graceful shutdown, startup failure recovery/logs and background failure state.
- [ ] Build Python embedded acquisition with pinned version/hash, offline cached reuse and _pth/config validation. Installed scripts use bundled interpreter.
- [ ] Add reproducible build/dev/pack/dist scripts and NSIS current-user installer with dev/stable identifiers and preserved app data.
- [ ] Verify packaged file whitelist excludes personal env/jobs/results and includes required Python resources/templates/config; generate checksums/notices.
- [ ] Run Node unit tests, prepare dependencies, assemble directory package and installer; run fake service/packaged smoke and report exact limitations.

### Task 4: Resource discovery, preferences and configuration migration

**Files:** platform/backend/{discovery,migration,desktop_features}.py; tests/test_desktop_{discovery,migration,features}.py; docs and ignore rules.

**Interfaces:** implements shared desktop API routes, uses Task 1 runtime paths and existing project store; no server.py edits to avoid overlap.

- [ ] Write failing tests for bounded/cancelled scans, link skipping, content detection, candidate ambiguity and old response ids.
- [ ] Implement background bounded scanner without executing candidates; configurable roots/depth/entry budget; per-task snapshots and errors.
- [ ] Implement schema-versioned atomic preferences and desktop info; no settings in resource root.
- [ ] Implement explicit legacy config preview token and import to isolated desktop data with backup, no modifications to source or actual business resources.
- [ ] Expose routes with validation, preserve RuntimeGuard/project revisions on writes and report conflict/unknown outcomes.
- [ ] Run focused tests and full integration suites; update docs with real evidence and unchecked acceptance items.

### Task 5: Integration, review and release validation

**Files:** integration fixes across above boundaries; desktop-ui browser/Electron tests; docs/desktop/{usage,acceptance,release-notes}.md.

- [ ] Run existing baseline tests, focused desktop suites, typecheck and production build.
- [ ] Run real local service against disposable fixtures and Electron runtime; verify cookie authentication, native bridge, no dev server and graceful close.
- [ ] Inspect visible production UI at 1366/1920 widths, empty state and populated fixture workflow; fix overflow and unreadable controls.
- [ ] Generate NSIS installer and hashes, inspect package manifest and license resources, run packaged smoke with system Python/Node excluded.
- [ ] Independent code review for task compliance, security, lifecycle and functional parity; resolve material findings and repeat covering checks.
- [ ] Record each task and limitation in progress ledger; provide usable build artifacts and distinguish simulated, real engine and external-machine acceptance.
