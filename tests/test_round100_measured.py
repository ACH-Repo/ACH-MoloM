"""Round 100: a measured pattern laid over the simulations.

Christian: "Could you add the loading in of another pattern for comparison
now?" - which is the whole point of simulating one, and the window could not
read a file at all.

Two halves. `core/pxrdfile.py` reads the TEXT formats, which have no standard
at all beyond "two or three columns of numbers under some header lines", so
the reader is written to that rather than to any one vendor. `core/bruker.py`
is VENDORED from Christian's own ACH-Diffraction-Analysis-Suite for the
binary ones - his answer to the same question ("should there not be plenty of
pxrd data file readers available in the diffract suite project?") and the
right one, since the `.raw` layout was reverse-engineered there against a
PowDLL export and is not something to re-derive from memory.
"""
import os
import struct

import numpy as np
import pytest

from molom.core import bruker
from molom.core import io as io_mod
from molom.core import pxrd
from molom.core import pxrdfile
from molom.core.structure import Structure

HERE = os.path.dirname(__file__)
SOLID_SOLUTION = os.path.join(HERE, "data", "cod_1547149_solid_solution.cif")


def _open(path, name="crystal"):
    atoms, meta = io_mod.read_structures(path)[0]
    s = Structure.from_atoms(atoms, name=name)
    s.metadata.update(meta or {})
    return s


# --------------------------------------------------------- the text reader
def test_two_and_three_columns_both_read():
    """.xy is 2-theta and intensity, .xye adds a sigma. The third column is
    the ESD and is not the pattern, so it must not be mistaken for one."""
    two = pxrdfile.parse("".join(
        "%.2f %d\n" % (10 + 0.02 * i, 100 + i) for i in range(12)))
    assert len(two) == 12
    three = pxrdfile.parse("".join(
        "%.2f %d %d\n" % (10 + 0.02 * i, 100 + i, 5 + i) for i in range(12)))
    assert len(three) == 12
    assert np.allclose(three.y[:3], [100, 101, 102])   # not the sigma column


def test_a_header_is_skipped_and_counted():
    """Every instrument writes something above the numbers. Saying how many
    lines were skipped is what tells a header apart from data that failed to
    parse - the two are indistinguishable from an atom count alone."""
    text = ("# Sample: quartz\n"
            "# Anode: Cu\n"
            "2Theta  I\n"
            + "".join("%.2f %d\n" % (10 + 0.02 * i, 100 + i)
                      for i in range(20)))
    data = pxrdfile.parse(text)
    assert len(data) == 20
    assert "3" in data.note          # three lines above the numbers


def test_commas_separate_and_commas_decimate_and_they_are_told_apart():
    """A German export writes `10,02;1234` - the SAME character as a column
    separator and as a decimal point. Deciding per file rather than per line,
    because a file is written by one machine in one locale."""
    assert pxrdfile.decimal_is_comma("10,02;1234\n10,04;1250\n")
    assert not pxrdfile.decimal_is_comma("10.02,1234\n10.04,1250\n")
    data = pxrdfile.parse("10,02;1234\n10,04;1250\n" * 6)
    assert data.x[0] == pytest.approx(10.02)
    assert data.y[0] == pytest.approx(1234)


def test_a_file_of_prose_is_refused_rather_than_read_as_one_point():
    """The dangerous failure is a reader that finds SOMETHING in anything.
    A pattern is a few hundred points at least, so a handful is a refusal."""
    with pytest.raises(pxrdfile.PatternFileError):
        pxrdfile.parse("This is a report about a sample.\nIt has no data.\n")
    with pytest.raises(pxrdfile.PatternFileError):
        pxrdfile.parse("10.0 100\n10.02 120\n")     # under MIN_POINTS
    with pytest.raises(pxrdfile.PatternFileError):
        pxrdfile.parse("")


def test_a_descending_scan_is_turned_the_right_way_round():
    """Some diffractometers scan downwards. Everything downstream - the
    envelope, the readout, the axis - assumes x increases."""
    text = "".join("%.2f %d\n" % (40 - 0.02 * i, 100 + i) for i in range(20))
    data = pxrdfile.parse(text)
    assert data.x[0] < data.x[-1]
    assert data.y[0] == 119 and data.y[-1] == 100


def test_normalised_is_a_percentage_of_the_strongest_point():
    """The same scale the simulations use, which is the only thing that lets
    the two be drawn on one axis - counts and |F|^2 share no unit."""
    data = pxrdfile.parse("".join("%.2f %d\n" % (10 + 0.02 * i, 10 * i)
                                  for i in range(1, 21)))
    assert data.normalised().max() == pytest.approx(100.0)


