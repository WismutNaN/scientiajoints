"""Recovery from a toolbar entry Blender will not let us re-register.

``bpy.utils.register_tool`` refuses an idname that is already in the toolbar,
and ``bpy.utils.unregister_tool`` can only remove the entry created by the
exact class object it is given. A second copy of the add-on, or a reload that
dropped the old classes from ``sys.modules`` before ``unregister()`` ran,
therefore leaves an entry nothing can clear, and enabling the add-on fails with
``Tool 'scientiajoints.measure' already exists!``.
"""

import collections
import sys
import types
import unittest

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module


#: Blender's ToolDef is a namedtuple, so it is also a ``tuple``. Anything that
#: tells a single tool from a nested group of tools by ``isinstance(item,
#: tuple)`` matches both and silently iterates a tool's fields instead, which
#: is why the stub has to be a namedtuple too.
_ToolDefBase = collections.namedtuple("ToolDef", ("idname", "keymap"))


def _ToolDef(idname, keymap=None):
    return _ToolDefBase(idname, keymap)


class _KeyMaps:
    def __init__(self):
        self.maps = {}

    def get(self, name):
        return self.maps.get(name)

    def remove(self, keymap):
        del self.maps[keymap.name]


class _KeyConfig:
    def __init__(self, *names):
        self.keymaps = _KeyMaps()
        for name in names:
            self.keymaps.maps[name] = types.SimpleNamespace(name=name)


def _install_toolsystem_stub(tools):
    """Stand in for Blender's 3D View toolbar tool lists."""
    helper = types.SimpleNamespace(_tools={"OBJECT": tools})
    module = types.ModuleType("bl_ui.space_toolsystem_common")
    module.ToolDef = _ToolDefBase
    module.ToolSelectPanelHelper = types.SimpleNamespace(
        _tool_class_from_space_type=staticmethod(lambda space_type: helper),
    )
    bl_ui = types.ModuleType("bl_ui")
    bl_ui.space_toolsystem_common = module
    sys.modules["bl_ui"] = bl_ui
    sys.modules["bl_ui.space_toolsystem_common"] = module
    return helper


class PurgeRegisteredToolsTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        self.bpy, _ = install_bpy_stub()
        self.keyconfig = _KeyConfig()
        self.bpy.context.window_manager = types.SimpleNamespace(
            keyconfigs=types.SimpleNamespace(default=self.keyconfig, addon=None),
        )
        self.module = load_addon_module("custom_measure_tool")

    def test_a_leftover_entry_is_removed_so_registration_can_proceed(self):
        builtin = _ToolDef("builtin.measure")
        tools = [builtin, None, _ToolDef("scientiajoints.measure")]
        _install_toolsystem_stub(tools)

        removed = self.module.purge_registered_tools()

        self.assertEqual(removed, ("scientiajoints.measure",))
        self.assertEqual(tools, [builtin])

    def test_entries_inside_a_group_are_removed_too(self):
        builtin = _ToolDef("builtin.cursor")
        ours = _ToolDef("scientiajoints.polygon_measure")
        neighbour = _ToolDef("builtin.select_box")
        tools = [builtin, (ours, neighbour)]
        _install_toolsystem_stub(tools)

        removed = self.module.purge_registered_tools()

        self.assertEqual(removed, ("scientiajoints.polygon_measure",))
        self.assertEqual(tools, [builtin, (neighbour,)])

    def test_a_group_left_empty_is_dropped(self):
        builtin = _ToolDef("builtin.cursor")
        tools = [builtin, (_ToolDef("scientiajoints.measure"),)]
        _install_toolsystem_stub(tools)

        self.module.purge_registered_tools()

        self.assertEqual(tools, [builtin])

    def test_other_tools_are_never_touched(self):
        tools = [_ToolDef("builtin.measure"), None, _ToolDef("some_addon.measure")]
        _install_toolsystem_stub(tools)

        removed = self.module.purge_registered_tools()

        self.assertEqual(removed, ())
        self.assertEqual(len(tools), 3)

    def test_the_key_map_of_a_removed_entry_is_left_alone(self):
        """Blender names a tool key-map after the tool's label, so two installed
        copies of the add-on share the name. Deleting it here took away the
        key-map a live registration of the other copy was using, and left that
        tool in the toolbar with nothing bound to it."""
        keymap_name = "3D View Tool: Object, Scientia Measure"
        self.keyconfig.keymaps.maps[keymap_name] = types.SimpleNamespace(name=keymap_name)
        _install_toolsystem_stub([_ToolDef("scientiajoints.measure", keymap=[keymap_name])])

        removed = self.module.purge_registered_tools()

        self.assertEqual(removed, ("scientiajoints.measure",), "the toolbar entry still goes")
        self.assertIsNotNone(
            self.keyconfig.keymaps.get(keymap_name),
            "the key-map may still belong to another live registration",
        )

    def test_an_unregistered_entry_is_removed_too(self):
        """Before registration ``keymap`` still holds the callback, not a name."""
        _install_toolsystem_stub([_ToolDef("scientiajoints.measure", keymap=[lambda km: None])])

        self.assertEqual(self.module.purge_registered_tools(), ("scientiajoints.measure",))

    def test_every_add_on_tool_is_covered(self):
        """A tool missing from TOOL_IDNAMES is one the purge cannot clean up,
        which is what makes the next registration fail."""
        self.assertEqual(
            set(self.module.TOOL_IDNAMES),
            {tool.bl_idname for tool in self.module._WORKSPACE_TOOLS},
        )
        self.assertEqual(
            set(self.module.TOOL_IDNAMES),
            {
                self.module.ScientiaMeasureWorkSpaceTool.bl_idname,
                self.module.ScientiaPolygonMeasureWorkSpaceTool.bl_idname,
                self.module.ScientiaTraceMeasureWorkSpaceTool.bl_idname,
            },
        )


if __name__ == "__main__":
    unittest.main()
