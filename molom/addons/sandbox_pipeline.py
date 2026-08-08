"""Bundled add-on: an ALTERNATIVE crystal pipeline, under experiment (🧪).

Shares Cell / Sites / Operators / Wrap / Dedupe with the real pipeline by
calling it, then diverges: occupancies are settled into atoms, boundary atoms
are repeated onto their equivalent faces, bonds come from the periodic graph,
and every fragment reaching into the cell is drawn WHOLE rather than being
relocated.

Nothing the application draws for real goes through this. Disabled by default.
"""
from molom.core import sandbox
from molom.ui.sandbox_page import SandboxPage

from molom.addons import _pipeline_host as host

ADDON = {
    "id": "sandbox_pipeline",
    "name": "Sandbox: alternative pipeline",
    "description": ("An experimental crystal pipeline that completes whole "
                    "molecules across the cell boundary instead of relocating "
                    "them. For trying an algorithm on and comparing it with "
                    "the shipping one."),
    "version": (1, 0),
    "author": "MoloM",
    "api": 1,
}

_KEY = "sandbox"


def _on_stage(window, index, text):
    result = sandbox.run(text, index, **window.sandbox_page.options())
    host.show_result(window, result, index, sandbox.STAGES,
                     window.sandbox_page, host.SANDBOX_NAME)


def register(window):
    page = SandboxPage()
    page.stage_requested.connect(
        lambda index, text, w=window: _on_stage(w, index, text))
    host.install(window, _KEY, "🧪",
                 "Sandbox: an alternative pipeline, for experimenting",
                 page, "sandbox_page")


def unregister(window):
    host.uninstall(window, _KEY, "sandbox_page")
