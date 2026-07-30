# The version here is a copy: Blender reads bl_info with ast.literal_eval before
# importing the add-on, so it cannot be computed. blender_manifest.toml is the
# source; `python tools/version.py <new version>` writes both.
bl_info = {
    "name": "ScientiaJoints",
    "author": "Scientia, Ivan Guzeev",
    "version": (3, 4, 7),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > ScientiaJoints",
    "description": "Export measurements with visualizations and adjustable settings",
    "category": "Object",
}

import bpy
import sys
import logging


def _purge_stale_submodules():
    """Drop cached submodules so an in-place update cannot mix old and new code.

    ``addon_utils.enable()`` reloads only this top-level package. Every
    submodule stays in ``sys.modules`` from the previous version, so installing
    an update without restarting Blender used to fail with
    ``ImportError: cannot import name ... from ScientiaJoints.operators``:
    the new ``__init__.py`` was asking a stale ``operators`` module for symbols
    that only exist in the new file. Clearing them here, before any submodule
    is imported below, makes the update read every file from disk again.
    """
    prefix = __name__ + "."
    for name in [name for name in sys.modules if name.startswith(prefix)]:
        del sys.modules[name]


_purge_stale_submodules()

from . import dependencies
from .scene_measurements import (
    define_scene_measurement_properties,
    scene_measurement_property_classes,
    scene_measurement_scene_properties,
)
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
    EnumProperty,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

classes = ()
_startup_diagnostics_generation = 0

_CORE_SCENE_PROPERTY_NAMES = (
    "my_light_settings",
    "az_real",
    "az_model",
    "figure_width",
    "figure_height",
    "marker_size",
    "edge_width",
    "marker_face_color",
    "marker_edge_color",
    "density_sigma",
    "stereonet_hemisphere",
    "real_time_update_histogram",
    "real_time_update_stereonet",
    "real_time_update_traces",
    "update_interval",
    *scene_measurement_scene_properties(),
)

_PANEL_SCENE_PROPERTY_NAMES = (
    "show_statistics",
    "show_export",
    "show_azimuth",
    "show_display_settings",
    "show_measurement_info",
    "show_measurement_display_settings",
    "show_label_field_settings",
    "show_overlay_style_settings",
)


def _schedule_startup_diagnostics():
    generation = _startup_diagnostics_generation

    def _run_later():
        try:
            if generation != _startup_diagnostics_generation:
                return None
            if getattr(bpy.context, "scene", None) is None:
                return 1.0
            _run_startup_diagnostics(bpy.context)
        except Exception as e:
            logger.warning("ScientiaJoints delayed startup diagnostics failed: %s", e, exc_info=True)
        return None

    try:
        bpy.app.timers.register(_run_later, first_interval=1.0)
    except Exception as e:
        logger.debug("Failed to schedule delayed startup diagnostics: %s", e)


def _run_startup_diagnostics(context):
    from . import operators

    runner = getattr(operators, "run_startup_diagnostics", None)
    if runner is None:
        logger.warning(
            "Startup diagnostics are unavailable because operators.py is from an older "
            "ScientiaJoints version. Close Blender and perform a clean add-on reinstall."
        )
        return None
    return runner(context)


#: Names ``register()`` needs from each module, checked before importing them
#: so a half-updated installation reports the real problem instead of an
#: ImportError deep inside registration.
_REQUIRED_MODULE_SYMBOLS = {
    "operators.py": ("ScientiaDiagnosticsOperator", "ScientiaInstallDependenciesOperator"),
    "custom_measure_tool.py": ("reset_tool_state",),
    "diagnostics.py": ("build_report",),
}


def _check_module_files_match():
    """Fail early and clearly when the add-on directory holds mixed versions.

    Copying new files over an old installation, or an interrupted install, can
    leave modules from two versions side by side. The resulting ImportError
    names a symbol instead of the cause, so the files are checked as text
    before anything is imported.
    """
    import os

    directory = os.path.dirname(os.path.abspath(__file__))
    stale = []
    for filename, symbols in _REQUIRED_MODULE_SYMBOLS.items():
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as e:
            stale.append(f"{filename} cannot be read ({e})")
            continue
        missing = [symbol for symbol in symbols if symbol not in source]
        if missing:
            stale.append(f"{filename} is missing {', '.join(missing)}")

    if stale:
        raise RuntimeError(
            "ScientiaJoints installation is incomplete: "
            + "; ".join(stale)
            + f". Close Blender, delete the folder {directory}, then install the release archive again."
        )


