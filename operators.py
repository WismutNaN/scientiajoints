import bpy
from bpy.types import Operator
from . import dependencies as deps
from .dependencies import dependency_summary
from .parser import MeasurementsParser
from .visualization import update_histogram_image, update_stereonet_image
import logging

logger = logging.getLogger(__name__)

DIAGNOSTICS_TEXT_NAME = "ScientiaJoints Diagnostics"

#: Last diagnostics report, kept so the popup buttons can act on it without
#: rebuilding (and re-running the self-test) on every redraw.
_last_report = {"text": "", "problems": (), "checks": ()}

#: State of the background dependency installation, read by the panel.
_install_state = {"job": None, "status": "idle", "message": "", "log": ""}


# ============================================================
# Helpers: safe attribute access (compat between Blender versions)
# ============================================================

def _get_first_attr(obj, names, default=None):
    for n in names:
        try:
            if hasattr(obj, n):
                return getattr(obj, n)
        except Exception:
            continue
    return default


def _set_first_attr(obj, names, value):
    for n in names:
        try:
            if hasattr(obj, n):
                setattr(obj, n, value)
                return True
        except Exception:
            continue
    return False


def _finish_export_operator(operator, result):
    if result.ok:
        operator.report({'INFO'}, result.message)
        logger.info(result.message)
        return {'FINISHED'}

    if result.filename is None:
        operator.report({'WARNING'}, result.message)
        logger.warning(result.message)
    else:
        operator.report({'ERROR'}, result.message)
        logger.error(result.message)
    return {'CANCELLED'}


def _build_diagnostics_text(context):
    lines = []

    deps_ok, deps_message = dependency_summary()
    lines.append(deps_message)

    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(bpy.data, "is_saved"):
        lines.append("Scene diagnostics deferred: Blender registration context is restricted.")
        return deps_ok, "\n".join(lines)

    if bpy.data.is_saved:
        lines.append("Blend file: saved")
    else:
        lines.append("Blend file: not saved; export will ask to save first")

    parser_ok = True
    try:
        parser = MeasurementsParser()
        if parser.layer_found:
            lines.append(
                "Measurements: "
                f"faces={len(parser.faces)}, edges={len(parser.edges)}, strokes={parser.total_strokes_count}"
            )
        else:
            parser_ok = False
            lines.append("Measurements: RulerData3D layer not found")

        if parser.duplicate_strokes_count:
            lines.append(f"Duplicates skipped: {parser.duplicate_strokes_count}")
        if parser.ignored_strokes_count:
            lines.append(f"Unsupported strokes ignored: {parser.ignored_strokes_count}")

        for message in parser.diagnostic_messages:
            if message not in lines:
                lines.append(message)
    except Exception as e:
        parser_ok = False
        lines.append(f"Parser error: {e}")

    return deps_ok and parser_ok, "\n".join(lines)


def run_startup_diagnostics(context=None):
    context = context or bpy.context
    ok, text = _build_diagnostics_text(context)
    if ok:
        logger.info("ScientiaJoints startup diagnostics OK:\n%s", text)
    else:
        logger.warning("ScientiaJoints startup diagnostics found issues:\n%s", text)
    return ok, text


# ============================================================
# Dependency installation and diagnostics report
# ============================================================


def install_state():
    """Read-only view of the background installation for the panel."""
    return dict(_install_state)


def dependencies_are_installing():
    job = _install_state.get("job")
    return bool(job is not None and job.running)


def reset_install_state():
    _install_state.update(job=None, status="idle", message="", log="")


def start_dependency_install(automatic=False, on_finished=None):
    """Install the chart packages on a worker thread.

    Never blocks: Blender keeps drawing while pip runs, and the result is
    picked up by a timer. Returns False when an installation is already
    running.
    """
    if dependencies_are_installing():
        return False

    job = deps.BackgroundInstall()
    if not job.start():
        return False

    _install_state.update(
        job=job,
        status="running",
        message="Installing chart packages...",
        log="",
    )
    logger.info("ScientiaJoints dependency installation started (%s).", "automatic" if automatic else "manual")

    def _poll():
        if job.running:
            return 0.5
        result = job.result()
        _finish_dependency_install(result, automatic=automatic)
        if on_finished is not None:
            try:
                on_finished(result)
            except Exception:
                logger.debug("Dependency install callback failed", exc_info=True)
        return None

    try:
        bpy.app.timers.register(_poll, first_interval=0.5)
    except Exception as e:
        logger.warning("Could not schedule the dependency install poll: %s", e)
    return True