# ------------------------------------------------------- the Bruker reader
def _raw101(n=64, start=10.0, step=0.02):
    """A minimal RAW1.01 file, laid out the way `bruker.read_raw` reads it."""
    blob = bytearray(b"RAW1.01" + b"\x00" * (bruker.RAW_FILE_HEADER - 7))
    header = bytearray(b"\x00" * 304)
    struct.pack_into("<I", header, bruker._RH_NSTEPS, n)
    struct.pack_into("<d", header, bruker._RH_START_2THETA, start)
    struct.pack_into("<d", header, bruker._RH_STEP, step)
    struct.pack_into("<I", header, 0, 304)          # header length
    blob += header
    for i in range(n):
        blob += struct.pack("<f", 100.0 + i)
    return bytes(blob)


def test_a_raw_scan_reads_its_own_start_and_step(tmp_path):
    path = tmp_path / "scan.raw"
    path.write_bytes(_raw101(n=64, start=10.0, step=0.02))
    x, y, note = bruker.read_raw(str(path))
    assert len(x) == 64
    assert x[0] == pytest.approx(10.0)
    assert x[1] - x[0] == pytest.approx(0.02)
    assert y[0] == pytest.approx(100.0)
    assert "RAW1.01" in note


def test_the_raw_start_is_TWO_theta_and_not_theta(tmp_path):
    """The trap the vendored reader exists to carry over: the header holds
    BOTH, eight bytes apart, and reading theta gives a pattern at half the
    angles - which looks like a perfectly ordinary pattern of a different
    compound. Nothing about the numbers says which one was read.
    """
    blob = bytearray(_raw101(n=32, start=20.0, step=0.02))
    # Write a DIFFERENT value where theta lives, and insist it is ignored.
    struct.pack_into("<d", blob, bruker.RAW_FILE_HEADER + bruker._RH_THETA,
                     10.0)
    path = tmp_path / "theta.raw"
    path.write_bytes(bytes(blob))
    x, _y, _n = bruker.read_raw(str(path))
    assert x[0] == pytest.approx(20.0)
    assert bruker._RH_START_2THETA == bruker._RH_THETA + 8


def test_a_file_that_is_not_a_raw_is_refused_by_its_magic(tmp_path):
    path = tmp_path / "nope.raw"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 900)
    with pytest.raises(bruker.BrukerError):
        bruker.read_raw(str(path))


def test_read_dispatches_on_the_extension(tmp_path):
    """`.raw` is BINARY and would be read as text as a handful of garbage
    floats - or, worse, as nothing at all with no explanation."""
    assert ".raw" in pxrdfile.BINARY_READERS
    assert ".brml" in pxrdfile.BINARY_READERS
    path = tmp_path / "scan.raw"
    path.write_bytes(_raw101(n=40))
    data = pxrdfile.read(str(path))
    assert len(data) == 40
    assert data.name == "scan"
    assert data.path == str(path)


