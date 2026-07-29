# Custom measurement tool

## Что делает стандартный Blender Measure/Ruler

Стандартный tool подключается из Python UI как workspace tool `builtin.measure`, но интерактивная часть реализована в C++ gizmo group.

Локальные точки входа Blender 5.1:

- `scripts/startup/bl_ui/space_toolsystem_toolbar.py`
  - `idname="builtin.measure"`
  - `widget="VIEW3D_GGT_ruler"`
  - `keymap="3D View Tool: Measure"`
- `scripts/presets/keyconfig/keymap_data/blender_default.py`
  - `view3d.ruler_add`
  - `view3d.ruler_remove`

Исходник Blender:

- `source/blender/editors/space_view3d/view3d_gizmo_ruler.cc`

Ключевые выводы из `view3d_gizmo_ruler.cc`:

- Runtime state хранится в `RulerInfo`/`RulerItem` внутри `wmGizmoGroup`, а не в Python.
- `RulerItem` хранит `float3x3 co`: line uses points `co[0]` and `co[2]`; angle/protractor uses `co[0]`, `co[1]`, `co[2]`.
- Drag anywhere creates a 2-point ruler.
- Drag ruler segment adds/moves center point and turns measurement into angle mode (`RULERITEM_USE_ANGLE`).
- Snap is handled through Blender transform snap API (`ED_gizmotypes_snap_3d_*`, `snap_object_project_view3d`, `snap_object_project_ray`).
- `Ctrl while dragging` enables snapping in the Measure tool keymap/help.
- `Shift while dragging` enables surface thickness behavior.
- Persistence happens by converting gizmo data to legacy Grease Pencil annotation layer `RulerData3D`.
- `view3d_ruler_to_gpencil()` writes all ruler items to `RulerData3D`; `view3d_ruler_from_gpencil()` restores them.

Практический вывод: exact performance and snapping parity с Blender Measure недостижимы в чистом Python без C++ gizmo/snap API. Python addon должен:

- не писать persistent data on every mousemove;
- использовать `draw_handler_add()` только для легкого preview;
- делать `scene.ray_cast()` only on mouse events, not draw;
- store final measurements in `.blend` through `bpy.types.Scene` properties or Blender annotation data.

## Почему C++ код Blender не встроен в текущий addon

Полная parity со стандартным Measure tool потребует C++-интеграции, потому что ключевые части стандартного инструмента используют internal Blender editor API:

- `wmGizmoGroup`, `wmGizmo`, `WM_gizmotype_find()`
- `ED_gizmotypes_snap_3d_*`
- `ed::transform::snap_object_project_view3d()`
- `ed::transform::snap_object_project_ray()`
- `ED_view3d_project_float_global()`
- legacy Grease Pencil ruler flags such as `GP_LAYER_IS_RULER`

Эти функции не являются стабильным Python API и не доступны обычному addon как импортируемый модуль. Реальные варианты C++-пути:

1. Patch/fork Blender: добавить `ScientiaJoints` tool в сам Blender рядом с `VIEW3D_GGT_ruler`.
2. Binary extension: собрать нативный модуль под конкретную версию Blender/Python/платформу. Это усложняет установку, требует toolchain, CI builds и контроля ABI.
3. Upstream contribution/patch: перенести нужные hooks в публичный Python/C API Blender, затем использовать их из addon.

Поэтому текущий этап оставляет C++ как roadmap item, а в addon реализует Python fallback. Он не может полностью повторить стандартный snap cursor/type feedback, но должен быть безопасно устанавливаемым и сохранять текущий export/visualization pipeline.

## Реализация Scientia custom tool

Файлы:

- `scene_measurements.py`
  - `ScientiaMeasurementPoint`
  - `ScientiaMeasurement`
  - `ScientiaMeasurementLayer`
  - helpers: `add_scene_measurement()`, `set_scene_measurement_points()`, `delete_active_scene_measurement()`
- `custom_measure_tool.py`
  - `ScientiaMeasureWorkSpaceTool`
  - `ScientiaMeasureDragOperator`
  - `ScientiaDeleteActiveMeasurementOperator`
  - `tool_icon()` - `bl_icon` для обоих tools. Blender резолвит `bl_icon` как `os.path.join(<blender datafiles>/icons, bl_icon + ".dat")`, а `os.path.join` отбрасывает первый аргумент при абсолютном втором, поэтому аддон отдает абсолютный путь в свой `icons/`. Если файла нет - fallback на `ops.view3d.ruler`. Артворк генерируется `tools/build_tool_icons.py`.
