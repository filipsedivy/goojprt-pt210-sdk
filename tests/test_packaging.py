"""Guard against undeclared runtime dependencies.

A dev-only package (``numpy`` once was one) that the SDK imports makes
``pip install goojprt-pt210-sdk`` fail at the first print, while CI stays
green because it installs the dev group too. Every third-party module
imported anywhere in the ``goojprt`` package — including imports inside
functions — must therefore belong to a declared dependency.
"""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_dependencies() -> set[str]:
    with open(ROOT / "pyproject.toml", "rb") as f:
        project = tomllib.load(f)["project"]
    return {
        _normalise(re.match(r"[A-Za-z0-9._-]+", requirement).group(0))
        for requirement in project["dependencies"]
    }


def _imported_top_level_modules(package_dir: Path) -> dict[str, Path]:
    """Map every top-level module imported inside ``package_dir`` to one importing file."""
    found: dict[str, Path] = {}
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], path)
    return found


def test_every_third_party_import_in_goojprt_is_a_declared_dependency():
    declared = _declared_dependencies()
    distributions = packages_distributions()
    undeclared = []
    for module, path in _imported_top_level_modules(ROOT / "goojprt").items():
        if module == "goojprt" or module in sys.stdlib_module_names:
            continue
        owners = {_normalise(d) for d in distributions.get(module, [])}
        if not owners & declared:
            undeclared.append(f"{module} (imported in {path.relative_to(ROOT)})")
    assert not undeclared, (
        "goojprt imports modules that no declared dependency provides — add the "
        "package to [project].dependencies in pyproject.toml: " + ", ".join(undeclared)
    )