# ------------------------------------------------------------- the window
@pytest.fixture
def bench(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.open_path(SOLID_SOLUTION)
    win.viewport.set_selection([])
    win.on_pxrd()
    return win


def _measured_file(tmp_path, lo=5.0, hi=60.0, step=0.02, name="measured"):
    """A believable scan OF the solid solution: its own reflections, broadened,
    on a sloping background with counting noise."""
    s = _open(SOLID_SOLUTION)
    pxrd.set_settings(s, two_theta_max=hi)
    x, y = pxrd.profile(pxrd.pattern_for(s), fwhm=0.14, step=step)
    keep = (x >= lo) & (x <= hi)
    x, y = x[keep], y[keep]
    rng = np.random.default_rng(7)
    counts = y * 90.0 + 240.0 - 1.6 * x + rng.normal(0, 9, x.size)
    path = tmp_path / (name + ".xye")
    path.write_text("# a measurement\n" + "".join(
        "%.4f %.2f %.2f\n" % (a, b, max(1.0, b) ** 0.5)
        for a, b in zip(x, counts)), encoding="utf-8")
    return str(path)


def _traces(win, measured=None):
    ts = win._pxrd_window.plot.traces
    if measured is None:
        return ts
    return [t for t in ts if (t.pattern is None) == measured]


def test_a_measured_pattern_is_drawn_with_the_simulations(bench, tmp_path):
    win = bench
    w = win._pxrd_window
    data = w.load_measured(_measured_file(tmp_path))
    assert data is not None
    assert len(_traces(win, measured=True)) == 1
    assert len(_traces(win, measured=False)) == 1


def test_the_measurement_sits_at_the_TOP_of_the_stack(bench, tmp_path):
    """Where the data belongs in every comparison figure: the measurement,
    and the candidate phases under it."""
    win = bench
    w = win._pxrd_window
    w.offset.setValue(60.0)
    w.load_measured(_measured_file(tmp_path))
    top = _traces(win, measured=True)[0]
    under = _traces(win, measured=False)[0]
    assert top.offset > under.offset


def test_a_measurement_has_no_reflections_and_nothing_asks_it_for_any(
        bench, tmp_path):
    """The tick marks, the hover readout, the hkl export - all three walk
    `trace.pattern.reflections`, and a measurement has no structure behind
    it. This is the one thing a measured trace genuinely cannot answer."""
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    trace = _traces(win, measured=True)[0]
    assert trace.pattern is None
    w.plot.repaint()                       # the tick marks
    rect = w.plot.plot_rect()
    assert isinstance(w.plot.readout(rect.center().x()), str)
    out = tmp_path / "export.csv"
    w.export(str(out))                     # the columns
    text = out.read_text(encoding="utf-8")
    assert "MEASURED" in text
    assert "measured" in text.splitlines()[3]


def test_colour_height_and_shift_all_reach_the_curve(bench, tmp_path):
    """The two numbers are KNOBS and not corrections. A measurement and a
    simulation agree on where the peaks are and not on how tall they are,
    and a flat sample below the focusing circle moves the whole pattern."""
    from molom.ui import pxrd_panel
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    entry = w.measured[0]
    dlg = pxrd_panel.MeasuredOptions(w, entry)
    dlg.scale.setValue(0.62)
    dlg.shift.setValue(-0.085)
    dlg._colour = pxrd_panel.QColor("#ff4488")
    dlg.apply()
    w.recompute()
    trace = _traces(win, measured=True)[0]
    assert trace.colour.name() == "#ff4488"
    assert float(np.max(trace.y)) == pytest.approx(62.0, abs=1e-6)
    assert trace.x[0] == pytest.approx(entry.data.x[0] - 0.085)


def test_unticking_takes_it_off_and_removing_takes_it_away(bench, tmp_path):
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    entry, box = w._measured_boxes[0]
    box.setChecked(False)
    assert _traces(win, measured=True) == []
    box.setChecked(True)
    assert len(_traces(win, measured=True)) == 1
    w.remove_measured(entry)
    assert w.measured == [] and w._measured_boxes == []
    assert _traces(win, measured=True) == []


def test_a_measurement_draws_with_no_crystal_ticked_at_all(bench, tmp_path):
    """The comparison is not the only use. Opening a scan and looking at it
    is, and a window that needs a crystal to show a file is one you cannot
    use for the first thing you want to do with a file."""
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    for _obj, box, _c in w.rows:
        box.setChecked(False)
    assert len(_traces(win, measured=True)) == 1
    lo, hi = w.plot.view_x()
    assert lo < 10.0 and hi > 50.0


def test_a_measurement_is_refused_on_a_Q_axis_and_says_why(bench, tmp_path):
    """A file is in 2 theta and carries no wavelength, so converting it would
    mean inventing one. Q is what makes two simulations at different
    wavelengths comparable (round 94); it cannot be applied to a measurement
    whose source is unknown."""
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    w.q_axis.setChecked(True)
    assert _traces(win, measured=True) == []
    assert "Q" in w.note.text() or "wavelength" in w.note.text()
    w.q_axis.setChecked(False)
    assert len(_traces(win, measured=True)) == 1


def test_a_truncated_comparison_says_so(bench, tmp_path):
    """The simulation stops at the default 50 deg and the measurement runs
    to 60 - so the curve simply goes flat, which reads as the phase having no
    reflections up there rather than as nothing having been calculated."""
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path, hi=60.0))
    assert "50" in w.note.text() and "range" in w.note.text()
    for obj, _box, _c in w.rows:
        pxrd.set_settings(obj.structure, two_theta_max=75.0)
    w.recompute()
    assert "raise the 2 theta range" not in w.note.text()


def test_reload_keeps_the_colour_scale_and_shift(bench, tmp_path):
    """A measurement is somebody else's file and it CHANGES - re-integrated,
    background-subtracted, repeated. Losing the alignment you just spent ten
    minutes on is the reason to reload rather than re-open."""
    win = bench
    w = win._pxrd_window
    path = _measured_file(tmp_path)
    w.load_measured(path)
    entry = w.measured[0]
    entry.colour, entry.scale, entry.shift = "#ff4488", 0.62, -0.085
    before = len(entry.data)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join("%.4f %.2f\n" % (60.02 + 0.02 * i, 300.0)
                         for i in range(50)))
    w.reload_measured(entry)
    assert len(entry.data) == before + 50
    assert (entry.colour, entry.scale, entry.shift) == ("#ff4488", 0.62,
                                                        -0.085)


