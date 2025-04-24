**Русская версия**: [readme_ru.md](readme_ru.md)

# ScientiaJoints

**Blender Add-on for Geomechanical Measurement Export and Visualization**

## Description

ScientiaJoints is a Blender add-on (compatible with Blender 4.2+) developed by Scientia and Ivan Guzeev. It automates exporting linear and angular measurements drawn with Grease Pencil (layer `RulerData3D`) into text and CSV files, and provides interactive visualizations of measurement distributions and plane orientations.

## Features

- **Raw Data Export** (_Raw Edges_, _Raw Faces_) to TXT files
- **Processed Data Export** (_CSV Edges_, _CSV Faces_) with computed:
  - center coordinates (`x`, `y`, `z`)
  - azimuth and dip angles
  - length of linear measurements
  - area and angular spread for planar measurements
- **Visualization**:
  - histogram of edge length distribution
  - stereonet density plot of plane poles
- **Display Settings**:
  - figure width & height, marker size, line width
  - update interval for real-time refresh
- **Real-Time Update** option for automatic chart regeneration
- **Interactive UI** in the 3D Viewport sidebar

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/scientia/ScientiaJoints.git
   ```
2. In Blender, go to **Edit → Preferences → Add-ons → Install...**, select the `ScientiaJoints` folder.
3. Enable the add-on and open the **ScientiaJoints** tab in the 3D Viewport sidebar.

## Usage

1. Draw measurements using Grease Pencil on the `Annotations → RulerData3D` layer.
2. Set **Real Azimuth** and **Model Azimuth** values in the add-on panel.
3. Under **Visualization**:
   - Click **Histogram** to display the edge length histogram.
   - Click **Stereonet** to display the stereonet plot.
4. Under **Export**, choose **Raw** or **CSV** format for edges or faces.
5. Adjust **Display Settings** and enable **Real-Time Update** if needed.

## Our Products

- **Magicore**  
  Service for automatic geomechanical core documentation generation from photos. [More](https://weare.science)
- **Digger**  
  Pit wall optimization software using 3D modeling. [More](https://weare.science)
- **Prorock 2.0**  
  Geomechanics solution for fracture and dynamic process modeling. [More](https://weare.science)
- **NUR Extensometer**  
  Instrument for automated monitoring of cracks and fissures. [More](https://weare.science)
- **Joint Explorer™**  
  Electronic geological compass for measuring azimuth and dip of structural elements. [More](https://weare.science)

Visit our website [weare.science](https://weare.science) for full product listings and documentation.
Follow us on LinkedIn: [WeAreScience](https://www.linkedin.com/company/wearescience/).

## Contributing

Feedback, bug reports, and pull requests are welcome! Please open issues and submit PRs in this repository.
