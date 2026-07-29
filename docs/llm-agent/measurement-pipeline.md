# Pipeline измерений

## 1. Источник данных

Пользователь может делать измерения стандартным Blender Measure/Ruler tool, `ScientiaMeasureWorkSpaceTool` или `ScientiaPolygonMeasureWorkSpaceTool`.

`SceneMeasurementSource` читает measurements, сохраненные в `bpy.types.Scene.scientia_measurements`.

- `ScientiaMeasurement.code` и `description` попадают в `MeasurementProperties`.
- `ScientiaMeasurement.properties_json` используется для дополнительных attributes.
- `ScientiaMeasurementCode.color` записывается как `display_color`.
- `ScientiaMeasurementCode.visible == False` исключает такие measurements из parser/export/visualization.
- Measurements без `code` считаются группой `No code`: цвет берется из `scene.scientia_measure_default_color`, видимость из `scene.scientia_measure_no_code_visible`.
- `ScientiaMeasurement.kind == "POLYLINE"` передается в application layer как `MeasurementKind.PLANE` через `StrokeInput.kind_hint`, если points >= 3.

`BlenderAnnotationSource` читает стандартный слой `RulerData3D`.

`BlenderAnnotationSource` ищет слой в таком порядке:

1. `bpy.data.annotations` - Blender 5.x / renamed annotations.
2. `bpy.data.grease_pencils` - legacy Blender 4.x и ниже.
3. `bpy.context.scene.annotation`, `scene.annotations`, `scene.grease_pencil` - fallback.

Layer names сравниваются через `layers.get("RulerData3D")`, `layers["RulerData3D"]`, затем через `layer.info`/`layer.name`.

## 2. Извлечение strokes

`infrastructure.blender_annotations.iter_layer_strokes(layer)` поддерживает несколько layouts:

- `layer.frames -> frame.strokes`
- `layer.frames -> frame.drawing.strokes`
- `layer.strokes`
- `layer.drawing.strokes`

Strokes сначала deduplicate по `stroke.as_pointer()` или `id(stroke)`, если оба API-пути возвращают один объект.

## 3. Raw classification

`MeasurementApplicationService.ingest_measurements()` получает `StrokeInput` от source и превращает их в `RawMeasurement`.

- `len(points) == 2` -> `MeasurementKind.LINEAR`
- `len(points) == 3` -> `MeasurementKind.PLANE`
- `len(points) >= 3` + `kind_hint == MeasurementKind.PLANE` -> `MeasurementKind.PLANE`
- иначе stroke игнорируется с debug log

Стандартный `RulerData3D` не получает `kind_hint`, поэтому legacy strokes с 4+ точками остаются unsupported и не превращаются в face случайно. Multi-point planes создаются только scene-stored инструментом `Scientia Polygon Plane`.

После чтения points application service deduplicate measurements по координатной сигнатуре `(kind, rounded point coordinates)`.
Это защищает от известного бага старых версий, где Blender мог хранить одинаковые ruler strokes в нескольких frames, и count трещин резко возрастал.

Diagnostics counters:

- `total_strokes_count` - сколько strokes parser увидел до классификации.
- `duplicate_strokes_count` - сколько координатных дублей пропущено.
- `ignored_strokes_count` - сколько strokes с неподдержанным количеством points пропущено.
- `layer_found` - найден ли слой `RulerData3D`.

Raw export:

- `export_raw_edges()` -> `{blend_root}_edges_raw.txt`
  - header: `EDGES POINTS {count}`
  - rows: `point1\tpoint2\tname\tlayer\tcode\tdescription\tattributes_json`
- `export_raw_faces()` -> `{blend_root}_faces_raw.txt`
  - header: `FACES POINTS {count}`
  - rows: `point1\tpoint2\tpoint3\tname\tlayer\tcode\tdescription\tattributes_json\tpoint_count\tpoints_json`
- Export methods first check `bpy.data.is_saved`; unsaved `.blend` returns `ExportResult(ok=False, filename=None, ...)` without extra parsing/writing.

## 4. Processed geometry

`get_processed_edges(az_real, az_model)`:

1. `domain.geometry.process_linear_measurement()` создает `MeasurementRecord`.
2. Считает `line_orientation`, `edge_orientation`, `length`, `center`.
3. Считает `line_orientation.rotated_azimuth = (azimuth + az_real - az_model) % 360`.
4. `parser.py` при необходимости конвертирует record в legacy `Edge`.

Processed edges CSV columns:

```text
x,y,z,azimuth,dip,edge_azimuth,edge_dip,rotated_azimuth,length,id,source,source_id,layer,name,code,description,attributes_json
```

