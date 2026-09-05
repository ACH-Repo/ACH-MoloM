"""Background subtraction for a MEASURED powder pattern.

A measurement has a background and a simulation does not, so the two curves
differ by a smooth function of 2-theta before either has said anything about
the phase. Christian put his finger on why it matters when the two are
stacked: "the experimental would have a massive foot like you often see in
synchrotron data" - and since every trace in the window is normalised to its
own strongest point, a large foot eats the dynamic range and the peaks come
out short against the simulation they are being compared with.

**TWO MODELS, and the newer one is the default.** `rolling_background` walks
the pattern from high angle to low and lets the background follow it only as
fast as a background can plausibly change - Christian's design, and the whole
of the second half of this module. `chebyshev_background` is the Rietveld
model and is kept, because a genuine amorphous hump is a thing a polynomial
can carry and the rolling walk deliberately cannot.

**CHEBYSHEV, because that is what a Rietveld program uses.** TOPAS, GSAS-II
and FullProf all model the background as a Chebyshev polynomial of the first
kind, and Christian asked for the same thing rather than something invented
here. The order is the user's - six is TOPAS's own common default and is what
this module defaults to.

**THE FIT HAS TO BE A LOWER ENVELOPE, NOT A LEAST-SQUARES CURVE**, and that
is the whole of the difficulty. A plain polynomial fit to (x, y) passes
through the MEAN of the data, so it is dragged upwards by every peak and then
subtracts intensity that belongs to the phase - worst exactly where the
pattern is most crystalline. `chebyshev_background` therefore fits
iteratively and CLIPS: each pass refits the ORIGINAL data with every point
above the current estimate pulled down to it, so the peaks stop pulling on
the next pass and the curve settles onto the baseline between them. Clipping
the already-clipped copy instead compounds, and the estimate creeps downwards
pass by pass - see the note in the loop. That is the
standard trick (Rietveld programs get the same effect by refining the
background simultaneously with the profile, which a standalone subtraction
cannot do).

**AND CHEBYSHEV CANNOT REACH THE SMALL-ANGLE END**, which is what
`remove_low_angle` is for. At very short wavelengths the direct beam leaves a
steep decay near 2 theta 0 that a low-order polynomial simply cannot
represent alongside an otherwise flat pattern - so the tail comes off FIRST,
as a power law, and the Chebyshev then works on something it is good at. That
ordering is Christian's.

**WHICH IS ALSO WHY THE ROLLING WALK EXISTS.** Every one of those pieces is a
prop under a model that does not fit the data: a polynomial that has to be
clipped so it stops fitting the peaks, a separate power law bolted on
because the polynomial cannot reach one end, and a beam-stop finder to tell
the power law where to start. The walk needs none of them - it removes a
small-angle foot as part of doing its ordinary job - and the price, which is
Christian's own and is stated in `rolling_background`, is that it gives up on
amorphous scattering entirely.

Nothing here knows about Qt, and none of it is specific to the file the
pattern came from.
"""

from typing import Optional, Tuple      # noqa: F401  (type comments)

import numpy as np

#: TOPAS's own common default, and Christian's suggestion.
DEFAULT_ORDER = 6

#: How many clip-and-refit passes. Measured on a synthetic pattern with a
#: strong foot: the estimate stops moving by about the fifth, and 12 leaves
#: room for a badly sloping background without being worth timing.
DEFAULT_PASSES = 12

#: A pass that moves the estimate by less than this fraction of the data's
#: range has converged, and the rest of the passes are skipped.
CONVERGED = 1e-4


