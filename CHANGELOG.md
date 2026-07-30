# Changelog

All notable changes to ScientiaJoints are documented here.

## [Unreleased]

### Added

- Added a trace measurement type and the `Scientia Trace` tool that creates it. A trace is an open polyline along a fracture: its length is the sum of its segments, which is what separates it from a linear measurement between the same two end points. The tool works like the polygon tool with the closing taken out - click along the trace, right click, Enter or Space to finish, Backspace to undo a point - and two points already make one. It has its own toolbar icon and never gets the area fill or the angle arc, because it encloses nothing.
  - Traces have their own visibility toggle next to `Linear` and `Planes`, in the sidebar and in the tool header. Hiding planes no longer hides traces, which matters because a trace has as many points as a polygon and the kind, not the point count, has to decide.
  - `Measurement Info` reports the total length, the segment count, the mean, smallest and largest segment, the straight span between the ends and the sinuosity. The same fields are available as viewport label fields.
  - Added `Export > Processed > Traces`, a CSV with one row per trace carrying the total length, segment count, mean, smallest and largest segment, the span and the sinuosity, alongside the trace's overall azimuth and plunge.
  - Added a separate `Trace Histogram` with its own auto-update toggle, matching the ones the edge histogram and the stereonet have. A trace length is a sum of segments and an edge length a straight distance, so one distribution cannot hold both. `Statistics` reports trace lengths in their own block for the same reason. Only one real-time chart runs at a time; the mutual exclusion is one helper rather than a pair of cross-references, because with three toggles the old pattern would have needed six.

### Changed

- The `Light` button is now `Rock Inspection`, and it does what its name says. It switches every 3D view to Rendered shading and lights the model for reading structure rather than for looking pretty: a sun grazing the surface at 22 degrees, which throws every fracture, groove and step into shadow where a light near the camera flattens them; near-parallel rays so a hairline fracture still casts something to see; no specular contribution at all, because a highlight on wet or polished rock hides exactly the texture being read; matte materials; and ambient light dropped to 0.12, so the contrast the sun buys is not filled straight back in. Eevee shadows and short-range indirect light are switched on so a crevice darkens instead of filling uniformly, and a higher-contrast colour management look is used when the configuration offers one.
- Pressing it again restores the viewport shading, world, material, camera, colour management look and render settings, and deletes the light it added along with its datablock, so repeated toggles accumulate nothing. The button reads `Restore View` and shows as depressed while the mode is on.

- Reordered the sidebar by how often each part is used. The chart buttons and the measurement work stay at the top; `Chart Appearance` follows, then `Export`, `Statistics` and `Azimuth Correction`, which are opened once a session rather than continuously. Inside `Chart Appearance` the stereonet controls come first - hemisphere, density sigma, pole size - because those are adjusted while reading a plot, and the image size and update interval moved below them.
- Replaced the icons on the measurement kind toggles. `Linear` used the edge-split modifier icon and `Planes` the face-snapping icon, neither of which depicts what it switched; they are now a dimension between two points and a flat quad, with a zigzag polyline for traces. The three come from one place in `scene_measurements.py`, so the tool header and the sidebar cannot drift apart.
- Every collapsible sidebar section now carries an icon next to its disclosure triangle, so a collapsed panel is still scannable, and the export and statistics rows are labelled by kind rather than by file format alone.
- The three tools no longer each draw their own copy of the tool header settings, which is how they came to offer different toggles.

## [Unreleased]

### Changed