def _delete_scene_properties(names):
    for name in names:
        try:
            if hasattr(bpy.types.Scene, name):
                delattr(bpy.types.Scene, name)
                logger.info("Scene property removed: %s", name)
        except Exception as e:
            logger.debug("Failed to remove Scene property %s: %s", name, e)


def _safe_unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
        logger.info("Unregistered class: %s", cls.__name__)
    except Exception as e:
        logger.debug("Class %s was not registered or could not be unregistered: %s", cls.__name__, e)


def _cleanup_partial_registration(registered_classes=()):
    _unregister_handlers()
    try:
        from .custom_measure_tool import unregister_measure_tool
        unregister_measure_tool()
    except Exception:
        pass
    for cls in reversed(tuple(registered_classes)):
        _safe_unregister_class(cls)
    _delete_scene_properties(_PANEL_SCENE_PROPERTY_NAMES)
    _delete_scene_properties(_CORE_SCENE_PROPERTY_NAMES)
    for cls in reversed(scene_measurement_property_classes()):
        _safe_unregister_class(cls)
    _safe_unregister_class(LightSettings)


def install_packages():
    """Kept for backwards compatibility with user scripts.

    Registration no longer installs anything synchronously; see
    :func:`_schedule_dependency_install`.
    """
    result = dependencies.install_required_packages()
    for message in result.messages:
        if result.ok:
            logger.info(message)
        else:
            logger.warning(message)
    return result


def _schedule_dependency_install():
    """Start the automatic dependency install after Blender is up.

    ``register()`` must never wait on pip: on a restricted network the
    download stalls until it times out, and Blender looked frozen at every
    start. The attempt runs on a worker thread, and it is not repeated more
    than once a day unless the user presses the button in the panel.
    """
    import os

    if bpy.app.background:
        # A headless render or a batch script must never pip-install anything.
        return
    if os.environ.get("SCIENTIAJOINTS_NO_AUTO_INSTALL"):
        logger.info("Automatic dependency install disabled by SCIENTIAJOINTS_NO_AUTO_INSTALL.")
        return

    def _start():
        try:
            from . import operators

            missing = dependencies.missing_packages()
            if missing and not dependencies.should_attempt_automatic_install():
                if missing:
                    logger.warning(
                        "ScientiaJoints chart packages are missing (%s). An automatic install was "
                        "already attempted; use Install chart packages in the sidebar to retry.",
                        ", ".join(missing),
                    )
                return None
            # Even when every module is discoverable, verify imports in
            # timeout-protected child processes. This catches an incompatible
            # binary wheel without importing it on Blender's UI thread.
            operators.start_dependency_install(automatic=True)
        except Exception as e:
            logger.warning("Could not start the automatic dependency install: %s", e, exc_info=True)
        return None

    try:
        bpy.app.timers.register(_start, first_interval=2.0)
    except Exception as e:
        logger.debug("Failed to schedule the dependency install: %s", e)


def _start_realtime_operator(operator_name, log_label):
    """Launch a modal operator outside the property update callback.

    Calling ``bpy.ops`` directly from a property ``update`` callback runs in a
    restricted context where Blender may refuse or mishandle the call, so the
    start is deferred by one timer tick.
    """
    def _run():
        try:
            getattr(bpy.ops.wm, operator_name)('INVOKE_DEFAULT')
        except Exception as e:
            logger.error("Failed to start real-time %s update: %s", log_label, e, exc_info=True)
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.0)
    except Exception as e:
        logger.error("Could not schedule the real-time %s update: %s", log_label, e, exc_info=True)


#: The real-time chart toggles. Only one runs at a time: each drives a modal
#: operator on a timer that reloads an image into the image editor, and two of
#: them doing that at once fight over the editor and pay the cost twice.
_REALTIME_TOGGLE_PROPERTIES = (
    "real_time_update_histogram",
    "real_time_update_stereonet",
    "real_time_update_traces",
)


