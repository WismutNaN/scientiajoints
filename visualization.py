import bpy
import contextlib
import logging
import os
from .parser import MeasurementsParser

logger = logging.getLogger(__name__)

#: Aliases numpy removed in 1.24. ``mplstereonet`` up to 0.6.2 still writes
#: ``dtype=np.float``, so on the numpy 2.x that Blender 5.x ships every density
#: contour raised ``module 'numpy' has no attribute 'float'`` and the stereonet
#: came out with poles but no density. 0.6.3 fixes it upstream and is what the
#: release bundles; this keeps an already installed older copy working.
#: Kept to the two names mplstereonet uses. ``np.bool`` and ``np.object`` are
#: left alone: numpy 2.x defines the first and warns about the second.
_NUMPY_REMOVED_ALIASES = {"float": float, "int": int}


@contextlib.contextmanager
def _numpy_legacy_aliases():
    """Restore the removed numpy aliases for the duration of the block.

    They have to go on the numpy module itself, because the affected code does
    ``import numpy as np`` and looks the attribute up at call time. Everything
    is removed again on the way out so no other add-on sees a numpy that
    disagrees with its own version.
    """
    import numpy as np

    added = [name for name in _NUMPY_REMOVED_ALIASES if not hasattr(np, name)]
    for name in added:
        setattr(np, name, _NUMPY_REMOVED_ALIASES[name])
    try:
        yield
    finally:
        for name in added:
            try:
                delattr(np, name)
            except Exception:
                pass

class Visualizer:
    def __init__(self, edges_data, faces_data, figure_width=6.0, figure_height=6.0, marker_size=2.0, edge_width=0.4, marker_face_color=(1.0, 1.0, 1.0), marker_edge_color=(0.0, 0.0, 0.0), density_sigma=1.2, hemisphere='UPPER'):
        self.edges_data = edges_data
        self.faces_data = faces_data
        self.figure_width = figure_width
        self.figure_height = figure_height
        self.marker_size = marker_size
        self.edge_width = edge_width
        self.marker_face_color = marker_face_color
        self.marker_edge_color = marker_edge_color
        self.density_sigma = density_sigma
        self.hemisphere = hemisphere

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
            logger.error("Error calculating edge statistics: %s", e, exc_info=True)
            return {}

    def plot_edges_histogram(self):
        lengths = [edge.length for edge in self.edges_data]
        if not lengths:
            logger.warning("No edge data to plot.")
            return None, {}

        try:
            import matplotlib
            matplotlib.use('Agg', force=True)  # Use 'Agg' backend for rendering without GUI
            import matplotlib.pyplot as plt
            import tempfile

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
            logger.error("Error generating edges histogram: %s", e, exc_info=True)
            return None, {}

    def plot_faces_stereonet(self):
        if not self.faces_data:
            logger.warning("No face data to plot.")
            return None

        try:
            import matplotlib
            matplotlib.use('Agg', force=True)  # Use 'Agg' backend for rendering without GUI
            import mplstereonet
            import matplotlib.pyplot as plt
            import matplotlib.colors
            import tempfile

            strikes = []
            dips = []
            pole_groups = {}

            for face in self.faces_data:
                dip_dir = face.rotated_azimuth
                if str(self.hemisphere).upper() == 'LOWER':
                    dip_dir = (dip_dir + 180) % 360
                strike = (dip_dir + 90) % 360
                dip = face.dip
                strikes.append(strike)
                dips.append(dip)
                color = _marker_color(getattr(face, "color", None), self.marker_face_color)
                pole_groups.setdefault(color, ([], []))
                pole_groups[color][0].append(strike)
                pole_groups[color][1].append(dip)

            # mplstereonet reaches for numpy attributes that no longer exist;
            # see _numpy_legacy_aliases. The whole figure is built inside the
            # block because the drawing code runs as late as savefig().
            with _numpy_legacy_aliases():
                fig, ax = mplstereonet.subplots(figsize=(self.figure_width, self.figure_height))
                ax.grid(kind='polar')

                # Create custom colormap
                custom_cmap = matplotlib.colors.ListedColormap([
                    '#ffffff', '#ecf0f5', '#d3eef1', '#b6f2de',
                    '#97f5ac', '#94f877', '#c5fb58', '#fde839',
                    '#fe811c', '#ff0000'
                ])

                # Density contours can fail for very small datasets; poles are still useful.
                try:
                    ax.density_contourf(
                        strikes, dips,
                        measurement='poles',
                        method='exponential_kamb',
                        sigma=self.density_sigma,
                        cmap=custom_cmap
                    )
                except Exception as e:
                    logger.warning("Stereonet density contours were skipped: %s", e)

                # Plot poles grouped by measurement/code color.
                for marker_color, (group_strikes, group_dips) in pole_groups.items():
                    ax.pole(
                        group_strikes, group_dips,
                        marker='o',
                        markerfacecolor=marker_color,
                        markeredgecolor=self.marker_edge_color,
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
            logger.error("Error generating faces stereonet: %s", e, exc_info=True)
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
        return True
    else:
        if report_errors:
            logger.warning("Histogram image not found.")
        return False

def update_stereonet_image(context, report_errors=True):
    import os
    parser = MeasurementsParser()
    az_real = context.scene.az_real
    az_model = context.scene.az_model
    figure_width = context.scene.figure_width
    figure_height = context.scene.figure_height
    marker_size = context.scene.marker_size
    edge_width = context.scene.edge_width
    marker_face_color = tuple(context.scene.marker_face_color)
    marker_edge_color = tuple(context.scene.marker_edge_color)
    density_sigma = context.scene.density_sigma
    hemisphere = context.scene.stereonet_hemisphere

    processed_faces = parser.get_processed_faces(az_real=az_real, az_model=az_model)

    visualizer = Visualizer([], processed_faces, figure_width=figure_width, figure_height=figure_height, marker_size=marker_size, edge_width=edge_width, marker_face_color=marker_face_color, marker_edge_color=marker_edge_color, density_sigma=density_sigma, hemisphere=hemisphere)
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
        return True
    else:
        if report_errors:
            logger.warning("Stereonet image not found.")
        return False

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


def _marker_color(color, fallback):
    if color is None:
        return tuple(fallback)
    try:
        values = tuple(float(channel) for channel in color)
    except Exception:
        return tuple(fallback)
    if len(values) == 3 or len(values) == 4:
        return values
    return tuple(fallback)
