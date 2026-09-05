"""Round 106 - C1: keyframe animation in the Blender export.

Verified end to end by RUNNING Blender (round 37's rule) - butane's central
torsion exported as 25 baked frames came back from the .blend with the
terminal methyl hydrogens sweeping 4.306 A and the three frozen scan atoms
at exactly 0.000, every fcurve LINEAR, 40 of 40 objects animated. These are
the offline halves of that.
"""

import numpy as np
import pytest

from molom.core import blender_export as be
from molom.core import bonding, style as style_mod
from molom.core.scene import Scene
from molom.core.structure import Structure


def _spinner(n_frames=6):
    """Two atoms, one of which walks along x - so a keyframed position has an
    unambiguous right answer at every frame."""
    symbols = ["C", "C"]
    frames = [np.array([[0.0, 0.0, 0.0], [1.5 + 0.1 * k, 0.0, 0.0]])
              for k in range(n_frames)]
    st = Structure(symbols, frames[0], name="pair")
    st.frames = frames
    st.bonds = [(0, 1, 1)]
    scene = Scene()
    scene.add(st, name="pair")
    return scene, st


def _options():
    options = be.ExportOptions()
    options.polyhedra = False
    options.unit_cell = False
    return options


def _style():
    return style_mod.STYLE_BY_KEY.get("ball_and_stick") or style_mod.DEFAULT


def _seek_for(st):
    def seek(t):
        st.set_frame(int(round(t)))
    return seek


def test_every_rendered_frame_is_BAKED():
    """Rather than keyframing the source frames and letting Blender
    interpolate. MoloM's player turns the rigid part of a motion as a
    ROTATION (round 22's rigid_lerp); Blender's linear interpolation takes
    the chord, so source-frame keys would make the render disagree with the
    viewport on exactly the case round 22 exists to fix."""
    scene, st = _spinner(6)
    times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    anim = be.collect_animation(scene, _style(), _options(), times,
                                _seek_for(st))
    assert len(anim["atoms"]) == len(times), "one entry per rendered frame"
    for k, positions in enumerate(anim["atoms"]):
        assert positions[0] == pytest.approx([0.0, 0.0, 0.0])
        assert positions[1][0] == pytest.approx(1.5 + 0.1 * k)


def test_the_bonds_are_keyframed_too_and_follow_the_atoms():
    """A bond is a scaled and rotated cylinder, so it needs its whole matrix
    and not just a location - which is why the collector carries both ends."""
    scene, st = _spinner(4)
    anim = be.collect_animation(scene, _style(), _options(),
                                [0.0, 1.0, 2.0, 3.0], _seek_for(st))
    assert len(anim["bonds"]) == 4
    assert anim["bonds"][0], "there is a bond to animate"
    for k, segments in enumerate(anim["bonds"]):
        far = max(max(seg[0][0], seg[1][0]) for seg in segments)
        assert far == pytest.approx(1.5 + 0.1 * k, abs=1e-6), \
            "the stick reaches the atom it is drawn to"


def test_the_lists_line_up_across_frames():
    """They have to: a keyframe is written per OBJECT, so entry n has to be
    the same atom at every frame."""
    scene, st = _spinner(5)
    anim = be.collect_animation(scene, _style(), _options(),
                                [0.0, 1.0, 2.0, 3.0, 4.0], _seek_for(st))
    counts = {(len(a), len(b))
              for a, b in zip(anim["atoms"], anim["bonds"])}
    assert len(counts) == 1
    assert not anim["notes"]


def test_a_CONNECTIVITY_CHANGE_is_trimmed_and_REPORTED():
    """Where a trajectory re-perceives different bonds partway along there is
    no correspondence to keyframe. Round 57's `FIXED_BONDS` covers a baked
    vibration and round 106's scan preview freezes them for the same reason,
    so this is the leftover case - and it is said out loud rather than
    producing sticks that jump between atoms."""
    symbols = ["C", "C"]
    st = Structure(symbols, np.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0]]),
                   name="pair")
    st.frames = [np.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0]]),
                 np.array([[0.0, 0.0, 0.0], [9.0, 0.0, 0.0]])]
    st.bonds = [(0, 1, 1)]
    scene = Scene()
    scene.add(st, name="pair")

    def seek(t):
        st.set_frame(int(round(t)))
        bonding.perceive_structure_bonds(st)   # 9 A apart is not a bond

    anim = be.collect_animation(scene, _style(), _options(), [0.0, 1.0], seek)
    assert anim["notes"] and "connectivity" in anim["notes"][0]
    assert len({len(b) for b in anim["bonds"]}) == 1, "trimmed to line up"


def test_the_summary_says_what_BAKING_COSTS():
    """Baking every frame is what makes the render match the viewport and it
    is also what makes a .blend large, so the number belongs in the export's
    own summary rather than being discovered afterwards."""
    scene, st = _spinner(10)
    anim = be.collect_animation(scene, _style(), _options(),
                                [float(k) for k in range(10)],
                                _seek_for(st))
    text = be.animation_summary(anim)
    assert "10 frames baked" in text and "keyframes" in text
    assert be.animation_summary(None) == ""
    assert be.animation_summary({"atoms": []}) == ""


def test_the_script_carries_the_animation_and_still_parses():
    """The generated file is Python that Blender runs, so a malformed data
    block is a syntax error in somebody else's program."""
    scene, st = _spinner(4)
    options = _options()
    data = be.collect(scene, _style(), options)
    anim = be.collect_animation(scene, _style(), options,
                                [0.0, 1.0, 2.0, 3.0], _seek_for(st))
    data["animation"] = {"frame_start": 1, "fps": 24,
                         "atoms": anim["atoms"], "bonds": anim["bonds"]}
    script = be.build_script(data, options, title="pair")
    compile(script, "generated.py", "exec")
    assert "ANIMATION = {" in script
    assert "build_animation(" in script
    assert "rotation_quaternion" in script, "bonds rotate, so quaternions"
    assert '"LINEAR"' in script
    # ...and it stays ASCII, which is round 37's rule for generated source
    assert all(ord(c) < 128 for c in script)


def test_an_export_with_NO_animation_is_unchanged():
    """The still export is the common case and must not grow a frame range,
    a keyframe or a line of animation code it has no use for."""
    scene, st = _spinner(3)
    options = _options()
    data = be.collect(scene, _style(), options)
    script = be.build_script(data, options, title="still")
    compile(script, "generated.py", "exec")
    assert "ANIMATION = {}" in script
    assert be.summarise(data).count(";") == 0, "no baking clause"
