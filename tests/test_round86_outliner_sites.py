"""Round 86: the crystallographic-site tier, the rows being freed again, and
the outliner's selection reaching the viewport.

Christian, 2026-08-25: "the outliner does not allow to toggle equivalent atoms
as a group. Right now the hierarchy is just mol > element > individual atoms.
But in between element and individual there should be another category for
crystal structures... Let's say I want to hide all oxygen atoms of a specific
type. I can't do that efficiently." Plus: expanding is slow, and a multi-row
selection was not reaching the 3D view.
"""
import numpy as np
import pytest

from molom.core import io as mio, occupancy
from molom.core.scene import Scene
from molom.core.structure import Structure
from molom.ui.outliner import OutlinerPanel, RowControls


# --------------------------------------------------------------- fixtures
def _ferrocene():
    recs = mio.read_structures("tests/data/cod_2101932_ferrocene.cif")
    atoms, meta = recs[0]
    symbols = [a[0] for a in atoms]
    coords = np.array([[a[1], a[2], a[3]] for a in atoms], dtype=float)
    s = Structure(symbols, [coords], [])
    s.metadata = dict(meta)
    return s


def _molecule(n=40):
    """No cell, no `site_of` - the tier must not appear at all."""
    return Structure(["C"] * n, [np.random.rand(n, 3) * 5], [])


@pytest.fixture
def panel_with():
    """Build an outliner over one structure.

    The QApplication is created here rather than taken as a fixture argument:
    a QWidget built without one does not fail, it HANGS, and a hang has no
    test name attached to it (round 75).
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    def build(structure, name="x"):
        scene = Scene()
        obj = scene.add(structure, name=name)
        panel = OutlinerPanel()
        panel.sync(scene, obj.id)
        return panel, scene, obj
    return build


def _element_group(panel, symbol):
    top = panel.tree.topLevelItem(0)
    top.setExpanded(True)
    for c in range(top.childCount()):
        item = top.child(c)
        if panel._kind(item) == "element" \
                and item.text(0).startswith(symbol + " "):
            return item
    raise AssertionError("no element group for " + symbol)


# ------------------------------------------------------- the core partition
def test_site_groups_partitions_a_crystal_by_asymmetric_unit_row():
    """Ferrocene's hundred drawn carbons are FIVE sites of twenty.

    This is the whole point of the tier: "all the oxygens of this type" is a
    question about the asymmetric unit, not about the element.
    """
    meta = _ferrocene().metadata
    carbons = [i for i, s in enumerate(_ferrocene().symbols) if s == "C"]
    groups = occupancy.site_groups(meta, carbons)
    assert len(groups) == 5
    assert [label for _s, label, _i in groups] == \
        ["C(11)", "C(12)", "C(13)", "C(14)", "C(15)"]
    assert all(len(indices) == 20 for _s, _l, indices in groups)
    # A partition: every carbon once, none invented.
    seen = sorted(i for _s, _l, idx in groups for i in idx)
    assert seen == sorted(carbons)


def test_a_site_label_is_the_files_own_label():
    """`asym_labels` carries the CIF's `_atom_site_label`, so a site is called
    what the refinement called it rather than what MoloM would guess."""
    meta = _ferrocene().metadata
    assert occupancy.site_label(meta, 1) == "C(11)"
    # No labels at all: an ordinal, NOT the element symbol - two sites of one
    # element would otherwise be given the same name, which is exactly the
    # distinction a label exists to make.
    assert occupancy.site_label({}, 3) == "site 4"


def test_one_site_is_not_a_grouping():
    """Ferrocene's ten iron atoms are all one site, so there is nothing to
    choose between and the tier must not appear."""
    s = _ferrocene()
    irons = [i for i, sym in enumerate(s.symbols) if sym == "Fe"]
    assert len(irons) == 10
    assert not occupancy.has_distinct_sites(s.metadata, irons)


def test_an_atom_with_no_site_is_grouped_separately_not_guessed():
    """An atom added by an edit is an image of nothing.

    Filing it under a site it has no relation to would be a quiet lie about
    the structure, so it gets its own group keyed `None`.
    """
    meta = {"site_of": [0, 0, 1], "asym_labels": ["O1", "O2"]}
    groups = occupancy.site_groups(meta, [0, 1, 2, 3, 4])
    assert groups[-1][0] is None
    assert groups[-1][2] == [3, 4]
    assert [g[0] for g in groups[:-1]] == [0, 1]


def test_no_site_information_means_one_group():
    """A molecule degrades to 'no site information' rather than to a guess."""
    assert occupancy.site_groups({}, [0, 1, 2]) == [(None, "", [0, 1, 2])]
    assert not occupancy.has_distinct_sites({}, [0, 1, 2])


# ------------------------------------------------------------- the tree
def test_the_tree_grows_a_site_tier_for_a_crystal(panel_with):
    panel, _scene, _obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "C")
    group.setExpanded(True)
    kinds = [panel._kind(group.child(k)) for k in range(group.childCount())]
    assert kinds == ["site"] * 5
    labels = [group.child(k).text(0).split()[0]
              for k in range(group.childCount())]
    assert labels == ["C(11)", "C(12)", "C(13)", "C(14)", "C(15)"]
    # and the atoms are one level further down
    site = group.child(0)
    site.setExpanded(True)
    assert site.childCount() == 20
    assert panel._kind(site.child(0)) == "atom"


def test_a_molecule_keeps_the_flat_element_to_atom_tree(panel_with):
    """No cell, no sites - the tier would be an extra click for nothing."""
    panel, _scene, _obj = panel_with(_molecule(40))
    group = _element_group(panel, "C")
    group.setExpanded(True)
    assert group.childCount() == 40
    assert panel._kind(group.child(0)) == "atom"


def test_a_single_site_element_stays_flat(panel_with):
    """Ferrocene's iron: ten atoms, one site, so straight to the atoms."""
    panel, _scene, _obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "Fe")
    group.setExpanded(True)
    assert group.childCount() == 10
    assert panel._kind(group.child(0)) == "atom"


