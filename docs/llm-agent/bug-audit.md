# Bug audit

## Этап 3.3.2

### Стереонет: плотность не отрисовывается

Симптом (лог пользователя):
`WARNING ... Stereonet density contours were skipped: module 'numpy' has no attribute 'float'.`
Стереонет сохранялся, полюса рисовались, плотности не было.

Причина: `mplstereonet` 0.6.2 использует `dtype=np.float` в `contouring.py` и
`stereonet_math.py`. Алиас удалён в numpy 1.24, Blender 5.x везёт numpy 2.x.
`plot_faces_stereonet()` ловит исключение вокруг `density_contourf` и только логирует
его - поэтому картинка выходила без плотности, а не с ошибкой.

Исправление, три уровня:
- `wheels/` теперь везёт `mplstereonet` 0.6.3, где upstream перешёл на `np.float64`.
  На PyPI у 0.6.3 нет wheel, только sdist, поэтому `tools/fetch_wheels.py` собирает его
  через `pip wheel` (пакет чисто питоновский, тег `py3-none-any` подходит всем платформам)
  и удаляет вытесненные версии из `wheels/`.
- `visualization._numpy_legacy_aliases()` возвращает `np.float`/`np.int` на время построения
  фигуры, чтобы уже установленная 0.6.2 продолжала работать. Снимается на выходе, чтобы
  другие аддоны не видели numpy, противоречащий своей версии.
- `dependencies.MINIMUM_VERSIONS` + `outdated_packages()`: pip запрашивается как
  `mplstereonet>=0.6.3`, а diagnostics показывает `TOO OLD` и Problem вместо молчаливой
  деградации.

Проверка: `plot_faces_stereonet()` со старой 0.6.2 на `sys.path`. Без шима - тот же warning,
что у пользователя; с шимом - ни одного. Закреплено `assertNoLogs` в `test_stereonet_smoke`.

### `Tool 'scientiajoints.measure' already exists!` при установке

Симптом: `mod.register()` → `register_measure_tool()` → `bpy.utils.register_tool` бросает
`Tool 'scientiajoints.measure' already exists!`, аддон не включается.

Причина: `bpy.utils.unregister_tool(cls)` ищет запись по конкретному объекту `ToolDef`,
сохранённому в `cls._bl_tool` при регистрации. Другой экземпляр модуля - аддон, поставленный
и как extension (`bl_ext.user_default.scientiajoints`), и как legacy (`scripts/addons/ScientiaJoints`),
либо reload, где `_purge_stale_submodules()` выбросил старые классы до `unregister()` - имеет
свои классы, поэтому очистить чужую запись он не может. `register_tool` же проверяет только
`bl_idname` в `cls._tools[context_mode]` и падает.

Исправление: `custom_measure_tool.purge_registered_tools()` проходит по
`ToolSelectPanelHelper._tool_class_from_space_type('VIEW_3D')._tools`, удаляет записи с нашими
`bl_idname` независимо от того, кто их регистрировал (включая вложенные группы), подчищает
разделители и снимает keymap записи так же, как это делает штатный `unregister_tool`.
Вызывается и в `register_measure_tool()`, и в `unregister_measure_tool()`. Если что-то было
удалено, в лог идёт warning про дублирующую установку.

Ограничение: две одновременные установки аддона остаются проблемой пользователя - падать
регистрация больше не будет, но панели и операторы всё равно регистрируются дважды.

## Этап 3.3.0

### Обновление аддона внутри работающего Blender: ImportError

Симптом (сообщение пользователя):
`ImportError: cannot import name 'ScientiaDiagnosticsCopyOperator' from 'ScientiaJoints.operators'`
при `Install from Disk` поверх включённого аддона.

Причина: `addon_utils.enable()` перезагружает **только** top-level пакет
(`importlib.reload(mod)` при изменении mtime у `__init__.py`). Все submodules остаются
в `sys.modules` от предыдущей версии, поэтому новый `__init__.py` спрашивает символы у
старого `operators.py`. Это тот же класс проблемы, что и в 3.2.2 с `run_startup_diagnostics`,
но обходное решение тогда закрыло только один символ.

Исправление: `_purge_stale_submodules()` в начале `__init__.py` удаляет из `sys.modules`
все `ScientiaJoints.*` до первого импорта submodule; при повторном включении все файлы
читаются с диска заново. Плюс `_check_module_files_match()` перед импортами в `register()`
проверяет файлы как текст и сообщает про неполную установку с указанием папки, вместо
ImportError с именем символа.

