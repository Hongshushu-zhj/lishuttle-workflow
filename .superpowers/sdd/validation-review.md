# Artifact validation review

Scope: `platform/backend/result_validation.py`, `tests/test_result_validation.py`, requirements in `p0-brief.md`, and read-only comparison with `D:/workspace/LAB/Lab20261013`. No engine runs, real data changes, implementation edits, or commits. Existing reported 39 tests were not rerun. Five concrete new scenarios were executed using the existing test fixture helpers in temporary directories; all fixtures were cleaned up.

## Verdicts

- **Spec compliance: changes required.** Five Important findings remain. The shared context contract is incompatible with calibration report lookup; calibration does not fully distinguish or verify the different model outcomes; floor validation disregards the configured cap.
- **Code quality: changes required.** Streaming hashes, per-product attribution, bounded metadata reads, separate process/artifact/business fields, and conservative handling of unknown formats are sound choices. However, the tests use an artificial `schema_name='demo'` without `task_name`, omit common-model outcomes, and do not cover actual floor contexts (`layer_count=None`, `layer_cap` present). Scanning every historical XML as a mandatory current artifact creates unrelated hard failures.
- **Severity:** 0 Critical; 5 Important. These are reproducible result-classification defects, not style preferences.

## Important findings

### 1. Calibration uses the XML filename instead of the engine task name for report prefixes

**Implementation:** `result_validation.py:46–49`, `:422–428`, `:438`. `schema_name` is used both for the baseline candidate list and `<name>_cell_summary.csv` / `<name>_scene_summary.csv` lookup.

**Contract/source:** The shared context contains both fields. `preflight.py:376` sets `schema_name=Path(schema_path).name` and `task_name=name`; its tests explicitly expect `schema.xml` versus `fixture` (`tests/test_preflight.py:77–78`). Engine `LiShuttle/src/ServiceHelper.cpp:77–78` reads the RuntimeSchema attribute value into `m_commonParams.schemaName`. `Propagation/Frame/src/PMCorrectionEngine.cpp:228–232` and `:238–240` use that value as the report prefix.

**New probe:** context `schema_name='schema.xml', task_name='demo'`, a new valid `demo_cell_summary.csv`, anchor, changed cells model and current Y/Y site log. Actual verdict: `failed`, issue `REQUIRED_FILE` for `schema.xml_cell_summary.csv`. The correct report is ignored; its baseline is also omitted. This affects ordinary XML filenames even when filename stem happens to equal the task name, because the filename includes `.xml`.

**Required change:** Use `task_name` consistently for engine report naming and baseline collection; preserve `schema_name` for identifying the input file. Add a fixture whose filename differs from its RuntimeSchema name and exercises the actual preflight context.

### 2. A failed or absent current common-model save can still produce full success

**Implementation:** `result_validation.py:442–460` recognizes only changed cells XML and `scenes/SceneModel.xml`; `:477–484` derives business status solely from site Y/N outcomes. `CalNewModelName` and current general-model/save messages are never consulted.

**Source:** `CorrectCalculator.cpp:436–451` independently determines whether a general model was successfully calibrated. `PMCorrectionEngine.cpp:300–324` saves it with `ModelName=CalNewModelName`, logging `Failed to save the common model!` on failure; `:379–393` calls common, cells and conditional scenes saves separately. `PropagationModelFactory.cpp:235–238` saves the common model in a top-level model XML, not `cells`.

**New probe:** new anchor/cell report, changed `cells/city.xml`, `CalNewModelName='new_general'`, current Y/Y site log, `The calibration of the general model completed!` and `Failed to save the common model!`; no top-level common model exists. Actual verdict/business: `success` / `success`, no issues.

**Required change:** Track general-model applicability and current outcome separately. When calibration reports a general-model update, verify that the actual saved XML contains that named model and current persistence evidence. A known save failure must prevent full success and explain which model failed; do not unconditionally require a common model when the source intentionally has no accepted general model.

