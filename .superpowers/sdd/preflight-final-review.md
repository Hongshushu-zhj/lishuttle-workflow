# Preflight repair review

Reviewed the repair report, original five findings, `preflight-final-review.diff`, current preflight implementation/tests/help changes, and `p0-brief.md`. Checked the relevant loaders read-only in `D:/workspace/LAB/Lab20261013`. No engine runs, implementation edits, real-data writes, commits, or reruns of the reported 61/14/12 test suites. Only new temporary-fixture probes were executed.

## Verdicts

- **Specification: changes required.** All five original Important findings are closed. The new resource checks largely follow the reviewed loader contracts. Two newly introduced boundary defects remain: a malformed numeric map input escapes the report interface, and floor-mode raster evidence includes bytes outside the grid that the engine actually loads.
- **Code quality: changes required.** The repaired full-layout fixtures and source-specific regressions substantially improve the original suite. Resource checks maintain the read-only boundary and explicitly leave dynamic startup unconfirmed. The two remaining issues need targeted regressions and small fixes; no broad redesign is required.
- **Critical: none. Important: two, detailed below.** No new actionable issue found in the mode applicability/help changes.

## Original findings: closed

| Original Important | Evidence of repair |
| --- | --- |
| Building branch selection | `preflight.py:727-743` selects the single source using `UsingBuildingPolygon`, matching `GeoDataMgr.cpp:540`. Both inactive-source regression cases are present. |
| Engineering required values/layout | `preflight.py:72-188` implements legacy defaults, Bin/cellformat.xml overrides and indoor fixed offsets; required strings/numerics now cover the loader's mandatory fields. Positive fixtures use full outdoor/indoor layouts and include missing-field/configured-reorder regressions. |
| Missing versus empty PolygonFilePath | `preflight.py:749-753` requires element presence for the outdoor prediction chain while preserving explicit-empty fallback; calibration/indoor remain exempt. |
| Exact DT heading false block | `preflight.py:581-589` warns on unfamiliar names and still reads positional measurements; alternate-header regression added. |
| PLANET projection structure | `preflight.py:291-298,717-721` checks the four-line/numeric shape and the fixture uses the engine-shaped projection. Truncated/nonfinite regressions added. |

## Remaining Important findings

### 1. Reject unrepresentable raster quantization without raising out of check_run

**Location:** `platform/backend/preflight.py:225`, exception boundary at `:238`.

`resolution` can be finite and positive while `resolution * 1024` overflows to infinity. `math.floor(inf)` then raises `OverflowError`, which `_index` does not catch. This escapes `check_run` instead of producing its required JSON-safe `{ok, issues, context}` report. The same path runs for ordinary outdoor ground/calibration inputs, before a controlled decision to block execution.

**New isolated repro:** replace the positive fixture's height index line with `tile.dat 0 10 0 10 1e308`. `check_run` raises `OverflowError: cannot convert float infinity to integer` rather than returning an error issue. No engine was run.

**Fix:** validate the scaled/quantized resolution before floor conversion and guard the complete dimension arithmetic against unrepresentable intermediate values. Return `MAP_INDEX_INVALID` for this input. Add a regression requiring a report, `ok=False`, and JSON serialization for finite-but-unrepresentable map geometry.

### 2. Restrict building raster evidence to the declared grid prefix

**Location:** `platform/backend/preflight.py:276-285`; related index calculation `:230-235`.

The index checker establishes the declared grid's minimum bytes, but `_building_height` then scans every byte in the file and first rejects an odd total file size. This differs from the actual loader: `GeoRasterData.cpp:19-23` calculates the grid size, `GeoDataUtility.cpp:303-304` reads exactly `count * sizeof(short)` bytes, and `PlanetHeightData.cpp:28-34` checks that requested prefix was read. Extra trailing bytes are ignored by the engine.

Two new isolated 2x2 raster probes demonstrate both directions:

- Declared 2x2 grid: first four int16 samples are all zero; an extra fifth sample is 6. Preflight returns `ok=True` with `building_sample_height=6`. The engine reads only the four zero samples, so that positive height cannot establish usable floor buildings.
- Declared 2x2 grid: samples `[0,6,0,3]`, followed by one extra byte. Preflight returns `ok=False` / `FLOOR_DATA_REQUIRED` solely because the total file length is odd. The engine reads the valid eight-byte grid prefix and ignores that byte.