def test_both_right_click_menus_offer_the_measured_entry(bench, tmp_path):
    """Christian's rule from round 96, applied to the new kind of trace: the
    per-line options are reachable from the LINE and from its tick box."""
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    entry = w.measured[0]
    trace = _traces(win, measured=True)[0]
    from_line = [a.text() for a in w.build_trace_menu(trace).actions()]
    assert any("Settings for" in t for t in from_line)
    assert any("Remove" in t for t in from_line)
    from_label = [a.text() for a in w.build_measured_menu(entry).actions()]
    assert any("Settings for" in t for t in from_label)
    assert any("Reload" in t for t in from_label)


def test_an_unreadable_file_is_reported_and_changes_nothing(bench, tmp_path):
    """A refusal has to say so ON SCREEN. A window that silently draws
    nothing is indistinguishable from one that is broken."""
    win = bench
    w = win._pxrd_window
    bad = tmp_path / "notes.txt"
    bad.write_text("Measured on Tuesday. Sample looked fine.\n",
                   encoding="utf-8")
    assert w.load_measured(str(bad)) is None
    assert w.measured == []
    assert "Could not read" in w.note.text()


def _brml(tmp_path, n=40, start=10.0, step=0.02):
    """A minimal .brml: a zip with one RawData xml of `<Datum>` rows.

    A row is `timePerStep, 1, 2theta, theta, intensity`, so THETA sits in the
    column next to the one wanted - the same trap as the .raw header, one
    column along instead of eight bytes along.
    """
    import zipfile
    path = tmp_path / "scan.brml"
    rows = "".join(
        "<Datum>0.5,1,{:.4f},{:.4f},{:.1f}</Datum>".format(
            start + step * i, (start + step * i) / 2.0, 100.0 + i)
        for i in range(n))
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("Experiment0/RawData0.xml", "<Root>" + rows + "</Root>")
    return str(path)


def test_a_brml_reads_two_theta_and_not_theta(tmp_path):
    path = _brml(tmp_path, n=40, start=10.0, step=0.02)
    x, y, _note = bruker.read_brml(path)
    assert len(x) == 40
    assert x[0] == pytest.approx(10.0)          # not 5.0, which is theta
    assert x[-1] == pytest.approx(10.0 + 0.02 * 39)
    assert y[0] == pytest.approx(100.0)


def test_a_zip_that_is_not_a_brml_is_refused(tmp_path):
    import zipfile
    path = tmp_path / "empty.brml"
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("readme.txt", "nothing to see")
    with pytest.raises(bruker.BrukerError):
        bruker.read_brml(str(path))


def test_a_brml_goes_through_the_same_window_path(tmp_path):
    data = pxrdfile.read(_brml(tmp_path, n=40))
    assert len(data) == 40
    assert data.name == "scan"