def chebyshev_background(x, y, order=DEFAULT_ORDER, passes=DEFAULT_PASSES):
    # type: (object, object, int, int) -> np.ndarray
    """The smooth background under a measured pattern, same shape as `y`.

    Fitted as a Chebyshev polynomial on x mapped to [-1, 1] - which is what
    makes the coefficients well conditioned, and is why Rietveld programs use
    Chebyshev rather than a raw power series at these orders.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    if x.size != y.size:
        raise ValueError("x and y must be the same length")
    order = max(0, int(order))
    if y.size <= order + 1:
        # Fewer points than coefficients: a fit would be meaningless, and a
        # flat baseline at the minimum is the honest answer.
        return np.full_like(y, float(y.min()) if y.size else 0.0)
    lo, hi = float(x.min()), float(x.max())
    span = hi - lo
    t = np.zeros_like(x) if span <= 0 else (2.0 * (x - lo) / span - 1.0)
    scale = float(np.ptp(y)) or 1.0
    working = y.copy()
    estimate = np.full_like(y, float(y.mean()))
    for _ in range(max(1, int(passes))):
        coeffs = np.polynomial.chebyshev.chebfit(t, working, order)
        fitted = np.polynomial.chebyshev.chebval(t, coeffs)
        moved = float(np.max(np.abs(fitted - estimate))) / scale
        estimate = fitted
        # CLIP THE ORIGINAL DATA against the current estimate, never the
        # already-clipped copy. A peak is intensity ADDED to the background,
        # so a point above the estimate is signal and is pulled down to it;
        # a point below is baseline or noise and is left alone (clipping
        # symmetrically would fit the middle of the noise and take the
        # estimate down with it).
        #
        # Clipping `working` instead of `y` compounds: every pass lowers the
        # points it already lowered, so the estimate creeps DOWNWARDS and the
        # subtraction leaves a rising positive residual. Measured on a
        # 500 + 5x baseline under one sharp peak - the residual drifted from
        # 4.9 to 23 across the pattern before this line read `y`.
        working = np.minimum(y, fitted)
        if moved < CONVERGED:
            break
    return estimate


def subtract_background(x, y, order=DEFAULT_ORDER, passes=DEFAULT_PASSES,
                        clip_negative=True):
    # type: (object, object, int, int, bool) -> Tuple[np.ndarray, np.ndarray]
    """`(corrected, background)`.

    `clip_negative` floors the result at zero. The background is an estimate,
    so the noise around it goes negative half the time - which is honest but
    reads as the baseline having structure, and on a log axis it cannot be
    drawn at all. The default matches what a Rietveld program shows.
    """
    background = chebyshev_background(x, y, order=order, passes=passes)
    corrected = np.asarray(y, dtype=float).reshape(-1) - background
    if clip_negative:
        corrected = np.maximum(corrected, 0.0)
    return corrected, background



# ------------------------------------------------- the derivative-gated walk
#: How steeply the background may climb toward LOW angle, as a fraction of
#: its own height per degree. Anything faster is decided to be a peak.
#:
#: **Chosen by measuring what constrains it from each side, on Christian's
#: own files, and neither side is where it was first guessed.**
#:
#: From ABOVE, the weak-peak floor: a peak has to stand roughly
#: `6 * slope * FWHM` above its background to survive, because that is how
#: far the envelope is allowed to climb across it. For a 0.06 degree peak
#: that is 8.9% at slope 0.5, 16.1% at 1.0 and 31.6% at 2.0 - so the cost of
#: a high limit is the weak reflections, and it is linear.
#:
#: From BELOW, following a real background: the limit only has to beat the
#: background's own relative decay, and a background is gentle. Measured
#: against a synthetic decay of 2.0 per degree - far steeper than anything
#: real away from the beam stop, which the `tail` term handles separately -
#: the reconstruction is within 0.4% of the truth at slope 1.0 and still
#: 0.6% at 0.5.
#:
#: And what does NOT constrain it, which is the surprise: amorphous
#: rejection. A halo is WIDE, so the envelope catches up with it whatever
#: the limit - two amorphous scans and an empty-capillary background all
#: come off to a residual of 0.3-0.7% of their range at every slope from 0.5
#: to 3.0. So the default is set by the weak peaks, and 1.0 is an order of
#: magnitude above every peak-free background slope measured (0.02-0.06 per
#: degree) while asking half of what 2.0 asks of a weak reflection.
DEFAULT_SLOPE = 1.0

#: Points in the moving average the derivative is taken on. Its whole job is
#: to stop point-to-point NOISE being read as a slope: without it the
#: envelope sits on the bottom of the noise band, which is a systematic
#: UNDERESTIMATE of the background. Measured on a noisy lab pattern (sigma
#: 26.6 counts) - the baseline sits 9.15 counts low at width 1, 2.5 at 5 and
#: 1.6 at 9, while the tallest peak loses 1.4%, 1.8% and 4.7% of its height.
#: Five is the least aggressive width that fixes most of the bias, and a
#: narrow synchrotron peak is the case that cannot afford more.
DEFAULT_SMOOTH = 5

#: How steeply the background may fall as a POWER LAW at the small-angle end,
#: as an exponent: the limit above is widened by `tail / x` per degree.
#:
#: Christian named the case this exists for - "starts low, spikes strongly,
#: then decays by power law until zero". A power law's RELATIVE slope is
#: `b / x`, which diverges as 2 theta goes to zero, so a constant relative
#: limit is certain to be exceeded there however it is set, and the whole
#: foot is then read as one enormous peak. Measured on the round-104 fixture:
#: with no allowance the beam-stop foot swamps everything and a real peak is
#: 1.9% of the scale; at 1.5 it is 29.6%. It costs the ordinary patterns
#: 3-5% of peak height, because at 30 degrees the extra allowance is
#: 1.5/30 = 0.05 per degree and simply does not bite.
#:
#: 1.5 rather than the 0.78 measured on Christian's own file, so that a
#: steeper foot is still covered; 0 switches the allowance off, for the case
#: of a genuine Bragg peak below half a degree.
DEFAULT_TAIL = 1.5

#: The two background models, named so a savefile and the dialog agree.
METHOD_ROLLING = "rolling"
METHOD_CHEBYSHEV = "chebyshev"


def smooth(y, width=DEFAULT_SMOOTH):
    # type: (object, int) -> np.ndarray
    """A moving average of odd `width`, with the ends REFLECTED.

    Reflected rather than zero-padded, because both ends of a diffractogram
    are exactly where this module has to be trusted - the low-angle end is
    the whole problem - and a pad of zeros would drag the average down there
    and invent a background feature that is not in the data.
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    width = max(1, int(width)) | 1              # odd, so it cannot shift x
    if width <= 1 or y.size < width:
        return y.copy()
    pad = width // 2
    padded = np.concatenate([y[pad:0:-1], y, y[-2:-pad - 2:-1]])
    return np.convolve(padded, np.ones(width) / width, mode="valid")


