bl_info = {
    "name": "ScientiaJoints",
    "author": "Scientia, Ivan Guzeev",
    "version": (2, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > ScientiaJoints",
    "description": "Export measurements with visualizations and adjustable settings",
    "category": "Object",
}

import bpy
import sys
import subprocess
import logging
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def install_packages():
    import ensurepip

    python_executable = sys.executable

    # Install pip if not installed
    try:
        ensurepip.bootstrap()
        logger.info("Pip installed successfully.")
    except Exception as e:
        logger.error(f"Failed to install pip: {e}")
        return

    # List of required packages
    packages = ['matplotlib', 'mplstereonet', 'numpy']

    # Install packages
    for package in packages:
        try:
            __import__(package)
            logger.info(f"'{package}' is already installed.")
        except ImportError:
            try:
                logger.info(f"Installing '{package}'...")
                subprocess.check_call([python_executable, '-m', 'pip', 'install', package])
                logger.info(f"'{package}' installed successfully.")
            except Exception as e:
                logger.error(f"Failed to install '{package}': {e}")

def update_real_time_update_histogram(self, context):
    if context.scene.real_time_update_histogram:
        context.scene.real_time_update_stereonet = False
        # Start the histogram real-time update operator
        bpy.ops.wm.real_time_histogram_update_operator()
    else:
        # Operator will stop itself
        pass

def update_real_time_update_stereonet(self, context):
    if context.scene.real_time_update_stereonet:
        context.scene.real_time_update_histogram = False
        # Start the stereonet real-time update operator
        bpy.ops.wm.real_time_stereonet_update_operator()
    else:
        # Operator will stop itself
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

class RulerSettings(bpy.types.PropertyGroup):
    is_custom_ruler: BoolProperty(default=False)
    color: FloatVectorProperty(size=3)
    opacity: FloatProperty()
    thickness: IntProperty()

def register():
    install_packages()

    # Register PropertyGroups
    bpy.utils.register_class(LightSettings)
    bpy.utils.register_class(RulerSettings)
    bpy.types.Scene.my_light_settings = PointerProperty(type=LightSettings)
    bpy.types.Scene.my_ruler_settings = PointerProperty(type=RulerSettings)

    # Import modules after installing packages and registering PropertyGroups
    try:
        from .operators import (
            ExportRawEdgesOperator,
            ExportRawFacesOperator,
            ExportProcessedEdgesOperator,
            ExportProcessedFacesOperator,
            ShowHistogramImageOperator,
            ShowStereonetImageOperator,
            RealTimeHistogramUpdateOperator,
            RealTimeStereonetUpdateOperator,
            ToggleLightSettingsOperator,
            ToggleRulerSettingsOperator
        )
        from .panel import MeasurementExporterPanel, init_properties
    except Exception as e:
        logger.error(f"Error importing modules: {e}")
        return

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

    bpy.types.Scene.update_interval = FloatProperty(
        name="Chart update interval",
        description="Set the interval (in seconds) for real-time updates. The interval can be changed in the visualization settings, but only when the automatic update function is disabled.",
        default=3.0,
        min=0.3,
        max=60.0
    )

    # Initialize custom properties
    init_properties()

    global classes
    classes = (
        ExportRawEdgesOperator,
        ExportRawFacesOperator,
        ExportProcessedEdgesOperator,
        ExportProcessedFacesOperator,
        ShowHistogramImageOperator,
        ShowStereonetImageOperator,
        RealTimeHistogramUpdateOperator,
        RealTimeStereonetUpdateOperator,
        ToggleLightSettingsOperator,
        ToggleRulerSettingsOperator,
        MeasurementExporterPanel,
    )

    for cls in classes:
        try:
            bpy.utils.register_class(cls)
            logger.info(f"Registered class: {cls.__name__}")
        except Exception as e:
            logger.error(f"Failed to register class {cls.__name__}: {e}")

    logger.info("ScientiaJoints addon registered.")

def unregister():
    global classes

    # Unregister PropertyGroups and delete Scene properties
    try:
        del bpy.types.Scene.my_light_settings
        del bpy.types.Scene.my_ruler_settings
    except AttributeError:
        pass

    bpy.utils.unregister_class(RulerSettings)
    bpy.utils.unregister_class(LightSettings)

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
            logger.info(f"Unregistered class: {cls.__name__}")
        except Exception as e:
            logger.error(f"Failed to unregister class {cls.__name__}: {e}")

    try:
        del bpy.types.Scene.az_real
        del bpy.types.Scene.az_model
        del bpy.types.Scene.figure_width
        del bpy.types.Scene.figure_height
        del bpy.types.Scene.marker_size
        del bpy.types.Scene.edge_width
        del bpy.types.Scene.real_time_update_histogram
        del bpy.types.Scene.real_time_update_stereonet
        del bpy.types.Scene.update_interval
        logger.info("Scene properties removed.")
    except AttributeError:
        pass

    # Clear custom properties
    from .panel import clear_properties
    clear_properties()

    logger.info("ScientiaJoints addon unregistered.")
