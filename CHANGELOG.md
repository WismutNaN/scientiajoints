# Changelog

All notable changes to ScientiaJoints are documented here.

## [3.3.2]

### Fixed

- Fixed the stereonet drawing poles but no density contours. `mplstereonet` 0.6.2 and older use `np.float`, an alias numpy removed in 1.24, so on the numpy that Blender 5.x ships every contour call failed with `module 'numpy' has no attribute 'float'`. The failure was only logged, which is why the chart still appeared, just without the density. The release now bundles `mplstereonet` 0.6.3, where upstream fixed it, and `visualization` restores the alias around the plotting call so an already installed older copy works too. `dependencies.py` knows the minimum version, asks pip for it, and the diagnostics report names an outdated copy instead of leaving it to be noticed on the chart.
- Fixed enabling the add-on failing with `Tool 'scientiajoints.measure' already exists!` when a toolbar entry from an earlier registration was still present. That happens when the add-on is installed both as an extension and as a legacy add-on, and when a reload drops the old classes before `unregister()` runs: `bpy.utils.unregister_tool()` matches the exact `ToolDef` object it stored on the class, so it cannot remove an entry left by a different copy of the module. Registration now clears any toolbar entry carrying one of the add-on's own identifiers, removes its key-map with it, and logs which duplicate installation to clean up.

### Added

- Added custom toolbar icons for the two ScientiaJoints workspace tools. Both used to borrow `ops.view3d.ruler`, so they were indistinguishable from each other and from Blender's own ruler. `Scientia Measure` now shows a plane through three point handles with the measured segment highlighted, and `Scientia Polygon Plane` shows a closed outline of picked points with the fitted plane normal rising out of it. They keep Blender's toolbar palette so they do not stand out. The artwork is vector source in `tools/build_tool_icons.py`, which renders the `icons/*.dat` triangle files Blender's toolbar actually loads; `--preview` writes a PNG contact sheet.

### Changed

- The add-on version is now set in one place, `blender_manifest.toml`, and changed with one command, `python tools/version.py <version>`. Blender parses `bl_info` out of `__init__.py` before importing the add-on, so that copy has to stay a literal; the command writes it, and `tools/build_release.py` now refuses to package a checkout whose two copies disagree instead of building an archive whose manifest and add-on list report different versions.

## [3.3.0]

### Added

