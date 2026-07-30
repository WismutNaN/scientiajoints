"""Chart dependency detection and installation for Blender Python.

The add-on needs ``matplotlib`` and ``mplstereonet`` (``numpy`` ships with
Blender). Installing them into a Blender build is the single most common
failure point reported by users, so this module is deliberately explicit about
every step it takes and every reason an attempt can fail:

- Blender's interpreter is resolved without ever launching ``blender.exe``.
- ``pip install --user`` is never used: Blender disables the user site.
- The install directory is picked from candidates that are importable already
  or deliberately added to ``sys.path``, actually writable, and short enough
  for the Windows 260 character path limit (a longer path silently breaks
  ``matplotlib`` at import time even though every file is on disk).
- Offline installation uses the complete non-numpy wheel set with
  ``--no-deps``; online installation pins numpy to Blender's version. Neither
  route can introduce a second, ABI-incompatible copy.
- Wheels shipped inside the add-on are preferred over PyPI, which makes the
  add-on installable on networks that block package indexes.
- Every subprocess has a timeout and its output is captured into the result.
"""

import hashlib
import importlib
import importlib.util
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_PACKAGES = ("matplotlib", "mplstereonet", "numpy")

#: pip requirement name for every import name that differs from it.
PIP_NAMES = {}

#: Versions the add-on needs beyond the package merely importing.
MINIMUM_VERSIONS = {
    # 0.6.2 and older write ``dtype=np.float``, an alias numpy removed in 1.24.
    # The package imports and draws poles, but every stereonet density contour
    # raises ``module 'numpy' has no attribute 'float'`` on the numpy that
    # Blender 5.x ships. ``visualization`` restores the alias so an installed
    # older copy keeps working; the bundled wheel is 0.6.3.
    "mplstereonet": "0.6.3",
}

#: Packages Blender ships itself. They must never be upgraded from PyPI: a
#: second copy shadowed by the bundled one causes binary incompatibility
#: errors in ``contourpy``/``matplotlib`` that read as random import crashes.
BUNDLED_PACKAGES = ("numpy",)

WHEELS_DIRECTORY_NAME = "wheels"

#: Longest path a wheel adds below the install directory, measured against
#: matplotlib's ``mpl-data`` tree, plus headroom.
LONGEST_RELATIVE_PACKAGE_PATH = 120
WINDOWS_MAX_PATH = 260

DEFAULT_PIP_TIMEOUT_SECONDS = 600.0
DEFAULT_RUNTIME_PROBE_TIMEOUT_SECONDS = 10.0
DEFAULT_PACKAGE_PROBE_TIMEOUT_SECONDS = 20.0
DEFAULT_OFFLINE_PIP_TIMEOUT_SECONDS = 180.0
#: Do not retry a failed automatic installation more often than this.
INSTALL_RETRY_INTERVAL_SECONDS = 24 * 60 * 60
# Bump when the automatic install preparation changes in a way that should
# retry a previously failed build immediately instead of waiting a day.
INSTALL_POLICY_VERSION = 3
_AUTO_INSTALL_TARGET = object()
_status_cache = {}
_status_cache_lock = threading.Lock()


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    installed: bool
    error: str = ""
    version: str = ""
    location: str = ""
    #: ``False`` means only the module specification was inspected. This is
    #: intentionally enough for panel drawing, where importing matplotlib can
    #: build its font cache and freeze Blender's UI.
    verified: bool = True


@dataclass(frozen=True)
class DependencyInstallResult:
    ok: bool
    messages: tuple
    missing_after_install: tuple
    log: str = ""
    attempts: tuple = ()
    #: Which source finally worked: bundled wheels, PyPI, or nothing.
    source: str = ""
    target: str = ""
    failed_stage: str = ""
    error_source: str = ""
    runtime: str = ""
    compatible_wheels: tuple = ()


@dataclass(frozen=True)
class PythonRuntime:
    """Identity of the Python process that will execute pip."""

    executable: str
    implementation: str
    version: tuple
    cache_tag: str
    bits: int
    system: str
    machine: str
    prefix: str = ""
    exec_prefix: str = ""

    @property
    def version_text(self):
        return ".".join(str(part) for part in self.version)

    @property
    def summary(self):
        implementation = {
            "cpython": "CPython",
            "pypy": "PyPy",
        }.get((self.implementation or "").lower(), (self.implementation or "Python").capitalize())
        tag = f", {self.cache_tag}" if self.cache_tag else ""
        return (
            f"{implementation} {self.version_text}{tag}, {self.bits}-bit "
            f"{self.system or 'unknown'} {self.machine or 'unknown'}"
        )


@dataclass(frozen=True)
class WheelSelection:
    compatible: tuple
    incompatible: tuple
    distributions: tuple
    supported_tag_sample: tuple = ()
    errors: tuple = ()


@dataclass
class InstallTarget:
    """A directory pip can install into."""

    path: str
    kind: str  # "interpreter" | "target"
    on_sys_path: bool
    writable: bool
    path_budget_ok: bool
    note: str = ""
    writable_checked: bool = True

    @property
    def usable(self):
        # A managed --target directory can be added to sys.path before pip
        # starts. Requiring it to have existed at Blender startup made the
        # normal per-user modules directory impossible to use on a clean
        # installation.
        return self.writable and self.path_budget_ok


@dataclass
class InstallAttempt:
    source: str
    command: tuple
    returncode: int
    output: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _pip_name(package):
    return PIP_NAMES.get(package, package)


def _pip_requirement(package):
    """The name to hand pip, with the minimum version when there is one."""
    minimum = MINIMUM_VERSIONS.get(package)
    return f"{_pip_name(package)}>={minimum}" if minimum else _pip_name(package)


def _version_key(version):
    """Sortable form of a release version; trailing suffixes are ignored."""
    parts = []
    for part in re.split(r"[._-]", str(version)):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def outdated_packages(packages=REQUIRED_PACKAGES, statuses=None):
    """Installed packages older than :data:`MINIMUM_VERSIONS` requires.

    Each entry is ``(name, installed version, required version)``. A package
    whose version cannot be read is left out: an unknown version is not
    evidence of an old one, and a false alarm here sends users reinstalling
    working dependencies.
    """
    outdated = []
    for status in statuses if statuses is not None else check_required_packages(packages):
        minimum = MINIMUM_VERSIONS.get(status.name)
        if not status.installed or not minimum or not status.version:
            continue
        installed_key = _version_key(status.version)
        if installed_key and installed_key < _version_key(minimum):
            outdated.append((status.name, status.version, minimum))
    return tuple(outdated)