def _finish_dependency_install(result, automatic=False):
    if result is None:
        _install_state.update(job=None, status="failed", message="Installation produced no result.")
        return

    deps.record_install_attempt(result)
    log = "\n".join(result.messages)
    if result.log:
        log = f"{log}\n\n{result.log}"

    if result.ok:
        message = "Chart packages installed. Histogram and stereonet are available."
        logger.info("ScientiaJoints dependencies installed:\n%s", log)
    else:
        message = "Could not install: " + ", ".join(result.missing_after_install or ("unknown",))
        logger.warning("ScientiaJoints dependency installation failed:\n%s", log)

    _install_state.update(
        job=None,
        status="ok" if result.ok else "failed",
        message=message,
        log=log,
    )
    _tag_ui_redraw()


def _tag_ui_redraw():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'VIEW_3D', 'PROPERTIES'}:
                    area.tag_redraw()
    except Exception:
        pass


class ScientiaInstallDependenciesOperator(Operator):
    bl_idname = "wm.scientia_install_dependencies"
    bl_label = "Install Chart Packages"
    bl_description = (
        "Install matplotlib and mplstereonet into Blender Python. "
        "Wheels shipped with the add-on are used first, so this also works without internet access"
    )

    def execute(self, context):
        if dependencies_are_installing():
            self.report({'INFO'}, "Installation is already running.")
            return {'CANCELLED'}
        if not start_dependency_install(automatic=False):
            self.report({'ERROR'}, "Could not start the installation. See the console for details.")
            return {'CANCELLED'}
        self.report({'INFO'}, "Installing chart packages in the background; Blender stays responsive.")
        return {'FINISHED'}


class ScientiaDiagnosticsOperator(Operator):
    bl_idname = "wm.scientia_diagnostics"
    bl_label = "ScientiaJoints Diagnostics"
    bl_description = (
        "Collect Blender, device, dependency and measurement information, run a self-test, "
        "and list detected problems with their probable cause"
    )

    run_self_tests: bpy.props.BoolProperty(
        name="Run self-test",
        description="Render a test chart and export a test file to a temporary directory",
        default=True,
    )

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        from . import diagnostics

        try:
            report = diagnostics.build_report(context, run_tests=self.run_self_tests)
            text = diagnostics.format_report(report)
        except Exception as e:
            logger.error("Diagnostics failed: %s", e, exc_info=True)
            self.report({'ERROR'}, f"Diagnostics failed: {e}")
            return {'CANCELLED'}

        _last_report.update(text=text, problems=tuple(report.problems), checks=tuple(report.checks))
        _store_report_text(text)
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        problems = _last_report["problems"]
        checks = _last_report["checks"]

        header = layout.row()
        if not problems:
            header.label(text="No problems detected.", icon='CHECKMARK')
        else:
            errors = sum(1 for problem in problems if problem.severity == "error")
            warnings = sum(1 for problem in problems if problem.severity == "warning")
            header.label(
                text=f"{errors} error(s), {warnings} warning(s), {len(problems) - errors - warnings} note(s)",
                icon='ERROR' if errors else 'INFO',
            )

        if checks:
            box = layout.box()
            box.label(text="Self-test")
            grid = box.grid_flow(columns=2, even_columns=True, align=True)
            for check in checks:
                icon = 'CHECKMARK' if check.passed else 'X'
                grid.label(text=check.name, icon=icon)

        for problem in problems[:8]:
            box = layout.box()
            icon = {'error': 'ERROR', 'warning': 'ERROR', 'info': 'INFO'}.get(problem.severity, 'INFO')
            box.label(text=problem.title, icon=icon)
            for line in _wrap(problem.cause, 78):
                box.label(text=f"    {line}")
            for line in _wrap(problem.action, 78):
                box.label(text=f"    > {line}")

        if len(problems) > 8:
            layout.label(text=f"...and {len(problems) - 8} more in the full report.")

        layout.separator()
        layout.label(text=f"Full report is in the Text editor as '{DIAGNOSTICS_TEXT_NAME}'.")
        row = layout.row(align=True)
        row.operator("wm.scientia_diagnostics_copy", icon='COPYDOWN')
        row.operator("wm.scientia_diagnostics_save", icon='FILE_TICK')
        if deps.missing_packages():
            layout.operator("wm.scientia_install_dependencies", icon='IMPORT')