- Added a Blender extension build (`blender_manifest.toml`) that ships `matplotlib` and `mplstereonet` as wheels inside the archive. Blender unpacks them itself, so installation needs no pip, no package index and no network. Both formats are released side by side: `ScientiaJoints-<version>-extension.zip` and the legacy `ScientiaJoints-<version>.zip` for `Install from Disk`.
- Added offline installation for the legacy build: wheels shipped in the add-on's `wheels/` directory are installed with `pip --no-index`, and only if that fails is PyPI used at all. `tools/fetch_wheels.py` downloads the wheels, optionally for every platform Blender supports.
- Added a diagnostics report behind the small `i` icon in the panel header: Blender build, device and GPU, the installed add-on version and whether it runs as an extension or a legacy add-on, how many wheels the build carries, Python and interpreter paths, dependency status with the exact file each package resolves to and **how each one was installed** (extension wheels, pip into Blender's Python, pip into the user modules directory, or shipped with Blender), the source and target of the last install run, install directories with their writability and remaining Windows path budget, `.blend` and scene parameters, measurement counts and sources, a six-step self-test, and a list of detected problems with their probable cause and the action to take. The report can be copied to the clipboard, saved to a file, and is always available in the Text editor as `ScientiaJoints Diagnostics`.
- Added an in-panel warning when charts are unavailable, naming the missing packages and offering `Install Chart Packages` and `Diagnostics` buttons. Previously the only sign of a failed installation was a line in the system console.
- Added near-duplicate detection: measurements that land on the same millimetre grid but are not exactly equal are kept and reported in Statistics and diagnostics, which catches a ruler copy that was nudged after Blender duplicated it into another annotation frame.
- Added reporting of ruler annotations spread over several timeline frames, the mechanism behind duplicated measurements after a frame change.
- Added `SCIENTIAJOINTS_NO_AUTO_INSTALL` to switch the automatic dependency install off entirely.
- Added detection of plane measurements whose points cannot define an orientation (all on one straight line, or all at the same position). The dip and azimuth are still computed and exported, but `Measurement Info` shows "Orientation is arbitrary" with the reason, Statistics counts them, the diagnostics report lists them by name, and the processed faces CSV gains a `degeneracy` column. A long thin trace such as 10 m by 5 cm is not affected.

### Changed

- Dependency installation no longer blocks Blender. `register()` only checks imports; the installation runs on a worker thread and reports back through the panel. A failed automatic attempt is retried at most once a day instead of on every start, and headless Blender never installs anything.
- pip is now invoked with `--no-input`, a timeout, `--only-binary`, and captured output. The install directory is chosen from candidates that are on `sys.path`, actually writable, and short enough for the Windows path limit; `--user` is never used because Blender disables the user site. `numpy` is pinned to the bundled version so a `--target` install cannot introduce a second, ABI-incompatible copy.
- Code and layer visibility is now display-only and no longer removes measurements from processing or export, which matches the linear/plane toggles and the documented behaviour. Hidden measurements are reported in the diagnostics instead.
- Measurement names are now unique; numbering by collection length repeated a name after any deletion, so two different measurements could share a name in the exported CSV.
- `Skipped duplicates` in Statistics is now an informational line (`Exact copies merged`) rather than an error.

### Fixed

- Fixed installing an update inside a running Blender failing with `ImportError: cannot import name ... from 'ScientiaJoints.operators'`. Blender reloads only the top-level package, so every submodule stayed in memory from the previous version and the new `__init__.py` was asking stale modules for symbols they did not have. The package now clears its own submodules from `sys.modules` before importing them, and `register()` checks the files on disk first so a genuinely incomplete installation says so instead of naming a missing symbol.
- Fixed the real-time chart toggles staying permanently stuck on "already running" when Blender dropped the modal operator without calling `cancel()`, for example on loading a file.
- Fixed the real-time chart operators being started from a property update callback, where Blender's restricted context can refuse or mishandle `bpy.ops` calls. They are now started one timer tick later.
- Fixed viewport preview state and cached geometry from a previous `.blend` surviving a file load, which drew a ghost measurement in the new file. A `load_post` handler now resets it.
- Fixed the viewport overlay running a full plane fit (an iterative eigen decomposition) for every polygon on every redraw; processed records are now cached per point position and azimuth correction.
- Fixed `sys.executable` being trusted blindly: on builds where it points at the Blender binary, `blender.exe -m pip install` started a second Blender instead of installing anything.

## [Unreleased]

### Added

- Added a deterministic release-package builder (`tools/build_release.py`) and archive-structure tests. Release ZIPs always contain the valid `ScientiaJoints/` Python package, verify required module symbols and syntax, and print a SHA-256 checksum.
- Added plane fit error for polygon (`POLYLINE`) measurements:
  - `fit_error` is the RMS distance of the points from the best-fit plane (model units);
  - `fit_error_relative` is the RMS divided by the mean point distance from the centroid, so it reads as "% of measurement size";
  - shown in `Measurement Info` (with a warning icon above 10%), available as a viewport label field (on by default), and exported in the processed faces CSV together with the new `point_count` column.
- Added a "Save the .blend file to enable export" warning inside the Export section when the file is unsaved.
- Added separate viewport visibility toggles for linear and plane/polygon measurements (`Measurement Display` panel and tool header). Display only: export, statistics, and charts are not affected. The active measurement always stays visible so a fresh 2-point measurement cannot vanish mid-edit.
- Added `X`/`Del` support to the `Scientia Polygon Plane` tool: deletes the active measurement when idle, removes the last placed point while drawing (same as `Backspace`).
- Added right-click to finish the polygon being drawn (with fewer than 3 points it still cancels); `Esc` always cancels.
- Added measurement deselection: a short click on empty space with the `Scientia Measure` tool clears the selection (a real drag still creates a measurement), plus an `Alt+A` shortcut in both tools and a deselect button in the tool header and `Measurement Info`. This also stops cursor jitter from creating degenerate micro-measurements on a plain click.

### Changed

- Linear measurement `dip` is now the plunge: 0° for a horizontal line, 90° for a vertical one (previously the angle was measured from the vertical). Affects the edges CSV `dip` column, the `Angle` value in `Measurement Info`, and viewport labels.
- `edge_azimuth`/`edge_dip` now describe the plane perpendicular to the measured segment (the segment is its normal), for matching spacing measurements against joint-set orientations: `edge_dip = 90° − plunge`, `edge_azimuth` equals the line azimuth. Previously `edge_dip` was always 45° regardless of input.
- Viewport labels for polygon planes now use all polygon points for dip/azimuth/area (previously only the first three points), and the label anchors at the polygon centroid.
- `Measurement Info` is now expanded by default; label field toggles moved into a collapsible `Label Fields` subsection; processed CSV export buttons are listed before raw TXT export.
- Statistics are cached for one second instead of re-parsing all measurements on every panel redraw.
- When all Scientia measurements are hidden by code/layer visibility, diagnostics now report how many measurements are hidden instead of claiming the `RulerData3D` layer was not found.

### Fixed

- Startup diagnostics no longer prevent registration when an update has left an older `operators.py` in Blender's module cache. The console now explains that a clean reinstall is required.
- Fixed the documented distribution workflow that allowed incorrectly packaged source ZIPs to fail installation with `No module named 'ScientiaJoints 3'`.
- Fixed editing a point of a 3-point polygon plane silently converting it from `POLYLINE` to `PLANE` (which changed how it is drawn and processed).
- Fixed `FaceView.__str__` crashing for polygon faces where the point angle is undefined.
- Removed scene collection mutation (`sync_scene_measurement_codes`) from panel/menu draw callbacks; Blender forbids writing to ID data during draw. Synchronization still happens in operators and property update callbacks.
- Fixed the stale `bl_info` version (2.3.0 → 3.2.0).

### Earlier unreleased changes

### Added

- Added label field settings for custom measurements:
  - linear labels can show distance, angle, corrected/raw azimuth, `dx`, `dy`, `dz`, and horizontal distance;
  - plane labels can show dip, corrected/raw azimuth, point angle, and area;
  - labels can optionally include code, name, and description.
- Added an active measurement code picker menu for assigning existing codes without retyping long names.
- Added code clearing for moving a measurement back to the `No code` group.
- Added the `Scientia Polygon Plane` toolbar tool for closed multi-point fracture polygons.
- Added best-fit plane processing for scene-stored `POLYLINE` measurements with three or more points.
- Added raw face export preservation for all polygon points via appended point count and JSON coordinate list.

### Changed

- Measurement Info now places `Code` before `Name`.
- Custom measurement labels now default to distance for linear measurements and `dip`/corrected `azimuth` for three-point plane measurements.
- Fracture code entries are now synchronized from existing measurements, so unused codes disappear automatically while used code settings are preserved.
- Per-measurement hide is no longer exposed or used for custom measurement filtering; visibility is controlled through code groups and `No code`.
- Standard `RulerData3D` strokes still accept only two or three points; multi-point planes require the scene-stored `POLYLINE` kind hint.

### Fixed

- Fixed stale fracture code entries remaining after all measurements with that code were deleted or renamed.
- Fixed previously hidden individual custom measurements staying effectively unrecoverable after removing the single-measurement hide control.

## [3.0.0] - 2026-07-03

Major release based on the original `2.2` add-on. This release fixes the measurement/export pipeline, adds a new scene-stored measurement tool, introduces fracture codes and display controls, and prepares the project for public release.

### Added

- Added the `Scientia Measure` toolbar tool for creating and editing measurements directly in the 3D View.
- Added scene-based measurement storage in `.blend` files via `bpy.types.Scene.scientia_measurements`.
- Added support for two-point linear measurements and three-point plane measurements from the custom tool.
- Added editable point handles for active/hovered measurements.
- Added angle arcs for three-point measurements.
- Added snap feedback markers:
  - circle for face/surface snap;
  - hourglass for edge snap;
  - square for vertex snap.
- Added `Snap` mode: snapping can be enabled by default, with `Ctrl` temporarily inverting the mode.
- Added `All Handles` mode for showing every measurement handle when needed.
- Added active measurement information panel:
  - linear distance;
  - angle/dip;
  - corrected and raw azimuth;
  - `dx`, `dy`, `dz`;
  - horizontal distance;
  - plane dip, azimuth, area, and angle.
- Added fracture code metadata for measurements.
- Added per-code color and visibility.
- Added implicit `No code` group for measurements without a fracture code.
- Added per-measurement description.
- Added export metadata fields:
  - `id`;
  - `source`;
  - `source_id`;
  - `layer`;
  - `name`;
  - `code`;
  - `description`;
  - `attributes_json`.
- Added stereonet coloring by fracture code or `No code` group.
- Added `Legacy Pole Color` fallback for standard `RulerData3D` measurements without code metadata.
- Added Russian LLM-agent documentation under `docs/llm-agent/`.
- Added root `README.md` for public installation and usage.
- Added `requirements.txt`.
- Added pure Python tests for domain geometry, parser behavior, export, dependencies, and visualization smoke checks.
- Added optional Blender headless smoke-test workflow.

### Changed

- Refactored the measurement pipeline toward a DDD-style structure:
  - `domain/` for pure measurement and geometry logic;
  - `application/` for ingest/process/export use cases;
  - `infrastructure/` for Blender adapters and file writers;
  - `parser.py` as a compatibility facade for existing UI/export code.
- Reworked parser input into a composite source:
  - custom `ScientiaScene` measurements;
  - standard Blender `RulerData3D` annotations.
- Reorganized the sidebar panel:
  - top-level histogram and stereonet buttons remain always visible;
  - settings are grouped into `Measurement Info`, `Measurement Display`, `Azimuth Correction`, `Export`, `Statistics`, and `Chart Appearance`.
- Renamed stereonet point color behavior so code-based measurement colors are primary, while `marker_face_color` is only a legacy fallback.
- Kept automatic dependency installation for normal users, but optimized it so `pip` is not started when dependencies are already installed.
- Improved Blender console/log diagnostics for dependency status, parser status, duplicate measurements, ignored strokes, and chart generation errors.
- Improved operator logging to keep full tracebacks in Blender console while keeping UI reports concise.
- Batched 3D measurement line/arc rendering by color to reduce draw overhead on large measurement sets.
- Limited screen-space handles to active/hovered measurements by default for better performance.

### Fixed

- Fixed duplicated fracture counts caused by duplicated ruler strokes across annotation frames.
- Fixed parsing for Blender layouts where strokes are stored under `frame.drawing.strokes`.
- Fixed unsupported stroke handling so unsupported point counts are ignored and reported.
- Fixed export/process operators reporting success when the `.blend` file was unsaved or writing failed.
- Fixed hidden mutation in azimuth/dip calculations; geometry calculations are now non-mutating.
- Fixed degenerate zero-length angle handling.
- Fixed stereonet generation failing entirely when density contours fail on small/problematic datasets; poles are still drawn.
- Fixed visualization operators returning success when no image was created.
- Fixed registration failures leaving partially registered classes/properties behind.
- Fixed `_RestrictContext` registration issue by avoiding direct scene access during restricted add-on registration.
- Fixed custom measurement visibility after cancel/escape so measurements remain visible.
- Fixed custom measurement tool blocking sidebar controls after a drag.
- Fixed `Ctrl + left drag` not starting a snapped measurement.
- Fixed accidental point dragging on inactive measurements; inactive measurements must be activated first, then edited.
- Fixed uncoded measurement color behavior: changing `No code` color now affects old and new uncoded measurements.
- Fixed hidden code visibility so it affects 3D overlay, selection/hit-testing, export, and stereonet rendering.
- Fixed stale/fragile standard Ruler display settings by removing the unsupported `ToggleRulerSettingsOperator` workflow.
- Fixed `.gitignore` cache and Blender backup patterns.

### Removed

- Removed legacy root `geometry.py`; geometry now lives in `domain/geometry.py`.
- Removed unused `storage.py`.
- Removed unstable `ToggleRulerSettingsOperator` and `RulerSettings` registration.
- Removed `Attributes JSON` from the UI while keeping the data field and export support internally.

### Documentation

- Added architecture documentation for the current DDD-oriented layout.
- Added measurement pipeline documentation.
- Added bug-audit documentation with known fixes and remaining risks.
- Added custom measurement tool research notes, including why exact Blender Measure parity would require Blender C++ internals or new public API hooks.
- Documented local Blender path and headless smoke-test commands.

### Tests

- Added and maintained tests for:
  - geometry calculations;
  - parser layout variants;
  - duplicate ruler stroke handling;
  - scene-stored measurements;
  - code visibility and `No code` behavior;
  - raw and processed export;
  - dependency checks;
  - visualization smoke behavior.

## [2.2] - Initial baseline

Initial add-on version used as the migration baseline.

### Existing functionality

- Read Blender Measure/Ruler annotations from `RulerData3D`.
- Classify two-point strokes as linear measurements.
- Classify three-point strokes as plane measurements.
- Export raw edge/face coordinates.
- Export processed CSV data.
- Generate edge-length histograms.
- Generate plane-orientation stereonets.
- Provide sidebar UI for visualization, export, statistics, and azimuth correction.
