<p align="center">
  <img src="docs/logo.png" alt="ScientiaJoints" width="140">
</p>

<h1 align="center">ScientiaJoints</h1>

<p align="center">
  A Blender add-on for measuring rock mass fracturing on a three-dimensional
  model of an outcrop.
</p>

<p align="center"><a href="README.ru.md">Русская версия</a></p>

![Example](screen.png)

## Task

The input is a polygonal model of an outcrop produced by photogrammetry or laser
scanning. The add-on takes fracture measurements from it, computes the
orientation and the metric quantities of each measurement, builds distributions
and exports the result to CSV.

The model has to be oriented. Any offset from true north is entered as an
azimuth correction and applied to the results (workflow, step 4).

The add-on supports the following measurements:

- dip azimuth and dip angle of a fracture plane;
- spacing between fractures of one set;
- fracture length along the surface;
- area of the outline in the plane of the measurement;
- grouping of measurements into sets through codes and pole density on the
  stereonet.

## Measurement types and computed quantities

| Type | Points | Computed |
|---|---|---|
| `LINEAR` | 2 | Distance between the points. Azimuth and plunge of the line, azimuth and dip of the plane perpendicular to it, corrected azimuth. Increments `dx`, `dy`, `dz` and the horizontal projection. |
| `PLANE` | 3 | Dip azimuth, dip angle, corrected azimuth. Triangle area. Angle at the middle point. A degeneracy flag when the points are collinear or coincident. |
| `POLYLINE` | 3 or more, outline closed | As `PLANE`, with the plane fitted to every point by least squares. Additionally the RMS distance of the points from the fitted plane, absolute and relative. |
| `TRACE` | 2 or more, outline open | Sum of the segment lengths. Segment count, mean, smallest and largest segment length. Straight distance between the ends and the ratio of the sum to it. Azimuth and plunge of the line between the ends. |

The azimuth correction applies to the azimuths of every type. The uncorrected
azimuth is kept and exported in a separate column.

## Tools

The three tools sit in the 3D View toolbar after Blender's own ruler.

| Icon | Tool | Action |
|---|---|---|
| ![](docs/icons/scientiajoints.measure.png) | Scientia Measure | Dragging empty space creates a `LINEAR` measurement. Dragging the middle of a segment adds a third point and turns the measurement into `PLANE`. Dragging a point moves it. |
| ![](docs/icons/scientiajoints.polygon_measure.png) | Scientia Polygon Plane | Clicks place the points of a closed outline; the measurement is stored as `POLYLINE`. Three points minimum. |
| ![](docs/icons/scientiajoints.trace_measure.png) | Scientia Trace | Clicks place the points of an open polyline; the measurement is stored as `TRACE`. Two points minimum. |

The polygon and the trace share their controls. `RMB`, `Enter` or `Space`
finishes the measurement. `Backspace`, `X` or `Del` removes the last point.
`Esc` cancels. The polygon also closes on a click on its first point. The trace
does not close.

In all three tools `Ctrl` toggles snapping to visible geometry. The default
snapping state is set in the tool header.

## Measurement sources

The add-on reads measurements from two sources: its own tools, which store
measurements in `.blend` scene properties, and the annotations of Blender's
ruler from the `RulerData3D` layer. Measurements from both sources are processed
the same way.

Exact duplicates are merged. Measurements whose coordinates agree to three
decimal places are both kept and reported in the diagnostics. For a model in
metres that is one millimetre. Only the operator can tell an accidental copy
from two fractures that are genuinely close.

## Installation

Two archives are published for every version. They install `matplotlib` and
`mplstereonet` in different ways.

### Extension

`ScientiaJoints-<version>-extension.zip` carries the wheels inside the archive.
Blender unpacks them itself, with no pip run, no package index and no network.
The installation path is short.

1. Download the extension ZIP. A GitHub `Source code` archive is not an
   installable package.
2. Drag the ZIP into Blender, or use
   `Edit > Preferences > Get Extensions > Install from Disk`.

