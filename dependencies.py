"""Chart dependency detection and installation for Blender Python.

The add-on needs ``matplotlib`` and ``mplstereonet`` (``numpy`` ships with
Blender). Installing them into a Blender build is the single most common
failure point reported by users, so this module is deliberately explicit about
every step it takes and every reason an attempt can fail:

- Blender's interpreter is resolved without ever launching ``blender.exe``.
- ``pip install --user`` is never used: Blender disables the user site.
- The install directory is picked from candidates that are actually on
  ``sys.path``, actually writable, and short enough for the Windows 260
  character path limit (a longer path silently breaks ``matplotlib`` at import
  time even though every file is on disk).
- ``numpy`` is pinned to the version bundled with Blender so a ``--target``
  install cannot introduce a second, ABI-incompatible copy.
- Wheels shipped inside the add-on are preferred over PyPI, which makes the
  add-on installable on networks that block package indexes.
- Every subprocess has a timeout and its output is captured into the result.
"""

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
#: Do not retry a failed automatic installation more often than this.
INSTALL_RETRY_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    installed: bool
    error: str = ""
    version: str = ""
    location: str = ""


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


@dataclass
class InstallTarget:
    """A directory pip can install into."""

    path: str
    kind: str  # "interpreter" | "target"
    on_sys_path: bool
    writable: bool
    path_budget_ok: bool
    note: str = ""

    @property
    def usable(self):
        return self.writable and self.path_budget_ok and (self.on_sys_path or self.kind == "interpreter")


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


def outdated_packages(packages=REQUIRED_PACKAGES):
    """Installed packages older than :data:`MINIMUM_VERSIONS` requires.

    Each entry is ``(name, installed version, required version)``. A package
    whose version cannot be read is left out: an unknown version is not
    evidence of an old one, and a false alarm here sends users reinstalling
    working dependencies.
    """
    outdated = []
    for status in check_required_packages(packages):
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
    module = sys.modules.get(package)
    version = str(getattr(module, "__version__", "") or "") if module is not None else ""
    location = str(getattr(module, "__file__", "") or "") if module is not None else ""
    if not version:
        try:
            from importlib import metadata

            version = metadata.version(_pip_name(package))
        except Exception:
            version = ""
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
            )
        )
    return tuple(statuses)


def missing_packages(packages=REQUIRED_PACKAGES):
    return tuple(status.name for status in check_required_packages(packages) if not status.installed)


def dependency_summary(packages=REQUIRED_PACKAGES):
    statuses = check_required_packages(packages)
    missing = [status.name for status in statuses if not status.installed and not status.error]
    broken = [f"{status.name}: {status.error}" for status in statuses if status.error]

    if not missing and not broken:
        return True, "Dependencies OK: " + ", ".join(status.name for status in statuses)

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
            if importlib.util.find_spec(package) is None:
                continue
            module = importlib.import_module(package)
        except Exception:
            continue
        version = str(getattr(module, "__version__", "") or "")
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
    if candidate and not looks_like_blender and os.path.basename(candidate).lower().startswith("python"):
        return candidate
    if candidate and not looks_like_blender and not binary:
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


def _user_scripts_modules_directory():
    try:
        import bpy

        scripts = bpy.utils.user_resource('SCRIPTS')
    except Exception:
        return ""
    if not scripts:
        return ""
    return str(Path(scripts) / "addons" / "modules")


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


def install_target_candidates():
    """Ordered install directories, best first.

    The interpreter's own ``site-packages`` is preferred because pip then sees
    the bundled ``numpy`` and skips it entirely. It is unwritable whenever
    Blender lives in ``Program Files``, which is why the user scripts modules
    directory (already on ``sys.path``) is the fallback.
    """
    candidates = []
    known_paths = _sys_path_set()

    site_packages = _interpreter_site_packages()
    if site_packages:
        candidates.append(
            InstallTarget(
                path=site_packages,
                kind="interpreter",
                on_sys_path=True,
                writable=_directory_is_writable(site_packages),
                path_budget_ok=path_budget(site_packages) >= LONGEST_RELATIVE_PACKAGE_PATH,
                note="Blender bundled Python site-packages",
            )
        )

    modules_directory = _user_scripts_modules_directory()
    if modules_directory:
        candidates.append(
            InstallTarget(
                path=modules_directory,
                kind="target",
                on_sys_path=os.path.normcase(os.path.abspath(modules_directory)) in known_paths,
                writable=_directory_is_writable(modules_directory),
                path_budget_ok=path_budget(modules_directory) >= LONGEST_RELATIVE_PACKAGE_PATH,
                note="Blender user scripts modules directory",
            )
        )

    return tuple(candidates)


def choose_install_target():
    for candidate in install_target_candidates():
        if candidate.usable:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Offline wheels
# ---------------------------------------------------------------------------


def addon_wheels_directory():
    return str(Path(__file__).resolve().parent / WHEELS_DIRECTORY_NAME)


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


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def _pip_available(python_executable, timeout=60.0):
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