Воспроизведение и проверка: `enable(старая версия)` → `disable` → `addon_install(новый zip)`
→ `enable` в одном процессе Blender. До правки — та же ошибка, что у пользователя;
после — `RELOAD_UPGRADE_OK`.

### matplotlib «установлен», но не импортируется: лимит пути Windows

Симптом: пользователь ставит зависимости, pip рапортует success, стереонет не появляется.

Причина подтверждена экспериментально на Blender 5.2: импорт падает с
`FileNotFoundError` на `matplotlib/mpl-data/stylelib/seaborn-v0_8-dark-palette.mplstyle`,
когда абсолютный путь файла достигает 260 символов (MAX_PATH). Файл физически на диске
есть, `os.listdir` его видит, но Blender-питон не может его открыть. Тот же механизм
ломает импорт любого подмодуля с длинным путём.

Исправление: `dependencies.path_budget()` считает остаток до лимита и отбраковывает
каталог установки заранее; диагностика показывает остаток по каждому кандидату и выдаёт
явную причину. Extension-сборка кладёт пакеты в короткий
`extensions/.local/lib/python3.x/site-packages`.

Покрытие: `tests/test_dependencies.py::PathBudgetTests`.

### `pip install --user` уходит мимо `sys.path`

Причина: Blender собран с `site.ENABLE_USER_SITE = False`, user site не в `sys.path`.

Исправление: `--user` не используется никогда; каталог выбирается из кандидатов,
которые реально в `sys.path` и реально доступны на запись (проверка записью, а не
`os.access` — на Windows ACL врут).

Покрытие: `tests/test_dependencies.py::OfflineWheelTests::test_user_site_is_never_used`.

### Второй numpy и ABI-конфликт

Причина: `pip install --target` игнорирует уже установленные пакеты и ставит свой numpy,
который затеняется бандлом Blender. При расхождении мажорных версий `contourpy`/`matplotlib`
падают с binary incompatibility.

Исправление: для `--target` генерируется constraints-файл с пином numpy на версию из
бандла Blender; extension-сборка numpy не везёт вовсе.

### Blender подвисает при запуске

Причина: `install_packages()` вызывался синхронно в `register()`, pip без `timeout`
и без `--no-input`. В сети с фильтрацией это минуты ожидания при каждом старте.

Исправление: `register()` только проверяет импорты. Установка идёт в рабочем потоке
(`dependencies.BackgroundInstall`), повтор автоматической попытки не чаще раза в сутки,
в headless-режиме установка не запускается. Вывод pip захватывается и попадает в отчёт.

### Отсутствие обратной связи в UI

Исправление: баннер в панели с перечнем недостающих пакетов, кнопкой установки и
кнопкой диагностики; кнопки графиков заблокированы, пока зависимостей нет.

### Дубликаты после смены кадра — остаточный случай

Точные копии удалялись и раньше. Не ловился случай, когда скопированный Blender'ом
stroke затем сдвинули: сигнатуры расходятся, в экспорте два измерения, в вьюпорте видно
одно (Blender показывает текущий кадр).

Исправление: `RawMeasurement.near_signature()` — огрублённая (1 мм) и независимая от
порядка точек сигнатура. Такие пары не удаляются (отличить намеренный близкий замер от
копии может только оператор), а попадают в Statistics и в отчёт диагностики. Отдельно
сообщается, если ruler-аннотации лежат на нескольких кадрах.

Покрытие: `tests/test_duplicates.py`.

### Видимость кодов молча урезала экспорт

Симптом: скрыл группу кодов для чистоты вида — выгрузил меньше замеров, без предупреждения.
Переключатели Linear/Planes при этом были display-only, поведение противоречило README.

Исправление: видимость больше не фильтрует источник. Скрытые замеры считаются и
упоминаются в диагностике.

### Залипание автообновления графиков

Причина: флаг `_running` не сбрасывался, если Blender снимал модальный оператор без
`cancel()` (загрузка файла, закрытие окна).

Исправление: общий базовый класс, сброс флагов в `register()` и в `load_post`.

### `bpy.ops` из update-колбэка свойства

Причина: модальные операторы стартовали прямо из `update=` свойства, где контекст
ограничен и вызов может быть отвергнут.