### Legacy add-on

`ScientiaJoints-<version>.zip` installs through
`Edit > Preferences > Add-ons > Install from Disk`. The add-on installs the
chart packages itself: first from the bundled wheels, and from PyPI if that
fails. The installation runs on a worker thread and does not block Blender.
Progress and the result appear in the add-on panel. A failed automatic attempt
is repeated no more than once a day. The `SCIENTIAJOINTS_NO_AUTO_INSTALL`
environment variable disables the automatic attempt.

The archive always contains `ScientiaJoints/__init__.py`. Blender requires that
directory name, and it does not depend on the name of the ZIP itself. An archive
whose root directory is named differently cannot be installed.

The minimum Blender version is 5.0.0. `mplstereonet` 0.6.3 or newer is required.
0.6.2 and earlier use `np.float`, removed in numpy 1.24, which stops the density
contours on the stereonet from being drawn.

### If the charts do not appear

The `i` icon in the panel header opens the diagnostics report. The report names
the cause and the action. The observed causes:

- the packages are not installed; the panel shows which are missing and offers
  the install button;
- the 260 character path limit on Windows. `matplotlib` reads its data files at
  import time. Past that limit the files exist but cannot be opened, and the
  import fails with `FileNotFoundError`. The report shows how many characters
  each install directory has left;
- a second copy of numpy beside the one Blender ships causes binary
  incompatibility errors in `matplotlib`;
- a network that blocks or inspects HTTPS. The report distinguishes a certificate
  failure, a proxy rejection, a timeout and an unreachable index.

The first three causes do not apply to the extension archive. The packages are
inside it, the installation path is short, and numpy is not installed into
Blender's interpreter.

## Workflow

1. Load the outcrop model.
2. Mark the fractures with the toolbar tools.
3. Assign codes to the measurements in `Measurement Info`. A code gets a colour
   and a visibility toggle, which allows one fracture set to be displayed at a
   time.
4. Enter the azimuth correction in `Azimuth Correction` if the model is rotated
   relative to true north. `Real` is the true azimuth of a reference direction,
   `Model` is the azimuth of the same reference in the model.
5. Open the charts with the buttons at the top of the panel: a histogram of edge
   lengths, a stereonet of pole density, a histogram of trace lengths. Each
   button has an auto-update toggle next to it. One runs at a time.
6. Export the result in `Export`. The CSV holds the computed quantities, the TXT
   the source coordinates. The `.blend` file has to be saved: the export path is
   built relative to it.

Trace lengths go to a separate histogram. A trace length is the sum of the
segment lengths, an edge length is the distance between two points. These are
different quantities, and one distribution does not describe both.

### Model display

`Chart Appearance > Blender View > Rock Inspection` puts every 3D view into
Rendered shading and sets the lighting: a directional source at 22 degrees
elevation, 0.5 degrees angular size and zero specular contribution, a matte
material, and background strength 1.5. The directional source produces shadows
in fractures and steps; the background sets the overall surface brightness.

Pressing it again restores the shading, background, material, camera, colour
management and render settings, and removes the source it added.

Note. The material parameters are applied to the material named `material0`. The
materials of the scene objects are not changed.

## Performance

Measured on a synthetic scene with the GPU and `blf` calls stubbed out, best of
five redraws:

| Measurements | Redraw time | Draw calls |
|---|---|---|
| 500 | 18 ms | 9 |
| 2000 | 23 ms | 9 |
| 10000 | 31 ms | 9 |

Before the optimisation 500 measurements took 163 ms in 5452 draw calls, and
2000 took 644 ms in 21823 draw calls. A scene of 10000 measurements did not
complete inside the two minute test limit.

The geometry of the three-dimensional pass is built in world space and cached.
Orbiting and panning do not recompute it. The screen-space elements, the point
handles and the labels, are rebuilt every frame. Their count is capped by
`Overlay Style > Viewport Budget`: 2000 handles and 200 labels by default. The
ones nearest the middle of the view are drawn, along with the active measurement
and the one under the cursor.

