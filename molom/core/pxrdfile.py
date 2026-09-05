"""Reading a MEASURED powder pattern, so a simulation can be laid over it.

The point of simulating a pattern is to compare it with one somebody took, so
this is the other half of `core/pxrd.py` - and it is deliberately a separate
module, because everything here is about a FILE FORMAT and nothing about
diffraction.

**There is no standard for the TEXT formats.** Every diffractometer writes
its own thing and the common denominator is two or three columns of numbers
with some header lines above them, so the text reader here is written to that
rather than to any one vendor:

    .xy    2-theta   intensity
    .xye   2-theta   intensity   sigma          (also .xys, .dat, .txt)
    .csv   the same, comma-separated

**The BINARY formats are a different matter and are not written here.**
`core/bruker.py` is vendored from Christian's own
`ACH-Diffraction-Analysis-Suite`, where the `.raw` layout was
reverse-engineered from the bytes and checked against a PowDLL export - that
is not something to re-derive, and its theta-versus-2-theta trap is exactly
the kind of error that produces a plausible-looking wrong answer. `.brml`
comes from the same place.

The rules that make it work on real files, each of which is a thing a real
file does:

* **A header is any line that does not start with two numbers.** Comment
  markers vary (`#`, `!`, `'`, `;`, `/*`), some files have none and simply
  begin with a title, and some carry a units line. Deciding by what a line IS
  rather than by what it starts with copes with all of them.
* **Both decimal separators.** A German instrument writes `12,345`, and a
  file written on one machine is routinely read on another. Only where a
  comma sits BETWEEN DIGITS, so a comma-separated file still separates.
* **Whitespace, comma, semicolon or tab** between the columns.
* **A constant step is not assumed.** Variable-step and interpolated files
  exist, and nothing here needs evenly spaced points.

What is NOT done, and is a decision rather than an omission: no background
subtraction, no smoothing and no wavelength conversion. A measurement is
somebody's data, and a viewer that silently alters it before showing it is
the thing this project keeps refusing to be.
"""

import os
import re

import numpy as np

#: What the Open dialog offers.
NAME_FILTERS = (
    "Powder patterns (*.xy *.xye *.xys *.dat *.txt *.csv *.asc *.raw *.brml"
    " *.udf *.plv)",
    "Bruker scans (*.raw *.brml)",
    "Riet7 (*.dat)",
    "Two-column data (*.xy *.dat *.txt *.asc)",
    "Three-column data (*.xye *.xys)",
    "Comma-separated values (*.csv)",
    "All files (*)",
)

#: Extensions that are certainly NOT a powder pattern, for deciding whether
#: a DROPPED file is worth handing to `read`. Deliberately a list of what to
#: refuse rather than a list of what to accept: the text formats have no
#: standard and a pattern turns up under `.txt`, `.asc` and half a dozen
#: house extensions, so a whitelist would refuse real data. What this stops
#: is a structure or a picture being read as a table of numbers - and note
#: `.xyz` is in here while `.xy` is not, which is a distinction one character
#: wide and the reason this is written down rather than guessed at each time.
NOT_PATTERNS = frozenset((
    ".cif", ".mmcif", ".xyz", ".molom", ".mol", ".mol2", ".sdf", ".pdb",
    ".cml", ".gro", ".hin", ".gzmat", ".pdbqt", ".mdl", ".inp", ".blend",
    ".py", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg",
    ".pdf", ".zip", ".gz", ".7z", ".exe", ".dll", ".docx", ".xlsx", ".pptx",
))


def looks_like_pattern(path):
    # type: (str) -> bool
    """Could this file be a powder pattern? Extension only, and permissive.

    The reader is the only thing that can really tell, so this exists to keep
    an obvious mis-drop - a .cif, a screenshot - from being read as a table
    of numbers. Anything that gets past it and turns out not to be a pattern
    is refused by `read` with a reason, which is a better answer than a drop
    that silently does nothing.
    """
    return os.path.splitext(str(path))[1].lower() not in NOT_PATTERNS


#: Extensions read by a FORMAT-SPECIFIC reader rather than as text. These are
#: binary, so there is no text fallback to try - a failure here is a failure.
BINARY_READERS = {".raw": "read_raw", ".brml": "read_brml"}