def point_noise(y):
    # type: (object) -> float
    """The point-to-point noise, robustly, from the SECOND difference.

    The second difference of a smooth curve is nearly zero whatever the
    curve is doing, so what is left is noise - which is what makes this
    readable on a pattern with an enormous slope under it, where the FIRST
    difference is mostly signal. The median absolute deviation ignores the
    peaks, since they are a minority of the points; 1.4826 turns a MAD into
    a sigma and sqrt(6) takes the second difference's sigma back to the
    point's own.
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    d2 = np.diff(y, 2)
    if d2.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(d2 - np.median(d2))) / np.sqrt(6.0))


def rolling_background(x, y, slope=DEFAULT_SLOPE, tail=DEFAULT_TAIL,
                       smooth_points=DEFAULT_SMOOTH):
    # type: (object, object, float, float, int) -> np.ndarray
    """The background under `y` as a SLOPE-LIMITED lower envelope.

    Christian's design, in his words: "run a rolling first derivative on a
    smoothed pattern so that spikes stand out and do not get flattened while
    also continuous rises will be taken out because the rolling derivative
    has a sensitivity parameter that dictates when background subtraction
    hits a peak and needs to stop fitting the pattern". It gives up on
    amorphous contributions BY CONSTRUCTION - whatever is not decided to be
    a peak IS the background - which is the trade that buys everything else.

    **WALKED FROM HIGH ANGLE TO LOW**, which is his instruction and does more
    work than it looks. The rule is that the background may FALL as fast as
    the data does and may only RISE at `slope`, with "rise" measured walking
    leftwards - so one pass handles the two ends of a peak in opposite ways.
    Coming down onto a peak's high-angle flank the data climbs faster than
    the limit, so the envelope is held at the baseline and the peak is
    bridged; carrying on over the top and down the low-angle flank the
    envelope is already low, so it stays there until the data comes back to
    meet it. No peak state to keep, no shoulders to find, and no way for the
    estimate to end up above the pattern.

    **AND IT IS WHAT MAKES A BEAM STOP COME OUT RIGHT.** The climb into the
    beam-stop shadow is a FALL walking leftwards, so the limit never applies
    to it and the envelope follows it down to the floor - which is correct,
    because that climb is background. That is the case `low_angle_tail`
    below was written for and could not do without being told where the edge
    was.

    `slope` is the sensitivity, in fraction of the background's own height
    per degree. RELATIVE rather than absolute because these files run from
    hundreds of counts to millions and one pattern's background spans a
    factor of 200 within itself, so no single absolute number could be right
    at both ends of it. LOWER treats more of the pattern as peak.

    Vectorised EXACTLY, not approximated. Written out, the recursion
    `b[i] = min(s[i], b[i+1] * exp(slope * (x[i+1] - x[i])))` is
    `b[i] = min over j >= i of s[j] * exp(slope * (x[j] - x[i]))`, so in log
    space it is a suffix minimum of `log(s) + slope * x` - one
    `np.minimum.accumulate`. Measured at 3841 points: 0.23 ms against 3.4 ms
    for the loop, which matters because this reruns on every touch of the
    sensitivity box.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    if x.size != y.size:
        raise ValueError("x and y must be the same length")
    if y.size == 0:
        return y.copy()
    ys = smooth(y, smooth_points)
    slope = max(0.0, float(slope))
    tail = max(0.0, float(tail))
    # A FLOOR under the logarithm, because a pattern that has already had a
    # background taken off contains zeros and negatives - `pxrdfile` says so
    # in its own note. Tied to the noise, so it is a quantity of the data
    # rather than a constant, with a fraction of the range as the fallback
    # for the synthetic case of no noise at all.
    floor = max(point_noise(y), 1e-9 * (float(np.ptp(ys)) or 1.0), 1e-12)
    positive = x[x > 0.0]
    smallest = float(positive.min()) if positive.size else 1.0
    # The power-law allowance is `tail * d(ln x)`, so it needs a floor under
    # x for the point at 2 theta 0 that a synchrotron file really does carry.
    allowance = slope * x + tail * np.log(np.maximum(x, 0.5 * smallest))
    logs = np.log(np.maximum(ys, floor)) + allowance
    envelope = np.minimum.accumulate(logs[::-1])[::-1] - allowance
    # Never above the data: `exp` of the floor can exceed a point that was
    # clamped up to it, and a background sitting over its own pattern is the
    # one thing this must not produce.
    return np.minimum(np.exp(envelope), ys)


