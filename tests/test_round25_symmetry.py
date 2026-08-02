"""Round 25: classifying symmetry operations so they can be drawn."""

import numpy as np
import pytest

from molom.core import cif, symmetry


def _op(text):
    return cif.SymOp.from_xyz(text)


def test_identity():
    assert symmetry.classify(_op("x,y,z")).kind == symmetry.IDENTITY


def test_inversion_centre_and_its_position():
    e = symmetry.classify(_op("-x,-y,-z"))
    assert e.kind == symmetry.INVERSION
    assert e.point == pytest.approx([0, 0, 0])
    shifted = symmetry.classify(_op("-x+1/2,-y+1/2,-z+1/2"))
    assert shifted.kind == symmetry.INVERSION
    assert shifted.point == pytest.approx([0.25, 0.25, 0.25])


def test_mirror_plane_normal():
    e = symmetry.classify(_op("-x,y,z"))
    assert e.kind == symmetry.MIRROR
    assert abs(float(e.direction @ np.array([1.0, 0, 0]))) == pytest.approx(1.0)


@pytest.mark.parametrize("text,order,axis", [
    ("-x,-y,z", 2, [0, 0, 1]),
    ("-x,y,-z", 2, [0, 1, 0]),
    ("x,-y,-z", 2, [1, 0, 0]),
    ("-y,x,z", 4, [0, 0, 1]),
    ("-y,x-y,z", 3, [0, 0, 1]),
])
def test_rotation_order_and_axis(text, order, axis):
    e = symmetry.classify(_op(text))
    assert e.kind == symmetry.ROTATION
    assert e.order == order
    assert abs(float(e.direction @ np.array(axis, dtype=float))) \
        == pytest.approx(1.0, abs=1e-6)


def test_a_screw_axis_is_told_from_a_plain_rotation():
    """P2_1: a 2-fold with half a cell of translation ALONG its own axis."""
    plain = symmetry.classify(_op("-x,y,-z"))
    screw = symmetry.classify(_op("-x,y+1/2,-z"))
    assert plain.kind == symmetry.ROTATION
    assert screw.kind == symmetry.SCREW
    assert screw.order == 2
    assert float(np.linalg.norm(screw.intrinsic)) == pytest.approx(0.5)


def test_a_glide_plane_is_told_from_a_mirror():
    mirror = symmetry.classify(_op("x,y,-z"))
    glide = symmetry.classify(_op("x+1/2,y,-z"))
    assert mirror.kind == symmetry.MIRROR
    assert glide.kind == symmetry.GLIDE
    # the glide vector lies IN the plane, never along its normal
    assert float(glide.intrinsic @ glide.direction) == pytest.approx(0.0,
                                                                     abs=1e-9)
    assert float(np.linalg.norm(glide.intrinsic)) == pytest.approx(0.5)


def test_the_screw_translation_lies_along_its_axis():
    screw = symmetry.classify(_op("-x,y+1/2,-z"))
    unit = screw.intrinsic / np.linalg.norm(screw.intrinsic)
    assert abs(float(unit @ screw.direction)) == pytest.approx(1.0)


def test_rotoinversion():
    e = symmetry.classify(_op("y,-x,-z"))     # -4 along z
    assert e.kind == symmetry.ROTOINVERSION
    assert e.order == 4


def test_planes_and_axes_are_distinguishable():
    assert symmetry.classify(_op("x,y,-z")).is_plane
    assert not symmetry.classify(_op("x,y,-z")).is_axis
    assert symmetry.classify(_op("-x,-y,z")).is_axis
    assert not symmetry.classify(_op("-x,-y,z")).is_plane


def test_duplicate_elements_are_collapsed():
    """A space group lists every coset representative, so one physical axis
    shows up many times — drawing each would be a hairball."""
    ops = [_op("x,y,z"), _op("-x,-y,z"), _op("-x,-y,z"), _op("x,y,-z")]
    elements = symmetry.classify_all(ops)
    assert len(elements) == 2


def test_a_real_space_group_reduces_to_a_handful():
    """P2_1/n from Christian's benzoic acid: 4 operations, and after dropping
    the identity that is a screw, an inversion and a glide."""
    ops = [_op(t) for t in ("x, y, z", "-x+1/2, y+1/2, -z+1/2",
                            "-x, -y, -z", "x-1/2, -y-1/2, z-1/2")]
    kinds = sorted(e.kind for e in symmetry.classify_all(ops))
    assert kinds == [symmetry.GLIDE, symmetry.INVERSION, symmetry.SCREW]


def test_ghost_images_are_every_copy_but_the_original():
    ops = [_op("x,y,z"), _op("-x,-y,z"), _op("x+1/2,y+1/2,z")]
    points = np.array([[0.1, 0.2, 0.3]])
    ghosts = symmetry.images_of(points, ops)
    assert len(ghosts) == 2               # identity dropped
    for g in ghosts:
        assert np.all(g >= -1e-9) and np.all(g < 1.0 + 1e-9)


def test_ghosts_land_where_the_operation_says():
    ops = [_op("-x,-y,z")]
    ghosts = symmetry.images_of(np.array([[0.1, 0.2, 0.3]]), ops)
    assert ghosts[0][0] == pytest.approx([0.9, 0.8, 0.3])