- `infrastructure/blender_scene_measurements.py`
  - `SceneMeasurementSource`
  - `CompositeMeasurementSource`

Scene storage:

- `bpy.types.Scene.scientia_measurements`
- `bpy.types.Scene.scientia_measurement_layers`
- `bpy.types.Scene.scientia_measurement_codes`
- `bpy.types.Scene.scientia_active_measurement_index`
- `bpy.types.Scene.scientia_active_measurement_layer_index`
- `bpy.types.Scene.scientia_measure_show_labels`
- `bpy.types.Scene.scientia_measure_label_background`
- `bpy.types.Scene.scientia_measure_reuse_last_code`
- `bpy.types.Scene.scientia_measure_snap_by_default`
- `bpy.types.Scene.scientia_measure_show_all_handles`
- `bpy.types.Scene.scientia_measure_no_code_visible`
- `bpy.types.Scene.scientia_measure_default_color`
- `bpy.types.Scene.scientia_measure_active_color`
- `bpy.types.Scene.scientia_label_show_code`
- `bpy.types.Scene.scientia_label_show_name`
- `bpy.types.Scene.scientia_label_show_description`
- `bpy.types.Scene.scientia_label_linear_*`
- `bpy.types.Scene.scientia_label_plane_*`

Measurement metadata:

- `ScientiaMeasurement.code` - fracture code assigned to one measurement.
- `ScientiaMeasurement.description` - free text description.
- `ScientiaMeasurement.properties_json` - JSON object for additional attributes; exported as `attributes_json`.
- `ScientiaMeasurementCode.name/color/visible` - code registry used for color and visibility.
- Measurements with empty `code` belong to the implicit `No code` group. Its visibility is `scientia_measure_no_code_visible`; its color is `scientia_measure_default_color`.
- If `scientia_measure_reuse_last_code` is enabled, `add_scene_measurement()` copies code from the previously active measurement.
- `sync_scene_measurement_codes()` keeps `scientia_measurement_codes` derived from existing measurements: unused codes are removed, missing used codes are added, existing color/visibility settings are preserved.

Эти properties сохраняются в `.blend`, потому что они зарегистрированы как Blender RNA `Scene` properties.

## Interaction model

Toolbar tools:

- `scientiajoints.measure`
- `scientiajoints.polygon_measure`

Gesture operators:

- `wm.scientia_measure_drag`
- `wm.scientia_polygon_measure`

Current behavior:

- The tool is registered in the left View3D toolbar through `bpy.utils.register_tool()`.
- Current registration target is `bl_context_mode='OBJECT'`, placed after Blender `builtin.measure`.
- To match Blender Measure across `EDIT_MESH`, `POSE`, curve modes, etc., add separate `WorkSpaceTool` registrations per Blender toolbar context or move to the C++ path.
- Left drag in viewport creates a 2-point `LINEAR` measurement.
- `Scientia Polygon Plane` is registered as a separate toolbar tool after `Scientia Measure`.
- `Scientia Polygon Plane` creates a `POLYLINE` measurement by clicking boundary points around a fracture; click the first point, press Enter, or press Space to finish. Backspace removes the last point.
- `POLYLINE` measurements are stored in scene data but processed/exported/visualized as planes through best-fit geometry.
- Snapping uses `context.scene.ray_cast()` from mouse ray to visible scene geometry.
- `scientia_measure_snap_by_default=False`: `Ctrl` enables snapping during drag.
- `scientia_measure_snap_by_default=True`: snapping is always on and `Ctrl` temporarily disables it.
- `Ctrl + left drag` is explicitly bound in `bl_keymap`, because Blender may otherwise route Ctrl-start differently.
- Without `Ctrl`, mouse is projected at depth of the first point/current edit point via `bpy_extras.view3d_utils.region_2d_to_location_3d()`.
- Dragging an existing point edits that point.
- Dragging an existing 2-point segment creates a center point and converts it into a 3-point `PLANE` measurement.
- In `Scientia Polygon Plane`, clicking an inactive measurement first activates it. Dragging a point of the active measurement edits that point with the same snapping behavior.
- Clicking an inactive measurement only activates it. Editing points/segments requires a second drag after the measurement is active.
- `X`/`Del` deletes active Scientia measurement while the toolbar tool is active.
- The operator is modal only during one drag gesture, so sidebar buttons and other plugin controls are not blocked after mouse release.
- Final data is written only on mouse release. During drag, only in-memory preview is drawn.

