import bpy
from bpy.types import Operator
from .parser import MeasurementsParser
from .visualization import update_histogram_image, update_stereonet_image
import logging

logger = logging.getLogger(__name__)


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


# ============================================================
# Helpers: Annotations / Measure layer discovery (Blender 5.0+)
# ============================================================

def _iter_annotation_datablocks():
    # Blender 5.0+: bpy.data.annotations (renamed); older: bpy.data.grease_pencils
    if hasattr(bpy.data, "annotations"):
        try:
            for ann in bpy.data.annotations:
                yield ann
        except Exception:
            pass

    if hasattr(bpy.data, "grease_pencils"):
        try:
            for gp in bpy.data.grease_pencils:
                yield gp
        except Exception:
            pass

    # Scene-linked fallback
    try:
        scene = bpy.context.scene
        if scene:
            for attr in ("annotation", "annotations", "grease_pencil"):
                if hasattr(scene, attr):
                    v = getattr(scene, attr)
                    if v:
                        yield v
    except Exception:
        pass


def _find_ruler_layer(layer_name="RulerData3D"):
    for db in _iter_annotation_datablocks():
        layers = getattr(db, "layers", None)
        if not layers:
            continue

        try:
            if hasattr(layers, "get"):
                ly = layers.get(layer_name)
                if ly:
                    return db, ly
        except Exception:
            pass

        try:
            ly = layers[layer_name]
            if ly:
                return db, ly
        except Exception:
            pass

        try:
            for ly in layers:
                lname = getattr(ly, "info", None) or getattr(ly, "name", None) or ""
                if str(lname) == layer_name or str(lname).startswith(layer_name):
                    return db, ly
        except Exception:
            pass

    return None, None


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
            parser.export_raw_edges()
            self.report({'INFO'}, "Raw edges exported successfully.")
            logger.info("Raw edges exported.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export raw edges: {e}")
            logger.error(f"Failed to export raw edges: {e}")
        return {'FINISHED'}


class ExportRawFacesOperator(Operator):
    bl_idname = "export.raw_faces"
    bl_label = "Raw Faces"
    bl_description = "Export of angular measurement coordinates to a TXT-file"

    def execute(self, context):
        logger.info("Exporting raw faces...")
        try:
            parser = MeasurementsParser()
            parser.export_raw_faces()
            self.report({'INFO'}, "Raw faces exported successfully.")
            logger.info("Raw faces exported.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export raw faces: {e}")
            logger.error(f"Failed to export raw faces: {e}")
        return {'FINISHED'}


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
            parser.process_edges(az_real=az_real, az_model=az_model)

            # Update visualization (safe)
            try:
                if context.area and hasattr(context.area, "tag_redraw"):
                    context.area.tag_redraw()
            except Exception:
                pass

            self.report({'INFO'}, "Processed edges exported successfully.")
            logger.info("Edges processed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to process edges: {e}")
            logger.error(f"Failed to process edges: {e}")
        return {'FINISHED'}


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
            parser.process_faces(az_real=az_real, az_model=az_model)

            # Update visualization (safe)
            try:
                if context.area and hasattr(context.area, "tag_redraw"):
                    context.area.tag_redraw()
            except Exception:
                pass

            self.report({'INFO'}, "Processed faces exported successfully.")
            logger.info("Faces processed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to process faces: {e}")
            logger.error(f"Failed to process faces: {e}")
        return {'FINISHED'}


# ============================================================
# Visualization operators
# ============================================================

class ShowHistogramImageOperator(bpy.types.Operator):
    bl_idname = "wm.show_histogram_image"
    bl_label = "Open Histogram"
    bl_description = "Display of the histogram of the distribution of linear measurements in the model"

    def execute(self, context):
        try:
            update_histogram_image(context)
            logger.info("Histogram image displayed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to display histogram: {e}")
            logger.error(f"Failed to display histogram: {e}")
        return {'FINISHED'}


class ShowStereonetImageOperator(bpy.types.Operator):
    bl_idname = "wm.show_stereonet_image"
    bl_label = "Open Stereonet"
    bl_description = "Display of the stereogram of plane orientations"

    def execute(self, context):
        try:
            update_stereonet_image(context)
            logger.info("Stereonet image displayed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to display stereonet: {e}")
            logger.error(f"Failed to display stereonet: {e}")
        return {'FINISHED'}


