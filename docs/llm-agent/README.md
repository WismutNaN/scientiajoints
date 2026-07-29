# ScientiaJoints для LLM-агента

Эта папка описывает текущий код Blender addon `ScientiaJoints` так, чтобы агент мог быстро понять поток данных, безопасно править баги и планировать расширения.

## Быстрый маршрут по коду

- `__init__.py` - регистрация addon, автоматическая установка Python-пакетов, `Scene` properties, `LightSettings`.
- `scene_measurements.py` - Scene-based storage для пользовательских измерений, слоев, видимости, цвета и будущих атрибутов.
- `custom_measure_tool.py` - toolbar tool `scientiajoints.measure`, drag operator `wm.scientia_measure_drag` и persistent View3D overlay.
- `domain/` - чистая доменная модель и геометрические расчеты без `bpy`, `mathutils`, matplotlib и файловой системы.
- `application/` - use-case services: ingest, deduplicate, process, export через ports.
- `infrastructure/` - Blender annotation source, Scene measurement source и TXT/CSV writers.
- `dependencies.py` - проверка и установка `matplotlib`, `mplstereonet`, `numpy` с видимым статусом для UI.
- `panel.py` - UI в `View3D > Sidebar > ScientiaJoints`; кнопки визуализации, экспорта, статистики и настроек.
- `parser.py` - compatibility facade поверх DDD application layer; сохраняет старые `faces`, `edges`, `get_processed_edges()`, export/process методы.
- `visualization.py` - `Visualizer`, histogram для `Edge.length`, stereonet для `Face.rotated_azimuth`/`Face.dip`.
- `operators.py` - Blender `Operator` classes, которые связывают UI с parser/export/visualization и настройками сцены.
- `custom-measure-tool.md` - исследование стандартного Blender Measure/Ruler и текущий собственный tool.
- `local-environment.md` - локальный путь к `blender.exe` и подсказки для будущего headless smoke.

## Основной workflow

1. Пользователь создает измерения стандартным Blender Measure tool или toolbar tool `scientiajoints.measure`.
2. Стандартный Blender хранит ruler strokes в annotation/grease pencil layer `RulerData3D`.
3. `wm.scientia_measure_drag` хранит данные в `bpy.types.Scene.scientia_measurements`.
4. `CompositeMeasurementSource` объединяет `SceneMeasurementSource` и `BlenderAnnotationSource`.
5. `MeasurementApplicationService.ingest_measurements()` классифицирует:
   - 2 points -> raw linear measurement -> `Edge`;
   - 3 points -> raw plane measurement -> `Face`;
   - другое количество points игнорируется.
6. Одинаковые измерения с той же координатной сигнатурой пропускаются как duplicates. Это защищает от резкого роста count, когда Blender хранит копии strokes в нескольких frames.
7. `process_edges()` и `process_faces()` строят `MeasurementRecord` и применяют поправку азимута:
   `(azimuth + az_real - az_model) % 360`.
8. `parser.py` конвертирует records в legacy `Edge`/`Face` objects для старой визуализации и UI.
9. Export methods пишут raw TXT или processed CSV через infrastructure writers.
10. `Visualizer` строит histogram/stereonet и открывает PNG в Blender Image Editor.

## Что запускать после правок

```powershell
python -m unittest discover -s tests -v
python -m py_compile __init__.py dependencies.py parser.py operators.py panel.py visualization.py scene_measurements.py custom_measure_tool.py domain\__init__.py domain\measurements.py domain\geometry.py application\__init__.py application\services.py infrastructure\__init__.py infrastructure\blender_annotations.py infrastructure\blender_scene_measurements.py infrastructure\exporters.py
```

Если доступен `blender.exe`, дополнительно нужен headless integration smoke: импортировать addon, вызвать `register()`, проверить operator registration, затем `unregister()`.