#: Extensions that MAY be a specific format and may equally be a plain table.
#: `.dat` is the case: Riet7 writes a header and then a block of bare
#: intensities with no x column, and other programs write two ordinary
#: columns into the same extension. Tried in order, then the text path.
AMBIGUOUS_READERS = {".dat": ("read_riet7",)}

#: A line has to give at least this many rows before the file is believed to
#: be a pattern. Two points is a line segment, not a diffractogram, and the
#: check is what stops an arbitrary text file being read as one.
MIN_POINTS = 8

#: The largest a scattering angle can be. Backscattering is 180 degrees and
#: there is nothing beyond it, so a first column that leaves this range is
#: not an angle and the file is not the two-column table it was read as.
MAX_TWO_THETA = 180.0

#: Column separators that are never ambiguous.
_SPLIT_PLAIN = re.compile(r"[\s;\t]+")
#: ...and the same with the comma, for a file whose decimal mark is a point.
_SPLIT_COMMA = re.compile(r"[\s;\t,]+")

_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_POINT_BETWEEN_DIGITS = re.compile(r"\d\.\d")
_COMMA_BETWEEN_DIGITS = re.compile(r"\d,\d")


def decimal_is_comma(text):
    # type: (str) -> bool
    """Is `,` this file's DECIMAL MARK, or its column separator?

    It cannot be decided token by token - `1,5` is one German number and
    `5.0,120` is two columns, and both are `digit , digit`. It can be decided
    for the FILE: a file that uses a decimal POINT anywhere cannot also be
    using a decimal comma, so its commas separate. Counting both and taking
    the majority survives a stray point in a header line, which is the case
    that would defeat a plain "is there a point?".
    """
    points = len(_POINT_BETWEEN_DIGITS.findall(text))
    commas = len(_COMMA_BETWEEN_DIGITS.findall(text))
    return commas > points


class PatternFileError(ValueError):
    """The file is not a powder pattern."""


class Measured(object):
    """A measured diffractogram: x, y, an optional sigma, and where it came
    from."""

    __slots__ = ("x", "y", "sigma", "name", "path", "note")

    def __init__(self, x, y, sigma=None, name="", path="", note=""):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.sigma = None if sigma is None else np.asarray(sigma, dtype=float)
        self.name = str(name or "")
        self.path = str(path or "")
        #: Anything the reader wants said out loud - how many header lines it
        #: skipped, whether the step is uneven, what it could not read.
        self.note = str(note or "")

    def __len__(self):
        return int(self.x.size)

    @property
    def two_theta_range(self):
        if not self.x.size:
            return (0.0, 0.0)
        return (float(self.x.min()), float(self.x.max()))

    def step(self):
        """The MEDIAN step, which is the honest single number for a file that
        may not have a constant one."""
        if self.x.size < 2:
            return 0.0
        return float(np.median(np.diff(self.x)))

    def normalised(self, top=100.0):
        """`y` scaled so its maximum is `top`, which is what puts a
        measurement and a simulation on one axis."""
        peak = float(self.y.max()) if self.y.size else 0.0
        if peak <= 0.0:
            return np.array(self.y, copy=True)
        return self.y * (float(top) / peak)


def _numbers(line, comma_decimal=False):
    """The leading numbers on a line, or None if it does not start with two.

    This is the whole header rule: a line that begins with two numbers is
    data and anything else is not, which copes with `#`, `!`, `'`, `;`, a
    bare title, and a units line without knowing about any of them.
    """
    text = line.strip()
    if comma_decimal:
        text = _DECIMAL_COMMA.sub(".", text)
        splitter = _SPLIT_PLAIN
    else:
        splitter = _SPLIT_COMMA
    if not text:
        return None
    out = []
    for token in splitter.split(text):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(float(token))
        except ValueError:
            # A trailing word is fine (some files end a row with a flag);
            # anything before two numbers is not.
            break
    return out if len(out) >= 2 else None


