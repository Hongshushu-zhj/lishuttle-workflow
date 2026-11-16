# LiShuttle Desktop UI

The production Vue workspace consumes the original local JSON API and the narrow `window.desktop` bridge. It does not execute commands, read arbitrary files, embed the old global DOM scripts, or require a development server after building.

## Reproduce

Use Node 24 (the controller tests use native TypeScript stripping):

```
npm ci
npm test
npm run typecheck
npm run build
```

Electron serves `dist` through its authenticated local Python service. `npm run dev` is for UI development only; it needs an explicitly configured backend origin/proxy to operate APIs.

## Boundaries

- `src/app/useProject.ts`: project and machine configuration, actual build presets, reuse, doctor/build.
- `src/app/useInputs.ts`: existing XML, byte-preserving import, task adaptation previews, bindings and assembly.
- `src/app/useEditors.ts`: serialized XML autosaves/defaults and explicit CSV saves with content/format revisions.
- `src/app/useSession.ts`: preflight/run/cancel, fixed sid, bounded log display, complete log export, results/history.
- `src/app/useDesktopFeatures.ts`: bounded discovery, revisioned preferences, explicit legacy import and maintenance previews.
- `src/domain/controllers.ts`: independently tested scope, dirty ledger, preview, workflow and log safety rules.

The interface keeps XML autosave distinct from explicit CSV save. An interrupted POST is never retried automatically; an unknown-outcome banner requires manual reconciliation. Failed or conflicted editor writes preserve drafts. Inputs and selected XML are independent of the fixed running session.

## Validation limits

Temporary fixtures can verify byte edits and the complete control flow without running a real engine. Actual LiShuttle licensing, real C++ execution, real VS compilation, third-party resources, installed-user privileges and external-machine acceptance require separate explicit acceptance. See the task and desktop acceptance reports.
