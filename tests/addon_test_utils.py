import importlib.util
import math
import sys
import types
from pathlib import Path


ADDON_DIR = Path(__file__).resolve().parents[1]


class Vector:
    """Stand-in for ``mathutils.Vector``.

    It carries the arithmetic the add-on's drawing code performs on points, so
    geometry helpers can be exercised without Blender. Anything beyond that is
    deliberately absent: a stub that silently answers more than it models hides
    the difference from the real thing rather than exposing it.
    """

    def __init__(self, xyz):
        self.x, self.y, self.z = (float(value) for value in xyz)

    def copy(self):
        return Vector((self.x, self.y, self.z))

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __getitem__(self, index):
        return (self.x, self.y, self.z)[index]

    def __eq__(self, other):
        return isinstance(other, Vector) and tuple(self) == tuple(other)

    def __hash__(self):
        return hash(tuple(self))

    def __repr__(self):
        return f"Vector(({self.x}, {self.y}, {self.z}))"

    def __add__(self, other):
        return Vector((self.x + other.x, self.y + other.y, self.z + other.z))

    def __sub__(self, other):
        return Vector((self.x - other.x, self.y - other.y, self.z - other.z))

    def __mul__(self, scalar):
        return Vector((self.x * scalar, self.y * scalar, self.z * scalar))

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return Vector((self.x / scalar, self.y / scalar, self.z / scalar))

    def cross(self, other):
        return Vector((
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        ))

    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    @property
    def length(self):
        return math.sqrt(self.dot(self))


def install_mathutils_stub():
    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = Vector
    sys.modules["mathutils"] = mathutils
    return mathutils


def install_bpy_stub(is_saved=True, filepath=None):
    save_calls = []

    def save_mainfile(*args, **kwargs):
        save_calls.append((args, kwargs))
        return {"FINISHED"}

    bpy = types.ModuleType("bpy")
    bpy.data = types.SimpleNamespace(
        is_saved=is_saved,
        filepath=filepath or str(ADDON_DIR / "scene.blend"),
        annotations=[],
        grease_pencils=[],
    )
    bpy.context = types.SimpleNamespace(
        scene=None,
        screen=types.SimpleNamespace(areas=[]),
    )
    bpy.ops = types.SimpleNamespace(
        wm=types.SimpleNamespace(save_mainfile=save_mainfile),
        screen=types.SimpleNamespace(area_split=lambda *args, **kwargs: {"FINISHED"}),
    )

    bpy_types = types.ModuleType("bpy.types")

    class Operator:
        def __init__(self):
            self.reports = []

        def report(self, level, message):
            self.reports.append((level, message))

    bpy_types.Operator = Operator
    bpy_types.WorkSpaceTool = object
    bpy_types.Menu = object
    bpy_types.Panel = object
    bpy_types.PropertyGroup = object
    bpy_types.Scene = object
    bpy_types.World = object
    bpy_types.Material = object

    bpy.types = bpy_types
    bpy_props = types.ModuleType("bpy.props")

    def fake_property(*args, **kwargs):
        return None

    for name in (
        "BoolProperty",
        "CollectionProperty",
        "EnumProperty",
        "FloatProperty",
        "FloatVectorProperty",
        "IntProperty",
        "PointerProperty",
        "StringProperty",
    ):
        setattr(bpy_props, name, fake_property)
    bpy.props = bpy_props
    sys.modules["bpy"] = bpy
    sys.modules["bpy.types"] = bpy_types
    sys.modules["bpy.props"] = bpy_props
    return bpy, save_calls


def ensure_addon_package():
    package = types.ModuleType("ScientiaJoints")
    package.__path__ = [str(ADDON_DIR)]
    sys.modules["ScientiaJoints"] = package
    return package


def load_addon_module(name):
    ensure_addon_package()
    fullname = f"ScientiaJoints.{name}"
    sys.modules.pop(fullname, None)

    parts = name.split(".")
    if len(parts) > 1:
        for index in range(1, len(parts)):
            parent_name = ".".join(parts[:index])
            parent_fullname = f"ScientiaJoints.{parent_name}"
            if parent_fullname not in sys.modules:
                load_addon_module(parent_name)

    module_path = ADDON_DIR.joinpath(*parts)
    if module_path.is_dir():
        file_path = module_path / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            fullname,
            file_path,
            submodule_search_locations=[str(module_path)],
        )
    else:
        file_path = module_path.with_suffix(".py")
        spec = importlib.util.spec_from_file_location(fullname, file_path)

    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


def has_modules(*names):
    return all(importlib.util.find_spec(name) is not None for name in names)