def test_a_site_row_controls_its_whole_orbit(panel_with):
    """The point of the tier: hiding "this kind of atom" is ONE click.

    The row's controls act on every drawn image of that site, which is the
    same rule the element row already used one level up.
    """
    panel, _scene, obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "C")
    group.setExpanded(True)
    site = group.child(2)
    control = panel.tree.itemWidget(site, 2)
    assert isinstance(control, RowControls)
    assert len(control._rows) == 20
    control._toggle_shown()
    assert len(obj.atom_hidden) == 20
    # ...and they really are one crystallographic site, not twenty carbons
    # that happened to be adjacent in the atom list.
    sites = {int(obj.structure.metadata["site_of"][i])
             for i in obj.atom_hidden}
    assert len(sites) == 1


# ------------------------------------------------- building and freeing rows
def test_collapsing_a_group_gives_the_row_widgets_back(panel_with):
    """Christian: "are the buttons etc. built on every single expand click and
    unregistered once unexpanded?" They were built once and NEVER freed - and
    `refresh_row_controls` walks every live control on every colour, label or
    visibility change, so a group opened once went on costing on every click
    for the rest of the session, on rows nobody could see.
    """
    panel, _scene, _obj = panel_with(_molecule(200))
    group = _element_group(panel, "C")
    before = len(panel._controls)
    group.setExpanded(True)
    assert len(panel._controls) >= before + 200
    group.setExpanded(False)
    assert len(panel._controls) == before
    # ...and it can be opened again, which needs the placeholder child back:
    # a QTreeWidget draws no expander arrow on an item with no children.
    assert panel._is_placeheld(group)
    group.setExpanded(True)
    assert group.childCount() == 200


def test_a_freed_control_is_not_left_in_the_refresh_list(panel_with):
    """`refresh_row_controls` catches RuntimeError for deleted widgets; the
    list should not need that to be correct."""
    panel, _scene, _obj = panel_with(_molecule(50))
    group = _element_group(panel, "C")
    group.setExpanded(True)
    group.setExpanded(False)
    panel.refresh_row_controls()          # must not raise
    assert all(c is not None for c in panel._controls)


def test_expanding_a_site_is_far_cheaper_than_expanding_the_element(
        panel_with):
    """The tier is a performance answer as well as a crystallographic one.

    Not a wall-clock assertion - that is a machine-speed assertion, and this
    project runs on two very different machines (round 65). What is pinned is
    the portable fact: opening the element builds FIVE rows rather than a
    hundred, and the hundred are only built if you ask for them.
    """
    panel, _scene, _obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "C")
    before = len(panel._controls)
    group.setExpanded(True)
    assert len(panel._controls) - before == 5
    group.child(0).setExpanded(True)
    assert len(panel._controls) - before == 25


