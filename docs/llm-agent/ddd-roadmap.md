# DDD roadmap для ScientiaJoints

Цель: постепенно отделить геологическую доменную модель от Blender API, UI, файлового экспорта и визуализации. Текущий этап не делает большой рефактор, а фиксирует безопасную траекторию.

Важное направление развития: сохранить быстрый workflow через стандартный Blender ruler, но заложить возможность внутренних измерений ScientiaJoints со свойствами, слоями, интерактивным просмотром, альтернативными источниками данных и автоматизированным выделением трещин.

## Принцип умеренной абстракции

- Не вводить большой framework, event sourcing, database или сложную plugin-систему до реальной необходимости.
- Делать один стабильный application boundary вокруг измерений: read -> normalize -> enrich -> process -> present/export.
- Новые возможности подключать через маленькие ports/interfaces, но оставлять текущий `MeasurementsParser` и operator IDs рабочими.
- Любая новая модель должна уметь импортировать/отражать текущие `RulerData3D` measurements, чтобы не ломать быстрый ручной workflow.

## Уже реализованный первый срез

- `domain/measurements.py` - `Point3D`, `RawMeasurement`, `MeasurementRecord`, `MeasurementSet`, diagnostics и metadata placeholders.
- `domain/geometry.py` - чистые расчеты linear/plane records без Blender API.
- `application/services.py` - ingestion, coordinate deduplication, processing и export orchestration.
- `infrastructure/blender_annotations.py` - `MeasurementSource` adapter для текущего `RulerData3D`.
- `infrastructure/exporters.py` - writers для существующих TXT/CSV форматов.
- `parser.py` - compatibility facade, который сохраняет старые public methods и legacy `Edge`/`Face` outputs для UI/visualization.

## Предлагаемые слои

### Domain

Pure Python, без `bpy`, `matplotlib`, файловой системы.

- Entities/value objects: `Point3D`, `Vector3`, `MeasurementId`, `MeasurementKind`, `LinearMeasurement`, `PlaneMeasurement`, `Orientation`, `AzimuthCorrection`.
- Aggregates: `MeasurementRecord` = geometry + calculated orientation + metadata + source reference; `MeasurementLayer` = named/grouped measurements.
- Metadata: lightweight `MeasurementProperties` for fracture attributes such as set name, confidence, roughness, aperture, persistence, comment, tags. Start as typed key/value schema, not a large class hierarchy.
- Domain services: geometry calculation, orientation normalization, spacing statistics, layer filtering/grouping, duplicate detection.
- Domain errors: degenerate measurement, unsupported measurement shape, invalid correction values, invalid property value.

Единственный источник геометрических расчетов: `domain/geometry.py`.

### Application

Use cases, которые оркестрируют domain и infrastructure.

- `IngestMeasurementsUseCase`
- `ParseMeasurementsUseCase`
- `ProcessLinearMeasurementsUseCase`
- `ProcessPlaneMeasurementsUseCase`
- `AssignMeasurementPropertiesUseCase`
- `AssignMeasurementLayerUseCase`
- `GetMeasurementInfoUseCase`
- `ExportRawMeasurementsUseCase`
- `ExportProcessedMeasurementsUseCase`
- `BuildHistogramUseCase`
- `BuildStereonetUseCase`
- `SuggestFractureCandidatesUseCase`

Здесь должны жить input/output DTOs, `ExportResult`, counts, warnings и user-facing messages.

`GetMeasurementInfoUseCase` нужен для hover/selection workflow: по selected/hovered measurement возвращать длину, dip, azimuth, rotated azimuth, layer, source, properties и diagnostic flags.

`SuggestFractureCandidatesUseCase` должен возвращать candidates/proposals, а не сразу изменять финальный набор измерений. Пользователь или отдельный workflow подтверждает их.

### Infrastructure

Adapters к внешнему миру.

- `MeasurementSource` port - общий источник raw measurements.
- `BlenderAnnotationReader` - `MeasurementSource` для стандартного ruler: все знания про `bpy.data.annotations`, `grease_pencils`, `frame.strokes`, `frame.drawing.strokes`.
- `ScientiaMeasurementStore` - будущий внутренний источник/хранилище ScientiaJoints measurements со свойствами и слоями.
- `RulerMirrorAdapter` - опциональный bridge, который импортирует стандартные ruler measurements во внутреннюю модель без потери быстрого workflow.
- `CsvMeasurementWriter` и `TxtRawMeasurementWriter`.
- `MatplotlibHistogramRenderer`.
- `MplStereonetRenderer`.
- `InteractiveChartRenderer` - будущий renderer для интерактивных histogram/stereonet; должен принимать те же processed DTOs, что и static renderers.
- `BlenderImagePresenter`.
- `BlenderOverlayPresenter` - будущий presenter для hover/selection labels во viewport.
- `BlenderCustomMeasurementTool` - будущий input adapter для собственного инструмента вместо или рядом с `RulerData3D`.
- `FractureCandidateDetector` - adapter/domain service для автоматизированного выделения трещин на основе заданных измерений/геометрии.
- Dependency/bootstrap adapter для проверки `numpy`, `matplotlib`, `mplstereonet`.

### Presentation

Blender UI and operators.

- `MeasurementExporterPanel` остается тонким: только layout и вызов operators.
- Operators становятся тонкими adapters: собрать `context.scene` settings, вызвать application use case, показать report, сделать UI redraw.
- Scene properties можно сгруппировать в settings DTOs.
- Viewport overlay/selection operators должны вызывать `GetMeasurementInfoUseCase`, а не пересчитывать geometry внутри UI.

## Планируемые extension points

### Свойства трещин