# --------------------------------------------- the formats that are traps
def _riet7(start=5.0, step=0.02, stop=10.0):
    """Riet7 `.dat`: a header carrying start/step/stop, then a block of BARE
    intensities with no x column at all."""
    n = int(round((stop - start) / step)) + 1
    body = "\n".join(" ".join(str(1000 + (i * 7) % 300)
                              for i in range(r * 10, min(r * 10 + 10, n)))
                     for r in range((n + 9) // 10))
    return ("{:.3f} {:.3f} {:.3f}  MeasureDateTime 21/05/2024 03:45\n"
            .format(start, step, stop) + body + "\n")


def test_an_angle_over_180_degrees_is_refused():
    """Backscattering is 180 deg and there is nothing beyond it, so this is
    GEOMETRY rather than a plausibility heuristic - and it is what catches a
    file whose numbers are not an (x, y) table at all. A Riet7 block of bare
    intensities pairs off perfectly happily and draws a pattern of nothing:
    measured, 276 points running to 1290 deg, with no error anywhere.
    """
    assert pxrdfile.MAX_TWO_THETA == 180.0
    with pytest.raises(pxrdfile.PatternFileError) as exc:
        pxrdfile.parse(_riet7())
    assert "2 theta" in str(exc.value)


def test_a_riet7_dat_is_read_by_its_header_not_as_columns(tmp_path):
    path = tmp_path / "scan.dat"
    path.write_text(_riet7(start=5.0, step=0.02, stop=10.0), encoding="utf-8")
    data = pxrdfile.read(str(path))
    assert len(data) == 251
    assert data.x[0] == pytest.approx(5.0)
    assert data.x[-1] == pytest.approx(10.0)
    assert "Riet7" in data.note


def test_the_riet7_date_is_not_read_as_the_first_intensities(tmp_path):
    """The header line ends with `21/05/2024 03:45`, and reading from the end
    of the MATCH rather than past the newline picks those digits up as counts
    - a spurious spike at the start of the pattern that looks like a real
    artefact. Upstream's own note, and worth keeping."""
    path = tmp_path / "scan.dat"
    path.write_text(_riet7(), encoding="utf-8")
    data = pxrdfile.read(str(path))
    assert data.y[0] == pytest.approx(1000.0)      # not 21, not 5, not 2024


def test_an_ordinary_two_column_dat_still_reads_as_columns(tmp_path):
    """`.dat` is ambiguous - Riet7 writes one thing into it and half a dozen
    other programs write a plain table. Tried in order, then the text path."""
    path = tmp_path / "plain.dat"
    path.write_text("".join("%.2f %d\n" % (10 + 0.02 * i, 100 + i)
                            for i in range(40)), encoding="utf-8")
    data = pxrdfile.read(str(path))
    assert len(data) == 40
    assert data.x[0] == pytest.approx(10.0)
    assert "Riet7" not in data.note


# ------------------------------------------- against the suite it came from
SUITE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "ACH-Diffraction-Analysis-Suite")
SUITE_EX = os.path.join(SUITE, "examples")

#: What the upstream readers give for these files, captured by RUNNING them
#: (`achdiff.tools.quickplot`) rather than written down from the format specs:
#: n, first x, last x, first y, sum of y.
UPSTREAM = {
    "sample-A-P4-cryst.brml": (5589, 3.0001, 59.9955, 1317.0, 11567392.0),
    "sample-B-F-0.20-dry.dat": (2251, 5.0, 50.0, 16.0, 52459.0),
    "sample-C_300_001_00000.xy": (3399, 0.017587149, 45.616391, 2395.5,
                                  3712809.5741629),
}


@pytest.mark.parametrize("name", sorted(UPSTREAM))
def test_the_vendored_readers_agree_with_the_suite_they_came_from(name):
    """The point of vendoring rather than re-deriving: MoloM must read
    Christian's own files exactly as his own program does, on all three
    shapes - a zipped XML archive, a header-driven intensity block, and a
    plain table. Anything else means the two programs disagree about a
    measurement, which is the worst kind of drift.

    Skips where the sibling repo is not checked out.
    """
    path = os.path.join(SUITE_EX, name)
    if not os.path.exists(path):
        pytest.skip("ACH-Diffraction-Analysis-Suite is not checked out here")
    n, x0, x1, y0, ysum = UPSTREAM[name]
    data = pxrdfile.read(path)
    assert len(data) == n
    assert float(data.x[0]) == pytest.approx(x0, abs=1e-6)
    assert float(data.x[-1]) == pytest.approx(x1, abs=1e-6)
    assert float(data.y[0]) == pytest.approx(y0, abs=1e-6)
    assert float(data.y.sum()) == pytest.approx(ysum, rel=1e-12)


def test_every_example_pattern_in_the_suite_reads():
    """A sweep rather than a fixture: whatever shapes his examples cover,
    none of them may raise. This is what caught Riet7 in the first place."""
    if not os.path.isdir(SUITE_EX):
        pytest.skip("ACH-Diffraction-Analysis-Suite is not checked out here")
    import glob
    read = 0
    for path in sorted(glob.glob(os.path.join(SUITE_EX, "*"))):
        if os.path.splitext(path)[1].lower() not in (
                ".xy", ".xye", ".dat", ".txt", ".csv", ".raw", ".brml"):
            continue
        data = pxrdfile.read(path)          # must not raise
        assert len(data) >= pxrdfile.MIN_POINTS
        assert 0.0 <= float(data.x.min())
        assert float(data.x.max()) <= pxrdfile.MAX_TWO_THETA
        read += 1
    assert read >= 5


# ------------------------------------ a refusal has to be VISIBLE (round 101)
def test_a_suppressed_measurement_says_so_in_the_note_and_on_its_box(
        bench, tmp_path):
    """Christian: "the checkboxes for them show up, but none are actually
    displayed." Reproduced on the Q axis, where dropping the trace is
    CORRECT - a measurement carries no wavelength - and the explanation was
    appended last, so `notes[:2]` truncated it away behind a B = 0 caveat
    that is true of every pattern. A refusal nobody can see is
    indistinguishable from a bug.
    """
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path, name="one"))
    w.load_measured(_measured_file(tmp_path, name="two"))
    assert len(_traces(win, measured=True)) == 2
    w.q_axis.setChecked(True)
    assert _traces(win, measured=True) == []
    # The note leads with it, ahead of any standing caveat.
    assert "NOT DRAWN" in w.note.text()
    assert w.note.text().index("NOT DRAWN") < 40
    # ...and so does the tick box the user is looking at.
    for _entry, box in w._measured_boxes:
        assert "#7a7a7a" in box.styleSheet()
        assert "NOT DRAWN" in box.toolTip()
    w.q_axis.setChecked(False)
    assert len(_traces(win, measured=True)) == 2
    for entry, box in w._measured_boxes:
        assert entry.colour in box.styleSheet()
        assert "NOT DRAWN" not in box.toolTip()