class ScientiaDiagnosticsCopyOperator(Operator):
    bl_idname = "wm.scientia_diagnostics_copy"
    bl_label = "Copy Report"
    bl_description = "Copy the full diagnostics report to the clipboard"

    def execute(self, context):
        text = _last_report["text"]
        if not text:
            self.report({'WARNING'}, "No report has been collected yet.")
            return {'CANCELLED'}
        context.window_manager.clipboard = text
        self.report({'INFO'}, "Diagnostics report copied to the clipboard.")
        return {'FINISHED'}


class ScientiaDiagnosticsSaveOperator(Operator):
    bl_idname = "wm.scientia_diagnostics_save"
    bl_label = "Save Report"
    bl_description = "Write the full diagnostics report to a text file"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filename_ext = ".txt"
    filter_glob: bpy.props.StringProperty(default="*.txt", options={'HIDDEN'})

    def invoke(self, context, event):
        import os
        import time

        if not self.filepath:
            directory = os.path.dirname(bpy.data.filepath) if bpy.data.is_saved else bpy.app.tempdir
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.filepath = os.path.join(directory or "", f"scientiajoints-diagnostics-{stamp}.txt")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        text = _last_report["text"]
        if not text:
            self.report({'WARNING'}, "No report has been collected yet.")
            return {'CANCELLED'}
        try:
            with open(bpy.path.abspath(self.filepath), "w", encoding="utf-8") as handle:
                handle.write(text)
        except Exception as e:
            self.report({'ERROR'}, f"Could not write the report: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Diagnostics report saved to {self.filepath}")
        return {'FINISHED'}


def _store_report_text(text):
    try:
        datablock = bpy.data.texts.get(DIAGNOSTICS_TEXT_NAME)
        if datablock is None:
            datablock = bpy.data.texts.new(DIAGNOSTICS_TEXT_NAME)
        datablock.clear()
        datablock.write(text)
    except Exception as e:
        logger.debug("Could not store the diagnostics text datablock: %s", e)


def _wrap(text, width):
    if not text:
        return ()
    import textwrap

    return tuple(textwrap.wrap(str(text), width=width))


# ============================================================
# Helpers: World background node
# ============================================================

def _ensure_world(scene: bpy.types.Scene) -> bpy.types.World:
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    world = scene.world
    if not world.use_nodes:
        world.use_nodes = True
    if world.node_tree is None:
        world.use_nodes = True
    return world


def _get_or_create_world_bg_node(world: bpy.types.World):
    """
    Returns (bg_node, out_node). Ensures nodes and link exist.
    """
    nt = world.node_tree
    nodes = nt.nodes
    links = nt.links

    # Output
    out_node = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None)
    if out_node is None:
        out_node = nodes.new("ShaderNodeOutputWorld")
        out_node.location = (400, 0)

    # Background
    bg_node = nodes.get("Background")
    if bg_node is None:
        bg_node = next((n for n in nodes if n.type == "BACKGROUND"), None)
    if bg_node is None:
        bg_node = nodes.new("ShaderNodeBackground")
        bg_node.location = (0, 0)
        bg_node.name = "Background"
        bg_node.label = "Background"

    # Ensure link: Background -> World Output (Surface)
    bg_out = bg_node.outputs.get("Background")
    out_in = out_node.inputs.get("Surface")
    if bg_out and out_in and not out_in.is_linked:
        links.new(bg_out, out_in)

    return bg_node, out_node


# ============================================================
# Helpers: Material + Principled
# ============================================================

def _get_or_create_principled_material(mat_name: str):
    """
    Ensures:
      - material exists
      - use_nodes = True
      - has Principled BSDF + Material Output
      - Principled is connected to Output Surface if not linked
    Returns (material, principled_node)
    """
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    if not mat.use_nodes:
        mat.use_nodes = True

    nt = mat.node_tree
    if nt is None:
        mat.use_nodes = True
        nt = mat.node_tree

    nodes = nt.nodes
    links = nt.links

    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        out = nodes.new("ShaderNodeOutputMaterial")
        out.location = (400, 0)

    principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (0, 0)

    surf = out.inputs.get("Surface")
    bsdf = principled.outputs.get("BSDF")
    if surf and bsdf and not surf.is_linked:
        links.new(bsdf, surf)

    return mat, principled


