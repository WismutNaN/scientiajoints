"""The one place the add-on version is set.

``blender_manifest.toml`` holds the version. Everything else derives from it:
the release archive names, the manifest the extension build writes, and the
``bl_info`` dict in ``__init__.py``.

``bl_info`` cannot simply import the number, because Blender reads it out of
the source file with ``ast.literal_eval`` before the add-on is ever imported,
so the tuple has to stay a literal. That is the one copy, and it is written by
this module rather than by hand::

    python tools/version.py            # print the current version
    python tools/version.py 3.4.0      # set it everywhere

``tools/build_release.py`` calls :func:`check_version` before it packages
anything, so a copy that drifted out of sync fails the build instead of
shipping two different version numbers.
"""

import argparse
import re
import sys
from pathlib import Path


MANIFEST_NAME = "blender_manifest.toml"
INIT_NAME = "__init__.py"

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_MANIFEST_LINE = re.compile(r'^version\s*=\s*"([^"]*)"\s*$', flags=re.MULTILINE)
_BL_INFO_LINE = re.compile(r'^(\s*"version":\s*)\(([^)]*)\)(,?)\s*$', flags=re.MULTILINE)


def read_version(addon_root):
    """The add-on version, from the manifest."""
    manifest_path = Path(addon_root) / MANIFEST_NAME
    match = _MANIFEST_LINE.search(manifest_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Could not read the version from {manifest_path}")
    return match.group(1)


def read_bl_info_version(addon_root):
    """The version copy carried by ``bl_info``, as a dotted string."""
    init_path = Path(addon_root) / INIT_NAME
    match = _BL_INFO_LINE.search(init_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Could not read bl_info['version'] from {init_path}")
    parts = [part.strip() for part in match.group(2).split(",") if part.strip()]
    return ".".join(parts)


def check_version(addon_root):
    """Return the version, or explain how to repair a mismatch."""
    version = read_version(addon_root)
    bl_info_version = read_bl_info_version(addon_root)
    if version != bl_info_version:
        raise ValueError(
            f"{MANIFEST_NAME} says {version} but {INIT_NAME} says {bl_info_version}. "
            f"Run `python tools/version.py {version}` to set both."
        )
    return version


def set_version(addon_root, version):
    """Write ``version`` to the manifest and to ``bl_info``."""
    if not VERSION_PATTERN.match(version):
        raise ValueError(f"Expected a version like 3.4.0, got '{version}'")
    addon_root = Path(addon_root)

    manifest_path = addon_root / MANIFEST_NAME
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest, replacements = _MANIFEST_LINE.subn(f'version = "{version}"', manifest, count=1)
    if not replacements:
        raise ValueError(f"Could not find the version line in {manifest_path}")
    manifest_path.write_text(manifest, encoding="utf-8")

    init_path = addon_root / INIT_NAME
    source = init_path.read_text(encoding="utf-8")
    tuple_text = ", ".join(version.split("."))
    source, replacements = _BL_INFO_LINE.subn(rf'\g<1>({tuple_text})\g<3>', source, count=1)
    if not replacements:
        raise ValueError(f"Could not find bl_info['version'] in {init_path}")
    init_path.write_text(source, encoding="utf-8")

    return version


def main():
    addon_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?", help="New version, e.g. 3.4.0. Omit to print the current one.")
    args = parser.parse_args()

    if args.version is None:
        try:
            print(check_version(addon_root))
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        return 0

    print(f"{read_version(addon_root)} -> {set_version(addon_root, args.version)}")
    print(f"Updated {MANIFEST_NAME} and {INIT_NAME}. Remember the CHANGELOG entry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
