# Preflight implementation report

Owned changes: `platform/backend/preflight.py`, `tests/test_preflight.py`, mode descriptions in `platform/backend/params_spec.json`, and mode applicability in `platform/backend/function_profiles.py`. No engine executions, source edits, project-input edits, template-default changes, or commits.

`check_run(env, schema_path, func, task_id)` returns `{ok, issues, context}`. Every issue has severity/code/message/field/path. Context pins the actual UTF-8 schema text and SHA256, scalar parameters, project/Bin/executable, runtime filename (`schema_name`), XML root name (`task_name`), string task ID, and actual output/pred/DT/model directories. Relative XML paths resolve from Bin. Missing metadata stays empty/None. Calls perform only reads.

Implemented checks cover executable/XML validity and duplicate scalars; CSV kind, finite numeric rows, IDs and AP floors; PLANET projection/index references and the real MapPath directory/name alternatives; indoor DAS floor IDs, header/wall truncation and AP-floor matching; region metadata/fallback; calibration required constraints, DT index references/header/data-cell matching; and raw lowercased, untrimmed spatial modes. `building` aliases `floor`; ground is one base layer, 3d uses floor(H/h)+1 without a fabricated final partial height. Floor mode records configured `layer_cap` separately and leaves actual `layer_count=None` because per-building scene FloorHeight determines actual floors. Indoor uses actual DAS IDs. Calibration stays ground and does not require 3d geometry or polygon inputs.

Source evidence reviewed from `D:/workspace/LAB/Lab20261013`: ServiceHelper.cpp:86-163; PredParams.cpp:9-126 and PredParams.h (`pred` directory constant); PredictionEngine.cpp:43-180; GeoAlgorithm.h (`GET_FLOORS`); GeoSubSys.cpp:7-83; GeoDataUtility.cpp:141-285 (MapPath aliases/menu, big-endian PLANET rasters); PlanetDemIndexFile.cpp and PlanetBuildVectorIndexFile.cpp (references/bounds); IndoorGeoInfo.cpp:48-85 and GeoFloorParser.cpp:142-285; CellLoader.cpp and IndoorAPLoader.cpp; CalibrationParams.cpp:31-108; PropagationFunc.cpp:143-178 (DT index); PMCorrectionEngine.cpp:86-223 (temporary model location); PMCorrectionData.cpp:146 and CellCorrectionData.cpp:238 (explicit ground); SectorPathlossforFloor.cpp:302-470 and SectorPathLossMatrix.cpp:141-170/286-368 (cache structure and hash dependency); GeoBuildingPolygon.cpp:101-116 (scene floors).

TDD evidence: initial suite showed 23 intentional missing-module assertion failures. Subsequent tests exposed absent menu/name alternatives/cache diagnostics, incorrect `prediction` directory assumption, duplicate XML behavior, schema filename/root-name distinction, invented floor totals, and overflow/invalid resolution/map handling before fixes. Final verification (2026-10-30):

- `python -m unittest discover -s tests -p test_preflight.py`: 34 passed.
- `python -m unittest discover -s tests -p test_function_profiles.py`: 14 passed.
- `python -m unittest discover -s tests -p test_parameter_catalog.py`: 12 passed.
- `python -m py_compile platform/backend/preflight.py platform/backend/function_profiles.py`: passed.

Boundaries/concerns: existing `*.loss3d.csv` cache headers are inspected for real PATHLOSS3D/floor-CSV version and step. A header/step match cannot prove compatibility: the engine hash incorporates C++ std::hash, converted antennas, serialized propagation models, and geometry/NLOS digests. Such caches are explicitly unconfirmed and never silently used to bypass missing building inputs. No invented sidecar flags or forced deletion/recalculation. This conservative check may block floor runs that the engine could serve solely from opaque caches. Preflight verifies input structure/reference availability; it does not reimplement the engine's full geometric, material, antenna/model loading, projection or ray computation. Region coordinate metadata is descriptive, not a prediction-result index. Result integrity/business success remains the independent validator's responsibility.

## Review repair pass (2026-10-30)