def _stop_other_realtime_updates(scene, keep):
    """Switch off every real-time toggle except ``keep``.

    Setting one to False re-enters its own update callback, which returns
    immediately because the value is off, so this cannot recurse.
    """
    for name in _REALTIME_TOGGLE_PROPERTIES:
        if name != keep and getattr(scene, name, False):
            setattr(scene, name, False)


def update_real_time_update_histogram(self, context):
    if context.scene.real_time_update_histogram:
        _stop_other_realtime_updates(context.scene, "real_time_update_histogram")
        _start_realtime_operator("real_time_histogram_update_operator", "histogram")
    # Switching the toggle off lets the running modal operator stop itself.


def update_real_time_update_stereonet(self, context):
    if context.scene.real_time_update_stereonet:
        _stop_other_realtime_updates(context.scene, "real_time_update_stereonet")
        _start_realtime_operator("real_time_stereonet_update_operator", "stereonet")
    # Switching the toggle off lets the running modal operator stop itself.


def update_real_time_update_traces(self, context):
    if context.scene.real_time_update_traces:
        _stop_other_realtime_updates(context.scene, "real_time_update_traces")
        _start_realtime_operator("real_time_traces_update_operator", "trace histogram")
    # Switching the toggle off lets the running modal operator stop itself.


@bpy.app.handlers.persistent
def _on_file_load(*_args):
    """Reset module level state that belongs to the previous .blend file."""
    try:
        from .custom_measure_tool import reset_tool_state

        reset_tool_state()
    except Exception as e:
        logger.debug("Could not reset the measure tool state: %s", e)
    try:
        from .operators import reset_realtime_operators

        reset_realtime_operators()
    except Exception as e:
        logger.debug("Could not reset the real-time operator state: %s", e)
    try:
        from .panel import invalidate_statistics_cache

        invalidate_statistics_cache()
    except Exception as e:
        logger.debug("Could not reset the statistics cache: %s", e)


@bpy.app.handlers.persistent
def _on_undo(*_args):
    """Throw away the cached viewport geometry after an undo or a redo.

    Undo restores the measurement collection behind the add-on's back: nothing
    calls the helpers that bump the revision the overlay cache is keyed on, so
    without this the viewport would keep drawing the state that was undone.
    """
    try:
        from .scene_measurements import bump_measurement_revision

        bump_measurement_revision()
    except Exception as e:
        logger.debug("Could not invalidate the measurement overlay cache: %s", e)


_HANDLER_LISTS = (
    ("load_post", "_on_file_load"),
    ("undo_post", "_on_undo"),
    ("redo_post", "_on_undo"),
)


def _register_handlers():
    _unregister_handlers()
    bpy.app.handlers.load_post.append(_on_file_load)
    bpy.app.handlers.undo_post.append(_on_undo)
    bpy.app.handlers.redo_post.append(_on_undo)


def _unregister_handlers():
    for list_name, handler_name in _HANDLER_LISTS:
        handlers = getattr(bpy.app.handlers, list_name, None)
        if handlers is None:
            continue
        for handler in list(handlers):
            if getattr(handler, "__name__", "") == handler_name:
                try:
                    handlers.remove(handler)
                except Exception:
                    pass

# Define PropertyGroups
class LightSettings(bpy.types.PropertyGroup):
    is_custom_settings: BoolProperty(default=False)
    engine: StringProperty()
    samples: IntProperty()
    raytracing: BoolProperty()
    film_transparent: BoolProperty()
    world_color: FloatVectorProperty(size=4)
    world_strength: FloatProperty()
    material_metallic: FloatProperty()
    material_roughness: FloatProperty()
    material_specular_ior: FloatProperty()
    focal_length: FloatProperty()
    clip_start: FloatProperty()
    clip_end: FloatProperty()
    #: Viewport shading to go back to. One value for every 3D view: the
    #: inspection mode puts them all in Rendered, so it restores them all the
    #: same way rather than pretending to remember each one.
    viewport_shading: StringProperty()
    #: Colour management look to go back to, and the raking light object to
    #: delete. Empty when there was nothing to change or nothing was created.
    view_look: StringProperty()
    created_light: StringProperty()

