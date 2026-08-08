"""Bundled add-on: the CIF pipeline, one stage at a time (🐞).

Load a CIF as text, then click any stage to run the REAL pipeline up to that
point and no further. Every click rebuilds from the text, so a picture can
never contain state left behind by a previous click.

Disabled by default. Preferences > Add-ons turns it on.
"""
from molom.core import pipeline
from molom.ui.debug_page import DebugPage

from molom.addons import _pipeline_host as host

ADDON = {
    "id": "debug_pipeline",
    "name": "Debug: CIF pipeline",
    "description": ("Step through the real CIF pipeline one stage at a time "
                    "— cell, sites, operators, wrap, dedupe, disorder, "
                    "molecules, boundary, bonds, fragments, complete — with a "
                    "per-stage trace of what each step did."),
    "version": (1, 0),
    "author": "MoloM",
    "api": 1,
}

_KEY = "debug"


def _on_stage(window, index, text):
    """Run the pipeline up to one stage and put THAT on screen.

    Deliberately does NOT go through `_perceive_fresh` — bonds are part of
    what is under inspection, and the stages below `bonds` are supposed to
    have none.
    """
    result = pipeline.run(text, index, disorder=window.disorder_policy)
    host.show_result(window, result, index, pipeline.STAGES,
                     window.debug_page, host.DEBUG_NAME)


def register(window):
    page = DebugPage()
    page.stage_requested.connect(
        lambda index, text, w=window: _on_stage(w, index, text))
    host.install(window, _KEY, "🐞",
                 "Debug: the CIF pipeline one stage at a time",
                 page, "debug_page")


def unregister(window):
    host.uninstall(window, _KEY, "debug_page")