Overlay:

- `ensure_measure_overlay()` registers permanent View3D draw handlers while the addon is enabled.
- `remove_measure_overlay()` removes them on `unregister()`.
- Measurements remain visible after the drag operator finishes or after pressing `Esc`.
- Lines and angle arcs are drawn in `POST_VIEW`.
- Draggable point handles are drawn in `POST_PIXEL`, not as 3D GPU points, so endpoints and center points stay readable on top of object surfaces.
- Endpoint handles are square; the center point of a 3-point angle is circular with a small cross. Active/preview/hovered handles are larger and brighter.
- For performance, point handles are drawn for active/hovered measurements by default. `scientia_measure_show_all_handles=True` restores all point handles, but this is expensive on large datasets.
- Snapped preview uses green color.
- Snap target marker shape indicates best-effort snap type:
  - `FACE`: circle;
  - `EDGE`: hourglass;
  - `VERTEX`: square.
- Snap type is classified in Python from `context.scene.ray_cast()` hit polygon by checking nearby projected vertices and edges. This is not exact parity with Blender's internal transform snap stack, but it gives useful visual feedback without native code.
- Three-point measurements draw an angle arc between the two rays.
- `POLYLINE` measurements draw a closed boundary polygon, not a 3-point angle arc.
- Two-point labels show distance by default. Optional label fields can add code, name, description, angle/dip, corrected/raw azimuth, `dx`, `dy`, `dz`, and horizontal distance.
- Three-point and `POLYLINE` labels show `dip` and corrected `azimuth` by default. Optional label fields can add code, name, description, raw azimuth, point angle for 3-point planes, and area.
- Label values are computed through the same `domain.geometry.process_linear_measurement()` and `domain.geometry.process_plane_measurement()` pipeline as export.
- Label backgrounds are controlled by `scientia_measure_label_background`.

Color/visibility:

- Active measurement color comes from `scene.scientia_measure_active_color`.
- Measurements with `code` use `ScientiaMeasurementCode.color`.
- Measurements without `code` use the implicit `No code` group color from `scene.scientia_measure_default_color`; this applies to old uncoded measurements too, not only new measurements.
- `ScientiaMeasurementCode.visible=False` hides matching measurements from 3D overlay, hit-testing, parser/export, and stereonet input.
- `scene.scientia_measure_no_code_visible=False` does the same for uncoded measurements.
- Per-measurement `ScientiaMeasurement.visible` is no longer exposed in UI and is not used for filtering custom measurements; visibility should be controlled by code groups or `No code`.
- `measurement_custom_properties()` writes `display_color`; `parser.FaceView.color` carries it into `visualization.Visualizer.plot_faces_stereonet()`.

Performance notes:

- 3D measurement lines/arcs are batched by color before GPU draw, instead of creating one batch per measurement.
- 3D duplicate point handles are not drawn; screen-space handles in `POST_PIXEL` are the interactive handles.
- `select` mode does not raycast on mouse move, so clicking inactive measurements does not perform unnecessary snap work.

## Parser integration

`parser._create_default_service()` now uses:

```python
CompositeMeasurementSource((
    SceneMeasurementSource(),
    BlenderAnnotationSource("RulerData3D"),
))
```

That means:

- existing standard Blender `RulerData3D` measurements still work;
- new `ScientiaScene` measurements are parsed/exported/visualized by the same application pipeline;
- `ScientiaMeasurement.kind == POLYLINE` is passed to the application layer as a plane `kind_hint`, so 4+ scene points are accepted as faces while legacy 4+ `RulerData3D` strokes remain unsupported;
- coordinate deduplication in `MeasurementApplicationService.ingest_measurements()` protects against duplicates across both sources.

## Extension points

Already prepared but not fully exposed in UI:

- `ScientiaMeasurement.layer`
- `ScientiaMeasurement.color`
- `ScientiaMeasurement.properties_json`

Recommended next steps:

1. Add a measurement list UI with active selection, visibility and color controls.
2. Add layer UI: create/rename/delete/toggle layer, set active layer.
3. Add optional support for separate boundary points vs interior fitting points if geological workflow requires both.
4. If Python interaction becomes too slow for large scenes, cache evaluated mesh BVHs during drag and invalidate on depsgraph update.
5. For exact Blender Measure behavior, implement a C++ path based on `VIEW3D_GGT_ruler`/transform snap internals or wait for public API hooks.