**Fix:** carry the source-derived grid byte/sample count in each raster index entry and scan only that prefix for positive building evidence. Do not reject parity of bytes beyond the loaded prefix. Add both regressions. This preserves minimum-length validation and matches the engine without changing files or performing geometric calculation.

## Resource-check assessment and limits

The newly checked scene default, required clutter menu in both PLANET path branches, nonrecursive output-parent behavior, antenna MaxGain/beam shapes, active antenna selection, outdoor model definitions, builtin model-zero references, and indoor's independent physical-model chain were compared with the relevant source ranges. The checked behavior follows `ServiceHelper`, `GeoDataMgr`, `AntennaLoader`, `CellLoader`/`IndoorAPLoader`, `CalcParamFactory`, `PropagationModelFactory` and `LiShuttlePropagationModel` for the ordinary supported cases. No additional Important false block was established in those checks.

Mode arithmetic/applicability, ordinary Bin-relative paths, unchanged XML/scalars, conservative cache warnings, and unknown actual floor totals remain consistent with the brief. DLL/license/log startup, opaque cache hashes, full model/scene semantics, material/geometry validity, and executable/source parity remain explicitly outside the guarantees of this static preflight. The reported passing suites were not independently rerun during this review.

## Final boundary/compatibility follow-up (2026-10-30)

Reviewed the regenerated diff, current repair, the five newly visible regression cases, and the appended implementation report. No suite, engine, or new probe was run in this follow-up; no implementation or real data was edited.

**The two boundary findings above are closed:**

- `preflight.py:226-244` checks the scaled resolution before `math.floor`, validates finite positive extents/ratios, and catches `OverflowError`. The regression at `tests/test_preflight.py:524` covers the original `1e308` case, overflowing extent subtraction and a step quantizing to zero; it requires structured `MAP_INDEX_INVALID`, `ok=False` and JSON-safe serialization.
- `preflight.py:235-240,280-290` carries the exact declared `raster_bytes` and bounds every raster read by that remaining prefix. It no longer rejects whole-file odd parity. Both original tail-sample scenarios have dedicated regressions at `tests/test_preflight.py:537` and `:544`.

**Compatibility handling is appropriate for this phase:** `preflight.py:678-684,708-723` routes `plindoor` and `indoorrays` to the indoor family while leaving their full function contract unconfirmed. Source identifiers are `LiShuttleTypes.h:27,35`; `PathLossCalcParams.cpp:255` confirms the indoor-rays path. Unknown debug/test/custom functions retain common executable/XML/output checks, warn `FUNCTION_UNREVIEWED`, and return before outdoor-specific assumptions. Visible tests preserve the missing-output/executable blocks and unknown layer count.

### One Important resource-path issue discovered in this follow-up

**Location:** `platform/backend/preflight.py:349,356`; associated fixture `tests/test_preflight.py:40` and test `:412`.

For absent or empty `SceneSettingsPath`, preflight uses `Bin/config/scenesettings.xml`. The actual source uses `m_processFolder + DEFAULT_CONFIG_DIR + '/scenesettings.xml'` (`LiShuttle/src/ServiceHelper.cpp:161-166`), and `DEFAULT_CONFIG_DIR` is **`runtimelibrary`**, not `config` (`SwanUtility/incl/LiShuttleTypes.h:42`). `ServiceHelper.cpp:178-191` establishes `m_processFolder` as the executable directory.

**Concrete consequences:** a valid configuration with only `Bin/runtimelibrary/scenesettings.xml` is falsely blocked as `SCENE_SETTINGS_MISSING`; conversely, the positive fixture with only `Bin/config/scenesettings.xml` can pass this check while the engine fails its actual default lookup. Explicit `SceneSettingsPath` references are unaffected.

**Fix:** change the fallback, diagnostic and default-path fixtures to `runtimelibrary/scenesettings.xml`. Add coverage that the real default succeeds while a config-only file cannot satisfy a missing/empty explicit setting. The earlier resource assessment's statement about the scene default is superseded by this finding; resolving the macro value was missed in that review.

**Final verdict for this revision:** specification **changes required** and code quality **changes required**, solely for the scene-default mismatch above. All seven previously recorded Important findings are closed. Remaining **Critical: zero; Important: one**. Reported 66/14/12 suite results were not independently rerun, as requested. Dynamic runtime and semantic validation limits remain unchanged.

