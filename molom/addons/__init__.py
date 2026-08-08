"""Add-ons that ship WITH MoloM, all disabled by default.

Discovered by `core.addons`, listed in Preferences > Add-ons alongside
anything the user has dropped in `~/.molom/addons/`, and enabled one at a
time. See `core/addons.py` for what an add-on module has to contain.

Nothing in `molom/ui/` or `molom/core/` may import from here: the dependency
runs one way only, which is what keeps an add-on removable.
"""