def parse(text, name="", path=""):
    # type: (str, str, str) -> Measured
    """Read a measured pattern out of the text of a file."""
    text = str(text)
    comma_decimal = decimal_is_comma(text)
    rows, skipped, widths = [], 0, set()
    for line in text.splitlines():
        values = _numbers(line, comma_decimal)
        if values is None:
            if rows:
                # A non-numeric line AFTER the data has started ends it -
                # some files append a footer, and reading it as a second
                # block would splice two ranges into one curve.
                break
            skipped += 1
            continue
        rows.append(values)
        widths.add(len(values))
    if len(rows) < MIN_POINTS:
        raise PatternFileError(
            "found {} row(s) of numbers - this does not look like a powder "
            "pattern (expected at least {})".format(len(rows), MIN_POINTS))
    columns = min(widths)
    x = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)
    sigma = (np.array([r[2] for r in rows], dtype=float)
             if columns >= 3 else None)
    order = np.argsort(x, kind="stable")
    if not np.all(order == np.arange(len(x))):
        # Descending or unsorted files exist. Sorted here so everything
        # downstream - the plot, the step, an interpolation - can assume it.
        x, y = x[order], y[order]
        if sigma is not None:
            sigma = sigma[order]
    # A SCATTERING ANGLE CANNOT EXCEED 180 DEGREES. That is geometry rather
    # than a plausibility heuristic, and it is the one check that catches a
    # whole class of silent corruption: a format whose numbers are not an
    # (x, y) table at all - a Riet7 block of bare intensities, a matrix, a
    # log - parses perfectly happily into pairs and draws as a pattern of
    # something. `2 theta = 1290 deg` is not a bad measurement, it is
    # evidence that the columns are not what they were taken for.
    if float(x.max()) > MAX_TWO_THETA or float(x.min()) < -1e-6:
        raise PatternFileError(
            "the first column runs from {:.4g} to {:.4g}, which is not a "
            "2 theta axis (a scattering angle lies between 0 and {:g} deg) "
            "- this is probably not a two-column pattern".format(
                float(x.min()), float(x.max()), MAX_TWO_THETA))
    notes = []
    if skipped:
        notes.append("skipped {} header line(s)".format(skipped))
    if comma_decimal:
        notes.append("read ',' as the decimal mark")
    if len(widths) > 1:
        notes.append("rows have {} to {} columns; used the first {}".format(
            min(widths), max(widths), columns))
    steps = np.diff(x)
    if steps.size and float(steps.max() - steps.min()) > 1e-6:
        notes.append("uneven step ({:.5g} to {:.5g} deg)".format(
            float(steps.min()), float(steps.max())))
    if np.any(y < 0.0):
        notes.append("contains negative counts (background already "
                     "subtracted?)")
    return Measured(x, y, sigma, name=name or "measured", path=path,
                    note="; ".join(notes))


def read(path):
    # type: (str) -> Measured
    """Read a measured pattern from disk, by EXTENSION where there is a
    format-specific reader and as text otherwise.

    Latin-1 as the text fallback, never an error: an instrument file
    routinely carries a degree sign or a micro in its header, in whatever
    code page the machine that wrote it used, and refusing to read a file of
    NUMBERS because of a character in a comment would be absurd.
    """
    name = os.path.splitext(os.path.basename(path))[0]
    extension = os.path.splitext(path)[1].lower()
    reader = BINARY_READERS.get(extension)
    if reader is not None:
        from . import bruker
        try:
            x, y, note = getattr(bruker, reader)(path)
        except bruker.BrukerError as exc:
            raise PatternFileError(str(exc))
        if len(x) < MIN_POINTS:
            raise PatternFileError(
                "{}: only {} point(s) in the scan".format(
                    os.path.basename(path), len(x)))
        return Measured(x, y, name=name, path=path, note=note)
    for reader in AMBIGUOUS_READERS.get(extension, ()):
        from . import bruker
        try:
            x, y, note = getattr(bruker, reader)(path)
        except (bruker.BrukerError, OSError, ValueError):
            continue                     # not that format; try the next
        if len(x) >= MIN_POINTS:
            return Measured(x, y, name=name, path=path, note=note)
    try:
        text = open(path, "r", encoding="utf-8").read()
    except UnicodeDecodeError:
        text = open(path, "r", encoding="latin-1").read()
    return parse(text, name=name, path=path)