def test_classification_survives_every_operation_of_a_big_group(tmp_path):
    """Fm-3m has 192 operations; none of them may raise or come back
    unclassified."""
    from tests.test_round18_cif import NACL_CIF
    data = cif.parse_cif(NACL_CIF)
    for op in data.symops:
        element = symmetry.classify(op)
        assert element.kind in (
            symmetry.IDENTITY, symmetry.TRANSLATION, symmetry.ROTATION,
            symmetry.SCREW, symmetry.MIRROR, symmetry.GLIDE,
            symmetry.INVERSION, symmetry.ROTOINVERSION)


# ------------------------------------------------- fractional -> Cartesian
def test_a_plane_normal_is_covariant_not_contravariant():
    """The bug this guards: normals transform with the INVERSE TRANSPOSE.
    Using the direct cell matrix is only correct for a cubic cell — in a
    monoclinic one an off-axis mirror came out ~60 degrees wrong."""
    cell = cif.Cell(5.415, 5.039, 21.630, 90.0, 96.14, 90.0)
    m = cell.matrix()
    mirror = symmetry.classify(_op("z,y,x"))
    assert mirror.is_plane
    got = symmetry.world_direction(mirror, m)
    naive = mirror.direction @ m
    naive = naive / np.linalg.norm(naive)
    assert abs(float(got @ naive)) < 0.9, "the two must genuinely differ"
    # The true normal is perpendicular to every vector lying IN the plane.
    # (1,1,0)-ish and (0,1,1)-ish fractional directions both lie in x<->z.
    for in_plane_frac in ([1.0, 0.0, 1.0], [0.0, 1.0, 0.0]):
        in_plane_cart = np.asarray(in_plane_frac) @ m
        assert float(got @ in_plane_cart) == pytest.approx(0.0, abs=1e-9)


def test_an_axis_is_contravariant():
    """An axis IS a lattice direction, so it uses the direct matrix."""
    cell = cif.Cell(5.415, 5.039, 21.630, 90.0, 96.14, 90.0)
    m = cell.matrix()
    axis = symmetry.classify(_op("-x,y,-z"))          # 2-fold along b
    got = symmetry.world_direction(axis, m)
    expect = axis.direction @ m
    expect = expect / np.linalg.norm(expect)
    assert abs(float(got @ expect)) == pytest.approx(1.0)


def test_both_agree_in_a_cubic_cell():
    """Which is why MOF-5 looked fine and hid the bug."""
    cell = cif.Cell(10.0, 10.0, 10.0)
    m = cell.matrix()
    for text in ("z,y,x", "-x,-y,z", "y,x,z"):
        e = symmetry.classify(_op(text))
        got = symmetry.world_direction(e, m)
        naive = e.direction @ m
        naive = naive / np.linalg.norm(naive)
        assert abs(float(got @ naive)) == pytest.approx(1.0, abs=1e-9)


# ------------------------------------------------------------ kind filtering
def test_filter_ops_keeps_only_the_enabled_kinds():
    ops = [_op("x,y,z"),                 # identity
           _op("-x,y,-z"),               # rotation
           _op("-x,y+1/2,-z"),           # screw
           _op("x,y,-z"),                # mirror
           _op("x+1/2,y,-z")]            # glide
    kinds = [e.kind for e in
             (symmetry.classify(o) for o in symmetry.filter_ops(
                 ops, ["screw"]))]
    assert symmetry.SCREW in kinds
    assert symmetry.ROTATION not in kinds
    assert symmetry.MIRROR not in kinds
    assert symmetry.IDENTITY in kinds, "the identity is not a switchable kind"


def test_filter_ops_with_no_filter_keeps_everything():
    ops = [_op("x,y,z"), _op("-x,y,-z"), _op("x,y,-z")]
    assert len(symmetry.filter_ops(ops, None)) == 3


def test_filter_ops_does_not_deduplicate():
    """Two distinct screw axes are ONE glyph but TWO different copies of the
    asymmetric unit, so the op list must keep both."""
    ops = [_op("-x,y+1/2,-z"), _op("-x+1/2,y+1/2,-z+1/2")]
    assert len(symmetry.filter_ops(ops, ["screw"])) == 2


def test_ghosts_follow_the_same_filter_as_the_glyphs():
    """Switching a kind off must remove its glyphs AND the copies it makes."""
    ops = [_op("x,y,z"), _op("-x,-y,z"), _op("x,y,-z")]
    points = np.array([[0.1, 0.2, 0.3]])
    everything = symmetry.images_of(points, symmetry.filter_ops(ops, None))
    rotations_only = symmetry.images_of(
        points, symmetry.filter_ops(ops, ["rotation"]))
    assert len(everything) == 2
    assert len(rotations_only) == 1


def test_switching_every_kind_off_leaves_only_the_original():
    ops = [_op("x,y,z"), _op("-x,-y,z"), _op("x,y,-z")]
    ghosts = symmetry.images_of(np.array([[0.1, 0.2, 0.3]]),
                                symmetry.filter_ops(ops, []))
    assert ghosts == []
