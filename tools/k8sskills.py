"""Load the pinned k8s-skills command checker, so the crew reuses its allow-list.

The checkout's code imports itself as ``tools.skillcheck...``, the same top-level name as this
package. It is imported with this package's ``tools`` entries swapped out of ``sys.modules`` for
the duration of the import and restored afterwards, so nothing of the checkout leaks.
"""

import importlib
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPO_URL = "https://github.com/k8s-servant/k8s-skills"
ROOT = Path(__file__).resolve().parent.parent
VERSIONS_ENV = ROOT / "tests" / "versions.env"
CACHE_DIR = ROOT / ".cache"

_loaded: dict[str, "Checker"] = {}


@dataclass
class Checker:
    """The k8s-skills command checker of one pinned ref."""

    allowlist: dict
    check_command: Callable[[str], list[str]]
    secret_problems: Callable[[str], list[str]]
    commands_module: ModuleType


def _read_pin(key: str) -> str:
    for line in VERSIONS_ENV.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip()
    raise ValueError(f"{key} not set in {VERSIONS_ENV}")


def read_ref() -> str:
    """Return K8S_SKILLS_REF (a readable label) from tests/versions.env."""
    return _read_pin("K8S_SKILLS_REF")


def read_sha() -> str:
    """Return K8S_SKILLS_SHA, the commit that is actually trusted, from tests/versions.env."""
    return _read_pin("K8S_SKILLS_SHA")


def _git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _download(sha: str, target: Path) -> None:
    """Fetch exactly commit ``sha`` into ``target``; no tag or branch is trusted."""
    target.mkdir(parents=True)
    _git("init", "--quiet", cwd=target)
    _git("fetch", "--quiet", "--depth", "1", REPO_URL, sha, cwd=target)
    _git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=target)


def _head(checkout: Path) -> str | None:
    try:
        return _git("rev-parse", "HEAD", cwd=checkout)
    except (subprocess.CalledProcessError, OSError):
        return None


def fetch(ref: str | None = None) -> Path:
    """Return the checkout of k8s-skills at the pinned commit, downloading it if needed.

    The checkout is executed, so its HEAD must equal K8S_SKILLS_SHA, also when it was restored
    from a cache. A checkout at another commit is deleted and downloaded once more.
    ``ref`` only names the directory.

    Raises:
        RuntimeError: If the checkout is not at the pinned commit after a fresh download.
    """
    ref = ref or read_ref()
    sha = read_sha()
    target = CACHE_DIR / f"k8s-skills-{ref}"
    if target.exists() and _head(target) == sha:
        return target
    shutil.rmtree(target, ignore_errors=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _download(sha, target)
    actual = _head(target)
    if actual != sha:
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError(f"k8s-skills checkout is at {actual}, expected {sha}")
    return target


def _import_commands(checkout: Path) -> ModuleType:
    own = {n: m for n, m in sys.modules.items() if n == "tools" or n.startswith("tools.")}
    for name in own:
        del sys.modules[name]
    try:
        init = checkout / "tools" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "tools", init, submodule_search_locations=[str(init.parent)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules["tools"] = package
        spec.loader.exec_module(package)
        return importlib.import_module("tools.skillcheck.commands")
    finally:
        for name in [n for n in sys.modules if n == "tools" or n.startswith("tools.")]:
            del sys.modules[name]
        sys.modules.update(own)


def load_checker(ref: str | None = None) -> Checker:
    """Load the command checker from the pinned k8s-skills checkout."""
    ref = ref or read_ref()
    checkout = fetch(ref)  # every call re-verifies the pinned commit before anything is imported
    if ref not in _loaded:
        commands = _import_commands(checkout)
        allowlist = commands.load_allowlist()
        _loaded[ref] = Checker(
            allowlist=allowlist,
            check_command=lambda cmd: commands._check_command(cmd, allowlist),
            secret_problems=commands._secret_problems,
            commands_module=commands,
        )
    return _loaded[ref]