def _package_import_error(package):
    try:
        if importlib.util.find_spec(package) is None:
            return "not installed"
        importlib.import_module(package)
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _package_details(package):
    """Version and file of an installed package.

    The distribution metadata is asked first, because it records what was
    actually installed. A module's ``__version__`` is only as accurate as the
    author's last release commit: mplstereonet 0.6.3 still calls itself
    ``0.6-dev`` in code, which would report a current install as outdated.
    """
    module = sys.modules.get(package)
    location = str(getattr(module, "__file__", "") or "") if module is not None else ""
    try:
        from importlib import metadata

        version = str(metadata.version(_pip_name(package)) or "")
    except Exception:
        version = ""
    if not version and module is not None:
        version = str(getattr(module, "__version__", "") or "")
    return version, location


def check_required_packages(packages=REQUIRED_PACKAGES):
    statuses = []
    for package in packages:
        error = _package_import_error(package)
        version, location = _package_details(package)
        statuses.append(
            DependencyStatus(
                name=package,
                installed=not error,
                error="" if error == "not installed" else error,
                version=version,
                location=location,
                verified=True,
            )
        )
    statuses = tuple(statuses)
    cache_dependency_statuses(statuses)
    return statuses


def lightweight_package_statuses(packages=REQUIRED_PACKAGES):
    """Inspect import specs and metadata without importing third-party code.

    This function is safe to call from panel drawing and the quick diagnostics
    popup. A found package is marked ``verified=False`` until the background
    probe has imported it in a disposable Python process.
    """
    statuses = []
    for package in packages:
        try:
            spec = importlib.util.find_spec(package)
        except Exception as e:
            statuses.append(
                DependencyStatus(
                    package,
                    False,
                    error=f"Module discovery failed: {type(e).__name__}: {e}",
                    verified=False,
                )
            )
            continue

        if spec is None:
            statuses.append(DependencyStatus(package, False, verified=False))
            continue

        version = ""
        try:
            from importlib import metadata

            version = str(metadata.version(_pip_name(package)) or "")
        except Exception:
            module = sys.modules.get(package)
            version = str(getattr(module, "__version__", "") or "") if module is not None else ""
        statuses.append(
            DependencyStatus(
                package,
                True,
                version=version,
                location=str(getattr(spec, "origin", "") or ""),
                verified=False,
            )
        )
    return tuple(statuses)


def cache_dependency_statuses(statuses):
    now = time.monotonic()
    with _status_cache_lock:
        for status in statuses:
            _status_cache[status.name] = (now, status)


def safe_dependency_statuses(packages=REQUIRED_PACKAGES):
    """Return verified cached statuses, falling back to spec-only detection."""
    requested = tuple(packages)
    with _status_cache_lock:
        cached = {name: _status_cache.get(name) for name in requested}
    fallback = {status.name: status for status in lightweight_package_statuses(requested)}
    return tuple(
        cached[name][1]
        if cached.get(name) is not None and cached[name][1].verified
        else fallback[name]
        for name in requested
    )


def missing_packages(packages=REQUIRED_PACKAGES):
    """Packages not discoverable without importing them on Blender's UI thread."""
    return tuple(
        status.name for status in safe_dependency_statuses(packages)
        if not status.installed
    )


def dependency_summary(packages=REQUIRED_PACKAGES):
    statuses = safe_dependency_statuses(packages)
    missing = [status.name for status in statuses if not status.installed and not status.error]
    broken = [f"{status.name}: {status.error}" for status in statuses if status.error]

    if not missing and not broken:
        if all(status.verified for status in statuses):
            return True, "Dependencies OK: " + ", ".join(status.name for status in statuses)
        return True, "Dependencies found; background verification pending: " + ", ".join(
            status.name for status in statuses
        )

    parts = []
    if missing:
        parts.append("Missing: " + ", ".join(missing))
    if broken:
        parts.append("Errors: " + "; ".join(broken))
    return False, " | ".join(parts)


def _distribution_installer(package):
    """The tool that installed a package, from the ``INSTALLER`` metadata file."""
    try:
        from importlib import metadata

        distribution = metadata.distribution(_pip_name(package))
        return (distribution.read_text("INSTALLER") or "").strip()
    except Exception:
        return ""


def package_install_method(status):
    """How a package ended up in this Blender, for the diagnostics report.

    Users and support need to know which of the several possible routes was
    actually taken: wheels unpacked by Blender from the extension, pip into
    Blender's own Python, pip into the user modules directory, or a copy that
    shipped with Blender itself.
    """
    location = str(getattr(status, "location", "") or "")
    if not location:
        return "not installed"

    absolute = os.path.normcase(os.path.abspath(location))
    installer = _distribution_installer(status.name)

    if os.path.normcase(os.sep + ".local" + os.sep) in absolute and "extensions" in absolute:
        return "Blender extension wheels (bundled in the add-on archive)"

    prefix = os.path.normcase(os.path.abspath(sys.exec_prefix))
    if absolute.startswith(prefix):
        if status.name in BUNDLED_PACKAGES:
            # Blender installs its own bundled packages with pip too, so the
            # INSTALLER marker cannot tell the two apart here.
            return "in Blender's own Python (shipped with Blender, or replaced by pip there)"
        if installer == "pip":
            return "pip, into Blender's own Python"
        return "shipped with Blender"

    modules_directory = _user_scripts_modules_directory()
    if modules_directory and absolute.startswith(os.path.normcase(os.path.abspath(modules_directory))):
        return "pip --target, into the Blender user modules directory"

    if installer:
        return f"{installer}, from {os.path.dirname(location)}"
    return f"other directory on sys.path: {os.path.dirname(location)}"


def bundled_package_versions(packages=BUNDLED_PACKAGES):
    """Versions of packages Blender ships, used to pin ``--target`` installs."""
    versions = {}
    for package in packages:
        try:
            from importlib import metadata

            version = str(metadata.version(_pip_name(package)) or "")
        except Exception:
            # Never import a binary package merely to prepare an install. If it
            # has already been loaded, its version is still a safe fallback.
            module = sys.modules.get(package)
            version = str(getattr(module, "__version__", "") or "") if module is not None else ""
        if version:
            versions[_pip_name(package)] = version
    return versions


# ---------------------------------------------------------------------------
# Interpreter and install target resolution
# ---------------------------------------------------------------------------


def _blender_binary_path():
    try:
        import bpy

        return str(getattr(bpy.app, "binary_path", "") or "")
    except Exception:
        return ""