- The viewport overlay is roughly 9x faster at 500 measurements and 28x at 2000, and its cost no longer grows with the size of the scene. Measured with the GPU and font calls stubbed out, best of five redraws: 500 measurements went from 163 ms to 18 ms, 2000 from 644 ms to 23 ms, and 10000 - which the old overlay could not complete inside a two minute benchmark - now draws in 31 ms. The number of draw calls per redraw fell from 21823 to 9 at 2000 measurements.
  - The 3D overlay is built once and reused. Its geometry is in world space, so orbiting, panning and zooming leave every vertex where it was; it used to be rebuilt every frame, tessellating each polygon and generating each angle arc again. It is now keyed on a revision the measurement helpers bump, plus the style values it depends on, and cleared on file load, undo and redo.
  - Point handles are gathered by colour and size and drawn as a handful of merged batches. Each handle used to issue three or four `batch_for_shader` calls, each allocating and uploading its own vertex buffer, which is what made a dense scene stall.
  - Handle geometry and the projection from world to screen are vectorised with numpy, which Blender bundles. The pure Python path remains as a fallback, and a GPU that refuses an array downgrades to it for the session with a warning rather than losing the overlay.
  - Measurements are culled against the viewport and ordered by distance to the middle of the view, so off-screen ones cost nothing.
  - Two budgets under `Overlay Style > Viewport Budget` cap the per-redraw cost of the screen-space work: `Handle Points` (2000) and `Labels` (200). What gets dropped is whatever is furthest from where you are looking; the active and hovered measurement are never dropped. Past those counts nothing on screen is legible anyway.
  - Smaller wins along the way: the angle arc no longer builds a rotation matrix per segment, the code colour and visibility lookups no longer scan the code collection once per measurement, point coordinates are read with `foreach_get` in one C call, the label plate's corner arcs are computed once per redraw instead of once per label, and label text is read once for both the handle and the label pass.
- `ANGLE_ARC_SEGMENTS` dropped from 32 to 16 and the handle circles from 20 and 28 segments to 12. At the size these are drawn the difference is not visible; the arc rewrite agrees with the rotation-matrix version it replaced to within 2.3e-07.

### Removed

- Removed the `All Handles` scene property. `All Points` and the handle budget decide this now.

## [Unreleased]

### Added

- Added viewport overlay style settings, grouped under `Overlay Style` in `Measurement Display`, directly after `Label Fields`:
  - `Line Width` sets the thickness of measurement lines. The outlines around the point handles scale with it, so the whole overlay thickens together instead of the lines pulling away from the handles.
  - `Label at Area Center` puts the label of a plane or polygon measurement in the middle of its surface instead of on the corner point the measurement hinges on, where the text landed beside the shape it describes rather than on it. The centre is area-weighted over the same triangles the fill is drawn from, so it agrees with what is shaded and does not drift towards whichever side of a traced outline carries the most points. Switch it off to get the corner back; that corner is also where the angle a plane label can report is measured.
  - `Label Size` sets the text size of the measurement labels. The line spacing, the padding around the text and the corner rounding are all relative to it, so a label keeps its proportions at any size.
  - `All Points` draws a handle on every point of every measurement. Switched off, only the active and hovered measurement keep theirs, which is quicker to draw and less cluttered on a dense scene; a measurement stays editable either way, because a point you cannot see is a point you cannot grab.
  - `Size` sets the handle diameter. The active and hovered handles stay proportionally larger, and the default reproduces the sizes the overlay used before the setting existed.
  - `Fill` shades plane and polygon measurements with a translucent surface in the measurement's own colour, so an area reads as a surface rather than an outline, with `Opacity` controlling how much shows through. Concave polygons are tessellated rather than fanned, so the fill of a traced fracture boundary stays inside it. Linear measurements enclose nothing and are never filled.

- Added `--png` to `tools/build_tool_icons.py`, writing each toolbar icon as a standalone PNG with a transparent background, for slides and documents. The `.dat` files the add-on ships are triangle lists no other program reads. The export is supersampled, and the edge pixels take their colour only from the covered samples, so the artwork does not get the dark fringe that averaging in the transparent ones produces on a light slide.

### Changed

- Point handles are now round dots instead of squares. The middle point of a three-point plane keeps a mark that tells it from an endpoint, and the mark takes black or white by the contrast against the handle underneath, which the previous fixed white cross lost against a light one.
- `Point Size` is now honoured as a diameter everywhere. The middle point of a three-point plane was drawn from the same number as a radius, which made it twice the size it asked for.
- Removed the separate `All Handles` toggle. It decided the same thing as `All Points` from another part of the panel, so turning point handles on appeared to do nothing until the second toggle was found as well.
- Measurement labels are now centred on the measurement they name. They used to hang off it by one corner, which put a label for a point at the top left of that point and made a dense scene hard to read. Each line is centred within the label as well.
- The label background is now a rounded plate instead of a square one.

### Fixed

- Fixed the diagnostics report calling a current `mplstereonet` outdated. The package version was read from the module's `__version__`, which 0.6.3 still leaves at `0.6-dev`; the distribution metadata, which records what was actually installed, is now asked first.

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
