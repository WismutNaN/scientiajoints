import bpy
import logging
import os
from .parser import MeasurementsParser

logger = logging.getLogger(__name__)

class Visualizer:
    def __init__(self, edges_data, faces_data, figure_width=6.0, figure_height=6.0, marker_size=2.0, edge_width=0.4):
        self.edges_data = edges_data
        self.faces_data = faces_data
        self.figure_width = figure_width
        self.figure_height = figure_height
        self.marker_size = marker_size
        self.edge_width = edge_width

    def get_edges_statistics(self):
        import numpy as np
        try:
            lengths = [edge.length for edge in self.edges_data]
            if not lengths:
                return {}
            mean = np.mean(lengths)
            median = np.median(lengths)
            std_dev = np.std(lengths)
            min_val = np.min(lengths)
            max_val = np.max(lengths)
            stats = {
                'Mean': mean,
                'Median': median,
                'Std Dev': std_dev,
                'Min': min_val,
                'Max': max_val
            }
            return stats
        except Exception as e:
            logger.error(f"Error calculating edge statistics: {e}")
            return {}

    def plot_edges_histogram(self):
        try:
            import matplotlib
            matplotlib.use('Agg')  # Use 'Agg' backend for rendering without GUI
            import matplotlib.pyplot as plt
            import numpy as np
            import tempfile

            lengths = [edge.length for edge in self.edges_data]
            if not lengths:
                logger.warning("No edge data to plot.")
                return None, {}

            stats = self.get_edges_statistics()

            plt.figure(figsize=(self.figure_width, self.figure_height))
            plt.hist(lengths, bins=20, color='#f49931', edgecolor='black')
            plt.title('Histogram of Edge Lengths')
            plt.xlabel('Length')
            plt.ylabel('Frequency')

            # Save plot to temporary file
            temp_dir = tempfile.gettempdir()
            histogram_path = os.path.join(temp_dir, 'edges_histogram.png')
            plt.savefig(histogram_path)
            plt.close()
            logger.info(f"Edges histogram saved to {histogram_path}")

            return histogram_path, stats
        except Exception as e:
            logger.error(f"Error generating edges histogram: {e}")
            return None, {}

    def plot_faces_stereonet(self):
        try:
            import mplstereonet
            import matplotlib.pyplot as plt
            import matplotlib.colors
            import tempfile

            if not self.faces_data:
                logger.warning("No face data to plot.")
                return None

            strikes = []
            dips = []

            for face in self.faces_data:
                strike = (face.rotated_azimuth + 90) % 360
                dip = face.dip
                strikes.append(strike)
                dips.append(dip)

            fig, ax = mplstereonet.subplots(figsize=(self.figure_width, self.figure_height))
            ax.grid(kind='polar')

            # Create custom colormap
            custom_cmap = matplotlib.colors.ListedColormap([
                '#ffffff', '#ecf0f5', '#d3eef1', '#b6f2de',
                '#97f5ac', '#94f877', '#c5fb58', '#fde839',
                '#fe811c', '#ff0000'
            ])

            # Plot density contour fill
            ax.density_contourf(
                strikes, dips,
                measurement='poles',
                method='exponential_kamb',
                cmap=custom_cmap
            )

            # Plot poles with specified style
            ax.pole(
                strikes, dips,
                marker='o',
                markerfacecolor='white',
                markeredgecolor='black',
                markersize=self.marker_size,
                markeredgewidth=self.edge_width
            )

            temp_dir = tempfile.gettempdir()
            stereonet_path = os.path.join(temp_dir, 'faces_stereonet.png')
            fig.savefig(stereonet_path)
            plt.close(fig)
            logger.info(f"Faces stereonet saved to {stereonet_path}")
            return stereonet_path
        except Exception as e:
            logger.error(f"Error generating faces stereonet: {e}")
            return None

def update_histogram_image(context, report_errors=True):
    import os
    parser = MeasurementsParser()
    az_real = context.scene.az_real
    az_model = context.scene.az_model
    figure_width = context.scene.figure_width
    figure_height = context.scene.figure_height

    processed_edges = parser.get_processed_edges(az_real=az_real, az_model=az_model)

    visualizer = Visualizer(processed_edges, [], figure_width=figure_width, figure_height=figure_height)
    histogram_path, _ = visualizer.plot_edges_histogram()

    if histogram_path and os.path.exists(histogram_path):
        image_name = os.path.basename(histogram_path)
        image = bpy.data.images.get(image_name)
        if image:
            # Reload image to update it
            image.filepath = histogram_path
            image.reload()
        else:
            image = bpy.data.images.load(histogram_path)

        # Open image in Image Editor
        open_image_in_image_editor(image)
        logger.info("Histogram image updated.")
    else:
        if report_errors:
            logger.warning("Histogram image not found.")

def update_stereonet_image(context, report_errors=True):
    import os
    parser = MeasurementsParser()
    az_real = context.scene.az_real
    az_model = context.scene.az_model
    figure_width = context.scene.figure_width
    figure_height = context.scene.figure_height
    marker_size = context.scene.marker_size
    edge_width = context.scene.edge_width

    processed_faces = parser.get_processed_faces(az_real=az_real, az_model=az_model)

    visualizer = Visualizer([], processed_faces, figure_width=figure_width, figure_height=figure_height, marker_size=marker_size, edge_width=edge_width)
    stereonet_path = visualizer.plot_faces_stereonet()

    if stereonet_path and os.path.exists(stereonet_path):
        image_name = os.path.basename(stereonet_path)
        image = bpy.data.images.get(image_name)
        if image:
            # Reload image to update it
            image.filepath = stereonet_path
            image.reload()
        else:
            image = bpy.data.images.load(stereonet_path)

        # Open image in Image Editor
        open_image_in_image_editor(image)
        logger.info("Stereonet image updated.")
    else:
        if report_errors:
            logger.warning("Stereonet image not found.")

def open_image_in_image_editor(image):
    for area in bpy.context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            area.spaces.active.image = image
            return
    # If no Image Editor area, create one
    bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
    new_area = bpy.context.screen.areas[-1]
    new_area.type = 'IMAGE_EDITOR'
    new_area.spaces.active.image = image