def test_an_alert_outranks_a_standing_caveat_in_the_note(bench, tmp_path):
    """Two sentences of room, and "no displacement parameters in the file" is
    true of every pattern here - it must never crowd out the one sentence
    saying where somebody's file went."""
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path, hi=60.0))
    shown = w.note.text()
    assert "raise the 2 theta range" in shown
    # The caveat is real and is in the tooltip; what it must not do is take
    # one of the two slots the line has.
    assert "B = 0" not in shown
    assert "B = 0" in w.note.toolTip()


# -------------------------------------------------- SVG export (round 101)
def test_the_plot_saves_as_real_vector_svg(bench, tmp_path):
    """A diffractogram is a polyline against an axis - vector content all the
    way down - so a raster grab is a figure nobody can rescale. The trap is
    the BLITTING CACHE (round 96): rendering the widget would embed that
    pixmap and produce an SVG with a bitmap in it, which is worthless."""
    pytest.importorskip("PySide6.QtSvg")
    win = bench
    w = win._pxrd_window
    w.resize(900, 560)
    w.load_measured(_measured_file(tmp_path))
    out = tmp_path / "plot.svg"
    assert w.save_svg(str(out)) == str(out)
    body = out.read_text(encoding="utf-8")
    assert body.lstrip().startswith("<?xml")
    assert "<svg" in body
    assert "<image" not in body and "base64" not in body   # no raster
    assert body.count("<polyline") + body.count("<path") >= 2


def test_the_svg_samples_finer_than_the_window(bench):
    """The min/max envelope is a per-PIXEL reduction and an SVG has no
    pixels, so at screen resolution the curve reads as polygonal the moment
    the figure is enlarged.

    `scale` is a FLOOR under the peak-derived count rather than the count
    itself: on a very wide window, or with no simulated trace to take a FWHM
    from, it is what stops the export dropping to screen resolution.
    """
    pytest.importorskip("PySide6.QtSvg")
    from molom.ui import pxrd_panel
    win = bench
    w = win._pxrd_window
    w.resize(900, 560)
    assert pxrd_panel.SVG_SCALE > 1.0
    on_screen = w.plot.columns(w.plot.plot_rect())
    assert w.export_columns() > on_screen
    # a huge floor wins where it is larger than what the peak asks for
    assert w.export_columns(scale=200.0) > w.export_columns(scale=4.0)


def test_the_svg_is_written_for_a_WHITE_PAGE_and_restores_the_screen(
        bench, tmp_path):
    """The plot's palette is a dark-theme choice: a measured trace at
    #e8e8e8 is invisible on white and the grid, a whisper on black, becomes
    heavy black rulings. And the swap must not leak - the window is still
    open behind the file dialog."""
    pytest.importorskip("PySide6.QtSvg")
    from PySide6.QtGui import QColor
    from molom.ui import pxrd_panel
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    bg_before = pxrd_panel._BG.name()
    colours_before = [QColor(t.colour).name() for t in w.plot.traces]
    w.save_svg(str(tmp_path / "light.svg"))
    assert pxrd_panel._BG.name() == bg_before
    assert [QColor(t.colour).name() for t in w.plot.traces] == colours_before