This section supersedes the original 34-test count and the earlier, narrower checks described above. All five Important findings in `preflight-review.md` were reproduced with failing regressions before implementation:

- Building selection now follows `UsingBuildingPolygon` exactly, with no inactive-source fallback. Raster inputs use big-endian int16 samples and the engine altitude range; vector evidence requires a matching positive-height attribute and finite geometry. Large attribute/geometry files and raster scans stream with bounded reads. Floor mode keeps actual layer count unknown and exposes only its configured cap and first usable sample height.
- Engineering data follows actual loader offsets and Bin/cellformat.xml overrides rather than inferring layout from headers. Fixtures now use the full modern 42-column outdoor and fixed 32-column indoor formats. Mandatory strings and numeric fields match loader parsing; known header conflicts with configured offsets block. Missing/invalid format configuration retains the legacy default layout with a warning; an original 35-column regression passes.
- Missing PolygonFilePath blocks outdoor prediction; an explicitly empty element keeps the engine's map-extent fallback. Calibration remains exempt.
- DT files always skip one header row and use the first five positional columns. Unfamiliar header labels warn rather than blocking otherwise valid measurements. Index references and matching usable cell measurements remain required.
- PLANET projection fixtures/checks now use four engine-shaped lines: zone on line two and four finite numeric values on line four.

Additional source-aligned repairs: identical duplicate XML scalars warn and retain the first value; differing duplicates block. Both PLANET path branches require the clutter menu. Raster references check source-derived grid dimensions and minimum byte length. Scene configuration is required with its real Bin-relative default. Outdoor model references must resolve to registered model definitions with the six required coefficients, allowing engine builtin auto/scene/cell model zero; indoor's fixed physical chain does not require an outdoor model definition. Antenna configuration, MaxGain, beam references and 2D/3D numeric shape are checked. Pre-suffixed antenna references require the exact loaded beam; base references select nonzero loaded tilts as GetAntNo does. Sensing antenna references apply only to commsensing. Outdoor communication antennas remain required even with AntGainCalced=false; indoor may skip them when false.

Ground and calibration context now report effective `mode.max_height=0` and preserve the XML numeric value separately as `mode.configured_max_height`; raw parameters/XML are unchanged. Output access uses read-only ancestor checks, detects file collisions, and blocks missing ancestors the engine's nonrecursive mkdir cannot create. Task name and task ID reject Windows illegal component characters `<>:"|?*` in addition to separators/NUL/empty names.

Further source evidence: CellLoader.h:19-60; CellLoader.cpp:31-110,393-405,664-700,835-935,1002-1055; IndoorAPLoader.cpp fixed offsets/CreateApCell/CreateAp; LabelColumnMap.cpp; GeoDataMgr.cpp:231-349,470-540; GeoRasterData.cpp:17-40; GeoXYRect.h:243; GeoTypes.h GIS_MAX_ALTITUDE; GeoDataUtility.cpp:280-350; MeasurementFileParser.cpp:62-94; CalcParamFactory.cpp:115; AntennaLoader.cpp:132-215,287-308,350-415,542-650; PropagationModelFactory.cpp; PropagationSubSys.cpp; LiShuttlePropagationModel.cpp:170-295; LiShuttleIndoorCalculator.cpp:97; ServiceHelper.cpp:86-175.

Runtime boundary: `main.cpp:388` calls ShuttleInit before argument processing. Its implementation is not in the reviewed tree; ThirdPart/include/LishuttleCtl.h:61 only declares the imported function, and ULog.h defines log4cpp.conf. The doctor checks at main.cpp:220-285 are not treated as mandatory startup gates. Every completed resource check therefore includes `RUNTIME_RESOURCES_UNCONFIRMED` warning and `resources.dynamic_runtime='unconfirmed'`, plus log configuration path/existence metadata. DLL resolution, license validation and logging initialization are not claimed verified. No process was launched and no OS DLL search algorithm was invented.

Fresh verification after repairs:

