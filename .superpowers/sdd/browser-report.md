# Isolated workflow browser QA

Date: 2026-11-05. No production code modifications, engine runs, real project/configuration writes, dependency installation, or existing browser session interaction.

## Reproduction

Run `python tests/workflow_browser_check.py` from the repository. It uses the installed Python Playwright package and installed Chrome (Edge fallback), launches its own headless browser context, serves the real `platform/frontend` assets on a temporary loopback port, and answers every `/api/` endpoint with in-memory fixtures. Unknown fixture endpoints fail the check. `WORKFLOW_BROWSER` can specify another installed Chromium executable. The harness is deliberately outside `test_*.py` discovery so normal backend tests do not acquire browser requirements.

The final run passed after the frontend manifest switched to its actual six-module composition. No module-loading shortcut, concatenated script injection, or DOM replacement is used. Runtime busy/idle changes travel through the normal fake `runtime_state` endpoint and production refresh function; selection, preview, apply, retry, editing, and function changes use real browser controls.

## Observed passing scenarios

- Real page bootstrap: six stage navigation buttons and no `pageerror` events.
- Empty compiler/toolchain settings disable compile while a matching existing executable remains usable. Clicking reuse succeeds and sends `build_status`, with no `toolkit` invocation.
- Real task and city selections synchronize the input controls; existing XML mode produces the path-difference preview and enables confirmation.
- A busy runtime response disables confirmation. Returning to idle preserves and re-enables the current valid preview.
- The first fake apply returns an ordinary recoverable error. Confirmation remains enabled; a manual second click succeeds, with exactly two render requests and the parameter editor loaded.
- A successful fake preflight enables run. Saving an XML parameter through the real input/change handlers invalidates that check, disables run, and preserves the assembled context.
- Switching from pred to commsensing marks the prior assembly stale and leaves run disabled.
- Full-page screenshots at 1440 × 1000 and 390 × 1000 viewports; document scroll width does not exceed viewport width in either case. Final screenshots are 1440 × 3529 and 390 × 4819.
- Visual inspection of the desktop overview and mobile top, assembly and parameter sections: readable single-column mobile cards, wrapped long paths/status messages, usable parameter controls, and no clipped document content.

Screenshots: `docs/superpowers/screenshots/workflow-desktop.png` and `docs/superpowers/screenshots/workflow-mobile.png`. They intentionally show the final stale assembly/check state after returning to edit inputs. The empty global toolchain form is expanded by production bootstrap to expose the missing compiler settings used by this scenario.

## Limits

This verifies frontend behavior against deterministic fixtures, not backend filesystem semantics, source XML preservation, compiler discovery, real engine execution, or result validity. It exercises one outdoor task and pred/commsensing, not every function/mode combination. Network interruption, stale tokens, schema_ok=false, duplicate clicks, CSV editing, and restored running sessions are outside this browser harness and remain the responsibility of focused state/backend regression tests. No product bug was observed in the covered browser scenarios.

## Final expanded run
Root reran the real-control fixture after integration/review fixes. Eleven scenarios pass, including XML save failure with retained value, filter preservation, explicit retry and discard, plus CSV dirty change-blocking and explicit saved-content reload. Parameter edits use real Tab/blur rather than synthesizing a duplicate change event. No pageerrors;1440px and390px screenshots regenerated, zero horizontal overflow. Toolkit snapshot addition subsequently validated by backend and frontend tests; no real toolkit or engine launch in browser.