Исправление: старт отложен на один тик таймера.

### Состояние прошлого файла переживало загрузку .blend

Причина: `_active_preview`, `_polygon_preview` и кэш записей — module-level.

Исправление: handler `load_post` сбрасывает состояние инструмента, флаги модальных
операторов и кэши панели.

### Полное разложение плоскости на каждый кадр отрисовки

Причина: подписи в оверлее вызывали `process_plane_measurement()` (итеративный Jacobi
eigen-solver) для каждого полигона на каждую перерисовку вьюпорта.

Исправление: кэш обработанных записей по координатам точек и азимутальной коррекции,
сбрасывается при загрузке файла и по достижении лимита.

### Одинаковые имена измерений

Причина: `name = f"M{len(measurements)}"` повторяется после любого удаления.

Исправление: `next_measurement_name()` ищет первый свободный номер.

Покрытие: `tests/test_duplicates.py::MeasurementNameTests`.

## Исправлено в предыдущем этапе

### Duplicate cracks from copied ruler frames

Симптом: во время картирования count трещин резко возрастает, а уже снятые измерения дублируются.

Вероятная причина в исходном коде: parser проходил по всем `layer.frames` и добавлял каждый `stroke`. Если Blender/annotation API хранит одинаковые ruler strokes в нескольких frames, это выглядело как новые трещины.

Исправление: `MeasurementsParser` теперь пропускает координатные дубли измерений и сохраняет `duplicate_strokes_count` для startup diagnostics и Statistics.

Покрытие: `tests/test_parser.py::test_duplicate_measurements_across_frames_are_skipped`.

### `frame.drawing.strokes` silently ignored

Симптом: в некоторых Blender API layouts `layer.frames` существует, но `frame.strokes` пустой/отсутствует, а реальные strokes лежат в `frame.drawing.strokes`. Старый `_iter_layer_strokes()` завершался после первой попытки и не доходил до drawing layout.

Исправление: `_iter_layer_strokes()` теперь читает оба контейнера per-frame и deduplicate strokes.

Покрытие: `tests/test_parser.py::test_parse_dimensions_from_frame_drawing_strokes`.

### False success reports for export

Симптом: `MeasurementsParser.export_*()` и `process_*()` могли вернуть `None` при unsaved `.blend` или ошибке записи, а Blender operator все равно сообщал success.

Исправление: добавлен `ExportResult(ok, filename, message)`. Export operators report `INFO`, `WARNING` или `ERROR` по фактическому результату.

Покрытие: `tests/test_export.py::test_unsaved_file_returns_failure_and_invokes_save_prompt` и CSV/TXT export tests.

### Hidden mutation in `Vector3D.azimuth()`

Симптом: `Vector3D.azimuth()` вызывал `multiply_minus()` при `z < 0`, меняя vector state. Результат `dip()` зависел от порядка вызовов.

Исправление: `azimuth()` и `dip()` используют `upward_components()` без изменения исходного vector.

Покрытие: `tests/test_geometry.py::test_vector_azimuth_and_dip_are_non_mutating`.

### Degenerate vector angle

Симптом: `degrees_with()` делил на zero length и полагался на broad exception.

Исправление: zero-length angle возвращает `0.0`, cosine clamp защищает от floating point overshoot.

Покрытие: `tests/test_geometry.py::test_degenerate_vector_angle_is_zero`.

### Broken `.gitignore`

Симптом: `.gitignore` содержал некорректный паттерн.

Исправление: добавлены `__pycache__/`, `*.py[cod]`, cache folders и Blender backup files.

### Installation problems hidden without a clear startup log

Симптом: пользователи не понимают, почему не строятся charts, если `matplotlib`, `mplstereonet` или `numpy` не установились в Blender Python. Короткий вывод в UI оказался неудобным: его плохо читать и копировать.

Исправление: добавлен `dependencies.py`, а startup diagnostics запускается один раз при `register()` и пишет полную информацию в Blender console/log. Панель не перегружена диагностическим блоком.

### Partial registration after import/register failure

Симптом: если импорт `operators.py`/`panel.py` или регистрация одного класса падали, `register()` мог тихо выйти или оставить Blender с частью `Scene` properties/classes.

Исправление: `register()` теперь логирует traceback, снимает уже добавленные classes/properties через `_cleanup_partial_registration()` и пробрасывает исключение наружу. `unregister()` стал идемпотентнее и не зависит от существования глобального `classes`.