### 3. Successful scene/general updates are reported as `no_update` when sites did not update

**Implementation:** `result_validation.py:416–420`, `:477–484` count only sites; even a verified current scene model contributes nothing to aggregate status or update counts.

**Source:** `CorrectCalculator.cpp:194–288` runs scene calibration separately and inserts successful scene models at `:281–283`. General calibration has its own outcome at `:436–451`. `PMCorrectionEngine.cpp:245–250` writes successful scene model rows; `LiShuttleSceneModel.cpp:699–702` only proceeds to save a nonempty model set.

**New probe:** site `success=Y, update=N`, current scene report with one row, changed `scenes/SceneModel.xml` containing a ModelName, and current scene-completed log. Actual verdict: `no_update`; `business.updated=0`, no issues. Thus the UI would announce no update despite a confirmed scene update. The inverse omission also prevents a general/scene failure from making an otherwise successful site run partial.

**Required change:** Preserve site statistics but expose/aggregate outcomes for cells, general and scenes separately. `no_update` must mean no applicable model kind updated; mixed confirmed outcomes must be represented as partial, with uncertainty kept explicit.

### 4. Floor mode includes stale directories above the current engine cap

**Implementation:** `result_validation.py:315–318`, `:339–360` uses only `layer_count` to exclude elevated directories, then demands every intermediate layer beneath the highest observed one. It ignores `mode.layer_cap`, `configured_layer_count` and `max_height`.

**Contract/source:** Actual floor preflight sets `layer_cap=floor(H/h)+1` and `configured_layer_count` at `preflight.py:443–445`, then intentionally sets `layer_count=None` at `:458` because actual building stacks are not globally rectangular. Engine `PredictionEngine.cpp:158–160` supplies the configured maximum to the calc suite; `IndicatorCalcSuite.cpp:413–415` and `:428–445` cap the actual floor count before expansion.

**New probe:** realistic floor context `layer_count=None, layer_cap=2, configured_layer_count=2, max_height=3, floor_height=3`; old `9m/RSRP.dem` exists before baseline; the current run creates complete ground and `3m` products. Actual verdict: `failed`, demanding missing `6m` and `9m` products and reporting the stale `9m/RSRP.dem` size. Those heights are excluded by the current engine settings.

**Required change:** Apply the known configured cap while observing region-specific building stacks. Ignore historical directories outside this run's applicable height range. Keep uncertainty about actual building floors separate from hard errors for files the current engine never intended to write.

### 5. An unchanged unrelated historical model XML makes a valid current run fail

**Implementation:** `result_validation.py:448–452` parses every XML beneath `models_dir` before checking whether it changed or is an applicable model. `_xml` adds a hard `MODEL_XML` issue at `:384–385` even for an unchanged irrelevant file.

**New probe:** malformed `models/legacy_unrelated.xml` exists in the baseline; the run creates a new cell report and a valid changed `cells/city.xml` with current Y/Y site log. Actual verdict: `failed`, sole issue `MODEL_XML` at the unchanged unrelated file. This is particularly consequential for in-place `Bin/models`, which is a shared existing resource tree.

**Required change:** Select applicable current model candidates using changed fingerprints, required paths and expected model identities before promoting XML parse errors to current-run failures. Historical unrelated XML may be diagnostic information but must not invalidate current artifact evidence.

## Coverage and limits

The reviewed implementation correctly uses the source's outdoor and indoor product names, int16 sentinel, GeoRasterRect rounding tolerance, region suffixes, per-height folder naming and site log format. Cancellation/nonzero exits cannot become full success. Existing fixtures cover several useful cases of old products, missing companion metrics, grid mismatches and conditional scene reports. These observations are from source review; the reported original test pass is not claimed as independently rerun.

The five probes above executed with exit code 0 and produced the stated verdicts. They used only synthetic temporary files; no wireless engine execution or physical-model accuracy assessment was performed. The generic fixture intentionally keeps `schema_name='demo'` for findings 2–5 to isolate each defect from finding 1.