def subtract_rolling(x, y, slope=DEFAULT_SLOPE, tail=DEFAULT_TAIL,
                     smooth_points=DEFAULT_SMOOTH, clip_negative=True):
    # type: (...) -> Tuple[np.ndarray, np.ndarray]
    """`(corrected, background)` for `rolling_background`.

    Subtracted from the RAW data and not from the smoothed copy the envelope
    was measured on, so what is left between the peaks is the measurement's
    own noise about zero rather than a manufactured flat line.
    """
    estimate = rolling_background(x, y, slope=slope, tail=tail,
                                  smooth_points=smooth_points)
    corrected = np.asarray(y, dtype=float).reshape(-1) - estimate
    if clip_negative:
        corrected = np.maximum(corrected, 0.0)
    return corrected, estimate

# --------------------------------------------------------- the low-angle tail
#: How far up the pattern the tail model is fitted by default, in the units
#: of x. Far enough to pin the decay, near enough that Bragg peaks are a
#: small part of what it sees.
DEFAULT_LOW_CUTOFF = 6.0


#: The widest a beam stop's shadow can be, in degrees. A stop subtends a
#: small angle, so a maximum further out than this is a REFLECTION and not
#: the edge of a shadow - which is not hypothetical: on Christian's own
#: i15-1-84514 the first version of `beam_stop_edge` returned 1.20 degrees,
#: the tallest Bragg peak in the pattern, and the trim then threw away every
#: point below it.
MAX_SHADOW = 0.5


