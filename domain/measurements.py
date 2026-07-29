from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Tuple


class MeasurementKind(str, Enum):
    LINEAR = "linear"
    PLANE = "plane"


@dataclass(frozen=True)
class Point3D:
    x: float
    y: float
    z: float

    @classmethod
    def from_object(cls, value):
        if hasattr(value, "co"):
            value = value.co
        elif hasattr(value, "position"):
            value = value.position
        elif hasattr(value, "location"):
            value = value.location
        return cls(float(value.x), float(value.y), float(value.z))

    def signature(self, precision: int = 6):
        return (round(self.x, precision), round(self.y, precision), round(self.z, precision))

    def __str__(self):
        return "{:.3f}\t{:.3f}\t{:.3f}".format(self.x, self.y, self.z)


@dataclass(frozen=True)
class Orientation:
    azimuth: float
    dip: float
    rotated_azimuth: float = 0.0


@dataclass(frozen=True)
class AzimuthCorrection:
    az_real: float = 0.0
    az_model: float = 0.0

    def apply(self, azimuth: float) -> float:
        return (azimuth + self.az_real - self.az_model) % 360


@dataclass(frozen=True)
class MeasurementProperties:
    values: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MeasurementLayer:
    name: str = "Default"
    color: Optional[Tuple[float, float, float]] = None
    visible: bool = True


@dataclass(frozen=True)
class RawMeasurement:
    kind: MeasurementKind
    points: Tuple[Point3D, ...]
    source: str = "RulerData3D"
    source_id: str = ""
    layer: str = "Default"
    properties: MeasurementProperties = field(default_factory=MeasurementProperties)

    def signature(self, precision: int = 6):
        return (
            self.kind.value,
            tuple(point.signature(precision=precision) for point in self.points),
        )

    def near_signature(self, precision: int = 3):
        """Coarse, order independent signature used to spot accidental copies.

        A ruler stroke that Blender copied into another annotation frame and
        that was then nudged slightly no longer matches :meth:`signature`, but
        it still lands on the same coarse grid. Sorting the points also catches
        a copy that was drawn in the opposite direction.
        """
        return (
            self.kind.value,
            len(self.points),
            tuple(sorted(point.signature(precision=precision) for point in self.points)),
        )


@dataclass(frozen=True)
class MeasurementRecord:
    id: str
    kind: MeasurementKind
    points: Tuple[Point3D, ...]
    center: Point3D
    source: str
    source_id: str
    layer: str = "Default"
    properties: MeasurementProperties = field(default_factory=MeasurementProperties)
    line_orientation: Optional[Orientation] = None
    plane_orientation: Optional[Orientation] = None
    edge_orientation: Optional[Orientation] = None
    length: Optional[float] = None
    area: Optional[float] = None
    degree: Optional[float] = None
    fit_error: Optional[float] = None
    fit_error_relative: Optional[float] = None
    #: Empty when the points define a plane. Otherwise a short reason why the
    #: orientation is arbitrary (collinear or coincident points). The values
    #: are still computed and exported, but must be shown as untrustworthy.
    degeneracy: str = ""

    @property
    def is_degenerate(self):
        return bool(self.degeneracy)


@dataclass(frozen=True)
class ParseDiagnostics:
    layer_found: bool = False
    total_strokes_count: int = 0
    duplicate_strokes_count: int = 0
    ignored_strokes_count: int = 0
    messages: Tuple[str, ...] = ()
    #: Pairs of ``source_id`` values that are nearly identical. These are kept
    #: in the export on purpose and only reported, because only the operator
    #: can tell an accidental copy from two genuinely close measurements.
    near_duplicate_pairs: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MeasurementSet:
    raw_measurements: Tuple[RawMeasurement, ...]
    diagnostics: ParseDiagnostics

    @property
    def edges(self):
        return tuple(m for m in self.raw_measurements if m.kind == MeasurementKind.LINEAR)

    @property
    def faces(self):
        return tuple(m for m in self.raw_measurements if m.kind == MeasurementKind.PLANE)
