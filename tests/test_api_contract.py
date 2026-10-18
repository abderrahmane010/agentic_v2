"""
Test de contrat : chaque méthode appelée dans le code doit exister.

Le code d'origine appelait des méthodes inexistantes de dataikuapi
(get_triggers, wait_for_completion, get_dataframe...). Ce test parcourt le
code source et vérifie que chaque nom de méthode appelé existe dans
dataikuapi (version fixée dans pyproject.toml), dans les types natifs ou
dans la liste des méthodes de la bibliothèque standard utilisées.
"""

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

import dataikuapi

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [*ROOT.glob("dataiku_mcp/**/*.py"), *ROOT.glob("scripts/*.py")]

# Méthodes de la bibliothèque standard / d'autres paquets appelées dans le code.
OTHER_LIBRARIES = {
    "add_argument", "basicConfig", "bind", "apply_defaults", "compile",
    "deepcopy", "dump", "dumps", "fromtimestamp", "fullmatch", "getLogger",
    "insert", "isoformat", "loads", "most_common", "parse", "parse_args",
    "resource", "run", "safe_dump", "search", "setLevel", "signature",
    "tool", "wraps", "walk", "info", "warning", "error", "debug",
    "exception", "list_tools", "call_tool", "read_resource", "glob", "exit", "getenv", "monotonic", "disable_warnings",
    "writer", "writerow", "writerows", "filterwarnings", "remove_tool",
    "finditer", "escape", "model_dump", "initialize", "sub", "findall",
}


def _dataikuapi_members() -> set[str]:
    names: set[str] = set()
    for module in pkgutil.walk_packages(dataikuapi.__path__, "dataikuapi."):
        try:
            mod = importlib.import_module(module.name)
        except Exception:
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            for klass in cls.__mro__:
                names.update(vars(klass))
    return names


BUILTIN_MEMBERS = {
    name for t in (dict, list, str, set, tuple, bytes, int, float) for name in dir(t)
}


def _own_functions() -> set[str]:
    """Fonctions du projet (appelées via leur module : recipes.run_recipe)."""
    return {
        node.name
        for path in SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }


def test_every_called_method_exists():
    known = (
        _dataikuapi_members() | BUILTIN_MEMBERS | OTHER_LIBRARIES | _own_functions()
    )
    unknown = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr not in known and not attr[0].isupper():  # classes
                    unknown.append(f"{path.relative_to(ROOT)}:{node.lineno} .{attr}()")
    assert not unknown, "Méthodes inconnues :\n" + "\n".join(unknown)


def test_removed_methods_are_not_used():
    """Méthodes qui n'existent pas sur les objets où le code les appelait."""
    forbidden = {
        "get_triggers", "add_dataset_trigger", "get_run_history", "get_dataframe",
        "write_with_schema", "get_step_runs", "get_activities",
        "get_resource_usage", "set_engine_type", "set_format_type",
        "set_recipe_params", "get_jobs",
    }
    found = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.attr}")
    assert not found, "\n".join(found)