def test_the_expansion_state_survives_a_sync_three_levels_deep(panel_with):
    """`sync` throws every item away, so what was open has to be found again
    by a PATH - `(object, symbol)` cannot tell an element group from the sites
    inside it once the tree is three deep."""
    panel, scene, obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "C")
    group.setExpanded(True)
    group.child(1).setExpanded(True)
    panel.sync(scene, obj.id)
    group = _element_group(panel, "C")
    assert group.isExpanded()
    site = group.child(1)
    assert site.text(0).startswith("C(12)")
    assert site.isExpanded()
    assert site.childCount() == 20


# ------------------------------------------------------------- selection
def test_selecting_rows_reports_the_atoms_they_stand_for(panel_with):
    """Christian: "selecting multiple atoms in the outline does not highlight
    them in the viewport, making editing multiple atoms very tiresome."
    """
    panel, _scene, obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "C")
    group.setExpanded(True)

    seen = []
    panel.atoms_selected.connect(lambda picks: seen.append(list(picks)))

    site = group.child(0)
    site.setSelected(True)
    assert seen and len(seen[-1]) == 20
    assert all(o == obj.id for o, _i in seen[-1])

    # a second site ADDS to the selection rather than replacing it
    group.child(2).setSelected(True)
    assert len(seen[-1]) == 40

    # single atoms
    panel.tree.clearSelection()
    site.setExpanded(True)
    site.child(0).setSelected(True)
    site.child(1).setSelected(True)
    assert len(seen[-1]) == 2

    # and the element row stands for every atom of that element
    panel.tree.clearSelection()
    group.setSelected(True)
    assert len(seen[-1]) == 100


def test_selected_atoms_never_repeats_an_atom(panel_with):
    """A site row and one of its own atom rows both selected is one atom, not
    two - otherwise every count downstream is wrong."""
    panel, _scene, _obj = panel_with(_ferrocene(), "ferrocene")
    group = _element_group(panel, "C")
    group.setExpanded(True)
    site = group.child(0)
    site.setExpanded(True)
    site.setSelected(True)
    site.child(0).setSelected(True)
    picks = panel.selected_atoms()
    assert len(picks) == len(set(picks)) == 20


def test_marking_the_hidden_stripe_is_not_a_rename(panel_with):
    """`setData` on column 0 emits `itemChanged`, and `_on_item_changed` reads
    column 0 on an object row as a RENAME.

    So marking the hidden stripe emitted `renamed(id, 'cubane')`, the app
    re-synced the whole outliner in response, every QTreeWidgetItem was
    destroyed, and the next `setData` in `_mark_hidden` hit a dead one. Qt
    swallows that RuntimeError, so the visible symptom was not a crash but
    `refresh_row_controls` ABORTING partway - with two molecules open, hiding
    atoms in one left the other's stripe stale.

    Predates round 86; found by running the round-86 manual checklist.
    """
    panel, _scene, obj = panel_with(_molecule(6))
    renames = []
    panel.renamed.connect(lambda oid, name: renames.append((oid, name)))
    obj.atom_hidden.add(0)
    panel._mark_hidden(panel.tree.topLevelItem(0), obj)
    assert renames == [], "marking the stripe must not look like a rename"


def test_refresh_marks_every_molecule_not_just_the_first(panel_with):
    """The consequence of the above: the loop has to reach the end."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.core.scene import Scene
    from molom.ui.outliner import OutlinerPanel, ROLE_HIDDEN

    scene = Scene()
    a = scene.add(_molecule(5), name="a")
    b = scene.add(_molecule(5), name="b")
    panel = OutlinerPanel()
    panel.sync(scene, a.id)
    b.atom_hidden.add(0)
    panel.refresh_row_controls()
    rows = {panel._obj_id(panel.tree.topLevelItem(k)):
            panel.tree.topLevelItem(k).data(0, ROLE_HIDDEN)
            for k in range(panel.tree.topLevelItemCount())
            if panel._kind(panel.tree.topLevelItem(k)) == "object"}
    assert rows.get(b.id) is True, "the SECOND molecule's stripe was not marked"