def _install_command(python_executable, packages, target, wheel_dirs, constraints, trusted_hosts):
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
):
    """Install missing packages, preferring wheels bundled with the add-on."""
    messages = []
    attempts = []
    initial_missing = missing_packages(packages)
    if not initial_missing:
        return DependencyInstallResult(
            True,
            ("Dependencies already installed: " + ", ".join(packages),),
            (),
        )

    python_executable = resolve_python_executable(python_executable)
    messages.append(f"Python interpreter: {python_executable}")

    target = choose_install_target()
    if target is None:
        problems = []
        for candidate in install_target_candidates():
            reason = []
            if not candidate.writable:
                reason.append("not writable")
            if not candidate.path_budget_ok:
                reason.append(
                    f"path too long ({path_budget(candidate.path)} characters left of the Windows limit)"
                )
            if not candidate.on_sys_path and candidate.kind != "interpreter":
                reason.append("not on sys.path")
            problems.append(f"{candidate.path}: {', '.join(reason) or 'unusable'}")
        messages.append("No usable install directory. " + " | ".join(problems))
        return DependencyInstallResult(False, tuple(messages), tuple(initial_missing), "\n".join(messages))

    messages.append(f"Install directory: {target.path} ({target.note})")

    pip_ok, pip_message = _pip_available(python_executable)
    if not pip_ok:
        messages.append(f"pip is not available ({pip_message}); bootstrapping it.")
        bootstrapped, bootstrap_log = _bootstrap_pip(python_executable, timeout)
        if not bootstrapped:
            messages.append(f"Failed to bootstrap pip: {bootstrap_log.strip()[-500:]}")
            return DependencyInstallResult(False, tuple(messages), tuple(initial_missing), "\n".join(messages))
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
            sources.append(("bundled wheels", wheel_directories(extra_wheel_directories), ()))
            messages.append(f"Found {len(wheels)} bundled wheel(s) in {', '.join(wheel_directories(extra_wheel_directories))}")
        if allow_online:
            sources.append(("PyPI", (), ()))
            if trusted_hosts:
                sources.append(("PyPI without certificate verification", (), tuple(trusted_hosts)))

        if not sources:
            messages.append("No installation source available: no bundled wheels and online installation is disabled.")
            return DependencyInstallResult(False, tuple(messages), tuple(initial_missing), "\n".join(messages))

        used_source = ""
        for source_name, wheel_dirs, hosts in sources:
            command = _install_command(
                python_executable,
                initial_missing,
                target,
                wheel_dirs,
                # An offline install resolves against the wheel directory,
                # which already fixes every version; pinning on top of it only
                # creates unsatisfiable requirements.
                "" if wheel_dirs else constraints,
                hosts,
            )
            logger.info("Installing %s from %s", ", ".join(initial_missing), source_name)
            attempt = _run_install(command, timeout)
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
                messages.append(f"pip install from {source_name} finished successfully.")
                break
            messages.append(
                f"Installation from {source_name} failed (exit code {attempt.returncode}): "
                + _summarize_pip_failure(attempt)
            )

    importlib.invalidate_caches()
    _ensure_on_sys_path(target)
    _drop_failed_imports(initial_missing)

    missing = missing_packages(packages)
    if missing:
        messages.append("Still missing after installation: " + ", ".join(missing))
        for hint in installation_hints(missing, target, attempts):
            messages.append(hint)
    else:
        messages.append("Dependencies are available: " + ", ".join(packages))

    log_parts = []
    for attempt in attempts:
        log_parts.append(f"$ {' '.join(attempt.command)}")
        log_parts.append(attempt.output.strip())
        log_parts.append(attempt.error.strip())
    log = "\n".join(part for part in log_parts if part)

    return DependencyInstallResult(
        not missing,
        tuple(messages),
        tuple(missing),
        log,
        tuple(attempts),
        source=used_source,
        target=target.path,
    )


def _ensure_on_sys_path(target):
    if target is None:
        return
    absolute = str(Path(target.path).absolute())
    if os.path.normcase(absolute) not in _sys_path_set():
        sys.path.append(absolute)


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


def installation_hints(missing, target=None, attempts=()):
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

    statuses = {status.name: status for status in check_required_packages(missing)}
    for name, status in statuses.items():
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
    write_install_state(state)


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

    def start(self):
        if self.running:
            return False
        self._result = None
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            name="ScientiaJoints-dependency-install",
            daemon=True,
        )
        self._thread.start()
        return True

    def _run(self):
        try:
            result = install_required_packages(self.packages, **self.kwargs)
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Dependency installation crashed")
            result = DependencyInstallResult(False, (f"Installation crashed: {e}",), self.packages)
        with self._lock:
            self._result = result

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self):
        return time.monotonic() - self._started_at if self._started_at else 0.0

    def result(self):
        with self._lock:
            return self._result