- Добавить `MeasurementProperties` как schema-based metadata: стандартные поля + user-defined fields.
- Хранить свойства отдельно от геометрии, чтобы импорт из `RulerData3D` не требовал менять стандартные Blender ruler objects.
- В UI сначала достаточно панели выбранного измерения; массовое редактирование и templates можно добавить позже.

### Слои и группы

- Ввести `MeasurementLayer` как доменную группировку: имя, цвет, видимость, фильтр экспорта/визуализации.
- Начать с mapping `RulerData3D` -> default layer и ручного назначения layers уже обработанным measurements.
- Не привязывать domain layer к Blender collection напрямую; Blender collection может быть только presentation/infrastructure detail.

### Hover/selection info

- Нужен стабильный `MeasurementId` и source reference, чтобы по выбранному/наведенному объекту получать вычисленные свойства.
- Для стандартного ruler ID может быть synthetic: source name + point coordinate signature + kind.
- Для будущего custom tool ID должен быть persistent и храниться вместе с measurement record.

### Интерактивные графики

- Не менять domain/application из-за способа рендера.
- `BuildHistogramUseCase` и `BuildStereonetUseCase` должны возвращать chart model/data DTOs.
- Static PNG renderer и interactive renderer используют один chart model.
- Interactive renderer можно реализовать позже через Blender UI panel, HTML/WebView-like workflow, viewport overlay или отдельный modal view.

### Свой инструмент измерений

- Стандартный ruler остается default `MeasurementSource`, потому что он быстрый и удобный.
- Custom tool должен добавляться как второй `MeasurementSource`, а не заменять parser сразу.
- Минимальная цель custom tool: сохранять geometry + `MeasurementId` + properties/layer сразу при создании измерения.
- Хороший промежуточный вариант: "promote ruler measurement" - пользователь делает измерение стандартной линейкой, addon импортирует его во внутренний record и позволяет назначить свойства.

### Автоматизированное выделение трещин

- Авто-алгоритм должен производить `FractureCandidate`, не `MeasurementRecord`.
- Candidate содержит geometry, confidence, method name, diagnostic info и ссылку на входные измерения.
- Отдельный use case подтверждает candidates и превращает их в measurements/layer.
- Это позволит тестировать алгоритмы без UI и без риска загрязнить ручные измерения.

## Поэтапная миграция

### Step 1: Stabilize domain tests

- Выполнено: новые DTO добавлены, корневой legacy `geometry.py` удален.
- Legacy-shaped `EdgeView`/`FaceView` остались только как adapter objects в `parser.py` для UI/visualization.
- Выполнено частично: domain/application tests добавлены.
- Расширить tests на реальные геологические cases, согласованные пользователем.

### Step 2: Extract Blender annotation adapter

- Выполнено: annotation reader вынесен в `infrastructure/blender_annotations.py`.
- Выполнено: `MeasurementsParser` зависит от `MeasurementApplicationService`, который зависит от source adapter.
- Осталось: формально выделить `MeasurementSource` protocol/class вместо duck typing.

### Step 3: Introduce measurement records without changing UI

- Выполнено: `MeasurementRecord` создается в domain layer.
- Выполнено: source reference/source_id передаются из `BlenderAnnotationSource`.
- Выполнено: существующие CSV/TXT outputs сохранены.
- Начать хранить optional properties/layer только внутри application result или scene custom data, без обязательной миграции старых файлов.

### Step 4: Extract application use cases

- Разделить чтение raw measurements, processing и export.
- Убрать запись файлов из `MeasurementsParser`.
- Operators получают `ExportResult` от application service.

### Step 5: Extract visualization presenters

- `Visualizer` разделить на:
  - statistics/domain calculation;
  - renderer to image path;
  - Blender image presenter.
- Ввести chart model DTO, чтобы позже добавить `InteractiveChartRenderer` без переписывания расчетов.
- Realtime operators должны пересоздавать только нужный output, без лишнего дублирования parser logic.

### Step 6: Add selection/hover read model

- Добавить `GetMeasurementInfoUseCase`.
- Для начала отдавать данные для selected measurement из synthetic ID/coordinate signature.
- UI overlay делать отдельно от domain, через `BlenderOverlayPresenter`.

### Step 7: Dependency and setup policy

- Сохранить automatic pip install в `register()` как default для обычных пользователей.
- Добавить preference для offline/managed environments, где auto-install можно отключить и оставить только "Install/Verify dependencies" operator.
- Документировать Blender Python environment и offline behavior.

## Границы, которые нельзя ломать

- Public operator IDs:
  - `export.raw_edges`
  - `export.raw_faces`
  - `export.processed_edges`
  - `export.processed_faces`
  - `wm.show_histogram_image`
  - `wm.show_stereonet_image`
- Default output filenames рядом с `.blend`.
- `RulerData3D` как default layer name.
- Existing `Scene` properties names, пока нет миграции пользовательских настроек.
- Быстрый workflow стандартной линейки Blender.
- Raw/processed export semantics для текущих 2-точечных и 3-точечных измерений.

## Acceptance criteria для будущего DDD refactor

- `geometry`/domain tests запускаются без Blender.
- Parser/application tests не требуют реального `bpy`, кроме отдельного integration suite.
- Operators не содержат расчетов geometry или CSV formatting.
- Visualization можно протестировать без открытия Blender Image Editor.
- Один headless Blender smoke подтверждает `register()`/`unregister()` и operator availability.
- Новый источник измерений можно добавить через `MeasurementSource` без изменения domain calculation.
- Свойства/слои можно добавить к measurement records без изменения формул `Edge`/`Face`.
- Interactive renderer может использовать те же chart DTOs, что и static PNG renderer.