def _get_principled_inputs(material_or_node):
    """
    Accepts either a Material or a Principled node.
    Returns: (metallic_input, roughness_input, specular_input)
    """
    principled = None

    # If Material passed, find Principled in its node tree
    if isinstance(material_or_node, bpy.types.Material):
        mat = material_or_node
        if (mat is None) or (not getattr(mat, "use_nodes", False)) or (mat.node_tree is None):
            return None, None, None
        principled = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    else:
        principled = material_or_node

    if (principled is None) or (not hasattr(principled, "inputs")):
        return None, None, None

    metallic_input = principled.inputs.get("Metallic")
    roughness_input = principled.inputs.get("Roughness")

    # Name may vary across versions / node definitions
    specular_input = (
        principled.inputs.get("Specular IOR Level") or
        principled.inputs.get("Specular") or
        principled.inputs.get("Specular IOR")
    )

    return metallic_input, roughness_input, specular_input


# ============================================================
# Export operators
# ============================================================

class ExportRawEdgesOperator(Operator):
    bl_idname = "export.raw_edges"
    bl_label = "Raw Edges"
    bl_description = "Export of linear measurement coordinates to a TXT-file"

    def execute(self, context):
        logger.info("Exporting raw edges...")
        try:
            parser = MeasurementsParser()
            result = parser.export_raw_edges()
            return _finish_export_operator(self, result)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export raw edges: {e}")
            logger.error("Failed to export raw edges: %s", e, exc_info=True)
            return {'CANCELLED'}


class ExportRawFacesOperator(Operator):
    bl_idname = "export.raw_faces"
    bl_label = "Raw Faces"
    bl_description = "Export of angular measurement coordinates to a TXT-file"

    def execute(self, context):
        logger.info("Exporting raw faces...")
        try:
            parser = MeasurementsParser()
            result = parser.export_raw_faces()
            return _finish_export_operator(self, result)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export raw faces: {e}")
            logger.error("Failed to export raw faces: %s", e, exc_info=True)
            return {'CANCELLED'}


class ExportProcessedEdgesOperator(Operator):
    bl_idname = "export.processed_edges"
    bl_label = "Processed Edges"
    bl_description = "Export of linear measurements with calculated center, distance, and measurement direction to a CSV-file"

    def execute(self, context):
        logger.info("Processing edges...")
        try:
            parser = MeasurementsParser()
            az_real = context.scene.az_real
            az_model = context.scene.az_model
            result = parser.process_edges(az_real=az_real, az_model=az_model)
            if not result.ok:
                return _finish_export_operator(self, result)

            # Update visualization (safe)
            try:
                if context.area and hasattr(context.area, "tag_redraw"):
                    context.area.tag_redraw()
            except Exception:
                pass

            return _finish_export_operator(self, result)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to process edges: {e}")
            logger.error("Failed to process edges: %s", e, exc_info=True)
            return {'CANCELLED'}


class ExportProcessedFacesOperator(Operator):
    bl_idname = "export.processed_faces"
    bl_label = "Processed Faces"
    bl_description = "Export of angular measurements with calculated center, dip angle, dip azimuth, measurement angle, and area to a CSV-file"

    def execute(self, context):
        logger.info("Processing faces...")
        try:
            parser = MeasurementsParser()
            az_real = context.scene.az_real
            az_model = context.scene.az_model
            result = parser.process_faces(az_real=az_real, az_model=az_model)
            if not result.ok:
                return _finish_export_operator(self, result)

            # Update visualization (safe)
            try:
                if context.area and hasattr(context.area, "tag_redraw"):
                    context.area.tag_redraw()
            except Exception:
                pass

            return _finish_export_operator(self, result)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to process faces: {e}")
            logger.error("Failed to process faces: %s", e, exc_info=True)
            return {'CANCELLED'}


# ============================================================
# Visualization operators
# ============================================================

class ShowHistogramImageOperator(bpy.types.Operator):
    bl_idname = "wm.show_histogram_image"
    bl_label = "Open Histogram"
    bl_description = "Display of the histogram of the distribution of linear measurements in the model"

    def execute(self, context):
        try:
            if not update_histogram_image(context):
                self.report({'WARNING'}, "Histogram image was not created. See Blender console for details.")
                return {'CANCELLED'}
            logger.info("Histogram image displayed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to display histogram: {e}")
            logger.error("Failed to display histogram: %s", e, exc_info=True)
            return {'CANCELLED'}
        return {'FINISHED'}