def current_python_runtime(explicit=None):
    """Describe Blender's active Python without starting another process."""
    implementation = str(getattr(sys.implementation, "name", "") or "")
    cache_tag = str(getattr(sys.implementation, "cache_tag", "") or "")
    return PythonRuntime(
        executable=resolve_python_executable(explicit),
        implementation=implementation,
        version=tuple(sys.version_info[:3]),
        cache_tag=cache_tag,
        bits=64 if sys.maxsize > 2**32 else 32,
        system=platform.system(),
        machine=platform.machine(),
        prefix=str(sys.prefix),
        exec_prefix=str(sys.exec_prefix),
    )


def probe_python_runtime(python_executable, timeout=DEFAULT_RUNTIME_PROBE_TIMEOUT_SECONDS):
    """Start the selected interpreter briefly and return its actual identity.

    The probe has a hard timeout and is only called by the background worker.
    A bad executable can therefore never turn into a frozen Blender window.
    """
    script = (
        "import json,platform,struct,sys;"
        "print(json.dumps({"
        "'executable':sys.executable,"
        "'implementation':sys.implementation.name,"
        "'version':list(sys.version_info[:3]),"
        "'cache_tag':getattr(sys.implementation,'cache_tag',''),"
        "'bits':struct.calcsize('P')*8,"
        "'system':platform.system(),"
        "'machine':platform.machine(),"
        "'prefix':sys.prefix,"
        "'exec_prefix':sys.exec_prefix"
        "}))"
    )
    try:
        completed = subprocess.run(
            [python_executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_subprocess_flags(),
        )
    except subprocess.TimeoutExpired:
        return None, (
            f"Python runtime detection timed out after {timeout:.0f} s at "
            f"{python_executable}; the process was stopped."
        )
    except Exception as e:
        return None, f"Could not start {python_executable}: {type(e).__name__}: {e}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return None, (
            f"Python runtime detection failed at {python_executable}: "
            f"{detail[-1][:500] if detail else f'exit code {completed.returncode}'}"
        )
    try:
        data = json.loads((completed.stdout or "").strip().splitlines()[-1])
        return PythonRuntime(
            executable=str(data.get("executable") or python_executable),
            implementation=str(data.get("implementation") or ""),
            version=tuple(int(part) for part in data.get("version", ())),
            cache_tag=str(data.get("cache_tag") or ""),
            bits=int(data.get("bits") or 0),
            system=str(data.get("system") or ""),
            machine=str(data.get("machine") or ""),
            prefix=str(data.get("prefix") or ""),
            exec_prefix=str(data.get("exec_prefix") or ""),
        ), ""
    except Exception as e:
        return None, f"Python runtime detection returned invalid data: {type(e).__name__}: {e}"


def runtime_mismatch(expected, actual):
    """Explain why an executable cannot install for the active Blender."""
    if expected is None or actual is None:
        return ""
    if expected.implementation != actual.implementation:
        return (
            f"implementation is {actual.implementation}, but Blender uses "
            f"{expected.implementation}"
        )
    if tuple(expected.version[:2]) != tuple(actual.version[:2]):
        return (
            f"version is {actual.version_text}, but Blender uses "
            f"{expected.version_text}"
        )
    if expected.bits != actual.bits:
        return f"architecture is {actual.bits}-bit, but Blender uses {expected.bits}-bit"
    if expected.system and actual.system and expected.system.lower() != actual.system.lower():
        return f"platform is {actual.system}, but Blender runs on {expected.system}"
    return ""


def resolve_python_executable(explicit=None):
    """Return a path to the Python interpreter, never the Blender binary.

    Blender sets ``sys.executable`` to its bundled ``python`` since 2.91, but
    custom builds and some distributions still leave it pointing at
    ``blender.exe``. Running ``blender.exe -m pip`` starts a second Blender
    instead of installing anything, so that case is detected and repaired.
    """
    candidate = explicit or sys.executable or ""
    binary = _blender_binary_path()
    looks_like_blender = bool(
        candidate
        and binary
        and os.path.normcase(os.path.abspath(candidate)) == os.path.normcase(os.path.abspath(binary))
    )
    if (
        candidate
        and not looks_like_blender
        and os.path.basename(candidate).lower().startswith("python")
        and (explicit is not None or Path(candidate).is_file())
    ):
        return candidate
    if candidate and not looks_like_blender and not binary and Path(candidate).is_file():
        return candidate

    for relative in ("bin/python.exe", "bin/python3.exe", "python.exe", "bin/python3", "bin/python"):
        probe = Path(sys.exec_prefix) / relative
        if probe.is_file():
            return str(probe)
    return candidate


