import bpy
from bpy.types import Panel
from .parser import MeasurementsParser
from .visualization import Visualizer
import logging

logger = logging.getLogger(__name__)

class MeasurementExporterPanel(Panel):
    bl_label = "ScientiaJoints"
    bl_idname = "OBJECT_PT_measurement_exporter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ScientiaJoints'

    def draw(self, context):
        layout = self.layout


        # 1. Visualization

        row = layout.row(align=True)
            # Histogram section
        col = row.column(align=True)
        subrow = col.row(align=True)
        subrow.operator("wm.show_histogram_image", text="Histogram", icon="SMOOTHCURVE")
        # "Display of the histogram of the distribution of linear measurements in the model"
        subrow.prop(context.scene, "real_time_update_histogram", text="", toggle=True, icon='FILE_REFRESH')
        # "Automatic chart update at a specified frequency. The frequency can be changed in the visualization settings, but only when the automatic update function is disabled."
            # Stereonet section
        col = row.column(align=True)
        subrow = col.row(align=True)
        subrow.operator("wm.show_stereonet_image", text="Stereonet", icon="SHADING_RENDERED")
        # "Display of the stereogram of plane orientations"
        subrow.prop(context.scene, "real_time_update_stereonet", text="", toggle=True, icon='FILE_REFRESH')
        # "Automatic chart update at a specified frequency. The frequency can be changed in the visualization settings, but only when the automatic update function is disabled."

        # 2. Export (under spoiler)
        box = layout.box()
        box.prop(context.scene, "show_export", text="Export", icon='TRIA_DOWN' if context.scene.show_export else 'TRIA_RIGHT', emboss=False)
        if context.scene.show_export:
            col = box.column(align=True)
            row = col.row(align=True)
            row.operator('export.raw_edges', text='Raw Edges', icon="EXPORT")
            # "Export of linear measurement coordinates to a TXT-file"
            row.operator('export.raw_faces', text='Raw Faces', icon="EXPORT")
            # "Export of angular measurement coordinates to a TXT-file"
            row = col.row(align=True)
            row.operator('export.processed_edges', text='CSV Edges', icon="EXPORT")
            # "Export of linear measurements with calculated center, distance, and measurement direction to a CSV-file"
            row.operator('export.processed_faces', text='CSV Faces', icon="EXPORT")
            # "Export of angular measurements with calculated center, dip angle, dip azimuth, measurement angle, and area to a CSV-file"
        

        # 3. Display Settings (under spoiler)
        box = layout.box()
        box.prop(context.scene, "show_display_settings", text="Display Settings", icon='TRIA_DOWN' if context.scene.show_display_settings else 'TRIA_RIGHT', emboss=False)
        if context.scene.show_display_settings:
            col = box.column(align=True)
            col.prop(context.scene, "update_interval", icon="TIME")
            col.separator()
            col.label(text="Figure Width and Height:")
            row = col.row(align=True)
            row.prop(context.scene, "figure_width", text="Width", icon="FIXED_SIZE")
            row.prop(context.scene, "figure_height", text="Height", icon="FIXED_SIZE")
            col.label(text="Stereonet Marker Size and Edge Width:")
            row = col.row(align=True)
            row.prop(context.scene, "marker_size", text="Marker Size", icon="PROP_OFF")
            row.prop(context.scene, "edge_width", text="Edge Width", icon="PROP_CON")

            col.label(text="View Settings")
            row = col.row(align=True)
            row.operator("wm.toggle_light_settings", text="Light Settings", icon="LIGHT")
            row.operator("wm.toggle_ruler_settings", text="Ruler Settings", icon="CON_DISTLIMIT")

        # 4. Statistics (under spoiler)
        box = layout.box()
        box.prop(context.scene, "show_statistics", text="Statistics", icon='TRIA_DOWN' if context.scene.show_statistics else 'TRIA_RIGHT', emboss=False)
        if context.scene.show_statistics:
            try:
                parser = MeasurementsParser()
                num_faces = len(parser.faces)
                num_edges = len(parser.edges)
                col = box.column(align=True)
                col.label(text=f"Faces: {num_faces}", icon="SNAP_FACE")
                col.label(text=f"Edges: {num_edges}", icon="MOD_EDGESPLIT")

                az_real = context.scene.az_real
                az_model = context.scene.az_model
                processed_edges = parser.get_processed_edges(az_real=az_real, az_model=az_model)

                if processed_edges:
                    visualizer = Visualizer(processed_edges, [])
                    stats = visualizer.get_edges_statistics()
                    col.separator()
                    col.label(text="Edges Statistics:", icon="SMOOTHCURVE")
                    col.label(text=f"Mean: {stats['Mean']:.2f}")
                    col.label(text=f"Median: {stats['Median']:.2f}")
                    col.label(text=f"Std Dev: {stats['Std Dev']:.2f}")
                    col.label(text=f"Min: {stats['Min']:.2f}")
                    col.label(text=f"Max: {stats['Max']:.2f}")
                else:
                    col.label(text="No processed edges for statistics.")
                    logger.info("No processed edges available for statistics.")
            except Exception as e:
                box.label(text="Error calculating statistics.")
                logger.error(f"Error calculating statistics: {e}")

        # 5. Azimuth Rotation (under spoiler)
        box = layout.box()
        box.prop(context.scene, "show_azimuth", text="Azimuth Rotation", icon='TRIA_DOWN' if context.scene.show_azimuth else 'TRIA_RIGHT', emboss=False)
        if context.scene.show_azimuth:
            col = box.column(align=True)
            row = col.row(align=True)
            row.prop(context.scene, "az_real")
            row.prop(context.scene, "az_model")
        
        

def init_properties():
    bpy.types.Scene.show_statistics = bpy.props.BoolProperty(name="Show Statistics", default=False)
    bpy.types.Scene.show_export = bpy.props.BoolProperty(name="Show Export", default=False)
    bpy.types.Scene.show_azimuth = bpy.props.BoolProperty(name="Show Azimuth", default=False)
    bpy.types.Scene.show_display_settings = bpy.props.BoolProperty(name="Show Display Settings", default=False)

def clear_properties():
    del bpy.types.Scene.show_statistics
    del bpy.types.Scene.show_export
    del bpy.types.Scene.show_azimuth
    del bpy.types.Scene.show_display_settings
