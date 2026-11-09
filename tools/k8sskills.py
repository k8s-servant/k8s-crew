"""Load the pinned k8s-skills command checker, so the crew reuses its allow-list.

The checkout's code imports itself as ``tools.skillcheck...``, the same top-level name as this
package. It is imported with this package's ``tools`` entries swapped out of ``sys.modules`` for
the duration of the import and restored afterwards, so nothing of the checkout leaks.
"""

import importlib
import importlib.util
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


def read_ref() -> str:
    """Return K8S_SKILLS_REF from tests/versions.env."""
    for line in VERSIONS_ENV.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "K8S_SKILLS_REF":
            return value.strip()
    raise ValueError(f"K8S_SKILLS_REF not set in {VERSIONS_ENV}")


def fetch(ref: str | None = None) -> Path:
    """Return the checkout of k8s-skills at ``ref``, cloning it (shallow) if missing."""
    ref = ref or read_ref()
    target = CACHE_DIR / f"k8s-skills-{ref}"
    if target.exists():
        return target
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", ref, REPO_URL, str(partial)],
        check=True,
    )
    partial.rename(target)
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
    if ref not in _loaded:
        commands = _import_commands(fetch(ref))
        allowlist = commands.load_allowlist()
        _loaded[ref] = Checker(
            allowlist=allowlist,
            check_command=lambda cmd: commands._check_command(cmd, allowlist),
            secret_problems=commands._secret_problems,
            commands_module=commands,
        )
    return _loaded[ref]