class ShowStereonetImageOperator(bpy.types.Operator):
    bl_idname = "wm.show_stereonet_image"
    bl_label = "Open Stereonet"
    bl_description = "Display of the stereogram of plane orientations"

    def execute(self, context):
        try:
            if not update_stereonet_image(context):
                self.report({'WARNING'}, "Stereonet image was not created. See Blender console for details.")
                return {'CANCELLED'}
            logger.info("Stereonet image displayed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to display stereonet: {e}")
            logger.error("Failed to display stereonet: %s", e, exc_info=True)
            return {'CANCELLED'}
        return {'FINISHED'}


class _RealTimeChartUpdateOperator(bpy.types.Operator):
    """Shared modal loop for the automatic chart refresh.

    The running flag is also cleared from ``load_post`` and ``register()``:
    Blender can drop a modal handler without calling ``cancel()`` (loading a
    file, closing the window it ran in), and a stale flag used to make the
    toggle permanently answer "already running" until Blender was restarted.
    """

    _timer = None
    #: Overridden on every concrete subclass so the flag is not shared.
    _running = False
    scene_property = ""
    label = "chart"

    def _update_chart(self, context, report_errors=False):
        raise NotImplementedError

    def modal(self, context, event):
        scene = getattr(context, "scene", None)
        if scene is None or not getattr(scene, self.scene_property, False):
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            try:
                self._update_chart(context, report_errors=False)
            except Exception as e:
                logger.error("Real-time %s update failed: %s", self.label, e, exc_info=True)
            return {'RUNNING_MODAL'}

        if event.type == 'ESC':
            self.cancel(context)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        cls = type(self)
        if cls._running:
            self.report({'INFO'}, f"Real-time {self.label} update already running")
            return {'CANCELLED'}

        scene = getattr(context, "scene", None)
        window = getattr(context, "window", None)
        if scene is None or window is None:
            self.report({'WARNING'}, f"Real-time {self.label} update needs an open window.")
            if scene is not None:
                setattr(scene, self.scene_property, False)
            return {'CANCELLED'}

        # Draw once immediately; the modal keeps running even without data yet.
        try:
            self._update_chart(context, report_errors=False)
        except Exception as e:
            self.report({'WARNING'}, f"Initial {self.label} update failed: {e}")
            logger.error("Initial %s update failed: %s", self.label, e, exc_info=True)

        wm = context.window_manager
        self._timer = wm.event_timer_add(scene.update_interval, window=window)
        wm.modal_handler_add(self)
        cls._running = True
        logger.info("Real-time %s update operator started.", self.label)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = getattr(context, "window_manager", None)
        if self._timer is not None and wm is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
        self._timer = None
        type(self)._running = False
        logger.info("Real-time %s update operator stopped.", self.label)
        return {'CANCELLED'}


class RealTimeHistogramUpdateOperator(_RealTimeChartUpdateOperator):
    bl_idname = "wm.real_time_histogram_update_operator"
    bl_label = "Real-Time Histogram Update Operator"
    bl_description = ("Automatic chart update at a specified frequency. "
                      "The frequency can be changed in the visualization settings, "
                      "but only when the automatic update function is disabled.")

    _running = False
    scene_property = "real_time_update_histogram"
    label = "histogram"

    def _update_chart(self, context, report_errors=False):
        return update_histogram_image(context, report_errors=report_errors)


class RealTimeStereonetUpdateOperator(_RealTimeChartUpdateOperator):
    bl_idname = "wm.real_time_stereonet_update_operator"
    bl_label = "Real-Time Stereonet Update Operator"
    bl_description = ("Automatic chart update at a specified frequency. "
                      "The frequency can be changed in the visualization settings, "
                      "but only when the automatic update function is disabled.")

    _running = False
    scene_property = "real_time_update_stereonet"
    label = "stereonet"

    def _update_chart(self, context, report_errors=False):
        return update_stereonet_image(context, report_errors=report_errors)


def reset_realtime_operators():
    """Clear the running flags after a file load or a re-registration."""
    RealTimeHistogramUpdateOperator._running = False
    RealTimeStereonetUpdateOperator._running = False


# ============================================================
# Toggle: Light / Camera / World / Material (Blender 5.0 safe)
# ============================================================