## Final approval after scene-default correction (2026-10-30)

The scene-default correction became available during this review and has now been inspected. `preflight.py:349,356` uses and reports `Bin/runtimelibrary/scenesettings.xml`, matching the resolved source macro. The positive fixture at `tests/test_preflight.py:40` and the mutually exclusive default-path regressions at `:417` and `:424` cover the real-default success and config-only rejection; the explicit-relative-path regression remains at `:411`. This closes the last Important finding. The implementation report records fresh 68 preflight / 14 profile / 12 catalog results and compile/diff checks; this reviewer did not rerun them or the engine.

**Superseding final verdict: specification approved; code quality approved for the reviewed scope. Remaining Critical: zero; Important: zero.** All eight findings recorded across the review passes are closed. The quantization guards, exact raster prefix, indoor aliases and unreviewed-function early-return handling are acceptable as inspected. Current regression locations after the scene tests were added are `tests/test_preflight.py:541` (numeric overflow), `:554` / `:561` (raster tails), and `:569` / `:579` (function compatibility). Approval concerns static preflight correctness within its documented limits; it does not assert dynamic startup, opaque cache compatibility, complete geometry/model semantics, or executable/source parity.

## Calibration identity snapshot follow-up (2026-10-30)

Reviewed only the new `engineering.records` initialization/population (`preflight.py:123,184-189`), its source basis, and the new snapshot regression (`tests/test_preflight.py:289-301`). `cell_id` comes from the effective configured `CellId` column, `site_name` from configured `SiteId`, and `transceiver_name` equals that cell ID. This matches ordinary `CellLoader.cpp:858,1017,1138-1142`, where the transceiver is created per parsed row and named from its attached first cell. The Python report stores fresh scalar dictionaries during preflight, so subsequent CSV edits cannot alter those captured identities.

Indoor parsing retains an explicit empty records list; the unreviewed-function early return does not invent engineering identities. The added test checks the distinct Site ID and Cell ID domains and then rewrites the input CSV while verifying the old context remains unchanged. The caller reports 69 preflight tests passed; no suite or engine was rerun for this review.

**Identity snapshot integration approved. Specification and code-quality approval remain in force; no new Critical or Important finding.**

## Executable-directory boundary follow-up (2026-10-30)

Reviewed only `preflight.py:648-649` and `tests/test_preflight.py:303-310`. Comparing normalized real executable-parent and configured Bin paths correctly blocks absolute or relative `EXE_NAME` values selecting another Bin. It keeps the checked XML/resources aligned with the executable-directory lookup used by the engine; an absolute executable path in the same normalized Bin still satisfies the comparison. The new regression covers both foreign-Bin path forms and requires `ok=False` with `EXE_LOCATION_MISMATCH`.

**Approved for the fixed actual-XML context requirement. Specification and code-quality approval remain; Critical: zero; Important: zero.** No suite or engine was rerun; the caller reports 70 preflight tests passed. No implementation was edited during review.

## Conditional reference checks follow-up (2026-10-30)

Reviewed only `_conditional_inputs` (`preflight.py:453-474`), its invocation and the two regressions at `tests/test_preflight.py:312-325`. `PredParams.cpp:75-78` reads a selection file only when `PredictedCells` is nonempty; `PathLossCalcParams.cpp:28-49` confirms unreadable/empty files fail `GetFocusedCells`. Requiring a readable nonempty file in that requested pred/commsensing branch prevents silent loss of the requested selection without imposing a new file-content format.

The enabled outdoor `CorrectByDT` check targets the actual `meas.anchor` consumed by `PathLossCalcEngine.cpp:199-204`, rather than imposing the raw calibration DT index contract. Missing/empty anchors block an explicitly requested correction instead of silently accepting absent correction evidence; existing opaque anchors produce only an unconfirmed-format warning. Disabled correction and absent selection skip the checks. Indoor functions fail neither reference check, and the existing unreviewed-function early return is unchanged.

**Approved within the reviewed function scope; no incorrect new format restriction or Important false block identified. Specification/code-quality approval remain; Critical: zero; Important: zero.** The caller reports 72 preflight tests passed; no suite or engine was rerun during this narrow review.