def _directory_is_writable(path):
    directory = Path(path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    # os.access() reports the wrong answer for Windows ACLs, so write a probe.
    try:
        handle = tempfile.NamedTemporaryFile(dir=str(directory), prefix=".scientia-write-test", delete=True)
        handle.close()
        return True
    except Exception:
        return False


def path_budget(path):
    """Remaining characters before the Windows 260 character path limit.

    ``matplotlib`` fails at import time with ``FileNotFoundError`` on files
    that exist but whose absolute path is longer than the limit, so an install
    directory that is already deep is rejected before anything is downloaded.
    """
    if platform.system() != "Windows":
        return LONGEST_RELATIVE_PACKAGE_PATH + 1
    return WINDOWS_MAX_PATH - len(str(Path(path).absolute())) - 1


def _user_scripts_modules_directory(create=True):
    try:
        import bpy

        try:
            # Blender's importable per-user directory is <SCRIPTS>/modules,
            # not <SCRIPTS>/addons/modules.
            modules = bpy.utils.user_resource('SCRIPTS', path="modules", create=create)
            if modules:
                return str(Path(modules))
        except TypeError:
            # Older API-compatible stubs and Blender builds only accept the
            # resource type. The fallback below keeps the same correct path.
            pass
        scripts = bpy.utils.user_resource('SCRIPTS')
    except Exception:
        return ""
    if not scripts:
        return ""
    return str(Path(scripts) / "modules")


def _interpreter_site_packages():
    """The bundled interpreter's own site-packages.

    Only directories below ``sys.exec_prefix`` qualify. When the add-on runs as
    an extension, Blender puts its own extension site-packages on ``sys.path``
    first; installing into that directory would fight with Blender's wheel
    manager, which removes what it did not install.
    """
    prefix = os.path.normcase(os.path.abspath(sys.exec_prefix))
    for entry in sys.path:
        if not entry.endswith("site-packages"):
            continue
        absolute = os.path.normcase(os.path.abspath(entry))
        if absolute.startswith(prefix) and Path(entry).is_dir():
            return entry
    return str(Path(sys.exec_prefix) / "Lib" / "site-packages")


def _sys_path_set():
    return {os.path.normcase(os.path.abspath(entry)) for entry in sys.path if entry}


def install_target_candidates(probe_writable=True):
    """Ordered install directories, best first.

    The per-user ``scripts/modules`` directory is preferred. It follows the
    active Blender profile, survives Blender upgrades, and never modifies the
    application's installation directory. Writability can be deferred to the
    worker so opening diagnostics and pressing Install stay instantaneous.
    """
    candidates = []
    known_paths = _sys_path_set()

    modules_directory = _user_scripts_modules_directory(create=probe_writable)
    if modules_directory:
        candidates.append(
            InstallTarget(
                path=modules_directory,
                kind="target",
                on_sys_path=os.path.normcase(os.path.abspath(modules_directory)) in known_paths,
                writable=_directory_is_writable(modules_directory) if probe_writable else True,
                path_budget_ok=path_budget(modules_directory) >= LONGEST_RELATIVE_PACKAGE_PATH,
                note="Blender user scripts modules directory",
                writable_checked=probe_writable,
            )
        )

    site_packages = _interpreter_site_packages()
    if site_packages:
        candidates.append(
            InstallTarget(
                path=site_packages,
                kind="interpreter",
                on_sys_path=True,
                writable=_directory_is_writable(site_packages) if probe_writable else True,
                path_budget_ok=path_budget(site_packages) >= LONGEST_RELATIVE_PACKAGE_PATH,
                note="Blender bundled Python site-packages (fallback)",
                writable_checked=probe_writable,
            )
        )

    return tuple(candidates)


def choose_install_target(probe_writable=True):
    for candidate in install_target_candidates(probe_writable=probe_writable):
        if candidate.usable:
            return candidate
    return None


def validate_install_target(target):
    """Validate and create a prepared target on the background worker."""
    if target is None:
        return None
    return InstallTarget(
        path=target.path,
        kind=target.kind,
        on_sys_path=target.on_sys_path,
        writable=_directory_is_writable(target.path),
        path_budget_ok=path_budget(target.path) >= LONGEST_RELATIVE_PACKAGE_PATH,
        note=target.note,
        writable_checked=True,
    )


# ---------------------------------------------------------------------------
# Offline wheels
# ---------------------------------------------------------------------------


def addon_wheels_directory():
    return str(Path(__file__).resolve().parent / WHEELS_DIRECTORY_NAME)


def installed_as_extension():
    return (__package__ or "").startswith("bl_ext.")


def wheel_directories(extra=()):
    directories = []
    for path in (addon_wheels_directory(), *extra):
        if path and Path(path).is_dir():
            directories.append(str(Path(path).resolve()))
    return tuple(directories)


def available_wheels(extra=()):
    wheels = []
    for directory in wheel_directories(extra):
        wheels.extend(str(path) for path in sorted(Path(directory).glob("*.whl")))
    return tuple(wheels)


def _packaging_api():
    """Use packaging directly, or pip's bundled copy in minimal Blender Python."""
    try:
        from packaging.tags import sys_tags
        from packaging.utils import canonicalize_name, parse_wheel_filename
    except ImportError:
        from pip._vendor.packaging.tags import sys_tags
        from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
    return sys_tags, canonicalize_name, parse_wheel_filename


def select_compatible_wheels(wheels=None, supported_tags=None):
    """Choose one best bundled wheel per distribution for this Python.

    Unlike passing a whole directory to pip and hoping it selects correctly,
    this preflight records incompatible files and passes only exact compatible
    wheel paths to the offline install command.
    """
    wheels = tuple(available_wheels() if wheels is None else wheels)
    try:
        sys_tags, canonicalize_name, parse_wheel_filename = _packaging_api()
        ordered_tags = tuple(supported_tags) if supported_tags is not None else tuple(sys_tags())
    except Exception as e:
        return WheelSelection(
            (),
            wheels,
            (),
            errors=(f"Could not calculate Python wheel tags: {type(e).__name__}: {e}",),
        )

    tag_rank = {str(tag): index for index, tag in enumerate(ordered_tags)}
    selected = {}
    incompatible = []
    errors = []
    for wheel in wheels:
        try:
            name, version, _build, tags = parse_wheel_filename(Path(wheel).name)
            ranks = [tag_rank[str(tag)] for tag in tags if str(tag) in tag_rank]
            if not ranks:
                incompatible.append(wheel)
                continue
            distribution = canonicalize_name(str(name))
            candidate = (version, -min(ranks), wheel)
            previous = selected.get(distribution)
            if previous is None or candidate[:2] > previous[:2]:
                if previous is not None:
                    incompatible.append(previous[2])
                selected[distribution] = candidate
            else:
                incompatible.append(wheel)
        except Exception as e:
            incompatible.append(wheel)
            errors.append(f"{Path(wheel).name}: {type(e).__name__}: {e}")

    compatible = tuple(selected[name][2] for name in sorted(selected))
    sample = tuple(str(tag) for tag in ordered_tags[:8])
    return WheelSelection(
        compatible,
        tuple(incompatible),
        tuple(sorted(selected)),
        supported_tag_sample=sample,
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def _pip_available(python_executable, timeout=15.0):
    try:
        completed = subprocess.run(
            [python_executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_subprocess_flags(),
        )
        return completed.returncode == 0, (completed.stdout or completed.stderr or "").strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _subprocess_flags():
    flags = {}
    if platform.system() == "Windows":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def _emit_progress(callback, stage, message):
    if callback is None:
        return
    try:
        callback(stage, message)
    except Exception:
        logger.debug("Dependency progress callback failed", exc_info=True)


def probe_package_imports(
    python_executable,
    packages=REQUIRED_PACKAGES,
    search_paths=(),
    timeout=DEFAULT_PACKAGE_PROBE_TIMEOUT_SECONDS,
    progress=None,
):
    """Import each package in a disposable process with a hard timeout."""
    script = (
        "import importlib,json,sys;"
        "from importlib import metadata;"
        "name=sys.argv[1];"
        "module=importlib.import_module(name);"
        "\ntry: version=metadata.version(name)\n"
        "except Exception: version=str(getattr(module,'__version__','') or '')\n"
        "print(json.dumps({'version':version,'location':str(getattr(module,'__file__','') or '')}))"
    )
    environment = os.environ.copy()
    ordered_paths = []
    for entry in search_paths:
        value = str(entry or "")
        if value and value not in ordered_paths:
            ordered_paths.append(value)
    if ordered_paths:
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            ordered_paths + ([existing] if existing else [])
        )

    statuses = []
    for package in packages:
        _emit_progress(progress, "package_probe", f"Checking import of {package}…")
        try:
            completed = subprocess.run(
                [python_executable, "-c", script, package],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
                **_subprocess_flags(),
            )
        except subprocess.TimeoutExpired:
            statuses.append(
                DependencyStatus(
                    package,
                    False,
                    error=(
                        f"Timeout while importing {package} after {timeout:.0f} s "
                        f"in {python_executable}; the probe was stopped."
                    ),
                    verified=True,
                )
            )
            continue
        except Exception as e:
            statuses.append(
                DependencyStatus(
                    package,
                    False,
                    error=f"Could not probe {package}: {type(e).__name__}: {e}",
                    verified=True,
                )
            )
            continue

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            error = detail[-1][:1000] if detail else f"exit code {completed.returncode}"
            if "No module named" in error:
                error = ""
            statuses.append(
                DependencyStatus(package, False, error=error, verified=True)
            )
            continue
        try:
            data = json.loads((completed.stdout or "").strip().splitlines()[-1])
            statuses.append(
                DependencyStatus(
                    package,
                    True,
                    version=str(data.get("version") or ""),
                    location=str(data.get("location") or ""),
                    verified=True,
                )
            )
        except Exception as e:
            statuses.append(
                DependencyStatus(
                    package,
                    False,
                    error=f"Import probe returned invalid data: {type(e).__name__}: {e}",
                    verified=True,
                )
            )

    statuses = tuple(statuses)
    cache_dependency_statuses(statuses)
    return statuses


def _bootstrap_pip(python_executable, timeout):
    try:
        completed = subprocess.run(
            [python_executable, "-m", "ensurepip", "--upgrade", "--default-pip"],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_subprocess_flags(),
        )
        return completed.returncode == 0, (completed.stdout or "") + (completed.stderr or "")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _write_constraints_file(directory):
    """Pin bundled packages so a --target install cannot change their ABI."""
    versions = bundled_package_versions()
    if not versions:
        return ""
    path = Path(directory) / "scientia-constraints.txt"
    path.write_text(
        "".join(f"{name}=={version}\n" for name, version in sorted(versions.items())),
        encoding="utf-8",
    )
    return str(path)


def _install_command(
    python_executable,
    packages,
    target,
    wheel_dirs,
    constraints,
    trusted_hosts,
    no_dependencies=False,
):
    command = [
        python_executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        "--only-binary",
        ":all:",
    ]
    if no_dependencies:
        command.append("--no-deps")
    if target is not None and target.kind == "target":
        command.extend(["--target", target.path, "--upgrade"])
    if wheel_dirs:
        command.append("--no-index")
        for directory in wheel_dirs:
            command.extend(["--find-links", directory])
    if constraints:
        command.extend(["--constraint", constraints])
    for host in trusted_hosts or ():
        command.extend(["--trusted-host", host])
    command.extend(_pip_requirement(package) for package in packages)
    return tuple(command)


def _bundled_wheel_packages(wheels):
    """Packages to install from a complete local wheel set, excluding Blender's.

    Passing only ``matplotlib`` to pip asks it to resolve dependencies and put a
    second numpy into the user target. Passing every bundled non-numpy package
    with ``--no-deps`` installs the complete chart stack while keeping the
    numpy that Blender owns.
    """
    return tuple(sorted({
        _wheel_distribution_name(path)
        for path in wheels
        if _wheel_distribution_name(path) not in BUNDLED_PACKAGES
    }))


def _wheel_distribution_name(path):
    return Path(path).name.split("-", 1)[0].replace("_", "-").lower()


def _run_install(command, timeout):
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            **_subprocess_flags(),
        )
        return InstallAttempt(
            source="",
            command=tuple(command),
            returncode=completed.returncode,
            output=(completed.stdout or "")[-8000:],
            error=(completed.stderr or "")[-8000:],
        )
    except subprocess.TimeoutExpired:
        return InstallAttempt(
            source="",
            command=tuple(command),
            returncode=-1,
            error=f"pip did not finish within {timeout:.0f} s and was stopped. "
                  "A proxy or firewall is the usual cause on restricted networks.",
        )
    except Exception as e:
        return InstallAttempt(source="", command=tuple(command), returncode=-1, error=f"{type(e).__name__}: {e}")


def install_required_packages(
    packages=REQUIRED_PACKAGES,
    python_executable=None,
    timeout=DEFAULT_PIP_TIMEOUT_SECONDS,
    extra_wheel_directories=(),
    allow_online=True,
    trusted_hosts=(),
    install_target=_AUTO_INSTALL_TARGET,
    install_targets=(),
    expected_runtime=None,
    search_paths=(),
    progress=None,
    check_only=False,
):
    """Install missing packages after verifying runtime, target and wheels."""
    messages = []
    attempts = []
    python_executable = resolve_python_executable(python_executable)
    _emit_progress(progress, "runtime", f"Checking Blender Python at {python_executable}…")
    actual_runtime, runtime_error = probe_python_runtime(python_executable)
    if runtime_error:
        messages.append(runtime_error)
        return DependencyInstallResult(
            False,
            tuple(messages),
            tuple(packages),
            "\n".join(messages),
            failed_stage="runtime detection",
            error_source=runtime_error,
        )

    mismatch = runtime_mismatch(expected_runtime, actual_runtime)
    if mismatch:
        error = (
            f"Selected interpreter does not match Blender: {mismatch}. "
            f"Selected executable: {python_executable}."
        )
        messages.append(error)
        return DependencyInstallResult(
            False,
            tuple(messages),
            tuple(packages),
            "\n".join(messages),
            failed_stage="runtime verification",
            error_source=error,
            runtime=actual_runtime.summary,
        )
    messages.append(f"Verified Python: {actual_runtime.summary}")
    messages.append(f"Python executable actually used: {actual_runtime.executable}")
    messages.append(f"Python prefix: {actual_runtime.prefix}")

    if check_only:
        _emit_progress(
            progress,
            "package_probe",
            "Checking packages managed by Blender Extension…",
        )
        statuses = probe_package_imports(
            python_executable,
            packages,
            search_paths=tuple(search_paths or sys.path),
            progress=progress,
        )
        missing = tuple(status.name for status in statuses if not status.installed)
        if not missing:
            _emit_progress(progress, "done", "Extension chart packages are ready.")
            return DependencyInstallResult(
                True,
                ("Blender Extension packages are installed and verified.",),
                (),
                source="existing",
                runtime=actual_runtime.summary,
            )
        failed = next(status for status in statuses if not status.installed)
        error = (
            f"Blender Extension could not import {failed.name}"
            + (f": {failed.error}" if failed.error else ".")
            + " Reinstall or repair the Extension so Blender can restore its declared wheels."
        )
        messages.append(error)
        return DependencyInstallResult(
            False,
            tuple(messages),
            missing,
            "\n".join(messages),
            failed_stage=f"Extension package import: {failed.name}",
            error_source=failed.error or error,
            runtime=actual_runtime.summary,
        )

    _emit_progress(progress, "target", "Checking the package install directory…")
    target_was_prepared = install_target is not _AUTO_INSTALL_TARGET
    if install_targets:
        target_options = tuple(install_targets)
    elif target_was_prepared:
        target_options = (install_target,) if install_target is not None else ()
    else:
        target_options = install_target_candidates()

    checked_targets = []
    target = None
    for option in target_options:
        checked = option if option.writable_checked else validate_install_target(option)
        checked_targets.append(checked)
        if target is None and checked.usable:
            target = checked
    if target is None:
        problems = []
        for candidate in checked_targets:
            reason = []
            if not candidate.writable:
                reason.append("not writable")
            if not candidate.path_budget_ok:
                reason.append(
                    f"path too long ({path_budget(candidate.path)} characters left of the Windows limit)"
                )
            if not candidate.on_sys_path and candidate.kind != "interpreter":
                reason.append("will be added to sys.path")
            problems.append(f"{candidate.path}: {', '.join(reason) or 'unusable'}")
        detail = " | ".join(problems)
        error = "No usable install directory." + (f" {detail}" if detail else "")
        messages.append(error)
        return DependencyInstallResult(
            False,
            tuple(messages),
            tuple(packages),
            "\n".join(messages),
            failed_stage="install directory verification",
            error_source=error,
            runtime=actual_runtime.summary,
        )

    messages.append(f"Install directory: {target.path} ({target.note})")
    _ensure_on_sys_path(target)
    probe_paths = tuple(
        dict.fromkeys((target.path, *tuple(search_paths or ()), *tuple(sys.path)))
    )

    _emit_progress(progress, "package_probe", "Checking currently installed chart packages…")
    initial_statuses = probe_package_imports(
        python_executable,
        packages,
        search_paths=probe_paths,
        progress=progress,
    )
    initial_missing = tuple(status.name for status in initial_statuses if not status.installed)
    if not initial_missing:
        _emit_progress(progress, "done", "Chart packages are ready.")
        return DependencyInstallResult(
            True,
            ("Dependencies already installed and verified: " + ", ".join(packages),),
            (),
            source="existing",
            target=target.path,
            runtime=actual_runtime.summary,
        )

    if any(package in BUNDLED_PACKAGES for package in initial_missing):
        status = next(
            status for status in initial_statuses
            if status.name in BUNDLED_PACKAGES and not status.installed
        )
        error = (
            f"Blender's bundled {status.name} could not be imported"
            + (f": {status.error}" if status.error else ".")
            + " ScientiaJoints will not install a second binary copy."
        )
        messages.append(error)
        return DependencyInstallResult(
            False,
            tuple(messages),
            initial_missing,
            "\n".join(messages),
            failed_stage=f"importing {status.name}",
            error_source=status.error or error,
            target=target.path,
            runtime=actual_runtime.summary,
        )

    _emit_progress(progress, "pip", "Checking pip in Blender Python…")
    pip_ok, pip_message = _pip_available(python_executable)
    if not pip_ok:
        messages.append(f"pip is not available ({pip_message}); bootstrapping it.")
        _emit_progress(progress, "pip_bootstrap", "Preparing pip in Blender Python…")
        bootstrapped, bootstrap_log = _bootstrap_pip(python_executable, min(timeout, 60.0))
        if not bootstrapped:
            error = f"Failed to bootstrap pip: {bootstrap_log.strip()[-500:]}"
            messages.append(error)
            return DependencyInstallResult(
                False,
                tuple(messages),
                initial_missing,
                "\n".join(messages),
                failed_stage="pip bootstrap",
                error_source=error,
                target=target.path,
                runtime=actual_runtime.summary,
            )
        messages.append("pip bootstrapped.")
    else:
        messages.append(f"pip: {pip_message}")

    with tempfile.TemporaryDirectory(prefix="scientia-deps-") as workdir:
        constraints = _write_constraints_file(workdir) if target.kind == "target" else ""
        if constraints:
            messages.append(
                "Pinned bundled packages so the install cannot add a second copy: "
                + ", ".join(f"{name}=={version}" for name, version in sorted(bundled_package_versions().items()))
            )

        sources = []
        wheels = available_wheels(extra_wheel_directories)
        if wheels:
            _emit_progress(
                progress,
                "wheel_selection",
                f"Selecting offline wheels for {actual_runtime.cache_tag or actual_runtime.version_text}…",
            )
            selection = select_compatible_wheels(wheels)
            compatible_non_numpy = tuple(
                path for path in selection.compatible
                if _wheel_distribution_name(path) not in BUNDLED_PACKAGES
            )
            required_offline = {
                _pip_name(name).replace("_", "-").lower()
                for name in initial_missing
                if name not in BUNDLED_PACKAGES
            }
            available_offline = {
                _wheel_distribution_name(path) for path in compatible_non_numpy
            }
            absent = sorted(required_offline - available_offline)
            messages.append(
                f"Offline wheel selection: {len(selection.compatible)} compatible, "
                f"{len(selection.incompatible)} incompatible for "
                f"{actual_runtime.cache_tag or actual_runtime.version_text}."
            )
            if selection.supported_tag_sample:
                messages.append("Supported wheel tags include: " + ", ".join(selection.supported_tag_sample[:4]))
            if selection.errors:
                messages.extend(selection.errors)
            if compatible_non_numpy and not absent:
                sources.append((
                    "bundled wheels",
                    wheel_directories(extra_wheel_directories),
                    (),
                    compatible_non_numpy,
                    True,
                    min(timeout, DEFAULT_OFFLINE_PIP_TIMEOUT_SECONDS),
                    selection,
                ))
            else:
                detail = ", ".join(absent) if absent else "no compatible chart wheels"
                messages.append(
                    f"Bundled wheels cannot satisfy this Python ({detail}); "
                    "incompatible files will not be passed to pip."
                )
        if allow_online:
            sources.append(("PyPI", (), (), initial_missing, False, timeout, None))
            if trusted_hosts:
                sources.append((
                    "PyPI without certificate verification",
                    (),
                    tuple(trusted_hosts),
                    initial_missing,
                    False,
                    timeout,
                    None,
                ))

        if not sources:
            error = (
                "No compatible installation source is available: the bundled wheels do not "
                "match this Python and online installation is disabled."
            )
            messages.append(error)
            return DependencyInstallResult(
                False,
                tuple(messages),
                initial_missing,
                "\n".join(messages),
                failed_stage="offline wheel selection",
                error_source=error,
                target=target.path,
                runtime=actual_runtime.summary,
            )

        used_source = ""
        used_selection = None
        for (
            source_name,
            wheel_dirs,
            hosts,
            source_packages,
            no_dependencies,
            source_timeout,
            source_selection,
        ) in sources:
            _emit_progress(
                progress,
                "pip_install",
                f"Installing chart packages from {source_name}; please wait…",
            )
            command = _install_command(
                python_executable,
                source_packages,
                target,
                wheel_dirs,
                # An offline install resolves against the wheel directory,
                # which already fixes every version; pinning on top of it only
                # creates unsatisfiable requirements.
                "" if wheel_dirs else constraints,
                hosts,
                no_dependencies=no_dependencies,
            )
            logger.info("Installing %s from %s", ", ".join(initial_missing), source_name)
            attempt = _run_install(command, source_timeout)
            attempt = InstallAttempt(
                source=source_name,
                command=attempt.command,
                returncode=attempt.returncode,
                output=attempt.output,
                error=attempt.error,
            )
            attempts.append(attempt)
            if attempt.returncode == 0:
                used_source = source_name
                used_selection = source_selection
                messages.append(f"pip install from {source_name} finished successfully.")
                break
            messages.append(
                f"Installation from {source_name} failed (exit code {attempt.returncode}): "
                + _summarize_pip_failure(attempt)
            )

    importlib.invalidate_caches()
    _ensure_on_sys_path(target)
    _drop_failed_imports(initial_missing)

    _emit_progress(progress, "verification", "Verifying installed packages in Blender Python…")
    final_statuses = probe_package_imports(
        python_executable,
        packages,
        search_paths=probe_paths,
        progress=progress,
    )
    missing = tuple(status.name for status in final_statuses if not status.installed)
    if missing:
        messages.append("Still missing after installation: " + ", ".join(missing))
        for hint in installation_hints(missing, target, attempts, statuses=final_statuses):
            messages.append(hint)
    else:
        messages.append("Dependencies are available: " + ", ".join(packages))
        _emit_progress(progress, "done", "Installation finished. Chart packages are ready.")

    log_parts = []
    for attempt in attempts:
        log_parts.append(f"$ {' '.join(attempt.command)}")
        log_parts.append(attempt.output.strip())
        log_parts.append(attempt.error.strip())
    log = "\n".join(part for part in log_parts if part)
    failed_status = next((status for status in final_statuses if not status.installed), None)
    failed_stage = f"importing {failed_status.name}" if failed_status is not None else ""
    error_source = failed_status.error if failed_status is not None else ""
    if missing and attempts and not used_source:
        failed_stage = f"pip install from {attempts[-1].source}"
        error_source = _summarize_pip_failure(attempts[-1])
    elif missing and not error_source and attempts:
        error_source = _summarize_pip_failure(attempts[-1])

    return DependencyInstallResult(
        not missing,
        tuple(messages),
        tuple(missing),
        log,
        tuple(attempts),
        source=used_source,
        target=target.path,
        failed_stage=failed_stage,
        error_source=error_source,
        runtime=actual_runtime.summary,
        compatible_wheels=tuple(used_selection.compatible) if used_selection else (),
    )


def _ensure_on_sys_path(target):
    if target is None:
        return
    absolute = str(Path(target.path).absolute())
    normalized = os.path.normcase(absolute)
    existing = [
        entry for entry in sys.path
        if entry and os.path.normcase(os.path.abspath(entry)) == normalized
    ]
    for entry in existing:
        sys.path.remove(entry)
    # A managed user target must win over stale copies elsewhere. numpy is
    # never installed there, so Blender's binary package remains authoritative.
    if target.kind == "target":
        sys.path.insert(0, absolute)
    else:
        sys.path.append(absolute)


def prepare_background_install():
    """Capture Blender-owned paths quickly; validate I/O on the worker."""
    runtime = current_python_runtime()
    if installed_as_extension():
        return {
            "python_executable": runtime.executable,
            "expected_runtime": runtime,
            "search_paths": tuple(sys.path),
            "check_only": True,
        }
    targets = install_target_candidates(probe_writable=False)
    target = next((candidate for candidate in targets if candidate.usable), None)
    _ensure_on_sys_path(target)
    return {
        "python_executable": resolve_python_executable(),
        "install_target": target,
        "install_targets": targets,
        "expected_runtime": runtime,
        "search_paths": tuple(sys.path),
    }


def _drop_failed_imports(packages):
    """Remove half-imported modules so a retry sees the freshly installed copy."""
    for package in packages:
        for name in [name for name in list(sys.modules) if name == package or name.startswith(package + ".")]:
            module = sys.modules.get(name)
            if module is not None and getattr(module, "__file__", None) is None:
                sys.modules.pop(name, None)


def _summarize_pip_failure(attempt):
    text = f"{attempt.error}\n{attempt.output}".lower()
    if "timed out" in text or "did not finish within" in text:
        return "the download timed out; a proxy or firewall usually causes this."
    if "certificate verify failed" in text or "sslerror" in text or "ssl:" in text:
        return (
            "TLS certificate verification failed. Corporate networks that inspect HTTPS traffic "
            "cause this; use bundled wheels or an internal package index."
        )
    if "proxyerror" in text or "proxy" in text:
        return "the proxy rejected the connection."
    if "could not find a version" in text or "no matching distribution" in text:
        return "no matching wheel was found for this Python version or platform."
    if "permission denied" in text or "access is denied" in text or "winerror 5" in text:
        return "the install directory is not writable."
    if "no space left" in text or "not enough space" in text:
        return "the disk is full."
    if "temporary failure in name resolution" in text or "getaddrinfo" in text or "network is unreachable" in text:
        return "the package index is unreachable (no network or DNS)."
    tail = (attempt.error or attempt.output or "").strip().splitlines()
    return tail[-1][:300] if tail else "see the diagnostics report for the full pip log."


def installation_hints(missing, target=None, attempts=(), statuses=None):
    """Human readable causes and next steps for a failed installation."""
    hints = []
    target = target or choose_install_target()

    if target is not None:
        remaining = path_budget(target.path)
        if remaining < LONGEST_RELATIVE_PACKAGE_PATH:
            hints.append(
                f"The install directory path leaves only {remaining} characters before the Windows "
                "260 character limit. matplotlib data files silently fail to open past that limit. "
                "Move the Blender configuration to a shorter path or install the extension build."
            )

    status_map = {
        status.name: status
        for status in (
            statuses if statuses is not None else safe_dependency_statuses(missing)
        )
        if status.name in missing
    }
    for name, status in status_map.items():
        if "numpy.dtype size changed" in status.error or "binary incompatibility" in status.error.lower():
            hints.append(
                f"{name} was built against a different numpy than the one Blender bundles. "
                "Remove the installed copy and reinstall so numpy stays at the bundled version."
            )
        elif isinstance(status.error, str) and "FileNotFoundError" in status.error:
            hints.append(
                f"{name} is installed but cannot read its own data files. This is the Windows "
                "path length limit; reinstall into a shorter directory."
            )

    if not available_wheels():
        hints.append(
            "No wheels are bundled with this add-on build. On a restricted network install the "
            "extension build, which carries the packages inside the archive."
        )

    for attempt in attempts:
        summary = _summarize_pip_failure(attempt)
        if summary not in hints:
            hints.append(f"{attempt.source}: {summary}")

    return tuple(hints)


# ---------------------------------------------------------------------------
# Attempt bookkeeping and background installation
# ---------------------------------------------------------------------------


def _state_file():
    try:
        import bpy

        config = bpy.utils.user_resource('CONFIG')
    except Exception:
        config = tempfile.gettempdir()
    return Path(config or tempfile.gettempdir()) / "scientiajoints_dependencies.json"


def read_install_state():
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_install_state(state):
    try:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("Could not store dependency install state: %s", e)


def should_attempt_automatic_install(packages=REQUIRED_PACKAGES, now=None):
    """Automatic installs retry at most once a day so startup stays fast."""
    if not missing_packages(packages):
        return False
    state = read_install_state()
    if state.get("fingerprint") != automatic_install_fingerprint(packages):
        # A new add-on build, Python, wheel set, or corrected install policy
        # deserves one immediate attempt even if an older build just failed.
        return True
    last = float(state.get("last_attempt", 0.0) or 0.0)
    if not last:
        return True
    now = time.time() if now is None else now
    return (now - last) >= INSTALL_RETRY_INTERVAL_SECONDS


def record_install_attempt(result, now=None):
    state = read_install_state()
    state["last_attempt"] = time.time() if now is None else now
    state["ok"] = bool(getattr(result, "ok", False))
    state["missing"] = list(getattr(result, "missing_after_install", ()) or ())
    state["source"] = str(getattr(result, "source", "") or "")
    state["target"] = str(getattr(result, "target", "") or "")
    state["runtime"] = str(getattr(result, "runtime", "") or "")
    state["failed_stage"] = str(getattr(result, "failed_stage", "") or "")
    state["error_source"] = str(getattr(result, "error_source", "") or "")
    state["fingerprint"] = automatic_install_fingerprint()
    write_install_state(state)


def automatic_install_fingerprint(packages=REQUIRED_PACKAGES):
    """Stable identity of the environment covered by one failed attempt."""
    try:
        target = choose_install_target(probe_writable=False)
        target_path = target.path if target is not None else ""
    except Exception:
        target_path = ""
    wheels = []
    for path in available_wheels():
        try:
            wheel_path = Path(path)
            wheels.append((wheel_path.name, wheel_path.stat().st_size))
        except OSError:
            wheels.append((Path(path).name, -1))
    payload = {
        "policy": INSTALL_POLICY_VERSION,
        "packages": [_pip_requirement(package) for package in packages],
        "python": list(sys.version_info[:3]),
        "executable": resolve_python_executable(),
        "addon": str(Path(__file__).resolve().parent),
        "target": target_path,
        "wheels": sorted(wheels),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BackgroundInstall:
    """Run ``install_required_packages()`` off the main thread.

    The worker never touches ``bpy``; the caller polls :meth:`result` from a
    Blender timer, so nothing blocks the UI and Blender startup never waits on
    the network.
    """

    def __init__(self, packages=REQUIRED_PACKAGES, **kwargs):
        self.packages = tuple(packages)
        self.kwargs = kwargs
        self._thread = None
        self._result = None
        self._started_at = 0.0
        self._lock = threading.Lock()
        self._stage = "queued"
        self._message = "Waiting to start…"

    def start(self):
        if self.running:
            return False
        self._result = None
        self._started_at = time.monotonic()
        self._stage = "starting"
        self._message = "Starting dependency check…"
        self._thread = threading.Thread(
            target=self._run,
            name="ScientiaJoints-dependency-install",
            daemon=True,
        )
        self._thread.start()
        return True

    def _run(self):
        try:
            caller_progress = self.kwargs.pop("progress", None)

            def progress(stage, message):
                with self._lock:
                    self._stage = str(stage)
                    self._message = str(message)
                if caller_progress is not None:
                    caller_progress(stage, message)

            result = install_required_packages(
                self.packages,
                progress=progress,
                **self.kwargs,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Dependency installation crashed")
            with self._lock:
                failed_stage = self._stage
            result = DependencyInstallResult(
                False,
                (f"Installation crashed at {failed_stage}: {e}",),
                self.packages,
                failed_stage=failed_stage,
                error_source=f"{type(e).__name__}: {e}",
            )
        with self._lock:
            self._result = result
            if result.ok:
                self._stage = "done"
                self._message = (
                    "Dependency check finished."
                    if result.source == "existing"
                    else "Installation finished. Chart packages are ready."
                )
            else:
                self._stage = result.failed_stage or self._stage or "failed"
                self._message = (
                    f"Stopped at {self._stage}: "
                    f"{result.error_source or 'see diagnostics for details'}"
                )

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self):
        return time.monotonic() - self._started_at if self._started_at else 0.0

    def result(self):
        with self._lock:
            return self._result

    def snapshot(self):
        with self._lock:
            return {
                "stage": self._stage,
                "message": self._message,
                "elapsed": self.elapsed,
            }
