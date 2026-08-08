"""Installable ADD-ONS, Blender's model.

An add-on is a Python module that MoloM imports and hands the main window to.
It may do anything the application itself can do — add a properties page,
register F3 operators, put items in menus, spawn scene objects. There is
deliberately no sandbox and no capability list: an add-on is opt-in, and a
user who installs one they wrote themselves owns the consequences.

**Writing one.** A module (`thing.py`) or a package (`thing/__init__.py`) with:

    ADDON = {
        "id": "my_thing",              # unique, stable, used in settings
        "name": "My Thing",
        "description": "What it does.",
        "version": (1, 0),
        "author": "Someone",
    }

    def register(window):
        ...                            # window is the live MainWindow

    def unregister(window):
        ...                            # undo whatever register did

**Where they live.** Two roots, both listed together:

* BUNDLED — `molom/addons/`, shipped with the application. The debug and
  sandbox pipeline pages live here, disabled by default, which is what keeps
  them out of the way while still proving this API carries a real page.
* USER — `~/.molom/addons/`, where anything dropped in shows up next launch.

**Metadata is read WITHOUT importing.** `ADDON` is parsed out of the source
with `ast`, so listing the available add-ons never executes third-party code
— only enabling one does. That keeps a broken add-on from taking the whole
preferences dialog down with it.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import traceback
from collections import namedtuple

__all__ = ["ADDON_API_VERSION", "AddOnInfo", "AddOnManager",
           "bundled_dir", "user_dir", "discover"]

#: Bumped when the contract above changes incompatibly. An add-on may declare
#: `"api": N` to say which it was written against.
ADDON_API_VERSION = 1

#: One discovered add-on. `error` is set when its metadata could not be read;
#: it is still listed, because a broken add-on the user cannot see is worse
#: than one they can see is broken.
AddOnInfo = namedtuple(
    "AddOnInfo", "id name description version author path bundled error")


def bundled_dir():
    # type: () -> str
    """The add-ons shipped inside the package."""
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "addons")


def user_dir():
    # type: () -> str
    """Where a user drops their own. Created on demand, never at import."""
    return os.path.join(os.path.expanduser("~"), ".molom", "addons")


def _candidates(root):
    # type: (str) -> list
    """`(id, path)` for every module or package directly under `root`."""
    out = []
    if not os.path.isdir(root):
        return out
    for entry in sorted(os.listdir(root)):
        if entry.startswith((".", "_")):
            continue
        full = os.path.join(root, entry)
        if os.path.isdir(full):
            init = os.path.join(full, "__init__.py")
            if os.path.isfile(init):
                out.append((entry, init))
        elif entry.endswith(".py"):
            out.append((entry[:-3], full))
    return out


def _read_metadata(path):
    # type: (str) -> tuple
    """The `ADDON` dict, parsed from source WITHOUT executing it."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError) as exc:
        return {}, "could not be read: {}".format(exc)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "ADDON" not in names:
            continue
        try:
            return ast.literal_eval(node.value), ""
        except (ValueError, SyntaxError) as exc:
            return {}, "ADDON is not a literal dict: {}".format(exc)
    return {}, "no ADDON dict found"


def discover(paths=None):
    # type: (list) -> list
    """Every add-on found under `paths` (bundled and user roots by default)."""
    roots = paths if paths is not None else [bundled_dir(), user_dir()]
    seen = {}
    for root in roots:
        bundled = os.path.abspath(root) == os.path.abspath(bundled_dir())
        for name, path in _candidates(root):
            meta, error = _read_metadata(path)
            ident = str(meta.get("id") or name)
            version = meta.get("version") or ()
            info = AddOnInfo(
                id=ident,
                name=str(meta.get("name") or name),
                description=str(meta.get("description") or ""),
                version=tuple(version) if isinstance(version, (list, tuple))
                else (version,),
                author=str(meta.get("author") or ""),
                path=path, bundled=bundled, error=error)
            # A user add-on with the same id shadows a bundled one, which is
            # how someone patches a shipped page without editing the install.
            seen[ident] = info
    return sorted(seen.values(), key=lambda a: (not a.bundled, a.name.lower()))


class AddOnManager(object):
    """Discovers, enables and disables add-ons.

    UI-free: it takes the object to hand to `register()` and knows nothing
    about how the enabled set is persisted. `MainWindow` keeps that in
    QSettings and passes it in.
    """

    def __init__(self, paths=None):
        self.paths = paths
        self.available = []        # type: list
        self._modules = {}         # id -> module
        self.errors = {}           # id -> message
        self.refresh()

    def refresh(self):
        self.available = discover(self.paths)
        return self.available

    def info(self, addon_id):
        # type: (str) -> AddOnInfo
        for info in self.available:
            if info.id == addon_id:
                return info
        return None

    @property
    def enabled(self):
        # type: () -> set
        return set(self._modules)

    def is_enabled(self, addon_id):
        return addon_id in self._modules

    def enable(self, addon_id, window):
        # type: (str, object) -> tuple
        """Import and register one add-on. Returns `(ok, message)`.

        Never raises: a third-party module that blows up on import or in
        `register()` must not take the application with it. The traceback is
        kept so the preferences dialog can show what went wrong.
        """
        if addon_id in self._modules:
            return True, ""
        info = self.info(addon_id)
        if info is None:
            return False, "no such add-on: {}".format(addon_id)
        if info.error:
            return False, info.error
        try:
            module = self._import(info)
        except Exception:                       # noqa: BLE001 - see docstring
            message = traceback.format_exc(limit=6)
            self.errors[addon_id] = message
            return False, message
        register = getattr(module, "register", None)
        if not callable(register):
            self.errors[addon_id] = "no register() function"
            return False, self.errors[addon_id]
        try:
            register(window)
        except Exception:                       # noqa: BLE001
            message = traceback.format_exc(limit=6)
            self.errors[addon_id] = message
            return False, message
        self._modules[addon_id] = module
        self.errors.pop(addon_id, None)
        return True, ""

    def disable(self, addon_id, window):
        # type: (str, object) -> tuple
        """Call `unregister()` if the add-on has one, and forget it.

        An add-on that does not clean up properly leaves its tab behind until
        the next launch — which is why the preferences dialog says a restart
        is needed rather than promising a live removal it cannot enforce.
        """
        module = self._modules.pop(addon_id, None)
        if module is None:
            return True, ""
        unregister = getattr(module, "unregister", None)
        if not callable(unregister):
            return True, ""
        try:
            unregister(window)
        except Exception:                       # noqa: BLE001
            message = traceback.format_exc(limit=6)
            self.errors[addon_id] = message
            return False, message
        return True, ""

    def enable_all(self, ids, window):
        # type: (list, object) -> dict
        """Enable each of `ids`, collecting failures rather than stopping."""
        failed = {}
        for addon_id in ids:
            ok, message = self.enable(addon_id, window)
            if not ok:
                failed[addon_id] = message
        return failed

    # ------------------------------------------------------------ internals
    def _import(self, info):
        """Import by PATH, so an add-on need not be on sys.path.

        The module is registered in `sys.modules` under a namespaced name so
        a package add-on's own relative imports work, and so enabling twice
        does not re-execute it.
        """
        name = "molom_addon_{}".format(info.id)
        if name in sys.modules:
            return sys.modules[name]
        is_package = os.path.basename(info.path) == "__init__.py"
        spec = importlib.util.spec_from_file_location(
            name, info.path,
            submodule_search_locations=[os.path.dirname(info.path)]
            if is_package else None)
        if spec is None or spec.loader is None:
            raise ImportError("cannot load {}".format(info.path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module
