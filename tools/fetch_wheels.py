"""Download the chart dependencies as wheels into ``wheels/``.

The wheels are what makes ScientiaJoints installable on a machine that cannot
reach a package index: the extension build hands them to Blender, and the
legacy build installs them with ``pip --no-index``.

Run this once per target platform on a machine that does have internet access:

    python tools/fetch_wheels.py                       # this machine
    python tools/fetch_wheels.py --platform win_amd64 --python-version 3.13
    python tools/fetch_wheels.py --all-platforms       # every platform Blender supports

``numpy`` is deliberately not downloaded: Blender ships it, and a second copy
is what causes the binary incompatibility errors that read as random matplotlib
crashes. Pass ``--include-numpy`` only for a Blender build without it.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1]
WHEELS_DIRECTORY = ADDON_ROOT / "wheels"

#: Requirements pip can resolve to a published wheel, per platform.
PACKAGES = ("matplotlib",)

#: Pure Python requirements that PyPI does not publish a wheel for, so one has
#: to be built. ``mplstereonet`` 0.6.3 is the first release that stopped using
#: ``np.float``, removed in numpy 1.24, which broke every stereonet density
#: contour on the numpy Blender 5.x ships - but it is an sdist-only release.
#: The build produces a ``py3-none-any`` wheel, so a single one covers every
#: platform.
BUILT_PACKAGES = ("mplstereonet>=0.6.3",)

NUMPY_PACKAGE = "numpy"

#: Wheel platform tags Blender publishes builds for.
BLENDER_PLATFORMS = (
    "win_amd64",
    "manylinux2014_x86_64",
    "macosx_11_0_arm64",
    "macosx_10_9_x86_64",
)

DEFAULT_PYTHON_VERSION = "3.13"


def download(packages, destination, platform=None, python_version=None, index_url=None):
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--no-input",
        "--disable-pip-version-check",
        "--only-binary",
        ":all:",
        "--dest",
        str(destination),
    ]
    if platform:
        # Cross-platform downloads cannot resolve the running interpreter's
        # environment, so pip requires both the platform and the version.
        command.extend(["--platform", platform, "--python-version", python_version or DEFAULT_PYTHON_VERSION])
    if index_url:
        command.extend(["--index-url", index_url])
    command.extend(packages)

    print("$", " ".join(command))
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(f"pip download failed with exit code {completed.returncode}")


def build(packages, destination, index_url=None):
    """Build wheels for requirements PyPI only publishes as source archives.

    ``pip wheel`` uses a published wheel when there is one and builds from the
    sdist otherwise. It cannot target another platform, which does not matter
    here: these packages are pure Python, so the wheel it produces is tagged
    ``py3-none-any`` and installs everywhere.
    """
    if not packages:
        return
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-input",
        "--disable-pip-version-check",
        "--no-deps",
        "--wheel-dir",
        str(destination),
    ]
    if index_url:
        command.extend(["--index-url", index_url])
    command.extend(packages)

    print("$", " ".join(command))
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(f"pip wheel failed with exit code {completed.returncode}")


def _version_key(wheel_name):
    """Sortable version of a wheel file name: ``name-version-tags.whl``."""
    version = wheel_name.split("-")[1]
    return tuple(
        int(part) if part.isdigit() else part
        for part in re.split(r"[._]", version)
    )


def drop_superseded_wheels(destination):
    """Keep the newest wheel of each distribution *and compatibility tag*.

    ``pip wheel`` and ``pip download`` write the new version next to the old
    one. Two versions of the same distribution in ``wheels/`` make the offline
    install ambiguous. Wheels for other Python ABIs and platforms are not
    superseded by one another; deleting them made ``--all-platforms`` silently
    leave only the last platform downloaded.
    """
    newest = {}
    for wheel in sorted(Path(destination).glob("*.whl")):
        parts = wheel.stem.split("-")
        if len(parts) < 5:
            continue
        distribution = parts[0]
        compatibility = tuple(parts[-3:])
        key = (distribution, compatibility)
        previous = newest.get(key)
        if previous is None:
            newest[key] = wheel
            continue
        try:
            older, newer = sorted((previous, wheel), key=lambda path: _version_key(path.name))
        except (IndexError, TypeError):
            continue
        print(f"Removing superseded wheel {older.name}")
        older.unlink()
        newest[key] = newer
    return tuple(sorted(newest.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", help="Wheel platform tag, for example win_amd64")
    parser.add_argument("--all-platforms", action="store_true", help="Download for every platform Blender supports")
    parser.add_argument("--python-version", default=DEFAULT_PYTHON_VERSION, help="Target Python version, e.g. 3.13")
    parser.add_argument("--index-url", help="Alternative package index, for example an internal mirror")
    parser.add_argument("--include-numpy", action="store_true", help="Also download numpy (Blender bundles it)")
    parser.add_argument("--clean", action="store_true", help="Empty wheels/ before downloading")
    args = parser.parse_args()

    packages = list(PACKAGES)
    if args.include_numpy:
        packages.append(NUMPY_PACKAGE)

    if args.clean and WHEELS_DIRECTORY.exists():
        shutil.rmtree(WHEELS_DIRECTORY)

    if args.all_platforms:
        for platform in BLENDER_PLATFORMS:
            download(packages, WHEELS_DIRECTORY, platform, args.python_version, args.index_url)
    else:
        download(packages, WHEELS_DIRECTORY, args.platform, args.python_version, args.index_url)

    build(BUILT_PACKAGES, WHEELS_DIRECTORY, args.index_url)
    drop_superseded_wheels(WHEELS_DIRECTORY)

    wheels = sorted(WHEELS_DIRECTORY.glob("*.whl"))
    total = sum(path.stat().st_size for path in wheels)
    print(f"\n{len(wheels)} wheel(s) in {WHEELS_DIRECTORY} ({total / 1024 / 1024:.1f} MB)")
    for path in wheels:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
