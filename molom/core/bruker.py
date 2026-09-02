"""Bruker AXS powder files: `.raw` (RAW1.01 binary) and `.brml` (zip + XML).

**VENDORED from ACH-Diffraction-Analysis-Suite** (`src/achdiff/core/bruker.py`
and the `read_brml` in `src/achdiff/tools/quickplot.py`), MIT, Christian
Nelle / AG Henke - the same arrangement `core/io.py` has with ORCA
Workbench's `coords.py`: keep it diffable, and fixes travel both ways.

**Do not rewrite this from the specification, because there is no
specification.** The `.raw` layout was reverse-engineered from the bytes in
that project and cross-checked against a PowDLL RIET7 `.dat` export of the
same scan, where the 2-theta grid and every intensity matched exactly. The
one trap it records is worth repeating here, because it is the kind of error
that looks right: in Bragg-Brentano geometry theta = 2 theta / 2, so reading
the header's `+8` field instead of `+16` gives a pattern whose peaks are all
at HALF their true angle - and it still looks like a plausible
diffractogram.

Only the first range of a multi-range file is read, which is the norm for a
single powder scan.
"""

import os
import re
import struct
import zipfile

import numpy as np

#: Bytes before the first range header.
RAW_FILE_HEADER = 712
_RH_NSTEPS = 4            # int32   step count
#: THE TRAP, named rather than left in a comment: the range header carries
#: BOTH angles, eight bytes apart, and reading theta gives a pattern at half
#: the angles - which looks like a perfectly ordinary pattern of a different
#: compound. Nothing about the numbers themselves says which one was read.
_RH_THETA = 8             # double  theta start        <- NOT this one
_RH_START_2THETA = 16     # double  2theta start       <- this one
_RH_STEP = 176            # double  step size


class BrukerError(ValueError):
    """The file is not a Bruker scan this can read."""


def read_raw(path):
    # type: (str) -> tuple
    """A Bruker `.raw` (RAW1.01/1.02) scan as `(two_theta, intensity)`.

    Raises `BrukerError` with an actionable message for the RAW generations
    that still need PowDLL or TOPAS to convert.
    """
    name = os.path.basename(path)
    with open(path, "rb") as handle:
        raw = handle.read()
    n = len(raw)
    if raw[:7] not in (b"RAW1.01", b"RAW1.02"):
        raise BrukerError(
            "{}: unsupported Bruker RAW variant (file starts with {!r}). "
            "Only RAW1.01 is read natively; convert other RAW generations "
            "with PowDLL or TOPAS first.".format(name, raw[:4]))
    n_ranges = struct.unpack_from("<i", raw, 12)[0]
    pos = RAW_FILE_HEADER
    if pos + 184 > n:
        raise BrukerError(
            "{}: file truncated before the range header.".format(name))
    header_len = struct.unpack_from("<i", raw, pos)[0]
    n_steps = struct.unpack_from("<i", raw, pos + _RH_NSTEPS)[0]
    start = struct.unpack_from("<d", raw, pos + _RH_START_2THETA)[0]
    step = struct.unpack_from("<d", raw, pos + _RH_STEP)[0]
    if not (0 < n_steps < 10 ** 7) or not (0 < header_len < n):
        raise BrukerError(
            "{}: implausible RAW range header (steps={}, header_len={})."
            .format(name, n_steps, header_len))
    if not (0 < step < 100):
        raise BrukerError(
            "{}: implausible RAW step size ({}).".format(name, step))
    data_off = pos + header_len
    if data_off + n_steps * 4 > n:
        raise BrukerError(
            "{}: RAW data block runs past the end of the file (need {} "
            "bytes at {}, file is {}).".format(
                name, n_steps * 4, data_off, n))
    y = np.frombuffer(raw, dtype="<f4", count=n_steps,
                      offset=data_off).astype(float)
    x = start + step * np.arange(n_steps)
    # The layout is named in the note: two generations are read here and they
    # differ, so "which one was this?" is the first question of any argument
    # about a scan that came out wrong.
    note = raw[:7].decode("ascii")
    if n_ranges > 1:
        note += "; {} ranges in the file, read the first".format(n_ranges)
    return x, y, note


_DATUM = re.compile(r"<Datum>([^<]+)</Datum>")
_RAWDATA = re.compile(r"Experiment0/RawData\d+\.xml$")


def read_brml(path):
    # type: (str) -> tuple
    """A Bruker `.brml` archive as `(two_theta, intensity)`.

    Each `<Datum>` row is `timePerStep, 1, 2theta, theta, intensity`, so the
    columns wanted are 2 and 4 - and the theta/2-theta trap of `read_raw`
    applies here too, one column along.
    """
    name = os.path.basename(path)
    with zipfile.ZipFile(path, "r") as archive:
        inner = next((n for n in archive.namelist() if _RAWDATA.match(n)),
                     None)
        if inner is None:
            raise BrukerError(
                "{}: no Experiment0/RawDataN.xml inside the archive."
                .format(name))
        xml = archive.read(inner).decode("utf-8", "replace")
    rows = _DATUM.findall(xml)
    if not rows:
        raise BrukerError("{}: no <Datum> rows in {}.".format(name, inner))
    try:
        data = np.array([r.split(",") for r in rows], dtype=float)
    except ValueError as exc:
        raise BrukerError("{}: could not read the <Datum> rows ({})."
                          .format(name, exc))
    if data.shape[1] < 5:
        raise BrukerError(
            "{}: a <Datum> row has {} columns, expected at least 5."
            .format(name, data.shape[1]))
    return data[:, 2], data[:, 4], "Bruker .brml ({})".format(inner)


# --------------------------------------------------------------- Riet7 .dat
#: `<start> <step> <stop>  MeasureDateTime ...` - the only line in the file
#: that says where the pattern is, since the intensities carry no x column.
_RIET7_HEADER = re.compile(
    r"(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+[Mm]easureDateTime")


def read_riet7(path):
    # type: (str) -> tuple
    """A Riet7 `.dat` scan as `(two_theta, intensity, note)`.

    INTENSITIES ONLY - the angles come from the header's start/step/stop and
    there is no x column at all. That is what makes the format dangerous to a
    generic two-column reader, which happily pairs the intensities off against
    one another and draws a pattern of nothing.
    """
    name = os.path.basename(path)
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    match = _RIET7_HEADER.search(text)
    if match is None:
        raise BrukerError(
            "{}: no Riet7 header (start step stop  MeasureDateTime).".format(
                name))
    start, step, stop = (float(g.replace(",", ".")) for g in match.groups())
    if not (0 < step < 100) or stop <= start:
        raise BrukerError(
            "{}: implausible Riet7 header (start={}, step={}, stop={})."
            .format(name, start, step, stop))
    # Skip past the newline ENDING the header line. Without it the trailing
    # date and time ("21/05/2024 03:45") are read as the first intensities and
    # put a spurious spike at the start of the pattern - upstream's own note,
    # and worth keeping because the result looks like a real artefact.
    newline = text.find("\n", match.end())
    tail = text[newline + 1:] if newline != -1 else text[match.end():]
    counts = np.array(re.findall(r"-?\d+", tail), dtype=float)
    expected = int(round((stop - start) / step)) + 1
    if counts.size < expected:
        raise BrukerError(
            "{}: the header promises {} intensities and the file has {}."
            .format(name, expected, counts.size))
    counts = counts[:expected]
    x = start + step * np.arange(expected)
    note = "Riet7 .dat; angles from the header, {:g} to {:g} deg".format(
        start, stop)
    return x, counts, note