class RealTimeHistogramUpdateOperator(bpy.types.Operator):
    bl_idname = "wm.real_time_histogram_update_operator"
    bl_label = "Real-Time Histogram Update Operator"
    bl_description = ("Automatic chart update at a specified frequency. "
                      "The frequency can be changed in the visualization settings, "
                      "but only when the automatic update function is disabled.")

    _timer = None
    _running = False

    def modal(self, context, event):
        if not context.scene.real_time_update_histogram:
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            try:
                update_histogram_image(context, report_errors=False)
            except Exception as e:
                logger.error(f"Real-time histogram update failed: {e}")
            return {'RUNNING_MODAL'}

        elif event.type in {'ESC'}:
            self.cancel(context)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        if RealTimeHistogramUpdateOperator._running:
            self.report({'INFO'}, "Real-time histogram update already running")
            return {'CANCELLED'}

        # Open histogram if not already open
        update_histogram_image(context, report_errors=False)

        wm = context.window_manager
        self._timer = wm.event_timer_add(context.scene.update_interval, window=context.window)
        wm.modal_handler_add(self)
        RealTimeHistogramUpdateOperator._running = True
        logger.info("Real-time histogram update operator started.")
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
        RealTimeHistogramUpdateOperator._running = False
        logger.info("Real-time histogram update operator stopped.")
        return {'CANCELLED'}


class RealTimeStereonetUpdateOperator(bpy.types.Operator):
    bl_idname = "wm.real_time_stereonet_update_operator"
    bl_label = "Real-Time Stereonet Update Operator"
    bl_description = ("Automatic chart update at a specified frequency. "
                      "The frequency can be changed in the visualization settings, "
                      "but only when the automatic update function is disabled.")

    _timer = None
    _running = False

    def modal(self, context, event):
        if not context.scene.real_time_update_stereonet:
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            try:
                update_stereonet_image(context, report_errors=False)
            except Exception as e:
                logger.error(f"Real-time stereonet update failed: {e}")
            return {'RUNNING_MODAL'}

        elif event.type in {'ESC'}:
            self.cancel(context)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        if RealTimeStereonetUpdateOperator._running:
            self.report({'INFO'}, "Real-time stereonet update already running")
            return {'CANCELLED'}

        # Open stereonet if not already open
        update_stereonet_image(context, report_errors=False)

        wm = context.window_manager
        self._timer = wm.event_timer_add(context.scene.update_interval, window=context.window)
        wm.modal_handler_add(self)
        RealTimeStereonetUpdateOperator._running = True
        logger.info("Real-time stereonet update operator started.")
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
        RealTimeStereonetUpdateOperator._running = False
        logger.info("Real-time stereonet update operator stopped.")
        return {'CANCELLED'}


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


# ============================================================
# Toggle: Ruler annotation settings
# ============================================================

class ToggleRulerSettingsOperator(bpy.types.Operator):
    bl_idname = "wm.toggle_ruler_settings"
    bl_label = "Toggle Ruler Settings"
    bl_description = "Toggle between custom ruler settings and default settings"

    def execute(self, context):
        scene = context.scene

        settings = getattr(scene, "my_ruler_settings", None)
        if settings is None:
            self.report({'ERROR'}, "Scene.my_ruler_settings is missing (PropertyGroup not registered?)")
            return {'CANCELLED'}

        _, ruler_layer = _find_ruler_layer("RulerData3D")
        if not ruler_layer:
            self.report({'ERROR'}, "RulerData3D layer not found (no Measure annotations in the scene?)")
            return {'CANCELLED'}

        # Ensure the layer is visible
        if hasattr(ruler_layer, "hide"):
            try:
                ruler_layer.hide = False
            except Exception:
                pass

        if not settings.is_custom_ruler:
            # Save current settings
            try:
                if hasattr(ruler_layer, "color"):
                    settings.color = ruler_layer.color[:]
            except Exception:
                pass
            try:
                if hasattr(ruler_layer, "opacity"):
                    settings.opacity = float(ruler_layer.opacity)
            except Exception:
                pass
            try:
                if hasattr(ruler_layer, "thickness"):
                    settings.thickness = int(ruler_layer.thickness)
            except Exception:
                pass

            # Apply custom settings
            try:
                if hasattr(ruler_layer, "color"):
                    ruler_layer.color = (1.0, 0.0, 0.0)  # Red
            except Exception:
                pass
            try:
                if hasattr(ruler_layer, "opacity"):
                    ruler_layer.opacity = 0.7
            except Exception:
                pass
            try:
                if hasattr(ruler_layer, "thickness"):
                    ruler_layer.thickness = 7
            except Exception:
                pass

            settings.is_custom_ruler = True
        else:
            # Restore saved settings
            try:
                if hasattr(ruler_layer, "color"):
                    ruler_layer.color = settings.color
            except Exception:
                pass
            try:
                if hasattr(ruler_layer, "opacity"):
                    ruler_layer.opacity = float(settings.opacity)
            except Exception:
                pass
            try:
                if hasattr(ruler_layer, "thickness"):
                    ruler_layer.thickness = int(settings.thickness)
            except Exception:
                pass

            settings.is_custom_ruler = False

        return {'FINISHED'}
