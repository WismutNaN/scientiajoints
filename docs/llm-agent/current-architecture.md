# Текущая архитектура

## Регистрация и UI

`__init__.py` - entrypoint Blender addon.

- `bl_info` задает имя, версию, target Blender и категорию. Версия там - копия: единственный источник - `version` в `blender_manifest.toml`, меняется командой `python tools/version.py <version>`, которая пишет оба файла. Blender читает `bl_info` через `ast.literal_eval` до импорта аддона, поэтому кортеж обязан оставаться литералом. `tools/build_release.py` падает, если копии разошлись.
- `register()` вызывает `install_packages()`, регистрирует `LightSettings`, добавляет `bpy.types.Scene.*` properties и регистрирует classes из `operators.py` и `panel.py`.
- Если `register()` падает на импорте или регистрации класса, он пишет traceback в Blender console/log, вызывает `_cleanup_partial_registration()` и пробрасывает ошибку наружу.
- `unregister()` удаляет properties и unregister classes через safe helpers, поэтому частичная регистрация не оставляет dangling Scene properties.
- `update_real_time_update_histogram()` и `update_real_time_update_stereonet()` взаимно выключают realtime режимы и запускают modal operators.

`panel.py` рисует `MeasurementExporterPanel`.

- Верхняя строка: `wm.show_histogram_image`, `wm.show_stereonet_image`, realtime toggles.
- `Measurement Info`: активное измерение, удаление, `Code` picker/text input, `Name`, `Description` и компактные вычисленные значения.
- `Measurement Display`: labels/background, optional label fields, reuse code, snap mode, handle visibility, active color, `No code` и fracture code colors/visibility.
- `Azimuth Correction`: ввод `az_real` и `az_model`.
- `Export`: raw/processed export buttons.
- `Statistics`: создает `MeasurementsParser`, считает edges/faces count и edge length statistics.
- `Chart Appearance`: figure size, marker style, density sigma, hemisphere, light preset toggle.

## Blender operators

`operators.py` содержит adapter слой между UI и application behavior.

- Startup diagnostics:
  - `run_startup_diagnostics()` вызывается один раз из `register()`.
  - Полная информация пишется в Blender console/log: dependency status, `.blend` save status, `RulerData3D`, counts, skipped duplicates, ignored strokes.
- Export operators:
  - `ExportRawEdgesOperator` -> `MeasurementsParser.export_raw_edges()`.
  - `ExportRawFacesOperator` -> `MeasurementsParser.export_raw_faces()`.
  - `ExportProcessedEdgesOperator` -> `MeasurementsParser.process_edges()`.
  - `ExportProcessedFacesOperator` -> `MeasurementsParser.process_faces()`.
- Visualization operators:
  - `ShowHistogramImageOperator` -> `update_histogram_image()`.
  - `ShowStereonetImageOperator` -> `update_stereonet_image()`.
  - realtime modal operators вызывают update функции по timer.
- Scene settings operators:
  - `ToggleLightSettingsOperator` временно меняет render/world/material/camera настройки.

Export operators теперь используют `ExportResult`, поэтому Blender reports не показывают success при unsaved `.blend` или ошибке записи файла.
Visualization operators используют boolean return из update functions и возвращают `CANCELLED`, если PNG не был создан.

## DDD layers

`domain/` - pure Python domain layer.

- `domain.measurements` содержит `Point3D`, `MeasurementKind`, `RawMeasurement`, `MeasurementRecord`, `MeasurementSet`, `ParseDiagnostics`, `MeasurementProperties`, `MeasurementLayer`, `AzimuthCorrection`.
- `domain.geometry` содержит чистые расчеты orientation/length/area/degree, включая best-fit plane для 4+ point `POLYLINE`, и строит `MeasurementRecord`.
- В этом слое нет `bpy`, `mathutils`, matplotlib, файловой системы и Blender UI.

`application/` - use-case/application layer.

- `MeasurementApplicationService.ingest_measurements()` читает `MeasurementSource`, классифицирует 2-точечные, 3-точечные и hinted multi-point plane measurements, делает coordinate deduplication и возвращает `MeasurementSet`.
- `process_edges()` и `process_faces()` применяют `AzimuthCorrection` и возвращают processed `MeasurementRecord`.
- Export methods принимают writers как ports и возвращают `ExportResult`.

`infrastructure/` - adapters.

- `BlenderAnnotationSource` ищет `RulerData3D` в `bpy.data.annotations`, `bpy.data.grease_pencils` и scene fallback.
- `iter_layer_strokes()` поддерживает `frame.strokes`, `frame.drawing.strokes`, direct `layer.strokes` и direct `layer.drawing.strokes`.
- `RawEdgeTxtWriter`, `RawFaceTxtWriter`, `ProcessedEdgeCsvWriter`, `ProcessedFaceCsvWriter` пишут geometry plus metadata (`layer`, `name`, `code`, `description`, `attributes_json`). `RawFaceTxtWriter` дополнительно сохраняет `point_count` и `points_json` для multi-point polygon faces.

`parser.py` теперь compatibility facade.

- Сохраняет старые поля `faces`/`edges` как списки `Point3D`-like объектов.
- Сохраняет `get_processed_edges()` и `get_processed_faces()` как `EdgeView`/`FaceView` objects со старым набором attributes для UI/visualization.
- Внутри использует `MeasurementApplicationService`, `BlenderAnnotationSource` и writers.
- Re-export старых helper names сохранен для тестов/скриптов: `_iter_annotation_datablocks`, `find_annotation_layer`, `_iter_layer_strokes`, `_stroke_points`.

Legacy compatibility objects are now generated inside `parser.py`.

- `EdgeView` и `FaceView` дают старые attributes (`length`, `dip`, `rotated_azimuth`, etc.) для `visualization.py` и UI.
- `EdgeView` и `FaceView` также несут metadata (`layer`, `name`, `code`, `description`, `color`), где `color` берется из `MeasurementProperties.display_color`.
- Отдельный корневой `geometry.py` удален, чтобы не было двух источников геометрической истины.
- Все расчеты живут в `domain.geometry`.

## Visualization

`visualization.py` смешивает application data и UI output.

- `Visualizer.get_edges_statistics()` считает mean/median/std/min/max через `numpy`.
- `plot_edges_histogram()` пишет `edges_histogram.png` во временную папку.
- `plot_faces_stereonet()` пишет `faces_stereonet.png` во временную папку через `mplstereonet`; если density contours не строятся на малом наборе, poles все равно сохраняются.
- Poles на stereonet группируются по `FaceView.color`, чтобы fracture code colors совпадали с 3D overlay.
- `update_histogram_image()` и `update_stereonet_image()` каждый раз создают `MeasurementsParser`, строят processed данные, открывают PNG в Image Editor и возвращают `True/False`.

## Основные границы риска

- Blender API annotations/grease pencil менялся между версиями; parser должен оставаться defensive.
- `install_packages()` автоматически ставит отсутствующие chart dependencies во время `register()`. Если все уже установлено, pip не запускается; результат и startup diagnostics пишутся в Blender console/log.
- Визуализация и UI сейчас напрямую создают `MeasurementsParser`, поэтому нет единого application service.
- Геологическая семантика азимута/падения должна проверяться на реальных сценах, не только на synthetic unit tests.