def register():
    global classes, _startup_diagnostics_generation

    registered_classes = []
    try:
        _startup_diagnostics_generation += 1

        bpy.utils.register_class(LightSettings)
        for cls in scene_measurement_property_classes():
            bpy.utils.register_class(cls)
        bpy.types.Scene.my_light_settings = PointerProperty(type=LightSettings)
        define_scene_measurement_properties()

        # Import modules after dependency setup and PropertyGroup registration.
        _check_module_files_match()
        from .operators import (
            ExportRawEdgesOperator,
            ExportRawFacesOperator,
            ExportProcessedEdgesOperator,
            ExportProcessedFacesOperator,
            ExportProcessedTracesOperator,
            ShowHistogramImageOperator,
            ShowTracesHistogramImageOperator,
            ShowStereonetImageOperator,
            RealTimeHistogramUpdateOperator,
            RealTimeStereonetUpdateOperator,
            RealTimeTracesUpdateOperator,
            ScientiaDiagnosticsCopyOperator,
            ScientiaDiagnosticsOperator,
            ScientiaDiagnosticsRunTestsOperator,
            ScientiaDiagnosticsSaveOperator,
            ScientiaInstallDependenciesOperator,
            ToggleLightSettingsOperator,
            reset_realtime_operators,
        )
        from .custom_measure_tool import (
            ScientiaDeleteActiveMeasurementOperator,
            ScientiaDeselectMeasurementOperator,
            ScientiaMeasureDragOperator,
            ScientiaPolygonMeasureOperator,
            ScientiaTraceMeasureOperator,
            register_measure_tool,
        )
        from .panel import (
            MeasurementExporterPanel,
            ScientiaAssignCodeOperator,
            ScientiaClearCodeOperator,
            ScientiaMeasurementCodeMenu,
            init_properties,
        )

        # Define properties
        bpy.types.Scene.az_real = FloatProperty(
            name="Real Azimuth",
            description="Input the real azimuth value",
            default=0.0,
            min=0.0,
            max=360.0
        )

        bpy.types.Scene.az_model = FloatProperty(
            name="Model Azimuth",
            description="Input the model azimuth value",
            default=0.0,
            min=0.0,
            max=360.0
        )

        # Visualization settings
        bpy.types.Scene.figure_width = FloatProperty(
            name="Figure Width",
            description="Set the width of the figures",
            default=6.0,
            min=1.0,
            max=20.0
        )

        bpy.types.Scene.figure_height = FloatProperty(
            name="Figure Height",
            description="Set the height of the figures",
            default=6.0,
            min=1.0,
            max=20.0
        )

        bpy.types.Scene.marker_size = FloatProperty(
            name="Marker Size",
            description="Set the size of the markers on the stereonet",
            default=2.0,
            min=0.1,
            max=10.0
        )

        bpy.types.Scene.edge_width = FloatProperty(
            name="Edge Width",
            description="Set the width of marker edges on the stereonet",
            default=0.4,
            min=0,
            max=5.0
        )

        bpy.types.Scene.marker_face_color = FloatVectorProperty(
            name="Legacy Pole Color",
            description="Fallback color for stereonet poles without measurement/code color metadata",
            subtype='COLOR',
            size=3,
            default=(1.0, 1.0, 1.0),
            min=0.0,
            max=1.0
        )

        bpy.types.Scene.marker_edge_color = FloatVectorProperty(
            name="Pole Outline",
            description="Outline (edge) color of points (poles) on the stereonet",
            subtype='COLOR',
            size=3,
            default=(0.0, 0.0, 0.0),
            min=0.0,
            max=1.0
        )

        bpy.types.Scene.density_sigma = FloatProperty(
            name="Density Sigma",
            description="Smoothing parameter (sigma) for stereonet density contours",
            default=1.2,
            min=0.1,
            max=6.0,
            step=10,
            precision=1
        )

        bpy.types.Scene.stereonet_hemisphere = EnumProperty(
            name="Hemisphere",
            description="Hemisphere for stereonet plotting",
            items=[
                ('UPPER', 'Upper', 'Upper hemisphere'),
                ('LOWER', 'Lower', 'Lower hemisphere (dip direction + 180°)'),
            ],
            default='UPPER'
        )

        bpy.types.Scene.real_time_update_histogram = BoolProperty(
            name="Real-Time Update",
            description="Toggle real-time updating of the histogram",
            default=False,
            update=update_real_time_update_histogram
        )

        bpy.types.Scene.real_time_update_stereonet = BoolProperty(
            name="Real-Time Update",
            description="Toggle real-time updating of the stereonet",
            default=False,
            update=update_real_time_update_stereonet
        )

        bpy.types.Scene.real_time_update_traces = BoolProperty(
            name="Real-Time Update",
            description="Toggle real-time updating of the trace length histogram",
            default=False,
            update=update_real_time_update_traces
        )

        bpy.types.Scene.update_interval = FloatProperty(
            name="Chart update interval",
            description="Set the interval (in seconds) for real-time updates. The interval can be changed in the visualization settings, but only when the automatic update function is disabled.",
            default=3.0,
            min=0.3,
            max=60.0
        )

        # Initialize custom properties
        init_properties()

        class_candidates = (
            ScientiaMeasureDragOperator,
            ScientiaPolygonMeasureOperator,
            ScientiaTraceMeasureOperator,
            ScientiaDeleteActiveMeasurementOperator,
            ScientiaDeselectMeasurementOperator,
            ExportRawEdgesOperator,
            ExportRawFacesOperator,
            ExportProcessedEdgesOperator,
            ExportProcessedFacesOperator,
            ExportProcessedTracesOperator,
            ShowHistogramImageOperator,
            ShowTracesHistogramImageOperator,
            ShowStereonetImageOperator,
            RealTimeHistogramUpdateOperator,
            RealTimeStereonetUpdateOperator,
            RealTimeTracesUpdateOperator,
            ToggleLightSettingsOperator,
            ScientiaInstallDependenciesOperator,
            ScientiaDiagnosticsOperator,
            ScientiaDiagnosticsRunTestsOperator,
            ScientiaDiagnosticsCopyOperator,
            ScientiaDiagnosticsSaveOperator,
            ScientiaAssignCodeOperator,
            ScientiaClearCodeOperator,
            ScientiaMeasurementCodeMenu,
            MeasurementExporterPanel,
        )

        for cls in class_candidates:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)
            logger.info("Registered class: %s", cls.__name__)

        register_measure_tool()
        reset_realtime_operators()
        _register_handlers()

        classes = tuple(registered_classes)

        try:
            diagnostics = _run_startup_diagnostics(bpy.context)
            if diagnostics is not None and "Scene diagnostics deferred" in diagnostics[1]:
                _schedule_startup_diagnostics()
        except Exception as e:
            logger.warning("ScientiaJoints startup diagnostics failed: %s", e, exc_info=True)

        _schedule_dependency_install()

        logger.info("ScientiaJoints addon registered.")
    except Exception:
        logger.exception("Failed to register ScientiaJoints addon.")
        _cleanup_partial_registration(registered_classes)
        classes = ()
        raise


def unregister():
    global classes, _startup_diagnostics_generation

    _startup_diagnostics_generation += 1
    _unregister_handlers()

    registered_classes = tuple(classes)
    try:
        from .custom_measure_tool import unregister_measure_tool
        unregister_measure_tool()
    except Exception as e:
        logger.debug("Scientia measure toolbar tool was not registered or could not be unregistered: %s", e)

    for cls in reversed(registered_classes):
        _safe_unregister_class(cls)
    classes = ()

    _delete_scene_properties(_PANEL_SCENE_PROPERTY_NAMES)
    _delete_scene_properties(_CORE_SCENE_PROPERTY_NAMES)
    for cls in reversed(scene_measurement_property_classes()):
        _safe_unregister_class(cls)
    _safe_unregister_class(LightSettings)

    logger.info("ScientiaJoints addon unregistered.")