Проверка: headless Blender smoke импортирует addon, вызывает `register()`, проверяет `bpy.types.Scene.az_real` и `bpy.ops.export.raw_edges`, затем вызывает `unregister()`.

### Unstable Ruler settings toggle removed

Симптом: `ToggleRulerSettingsOperator` пытался менять display properties стандартного `RulerData3D`, но эти поля нестабильны между версиями Blender и часто давали ошибки или не давали заметного эффекта.

Исправление: кнопка и оператор удалены из публичного UI/registration. Настройка стандартного Blender ruler layer больше не является частью поддерживаемого workflow; собственный Scientia overlay управляется через `Measurement Display`.

### Visualization operators reported success on failure

Симптом: `wm.show_histogram_image` и `wm.show_stereonet_image` возвращали `FINISHED` даже после исключения или отсутствия созданного PNG.

Исправление: `update_histogram_image()` и `update_stereonet_image()` возвращают `True/False`; operators возвращают `CANCELLED` и пишут warning/error, если картинка не создана. Полная причина остается в Blender console/log.

### Stereonet density contour failure on small datasets

Симптом: `mplstereonet.density_contourf()` может падать на малом числе плоскостей, из-за чего не показывались даже pole points.

Исправление: density contours обернуты в локальный `try`; при ошибке contour пропускается, но `ax.pole()` и сохранение stereonet PNG продолжаются.

### Unnecessary parsing before unsaved export check

Симптом: export/process methods сначала запускали `_ensure_ready()` и только потом проверяли `bpy.data.is_saved`.

Исправление: проверка `.blend` save status перенесена в начало `export_raw_edges()`, `export_raw_faces()`, `process_edges()` и `process_faces()`.

### Invalid module name during ZIP installation

Симптом: Blender legacy installer завершался с `No module named 'ScientiaJoints 3'`, если release был упакован в каталог `ScientiaJoints 3/` или распространялся как generic source archive.

Причина: ошибка возникает до импорта `__init__.py`; код addon не может ее диагностировать или исправить во время `register()`.

Исправление: `tools/build_release.py` создает проверенный ZIP с единственным package root `ScientiaJoints/`. Имя внешнего ZIP не влияет на Python module name. Структура зафиксирована в `tests/test_release_package.py` и проверена реальной установкой в изолированный профиль Blender 5.1.2.

### Mixed modules after in-process update

Симптом: новый `__init__.py` импортировал отсутствующий `run_startup_diagnostics` из старого `operators.py`.

Причина: обновление включенного addon в том же Blender process может оставить ранее импортированные submodules в `sys.modules`; ручное копирование поверх старой папки также создает смешанную установку.

Исправление:

- release version поднята до `3.2.2`;
- startup diagnostics сделана необязательной для регистрации и при несовпадении пишет понятное console warning;
- release builder проверяет Python syntax и обязательный API в `operators.py`, `custom_measure_tool.py` и `panel.py`;
- README требует закрыть Blender и удалить старую папку `ScientiaJoints` перед повторной установкой после подобных ошибок.

## Аудит математики полигональной плоскости (3.3.0)

Сверка с независимой реализацией на numpy (SVD-подгонка плоскости, формула Ньюэлла),
300 случайных полигонов + аналитические плоскости.

Подтверждено корректным:

| Проверка | Максимальная ошибка |
|---|---|
| `dip` vs numpy SVD | 4.4e-13° |
| `rotated_azimuth`/`azimuth` vs numpy SVD | 8.0e-13° |
| Аналитические плоскости 0…89°, азимуты по кругу | < 1e-9 |
| `fit_error` (RMS) vs numpy | 3.1e-15 |
| Площадь плоского полигона vs Ньюэлл | 5.6e-16 относительной |
| 3 точки vs N точек на одной плоскости | < 1e-12 |
| Собственный Jacobi-солвер vs SVD | совпадает |

Конвенции: `dip` — угол нормали от вертикали (равен падению плоскости); `azimuth` —
направление максимального падения, отсчёт по часовой стрелке от +Y. Для неплоского
полигона площадь — проекция на подогнанную плоскость (не Ньюэлл); это правильное
определение для замеренной поверхности, расхождение с Ньюэллом на шумных полигонах
(~4e-8) не дефект.

### Известное ограничение: азимут падения субвертикальных плоскостей