- `python -m unittest discover -s tests -p test_preflight.py`: 61 tests passed (5.640s).
- `python -m unittest discover -s tests -p test_function_profiles.py`: 14 tests passed.
- `python -m unittest discover -s tests -p test_parameter_catalog.py`: 12 tests passed.
- `python -m py_compile platform/backend/preflight.py platform/backend/function_profiles.py`: exit 0.
- `git diff --check`: exit 0 (only an existing CRLF conversion advisory for another agent's test_project_defaults.py).

Read-only behavior is covered by before/after file bytes and modification timestamps in isolated fixtures; missing output trees remain absent. No engine execution, project source/input modification, commit, staging or unrelated-file edits occurred. Parent is handling real-schema scratch acceptance separately. Remaining limits: geometric enclosure/material validity, full model/scene semantic loading, opaque cache hash compatibility, projection computation and dynamic runtime initialization remain engine responsibilities rather than guarantees from this preflight.

## Final boundary and compatibility repair (2026-10-30)

Reproduced both Important findings in `preflight-final-review.md` with regressions before changing implementation. A finite `1e308` raster resolution previously raised OverflowError instead of returning check_run's report. Quantization now validates its scaled intermediate before floor conversion; extent subtraction and dimension ratios must also remain finite and positive, and the index exception boundary catches OverflowError. Tests cover huge finite resolution, overflowing extent subtraction, and resolution quantizing to zero; each returns MAP_INDEX_INVALID, ok=false, and JSON-safe output.

Raster index entries now carry `raster_bytes`, the exact source-derived grid prefix length. Building evidence reads at most that length in bounded chunks and ignores bytes after it. Regressions prove that a fifth positive sample cannot establish floor buildings for a declared four-sample zero grid, while a valid four-sample grid followed by one odd trailing byte is accepted. Source remains GeoRasterData.cpp:19-23, GeoDataUtility.cpp:303-304 and PlanetHeightData.cpp:28-34; no data was changed.

Compatibility correction: plindoor and indoorrays use the indoor family (LiShuttleTypes.h:27,35; PathLossofIndoorEngine.cpp and PathLossCalcParams.cpp:255). They retain FUNCTION_UNREVIEWED and context.function_contract='unconfirmed' because their full function/result contracts were not added to this phase. Unknown debug/test/custom functions return after the actual common XML/executable/output checks, with the same unreviewed warning/status; they do not inherit outdoor CSV, map, layer, resolution, polygon, scene or propagation-resource requirements. Their layer count remains unknown. Regression coverage also confirms common missing-output and missing-executable errors still block these functions. Existing reviewed-function checks are unchanged.

Fresh verification:

- `python -m unittest discover -s tests -p test_preflight.py`: 66 passed (5.981s).
- `python -m unittest discover -s tests -p test_function_profiles.py`: 14 passed.
- `python -m unittest discover -s tests -p test_parameter_catalog.py`: 12 passed.
- `python -m py_compile platform/backend/preflight.py`: exit 0.
- `git diff --check`: exit 0; same unrelated CRLF advisory only.

Only preflight.py, test_preflight.py and this append-only report were edited in this final repair. No engine execution, real source/data modification, staging or commit. Ready for another review; the previously stated semantic/runtime limits remain.

## Scene default-path correction (2026-10-30)

The previous report's claim that the default scene path was Bin/config/scenesettings.xml was incorrect. Read-only source verification shows DEFAULT_CONFIG_DIR="runtimelibrary" in SwanUtility/incl/LiShuttleTypes.h:42 and ServiceHelper.cpp:161-166 appending it with SCENEINFOMATION_FILE. The actual default is therefore Bin/runtimelibrary/scenesettings.xml. Both the implementation and missing-scene diagnostic now use that path, as does the main positive fixture. Explicit SceneSettingsPath still resolves relative to Bin.

TDD: two new mutually exclusive fixtures failed before implementation: only runtimelibrary/scenesettings.xml present incorrectly blocked; only old config/scenesettings.xml present incorrectly passed. Both pass after correction. The existing explicit-relative-path test also passes. Fresh verification: 68 preflight tests passed (7.546s), 14 function-profile tests passed, 12 parameter-catalog tests passed, py_compile and git diff --check exit 0 (same unrelated CRLF advisory). Only the owned preflight module/tests and this report were edited; no engine execution, real data/source edit, staging or commit.
