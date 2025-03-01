import bpy
from bpy.types import Operator
from .parser import MeasurementsParser
from .visualization import update_histogram_image, update_stereonet_image
import logging

logger = logging.getLogger(__name__)

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
            # Update visualization
            context.area.tag_redraw()
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
            # Update visualization
            context.area.tag_redraw()
            self.report({'INFO'}, "Processed faces exported successfully.")
            logger.info("Faces processed.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to process faces: {e}")
            logger.error(f"Failed to process faces: {e}")
        return {'FINISHED'}


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
    bl_description = "Automatic chart update at a specified frequency. The frequency can be changed in the visualization settings, but only when the automatic update function is disabled."

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
    bl_description = "Automatic chart update at a specified frequency. The frequency can be changed in the visualization settings, but only when the automatic update function is disabled."

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




# class ToggleLightSettingsOperator(bpy.types.Operator):
#     bl_idname = "wm.toggle_light_settings"
#     bl_label = "Toggle Light Settings"
#     bl_description = "Toggle between custom light settings and default settings"
    
#     is_custom_settings = bpy.props.BoolProperty(default=False)
#     saved_settings = None  # Инициализация как None

#     def execute(self, context):
#         scene = context.scene
#         world = scene.world
#         material = bpy.data.materials.get("material0")

#         if not material:
#             self.report({'ERROR'}, "Material 'material0' not found")
#             return {'CANCELLED'}

#         if not material.use_nodes:
#             self.report({'ERROR'}, "Material 'material0' does not use nodes")
#             return {'CANCELLED'}

#         nodes = material.node_tree.nodes
#         principled_bsdf = None
#         for node in nodes:
#             if node.type == 'BSDF_PRINCIPLED':
#                 principled_bsdf = node
#                 break

#         if not principled_bsdf:
#             self.report({'ERROR'}, "Principled BSDF node not found in 'material0'")
#             return {'CANCELLED'}

#         metallic_input = principled_bsdf.inputs.get("Metallic")
#         roughness_input = principled_bsdf.inputs.get("Roughness")
#         specular_ior_input = principled_bsdf.inputs.get("Specular IOR Level")

#         if not (metallic_input and roughness_input and specular_ior_input):
#             self.report({'ERROR'}, "One or more required inputs not found in Principled BSDF")
#             return {'CANCELLED'}

#         # Если это первый вызов, сохраняем начальные настройки
#         if self.saved_settings is None:
#             # Сохранение начальных настроек
#             self.saved_settings = {
#                 "engine": scene.render.engine,
#                 "samples": scene.eevee.taa_samples,
#                 "raytracing": scene.eevee.use_gtao,
#                 "film_transparent": scene.render.film_transparent,
#                 "world_color": world.node_tree.nodes["Background"].inputs[0].default_value[:],
#                 "world_strength": world.node_tree.nodes["Background"].inputs[1].default_value,
#                 "material_metallic": metallic_input.default_value,
#                 "material_roughness": roughness_input.default_value,
#                 "material_specular_ior": specular_ior_input.default_value
#             }

#             # Установка кастомных настроек
#             scene.render.engine = 'BLENDER_EEVEE_NEXT'
#             scene.eevee.taa_samples = 64
#             scene.eevee.use_gtao = True
#             scene.render.film_transparent = True

#             world.node_tree.nodes["Background"].inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)  # Белый цвет
#             world.node_tree.nodes["Background"].inputs[1].default_value = 0.5  # Strength

#             metallic_input.default_value = 0.0
#             roughness_input.default_value = 1.0
#             specular_ior_input.default_value = 0.0

#         else:
#             # Восстановление исходных настроек
#             if "engine" in self.saved_settings:
#                 scene.render.engine = self.saved_settings["engine"]
#                 scene.eevee.taa_samples = self.saved_settings["samples"]
#                 scene.eevee.use_gtao = self.saved_settings["raytracing"]
#                 scene.render.film_transparent = self.saved_settings["film_transparent"]