def test_every_trace_reaches_a_printable_contrast_keeping_its_hue(
        bench, tmp_path):
    """The rule the MEASUREMENT changed. The first cut darkened only colours
    above a threshold - but the trace palette runs 0.567 to 0.796 and the
    measured palette 0.776 to 0.910, so they OVERLAP and no threshold
    separates them; and every screen colour sits between 1.24:1 and 1.70:1
    against white, where line art wants 3:1. So they all come down, and the
    hue is what survives to say which trace is which.
    """
    from PySide6.QtGui import QColor
    from molom.ui import pxrd_panel
    win = bench
    w = win._pxrd_window
    w.load_measured(_measured_file(tmp_path))
    assert len(w.plot.traces) >= 2
    for trace, paper in zip(w.plot.traces, w.plot.darken_for_paper()):
        luma = pxrd_panel.PxrdPlot._luma(paper)
        assert luma == pytest.approx(pxrd_panel.PAPER_LUMA, abs=1e-3)
        # 2.23:1 is the MEAN of matplotlib's tab10, which is the empirical
        # convention for a scientific figure. The first cut used the WCAG
        # 3:1 and came out darker than every member of tab10, Okabe-Ito and
        # ColorBrewer Set1 - Christian spotted it immediately.
        assert 1.05 / (luma + 0.05) == pytest.approx(2.23, abs=0.05)
        screen = QColor(trace.colour)
        if screen.saturationF() > 0.05:
            assert paper.hueF() == pytest.approx(screen.hueF(), abs=0.02)


def test_a_colour_already_dark_enough_is_left_exactly_alone(bench):
    """What protects a colour somebody picked by hand: the rule is a
    ceiling, not a normalisation."""
    from PySide6.QtGui import QColor
    win = bench
    w = win._pxrd_window
    assert w.plot.traces
    w.plot.traces[0].colour = QColor("#102040")     # already dark
    assert w.plot.darken_for_paper()[0].name() == "#102040"


def test_save_image_still_writes_a_png(bench, tmp_path):
    out = tmp_path / "plot.png"
    assert w_save(bench, out) == str(out)
    assert out.stat().st_size > 1000


def w_save(win, out):
    return win._pxrd_window.save_image(str(out))


# --------------------------- point density: screen and export (round 101b)
def test_the_stored_step_follows_the_PEAK_not_a_fixed_number_of_degrees():
    """A fixed 0.01 deg is 10 points across a 0.1 deg peak and 2 across a
    0.02 deg one, so it is simultaneously too coarse for a sharp pattern and
    wasteful for a broad one. The invariant that means something is points
    per FWHM."""
    for fwhm in (0.02, 0.10, 0.50):
        assert (fwhm / pxrd.step_for(fwhm)
                == pytest.approx(pxrd.STORED_PER_FWHM))
    assert pxrd.STORED_PER_FWHM == 20.0
    # an explicit step still wins, so a savefile that carries one is honoured
    assert pxrd.step_for(0.10, 0.02) == pytest.approx(0.02)


def test_stored_density_does_not_change_what_is_DRAWN(bench):
    """Why doubling it is free: the min/max envelope reduces to about one
    point per column whatever is stored, so the paint cost is bounded by the
    window and not by the profile. Measured as the drawn point count, which
    is deterministic - wall-clock on this machine drifts by 50%."""
    win = bench
    w = win._pxrd_window
    w.resize(1000, 620)
    plot = w.plot
    counts = []
    for step in (0.01, 0.005, 0.0025):
        for obj, _box, _c in w.rows:
            pxrd.set_settings(obj.structure, step=step)
        w._profiles.clear()
        w.recompute()
        stored = sum(len(t.x) for t in plot.traces)
        drawn = 0
        for trace in plot.traces:
            poly = plot._envelope(trace, plot.plot_rect(), *plot.view_x())
            drawn += len(poly) if poly is not None else 0
        counts.append((stored, drawn))
    # stored quadruples...
    assert counts[-1][0] > 3.5 * counts[0][0]
    # ...and drawn barely moves
    assert counts[-1][1] < 1.1 * counts[0][1]


def test_a_vector_export_takes_its_resolution_from_the_PEAK(bench, tmp_path):
    """"Blocky when zoomed out" - and the ceiling was never the stored grid,
    it was the per-column reduction: a 939 px plot over 45 degrees gives
    about 2 columns across a 0.1 degree peak, and 8 even at 4x."""
    win = bench
    w = win._pxrd_window
    w.resize(1000, 620)
    plot = w.plot
    lo, hi = plot.view_x()
    fwhm = min(t.fwhm for t in plot.traces if t.fwhm > 0.0)
    columns = w.export_columns()
    per_fwhm = fwhm / ((hi - lo) / columns)
    assert per_fwhm == pytest.approx(pxrd_panel_svg_per_fwhm(), rel=1e-6)
    # never coarser than the old width-based figure, never past the cap
    from molom.ui import pxrd_panel
    assert columns >= int(plot.plot_rect().width() * pxrd_panel.SVG_SCALE)
    assert columns <= pxrd_panel.SVG_MAX_COLUMNS


def pxrd_panel_svg_per_fwhm():
    from molom.ui import pxrd_panel
    return pxrd_panel.SVG_PER_FWHM