`get_processed_faces(az_real, az_model)`:

1. `domain.geometry.process_plane_measurement()` создает `MeasurementRecord`.
2. Для 3 точек считает plane normal через тот же deterministic path, для 4+ точек делает best-fit plane approximation по covariance matrix и eigenvector с минимальной дисперсией.
3. Считает `plane_orientation`, `area`, `degree`, `center`.
   - `area` для 4+ точек считается как площадь замкнутого boundary polygon после проекции в fitted plane.
   - `degree` сохраняется только для 3-точечных plane measurements; для `POLYLINE` это `None`.
4. Считает `plane_orientation.rotated_azimuth = (azimuth + az_real - az_model) % 360`.
5. `parser.py` при необходимости конвертирует record в legacy `Face`.

Processed faces CSV columns:

```text
x,y,z,azimuth,dip,rotated_azimuth,area,degree,point_count,fit_error,fit_error_relative,id,source,source_id,layer,name,code,description,attributes_json
```

- `fit_error` - RMS расстояние точек от best-fit plane в единицах модели; ровно `0.0` для 3 точек.
- `fit_error_relative` - `fit_error / средний радиус точек от centroid`; `0.1` значит разброс вне плоскости ~10% от размера измерения.

## 5. Геометрические правила

`domain.geometry.Vector3.azimuth()`:

- берет vector components в upper hemisphere (`z >= 0`);
- возвращает `atan2(x, y) % 360`;
- не меняет `self.x/self.y/self.z`.

`domain.geometry.Vector3.dip()`:

- использует тот же upper-hemisphere orientation;
- возвращает `atan2(horizontal_length, z)` — угол от вертикали; для нормали плоскости это dip самой плоскости;
- не зависит от того, вызывался ли `azimuth()` раньше.

`domain.geometry.Vector3.plunge()`:

- возвращает `atan2(z, horizontal_length)` upper-vector — угол от горизонтали;
- используется как `dip` линейных измерений (0 = горизонтальная линия, 90 = вертикальная).

`Face`:

- для 3+ points normal vector строится через `fit_plane_normal()`;
- `fit_plane_normal()` использует centroid, covariance matrix и eigenvector с минимальной дисперсией, затем стабилизирует знак normal по Newell/winding normal;
- `area` считается через projection в локальный basis fitted plane и shoelace formula;
- `degree` - угол между двумя сторонами, нужен как диагностический/измерительный показатель только для 3-точечных measurements.

`Edge`:

- `length` - длина исходного 2-точечного измерения;
- `azimuth`/`dip` - ориентация самой линии; `dip` — это plunge (0 для горизонтальной линии, 90 для вертикальной);
- `edge_azimuth`/`edge_dip` - ориентация плоскости, перпендикулярной измеренному отрезку (отрезок — её нормаль). Замеры spacing делаются перпендикулярно системе трещин, поэтому сопоставление этой ориентации со средними ориентациями систем позволяет привязать замер к конкретной системе. `edge_dip = 90 - plunge`, `edge_azimuth` совпадает с азимутом линии (upper-hemisphere). До версии 3.2 формула была сломана и всегда давала `edge_dip = 45`.

## 6. Visualization

Histogram:

- source: processed `Edge.length`;
- output: temp file `edges_histogram.png`;
- statistics: `Mean`, `Median`, `Std Dev`, `Min`, `Max`.

Stereonet:

- source: processed faces;
- `dip_dir = face.rotated_azimuth`;
- if `stereonet_hemisphere == 'LOWER'`, `dip_dir = (dip_dir + 180) % 360`;
- `strike = (dip_dir + 90) % 360`;
- plotted as poles via `mplstereonet`;
- poles are grouped by `face.color`, which comes from `MeasurementProperties.display_color`, so fracture code colors are preserved on the stereonet;
- hidden fracture codes and hidden `No code` measurements are filtered earlier by `SceneMeasurementSource`, so they do not appear on the stereonet;
- `marker_face_color` is now only a fallback/legacy pole color for measurements without color metadata, such as standard `RulerData3D`.
- density contours are best-effort: if `density_contourf()` fails on a small or problematic dataset, poles are still plotted and saved.

`update_histogram_image()` and `update_stereonet_image()` return `True` when a PNG was loaded into Blender Image Editor and `False` when no image was created.

## 7. Failure behavior

Export/process methods return `ExportResult`.

- `ok=True`: file was written.
- `ok=False`, `filename=None`: `.blend` is not saved; addon invokes `bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')` and asks user to retry export.
- `ok=False`, `filename=<path>`: write/process failure; Blender operator reports error.