#                 world.node_tree.nodes["Background"].inputs[0].default_value = self.saved_settings["world_color"]
#                 world.node_tree.nodes["Background"].inputs[1].default_value = self.saved_settings["world_strength"]

#                 metallic_input.default_value = self.saved_settings["material_metallic"]
#                 roughness_input.default_value = self.saved_settings["material_roughness"]
#                 specular_ior_input.default_value = self.saved_settings["material_specular_ior"]

#             # Очищаем настройки после восстановления
#             self.saved_settings = None

#         self.is_custom_settings = not self.is_custom_settings

#         return {'FINISHED'}



# class ToggleRulerSettingsOperator(bpy.types.Operator):
#     bl_idname = "wm.toggle_ruler_settings"
#     bl_label = "Toggle Ruler Settings"
#     bl_description = "Toggle between custom ruler settings and default settings"

#     is_custom_ruler_settings = bpy.props.BoolProperty(default=False)
#     saved_ruler_settings = None  # Инициализация как None

#     def execute(self, context):
#         scene = context.scene
#         ruler_layer = None

#         for annotation in scene.grease_pencil.layers:
#             if annotation.info == "RulerData3D":
#                 ruler_layer = annotation
#                 break

#         if not ruler_layer:
#             self.report({'ERROR'}, "RulerData3D layer not found in Annotations")
#             return {'CANCELLED'}

#         ruler_layer.hide = False  # Включаем слой

#         # Если это первый вызов и saved_ruler_settings еще не существует
#         if self.saved_ruler_settings is None:
#             self.saved_ruler_settings = {
#                 "color": ruler_layer.color[:],
#                 "opacity": ruler_layer.opacity,
#                 "thickness": int(ruler_layer.thickness)
#             }

#             # Установка новых значений
#             ruler_layer.color = (1.0, 0.0, 0.0)  # Красный цвет (только 3 значения)
#             ruler_layer.opacity = 0.7  # Непрозрачность
#             ruler_layer.thickness = 7  # Толщина как int

#         else:
#             # Восстановление исходных настроек
#             ruler_layer.color = self.saved_ruler_settings["color"]
#             ruler_layer.opacity = self.saved_ruler_settings["opacity"]
#             ruler_layer.thickness = self.saved_ruler_settings["thickness"]

#             # Удаление сохраненных настроек
#             self.saved_ruler_settings = None

#         self.is_custom_ruler_settings = not self.is_custom_ruler_settings

#         return {'FINISHED'}


