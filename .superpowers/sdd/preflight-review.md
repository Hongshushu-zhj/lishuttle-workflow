# Preflight review

Scope: the supplied preflight diff and current `platform/backend/preflight.py`, preflight changes in `function_profiles.py` / `params_spec.json`, and `tests/test_preflight.py`. Engine source inspected read-only at `D:/workspace/LAB/Lab20261013`. No engine executions, production input writes, commits, or reruns of the reported suites. New isolated Python probes exercised the concrete cases below.

## Verdicts

- **Specification: changes required.** Spatial mode parsing, ground/3d arithmetic, indoor/cali applicability, explicit unknown floor totals, Bin-relative ordinary paths, and conservative cache treatment agree with the brief. However, floor mode can pass without usable building inputs for the engine's selected branch, and several actual input requirements are missed or strengthened beyond the engine contract.
- **Code quality: changes required.** The read-only report/context boundary and small parser helpers are clear. The important weakness is that the positive fixtures are not valid engine inputs, so the suite demonstrates the Python parser's assumptions rather than agreement with the real loaders. The issues below are independent of the already-reported suite results.
- **Critical findings: none. Important findings: five.** No actionable issue found in the narrow `function_profiles.py` or `params_spec.json` changes.

## Important findings

### 1. Select building inputs using `UsingBuildingPolygon`

**Location:** `platform/backend/preflight.py:446-453`; supporting test `tests/test_preflight.py:197`.

The floor prerequisite accepts a positive height from either `BuildingIndexPath` or `BulidVectorIndexPath`, irrespective of `UsingBuildingPolygon`. The engine loads exactly one branch: `GIS/Data/src/GeoDataMgr.cpp:540` selects vector data when true (the default from `LiShuttle/src/ServiceHelper.cpp:94`) and raster data when false. Missing vector input in the true branch produces an empty building collection (`GeoDataMgr.cpp:480-489`); it does not fall back to the raster.

**Concrete repro:** the current positive building test's raster-only fixture, with `SpatialCalcMode=floor`, `UsingBuildingPolygon=true`, no vector data, returns `ok=True` and no issues. That raster supplies no buildings to the actual engine. The inverse case, vector-only input with `UsingBuildingPolygon=false`, can similarly pass this prerequisite although the engine cannot load its building raster.

**Fix:** validate usable heights/geometry from the active branch only, retaining the demonstrably compatible cache exception if one can actually be established. Correct the raster-positive test to set `UsingBuildingPolygon=false`, and add both inactive-data regressions.

### 2. Engineering validation misses required row values and the engine layout

**Location:** `platform/backend/preflight.py:66-93`; `tests/test_preflight.py:45-54`.

The helper validates only ID, coordinates, height, azimuth and max power. Even a blank `Antenna`, EPRE, or propagation-model value passes. Those are mandatory to the real loaders: `NetEntity/src/CellLoader.cpp:864,920,1032` and `NetEntity/src/IndoorAPLoader.cpp:161,185-186,214` use `PARSE_NOEMPTY_*` for these values. Other mandatory values include channel, tilt and Tx/Rx counts. Furthermore, outdoor columns/header count come from Bin's `cellformat.xml` (`CellLoader.cpp:400-405`), while indoor uses fixed offsets. A header-driven rearranged CSV can therefore pass this checker and fail the actual loader.

**Concrete repro:** copied the real full-width `gongcan/zhengzhou-hybrid-109034/engineering.csv` to a temporary directory and blanked `Antenna`, `EPRE per antenna port`, and `Main Propagation Model` in its two data rows. `_engineering` still reported two usable rows and zero issues. The suite's seven-column outdoor and nine-column indoor positive CSVs are also incompatible with the engine layouts.

**Fix:** inspect the engine's applicable configured/fixed column contract and reject absent mandatory fields/values before reporting usable rows. Use valid full-layout positive fixtures, plus regressions for missing mandatory values and a reordered layout. This need not reproduce antenna gain or model computation.

### 3. Distinguish a missing polygon element from a present empty element

**Location:** `platform/backend/preflight.py:459-460`.

`params.get('PolygonFilePath')` collapses absent and empty to the same fallback warning. The engine's `Prediction/src/PredParams.cpp:104` calls `XML_FORCE_PARSE_TEXT`; the macro at `SwanUtility/incl/LiShuttleTypes.h:123-133` throws when the element is absent. A present empty element is accepted and can fall back to map bounds, as intended by the existing empty-polygon test.

**Concrete repro:** remove `PolygonFilePath` from the otherwise passing fixture: `check_run(..., 'pred', ...)` returns `ok=True` with only `REGION_MAP_FALLBACK`. The engine fails during parameter setup. `commsensing` shares that parser.

**Fix:** require the element for pred/commsensing, while continuing to permit a present empty value. Keep cali/indoor exempt. Add a missing-element regression separate from the existing empty-element test.

### 4. Do not block positional-valid DT files solely for header labels

**Location:** `platform/backend/preflight.py:301-304`.

The checker requires normalized header labels to equal `PCTime,cellID,Lon,Lat,RSRP`. The actual `Propagation/Interface/src/MeasurementFileParser.cpp:62-94` skips one header row and reads fixed positions; its column constants are in `MeasurementFileParser.h:10-16`. It never validates header wording. This introduces a false block for a usable DT file with descriptive/localized labels.

**Concrete repro:** keep the fixture data row `20250101,c1,119,26,-90`, but rename the header to `Time,ServingCell,Longitude,Latitude,Signal`. The checker returns `ok=False` with `DT_HEADER` and `DT_NO_USABLE_ROWS`; the engine reads the same measurement values as before.

**Fix:** validate five positional columns and usable data independently of header wording; unfamiliar labels may produce a warning. Add a positional-valid alternate-header regression.

### 5. Reject structurally invalid PLANET projection files

**Location:** `platform/backend/preflight.py:432-434`; positive fixture `tests/test_preflight.py:31`.

Checking only existence/nonzero size permits a projection file that the engine deterministically refuses. `GIS/Data/src/GeoDataMgr.cpp:320-345` requires at least four parsed lines and reads the zone from line two and four projection values from line four. The default positive fixture contains only `UTM\n`; this is not a loadable projection.

**Concrete repro:** the ordinary passing fixture, with its one-line projection, returns `ok=True`. `GeoDataMgr::SetMapFolder` explicitly returns false when parsed line count is below four.

**Fix:** check the minimal source-defined projection structure and finite numeric fields, without reimplementing projection math. Replace the positive projection fixture with the actual four-line structure and add a truncated/invalid projection regression.

## Verified boundaries

The new probes only wrote temporary synthetic/copied inputs. No reported test suites were rerun. The ordinary ground/3d/cali/indoor mode branches and cache warnings were inspected against source; I found no additional Important issue in their basic arithmetic/applicability. Floor caches remain explicitly unconfirmed, which is consistent with the brief's requirement for demonstrable compatibility; header/step parity alone is insufficient. Ordinary XML relative paths and DT index references are resolved against the expected Bin/input directory respectively. This review does not certify the executable matches the inspected source, nor full geometric/material/ray validity.