def beam_stop_edge(x, y, cutoff=DEFAULT_LOW_CUTOFF):
    # type: (object, object, float) -> float
    """Where the direct beam stops rising, i.e. the first usable angle.

    Intensity behind a beam stop RISES to the edge of the shadow and decays
    after it, so the turning point is the boundary and everything below it is
    inside the shadow rather than being data. Measured on Christian's
    `i15-1-70985_tth_det2_norm_0.xy`: intensity climbs 8 707 -> 171 400 over
    the first eight hundredths of a degree and then falls away smoothly, so
    the edge is at 0.080 and the nine points below it are not measurements of
    anything.

    **A SCAN NEED NOT CONTAIN A SHADOW AT ALL**, and saying so is most of
    what this does. `i15-1-84514` starts at 373 counts and climbs for a whole
    degree with no turnover, because the stop is outside the recorded range -
    so the in-window maximum there is a Bragg peak, and answering with it
    threw away a degree of perfectly good data. Two things have to hold
    before a maximum is believed to be an edge: it must lie inside
    `MAX_SHADOW`, and the pattern must have DECAYED to less than half of it
    by the end of the window, which is what a shadow does and what a
    reflection sitting on a rising foot does not. Otherwise the answer is the
    first point, i.e. nothing is dropped.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    if not x.size:
        return 0.0
    near = x <= float(cutoff)
    if not near.any():
        return float(x[0])
    xs, ys = x[near], smooth(y[near], DEFAULT_SMOOTH)
    apex = int(np.argmax(ys))
    if xs[apex] - float(xs[0]) > MAX_SHADOW:
        return float(x[0])
    if float(ys[-1]) >= 0.5 * float(ys[apex]):
        return float(x[0])
    return float(xs[apex])


def trim_below(x, y, start=0.0, cutoff=DEFAULT_LOW_CUTOFF):
    # type: (object, object, float, float) -> tuple
    """`(x, y, start)` with the beam-stop region DROPPED and nothing else.

    The one half of `remove_low_angle` that is not about the Chebyshev. The
    rise into a beam stop is not a measurement of anything - intensity climbs
    because the shadow is ending, and no smooth function takes out a
    nine-point ramp without taking real peaks with it - so those points are
    dropped rather than fitted. `start = 0` finds the edge itself.

    Kept apart from the power-law model because the two answer different
    questions and only one of them is a crutch: `rolling_background` removes
    a small-angle foot on its own and wants no tail fitted underneath it,
    while the ramp at the very edge of the shadow is a spike that no
    background model should be asked to explain.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    if not x.size:
        return x, y, 0.0
    start = float(start) if float(start) > 0.0 else beam_stop_edge(x, y,
                                                                   cutoff)
    keep = x >= start
    if int(keep.sum()) < 4:
        return x, y, float(x[0])
    return x[keep], y[keep], start