class ToggleLightSettingsOperator(bpy.types.Operator):
    bl_idname = "wm.toggle_light_settings"
    bl_label = "Toggle Light and Camera Settings"
    bl_description = "Toggle between custom light, view, and camera settings, and default settings"

    def execute(self, context):
        scene = context.scene
        settings = scene.my_light_settings

        if not settings.is_custom_settings:
            # Сохраняем текущие настройки
            settings.engine = scene.render.engine
            settings.samples = scene.eevee.taa_samples
            settings.raytracing = scene.eevee.use_gtao
            settings.film_transparent = scene.render.film_transparent

            world = scene.world
            settings.world_color = world.node_tree.nodes["Background"].inputs[0].default_value[:]
            settings.world_strength = world.node_tree.nodes["Background"].inputs[1].default_value

            material = bpy.data.materials.get("material0")
            if not material or not material.use_nodes:
                self.report({'ERROR'}, "Material 'material0' not found or does not use nodes")
                return {'CANCELLED'}

            nodes = material.node_tree.nodes
            principled_bsdf = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
            if not principled_bsdf:
                self.report({'ERROR'}, "Principled BSDF node not found in 'material0'")
                return {'CANCELLED'}

            metallic_input = principled_bsdf.inputs.get("Metallic")
            roughness_input = principled_bsdf.inputs.get("Roughness")
            specular_ior_input = principled_bsdf.inputs.get("Specular IOR Level")

            settings.material_metallic = metallic_input.default_value
            settings.material_roughness = roughness_input.default_value
            settings.material_specular_ior = specular_ior_input.default_value

            camera = scene.camera.data if scene.camera else None
            if camera:
                settings.focal_length = camera.lens
                settings.clip_start = camera.clip_start
                settings.clip_end = camera.clip_end

            # Применяем кастомные настройки
            scene.render.engine = 'BLENDER_EEVEE_NEXT'
            scene.eevee.taa_samples = 64
            scene.eevee.use_gtao = True
            scene.render.film_transparent = True

            world.node_tree.nodes["Background"].inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
            world.node_tree.nodes["Background"].inputs[1].default_value = 0.5

            metallic_input.default_value = 0.0
            roughness_input.default_value = 1.0
            specular_ior_input.default_value = 0.0

            if camera:
                camera.lens = 50
                camera.clip_start = 0.1
                camera.clip_end = 10000

            settings.is_custom_settings = True
        else:
            # Восстанавливаем сохранённые настройки
            scene.render.engine = settings.engine
            scene.eevee.taa_samples = settings.samples
            scene.eevee.use_gtao = settings.raytracing
            scene.render.film_transparent = settings.film_transparent

            world = scene.world
            world.node_tree.nodes["Background"].inputs[0].default_value = settings.world_color
            world.node_tree.nodes["Background"].inputs[1].default_value = settings.world_strength

            material = bpy.data.materials.get("material0")
            if not material or not material.use_nodes:
                self.report({'ERROR'}, "Material 'material0' not found or does not use nodes")
                return {'CANCELLED'}

            nodes = material.node_tree.nodes
            principled_bsdf = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
            if not principled_bsdf:
                self.report({'ERROR'}, "Principled BSDF node not found in 'material0'")
                return {'CANCELLED'}

            metallic_input = principled_bsdf.inputs.get("Metallic")
            roughness_input = principled_bsdf.inputs.get("Roughness")
            specular_ior_input = principled_bsdf.inputs.get("Specular IOR Level")

            metallic_input.default_value = settings.material_metallic
            roughness_input.default_value = settings.material_roughness
            specular_ior_input.default_value = settings.material_specular_ior

            camera = scene.camera.data if scene.camera else None
            if camera:
                camera.lens = settings.focal_length
                camera.clip_start = settings.clip_start
                camera.clip_end = settings.clip_end

            settings.is_custom_settings = False

        return {'FINISHED'}


# Добавляем исправленный класс ToggleRulerSettingsOperator
class ToggleRulerSettingsOperator(bpy.types.Operator):
    bl_idname = "wm.toggle_ruler_settings"
    bl_label = "Toggle Ruler Settings"
    bl_description = "Toggle between custom ruler settings and default settings"

    def execute(self, context):
        scene = context.scene
        settings = scene.my_ruler_settings

        ruler_layer = None
        for annotation in scene.grease_pencil.layers:
            if annotation.info == "RulerData3D":
                ruler_layer = annotation
                break

        if not ruler_layer:
            self.report({'ERROR'}, "RulerData3D layer not found in Annotations")
            return {'CANCELLED'}

        ruler_layer.hide = False  # Включаем слой

        if not settings.is_custom_ruler:
            # Сохраняем текущие настройки
            settings.color = ruler_layer.color[:]
            settings.opacity = ruler_layer.opacity
            settings.thickness = ruler_layer.thickness

            # Применяем кастомные настройки
            ruler_layer.color = (1.0, 0.0, 0.0)  # Красный цвет
            ruler_layer.opacity = 0.7
            ruler_layer.thickness = 7
            settings.is_custom_ruler = True
        else:
            # Восстанавливаем сохранённые настройки
            ruler_layer.color = settings.color
            ruler_layer.opacity = settings.opacity
            ruler_layer.thickness = settings.thickness
            settings.is_custom_ruler = False

        return {'FINISHED'}