class ToggleLightSettingsOperator(bpy.types.Operator):
    bl_idname = "wm.toggle_light_settings"
    bl_label = "Toggle Light and Camera Settings"
    bl_description = "Toggle between custom light, view, and camera settings, and default settings"

    def execute(self, context):
        scene = context.scene

        # PropertyGroup must exist (defined elsewhere in the addon)
        settings = getattr(scene, "my_light_settings", None)
        if settings is None:
            self.report({'ERROR'}, "Scene.my_light_settings is missing (PropertyGroup not registered?)")
            return {'CANCELLED'}

        eevee = getattr(scene, "eevee", None)

        # Blender variants: viewport samples vs render samples
        samples_names = ("taa_samples", "taa_render_samples")
        # Blender 5.0: GTAO removed; Raytracing checkbox exists in Eevee Next
        ray_flag_names = ("use_raytracing", "use_gtao")

        # Ensure world + background node exist
        world = _ensure_world(scene)
        bg_node, _out_node = _get_or_create_world_bg_node(world)

        # Ensure material exists and has Principled
        material, principled_node = _get_or_create_principled_material("material0")
        metallic_input, roughness_input, specular_input = _get_principled_inputs(principled_node)

        if not settings.is_custom_settings:
            # -----------------------------
            # Save current settings
            # -----------------------------
            settings.engine = scene.render.engine

            if eevee:
                settings.samples = int(_get_first_attr(eevee, samples_names, default=0) or 0)
                settings.raytracing = bool(_get_first_attr(eevee, ray_flag_names, default=False))
            else:
                settings.samples = 0
                settings.raytracing = False

            settings.film_transparent = scene.render.film_transparent

            try:
                settings.world_color = bg_node.inputs[0].default_value[:]
                settings.world_strength = float(bg_node.inputs[1].default_value)
            except Exception:
                settings.world_color = (1.0, 1.0, 1.0, 1.0)
                settings.world_strength = 1.0

            # Save material params (if sockets exist)
            if metallic_input is not None:
                settings.material_metallic = float(metallic_input.default_value)
            if roughness_input is not None:
                settings.material_roughness = float(roughness_input.default_value)
            if specular_input is not None:
                settings.material_specular_ior = float(specular_input.default_value)

            # Save camera
            camera = scene.camera.data if scene.camera else None
            if camera:
                settings.focal_length = float(camera.lens)
                settings.clip_start = float(camera.clip_start)
                settings.clip_end = float(camera.clip_end)

            # -----------------------------
            # Apply custom settings
            # -----------------------------
            # Prefer Eevee Next if available
            try:
                enum_items = scene.render.bl_rna.properties["engine"].enum_items
                if "BLENDER_EEVEE_NEXT" in enum_items.keys():
                    scene.render.engine = "BLENDER_EEVEE_NEXT"
                elif "BLENDER_EEVEE" in enum_items.keys():
                    scene.render.engine = "BLENDER_EEVEE"
            except Exception:
                # fallback: keep current engine
                pass

            if eevee:
                _set_first_attr(eevee, samples_names, 64)
                _set_first_attr(eevee, ray_flag_names, True)

            scene.render.film_transparent = True

            # World background: white + moderate strength
            try:
                bg_node.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
                bg_node.inputs[1].default_value = 0.5
            except Exception:
                pass

            # Material: matte, no specular
            try:
                if metallic_input is not None:
                    metallic_input.default_value = 0.0
                if roughness_input is not None:
                    roughness_input.default_value = 1.0
                if specular_input is not None:
                    specular_input.default_value = 0.0
            except Exception:
                pass

            # Camera defaults
            camera = scene.camera.data if scene.camera else None
            if camera:
                camera.lens = 50
                camera.clip_start = 0.1
                camera.clip_end = 10000

            settings.is_custom_settings = True

        else:
            # -----------------------------
            # Restore saved settings
            # -----------------------------
            scene.render.engine = settings.engine

            if eevee:
                _set_first_attr(eevee, samples_names, int(settings.samples))
                _set_first_attr(eevee, ray_flag_names, bool(settings.raytracing))

            scene.render.film_transparent = bool(settings.film_transparent)

            # World restore
            try:
                bg_node.inputs[0].default_value = settings.world_color
                bg_node.inputs[1].default_value = float(settings.world_strength)
            except Exception:
                pass

            # Material restore (if sockets exist)
            try:
                if metallic_input is not None:
                    metallic_input.default_value = float(settings.material_metallic)
                if roughness_input is not None:
                    roughness_input.default_value = float(settings.material_roughness)
                if specular_input is not None:
                    specular_input.default_value = float(settings.material_specular_ior)
            except Exception:
                pass

            # Camera restore
            camera = scene.camera.data if scene.camera else None
            if camera:
                camera.lens = float(settings.focal_length)
                camera.clip_start = float(settings.clip_start)
                camera.clip_end = float(settings.clip_end)

            settings.is_custom_settings = False

        return {'FINISHED'}