def low_angle_tail(x, y, start, cutoff=DEFAULT_LOW_CUTOFF, passes=8):
    # type: (object, object, float, float, int) -> np.ndarray
    """The small-angle tail `a * x**-b`, evaluated over all of `x`.

    **A POWER LAW, not an exponential, and that was measured rather than
    assumed.** Christian described it as "an exponential looking curve close
    to 2theta = 0"; fitting both to the 0.1-5 degree range of his synchrotron
    file gives rms **2 630** for `a x^-b` against **9 443** for `a e^-x/t`, so
    the power law wins by a factor of three and is what is used. The fitted
    exponent there is about 0.78.

    Fitted as a straight line in log-log, with the same lower-envelope
    clipping `chebyshev_background` uses and for the same reason: the Bragg
    peaks in the fitted window are signal sitting ON the tail, and a
    least-squares line through them would ride up and subtract intensity that
    belongs to the phase.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    start = max(float(start), 1e-9)
    inside = (x >= start) & (x <= float(cutoff)) & (x > 0.0)
    if int(inside.sum()) < 4:
        return np.zeros_like(y)
    xs, ys = x[inside], y[inside]
    # A PURE `a x^-b`, fitted in log-log, and DELIBERATELY no additive term.
    # Subtracting an estimated pedestal before the log fit was tried and is
    # worse, not better: `a x^-b - c` is not a power law, so the log-log line
    # is biased and the model then OVERSHOOTS at the very start - measured at
    # 20% of the peak height on a pure test curve. The pedestal a tail
    # settles onto is the ordinary background, which is exactly what the
    # Chebyshev pass is for; this one has the single job of removing the
    # near-divergence that a low-order polynomial cannot follow.
    work = ys.copy()
    amplitude, exponent = 0.0, 0.0
    for _ in range(max(1, int(passes))):
        usable = work > 0.0
        if int(usable.sum()) < 3:
            break
        slope, intercept = np.polyfit(np.log(xs[usable]),
                                      np.log(work[usable]), 1)
        amplitude, exponent = float(np.exp(intercept)), float(-slope)
        work = np.minimum(ys, amplitude * xs ** (-exponent))
    if amplitude <= 0.0:
        return np.zeros_like(y)
    # Clamped at `start`, because a power law diverges at zero and the points
    # below the beam stop are about to be dropped anyway.
    return amplitude * np.maximum(x, start) ** (-exponent)


def remove_low_angle(x, y, start=0.0, cutoff=DEFAULT_LOW_CUTOFF,
                     clip_negative=True):
    # type: (object, object, float, float, bool) -> tuple
    """`(x, y, start)` with the beam-stop region dropped and the tail removed.

    TWO things, because the low-angle end has two problems and only one of
    them can be subtracted. The smooth decay is a background and comes off as
    one. The rise INTO the beam-stop edge is not a measurement of anything -
    no smooth function can take out a nine-point ramp without taking real
    peaks with it - so those points are dropped instead. `start = 0` finds
    the edge itself (see `beam_stop_edge`).

    Why it matters even though Chebyshev is already there: at very short
    wavelengths the tail is enormous, and a low-order polynomial cannot
    follow a near-divergence at one end of an otherwise flat pattern. On
    Christian's file the whole pattern normalises to a beam-stop maximum of
    171 400 - nine times the tallest real Bragg peak - so every peak in the
    window is drawn at a tenth of its height. Removing the tail first takes
    the maximum to 18 195 at 2 theta 2.95, a peak 0.030 degrees wide.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    if not x.size:
        return x, y, 0.0
    start = float(start) if float(start) > 0.0 else beam_stop_edge(x, y,
                                                                   cutoff)
    keep = x >= start
    if int(keep.sum()) < 4:
        keep = np.ones_like(x, dtype=bool)
        start = float(x[0])
    xk, yk = x[keep], y[keep]
    tail = low_angle_tail(xk, yk, start, cutoff=cutoff)
    out = yk - tail
    if clip_negative:
        out = np.maximum(out, 0.0)
    return xk, out, start