def test_a_sharper_peak_asks_for_more_columns_and_is_capped(bench):
    """The count follows the narrowest trace, because that is the one that
    goes polygonal first - and it is capped so a very sharp peak over a very
    wide range cannot ask for a ten-megabyte figure."""
    from molom.ui import pxrd_panel
    win = bench
    w = win._pxrd_window
    wide = w.export_columns()
    for obj, _box, _c in w.rows:
        pxrd.set_settings(obj.structure, fwhm=0.01)
    w._profiles.clear()
    w.recompute()
    assert w.export_columns() > wide
    for obj, _box, _c in w.rows:
        pxrd.set_settings(obj.structure, fwhm=1e-4)
    w._profiles.clear()
    w.recompute()
    assert w.export_columns() == pxrd_panel.SVG_MAX_COLUMNS


def test_the_svg_really_carries_the_extra_vertices(bench, tmp_path):
    pytest.importorskip("PySide6.QtSvg")
    import re
    win = bench
    w = win._pxrd_window
    w.resize(1000, 620)
    coarse = tmp_path / "coarse.svg"
    fine = tmp_path / "fine.svg"
    # the old behaviour: columns from the widget alone
    w.save_svg(str(fine))
    original = w.export_columns
    try:
        w.export_columns = lambda scale=4.0: int(
            w.plot.plot_rect().width() * scale)
        w.save_svg(str(coarse))
    finally:
        w.export_columns = original

    def vertices(path):
        body = path.read_text(encoding="utf-8")
        assert "<image" not in body
        return sum(len(m.split())
                   for m in re.findall(r'points="([^"]*)"', body))

    assert vertices(fine) > 1.5 * vertices(coarse)


# ------------------------------- the two tails are not the same (round 101c)
def test_the_two_peak_shapes_are_windowed_at_different_distances():
    """A Gaussian and a Lorentzian die at completely different rates, and
    both used one window. The Gaussian is exp(-399) at 12 FWHM - exactly
    zero in double precision - while the Lorentzian is still 1.7e-3 there,
    because a 1/d^2 tail never really stops."""
    import math
    sigma = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))   # FWHM = 1
    assert math.exp(-0.5 * (pxrd.REACH_GAUSSIAN / sigma) ** 2) < 1e-10
    assert 1.0 / (1.0 + (pxrd.REACH_LORENTZIAN / 0.5) ** 2) > 1e-3
    assert pxrd.REACH_GAUSSIAN < pxrd.REACH_LORENTZIAN


def test_narrowing_the_gaussian_window_changes_nothing_that_can_be_seen():
    """The whole justification: it has to be exact to the precision anybody
    could ever plot. Measured at 1.3e-9 % of the peak."""
    s = _open(SOLID_SOLUTION)
    pxrd.set_settings(s, two_theta_max=50.0)
    pattern = pxrd.pattern_for(s)
    peaks = pxrd.peak_positions(pattern, pxrd.AXIS_TWO_THETA)
    x = np.arange(5.0, 50.0, pxrd.step_for(0.10))
    narrow = pxrd.profile_at(pattern, x, fwhm=0.10, shape="gaussian",
                             peaks=peaks)
    # the same sum with NO windowing at all, which is what it approximates
    sigma = 0.10 / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    full = np.zeros_like(x)
    for centre, height in peaks:
        full += height * np.exp(-0.5 * ((x - centre) / sigma) ** 2)
    assert np.max(np.abs(narrow - full)) / float(full.max()) < 1e-9


def test_the_pseudo_voigt_keeps_ONE_window(monkeypatch):
    """Recorded because the arithmetic argues the other way and the
    measurement does not: splitting its two halves was built and came out
    SLOWER (1.44 -> 1.53 ms), the extra slice and accumulate costing more
    than the exponentials they remove. So the default shape must still see
    every sample the Lorentzian reach covers."""
    s = _open(SOLID_SOLUTION)
    pxrd.set_settings(s, two_theta_max=50.0)
    pattern = pxrd.pattern_for(s)
    peaks = [(20.0, 100.0)]
    fwhm = 0.10
    # a sample 6 FWHM out is past the Gaussian window and inside the
    # Lorentzian one, so a pseudo-Voigt must still put something there
    x = np.array([20.0 + 6.0 * fwhm])
    y = pxrd.profile_at(pattern, x, fwhm=fwhm, shape="pseudo_voigt",
                        eta=0.5, peaks=peaks)
    assert y[0] > 0.0
    lorentz_only = 100.0 * 0.5 / (1.0 + (6.0 * fwhm / (fwhm / 2.0)) ** 2)
    assert y[0] == pytest.approx(lorentz_only, rel=1e-6)