`Vector3.upper()` разворачивает нормаль по знаку `z`, а у вертикальной плоскости `z` —
шум подгонки, поэтому знак случаен. Измерено на вертикальной трещине, 20 обводок
полигона 1 м с шумом 1 см:

| dip | развернулось на 180° | азимуты |
|---|---|---|
| 75° | 0 из 20 | 200 |
| 85° | 0 из 20 | 200 |
| 89° | 0 из 20 | 200 |
| 89.9° | 11 из 20 | 20, 200 |
| 90° | 13 из 20 | 20, 200 |

Тот же полигон, обведённый в обратную сторону, при dip 90° даёт 180° против 0°.
Следствие: набор вертикальных трещин расщепляется в CSV на две группы и даёт два
кластера полюсов на противоположных краях стереограммы.

Решение владельца проекта (2026-07-29): **оставить как есть**, направление падения у
вертикальной плоскости физически неоднозначно; разбираться на этапе анализа.
До 89° поведение полностью стабильно.

### Вырожденные полигоны

Коллинеарные или совпадающие точки давали уверенные `dip`/`azimuth` без предупреждения.
Исправлено: `plane_degeneracy()` по отношению собственных чисел матрицы разброса
(λ2/λ1 < 1e-10 — точки на прямой; RMS-радиус ≈ 0 — точки совпадают). Значения
по-прежнему считаются и экспортируются (решение владельца), но помечаются в
`Measurement Info`, в Statistics, в отчёте диагностики и колонкой `degeneracy` в CSV.
Вытянутая трещина 10 м × 5 см даёт λ2/λ1 ≈ 2.5e-5 и вырожденной не считается.

Покрытие: `tests/test_plane_geometry.py`.

## Оставшиеся риски

- `Visualizer.plot_faces_stereonet()` не имеет unit-level геологической oracle-проверки. Нужна проверка на реальных измерениях и ожидаемых stereonet plots.
- `open_image_in_image_editor()` меняет layout через `bpy.ops.screen.area_split()`. Поведение оставлено по решению владельца проекта.
- Автоустановка зависимостей всё ещё сетезависима в legacy-сборке, если wheels в архив не положили. Extension-сборка это закрывает.
- Отдельный экспортный диалог выбора файла не сделан: экспорт по-прежнему пишет файлы с фиксированными именами рядом с `.blend` и перезаписывает их без подтверждения.
- Подписи в вьюпорте используют фиксированный `blf.size(12)` и не учитывают `ui_scale`.

## Regression commands

```powershell
python -m unittest discover -s tests -v
python -m py_compile __init__.py dependencies.py diagnostics.py parser.py operators.py panel.py visualization.py scene_measurements.py custom_measure_tool.py domain\__init__.py domain\measurements.py domain\geometry.py application\__init__.py application\services.py infrastructure\__init__.py infrastructure\blender_annotations.py infrastructure\blender_scene_measurements.py infrastructure\exporters.py tools\build_release.py tools\fetch_wheels.py
python tools\build_release.py
& 'E:\SteamLibrary\steamapps\common\Blender\blender.exe' --command extension validate dist\ScientiaJoints-3.3.0-extension.zip
& 'E:\SteamLibrary\steamapps\common\Blender\blender.exe' --background --factory-startup --python-expr "import sys; sys.path.insert(0, r'C:\Users\Wismut\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons'); import ScientiaJoints; import bpy; ScientiaJoints.register(); assert hasattr(bpy.types.Scene, 'az_real'); assert hasattr(bpy.ops.export, 'raw_edges'); assert hasattr(bpy.ops.wm, 'scientia_diagnostics'); from ScientiaJoints import diagnostics; print(diagnostics.report_text(bpy.context)); ScientiaJoints.unregister(); print('SCIENTIAJOINTS_BLENDER_SMOKE_OK')"
```

Установка в изолированный профиль (короткий путь обязателен, иначе сработает MAX_PATH):

```powershell
$env:BLENDER_USER_RESOURCES = 'C:\Temp\sj-profile'
& 'E:\SteamLibrary\steamapps\common\Blender\blender.exe' --background --command extension install-file -r user_default -e dist\ScientiaJoints-3.3.0-extension.zip
```

Current pure Python environment may skip non-empty visualization smoke tests if `matplotlib`, `numpy` or `mplstereonet` are not installed outside Blender. Blender addon registration still requires a real Blender Python runtime.