## Building a release

Python 3.10 or newer and a complete repository checkout are required. Blender is
needed only to validate the built archive.

1. Set the version:

   ```powershell
   python tools\version.py 3.4.2
   ```

   The version is stored in `blender_manifest.toml`. Blender reads `bl_info`
   from `__init__.py` with `ast.literal_eval` before the add-on is imported, so
   that copy cannot be computed. The command writes both files.
   `tools\build_release.py` refuses to package a checkout whose values have
   diverged. With no argument the command prints the current version.

2. Add an entry to `CHANGELOG.md`.

3. Download the wheels. Run this with the Blender interpreter so the tags match
   the target version:

   ```powershell
   & 'E:\SteamLibrary\steamapps\common\Blender\5.2\python\bin\python.exe' tools\fetch_wheels.py --platform win_amd64 --python-version 3.13
   ```

   `--all-platforms` collects the set for Windows, Linux and macOS. The `wheels/`
   directory is not committed and is rebuilt for each release.

4. Run the tests from the repository root:

   ```powershell
   python -m unittest discover -s tests -v
   ```

5. Build the archives:

   ```powershell
   python tools\build_release.py
   ```

   The command writes `dist/ScientiaJoints-<version>.zip` and
   `dist/ScientiaJoints-<version>-extension.zip`, checks the package structure,
   the Python syntax, the presence of the required symbols in the modules and
   the agreement between the manifest and the bundled wheels, and prints
   SHA-256. `--format legacy` and `--format extension` build one archive.

6. Validate the extension archive with Blender:

   ```powershell
   & 'E:\SteamLibrary\steamapps\common\Blender\blender.exe' --command extension validate "dist\ScientiaJoints-$(python tools\version.py)-extension.zip"
   ```

7. Install both archives into a clean profile. `BLENDER_USER_RESOURCES` has to
   point at an empty directory with a short path.

The legacy archive contains the numpy wheel. `pip --target` resolves
dependencies without regard to the packages already installed, and without that
wheel an offline installation fails. The extension archive does not contain
numpy: Blender ships its own, and a second copy causes binary incompatibility
errors.

### Artwork

Blender loads the tool icons from `icons/*.dat`. The format holds a list of
triangles on a 255×255 canvas rather than a raster image. The artwork is defined
as vectors in `tools/build_tool_icons.py`:

```powershell
python tools\build_tool_icons.py --preview preview.png
python tools\build_tool_icons.py --png --png-size 1024
python tools\build_logo.py --size 512
```

The `.dat` files are committed and a normal build does not regenerate them. The
script has to be run after a change to the drawing code. `--png` writes PNGs
with a transparent background, and `tools/build_logo.py` writes the add-on logo.
`tests/test_tool_icons.py` checks that the committed `.dat` files match the
generator output, that the format is valid, and that the tools do not use
Blender's built-in ruler icon instead of their own.

## Development checks

```powershell
python -m unittest discover -s tests -v
```

Registration check in Blender:

```powershell
& 'E:\SteamLibrary\steamapps\common\Blender\blender.exe' --background --factory-startup --python-expr "import addon_utils, bpy; addon_utils.enable('ScientiaJoints', default_set=False, persistent=False); assert hasattr(bpy.ops.export, 'raw_edges'); print('SMOKE_OK')"
```

## Documents

- [CHANGELOG.md](CHANGELOG.md) — changes by version.
- [docs/llm-agent/](docs/llm-agent/) — architecture, defect analysis, and a
  description of the measurement processing pipeline.
- [README.ru.md](README.ru.md) — Russian version.

## License

`blender_manifest.toml` declares GPL-3.0-or-later. There is no `LICENSE` file in
the repository.

The Blender Foundation's position is that an add-on using the Blender Python API
is a derivative work of Blender and requires a GPL-compatible license. The
extensions.blender.org platform accepts only such licenses for code. A license
that forbids modification is not compatible with the GPL.
