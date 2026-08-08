"""The 3D viewport: instanced ball-and-stick over a multi-molecule Scene,
with Blender-style navigation, selection tools, and the G/R/origin modals.

Rendering: ONE unit icosphere + ONE unit cylinder, instanced across every
visible object; the floor grid is a procedural shader quad (apparently
infinite, distance-faded). All chemistry/math lives in molom.core; this file
uploads buffers, forwards events, and paints 2D overlays with QPainter.

Input map (device-aware — see core/input_map.py and docs/OPERATORS.md):
- scroll on a TRACKPAD orbits: with atoms SELECTED this tumbles the anchored
  molecule(s) about the selection anchor (camera/horizon stay put — the
  vertigo fix); with nothing selected it turntable-orbits the camera
  (yaw world Z + pitch only, NO roll). Ctrl=zoom, Shift=pan.
- a notched MOUSE WHEEL zooms instead (one notch = one step), because on a
  desktop that is what every other program does and one notch of orbit is a
  ~11 deg jump. Ctrl=zoom, Shift=pan there too. Which scheme applies is the
  `input_preset` (auto detects it from pixelDelta per event).
- MMB drag = orbit (Shift=pan, Ctrl=zoom), Alt+LMB drag = orbit for mice
  without a usable middle button, RMB drag = pan
- LMB click pick; dbl-click atom = select molecule; plain left-drag = box
  select; Shift+Space,B / L arm box/lasso tools
- compass balls: hover lights labels, click = axis view (auto-ortho,
  pops back to perspective on the next orbit)
- G grab / R rotate modals: X/Y/Z global -> local -> off, Shift+X/Y/Z plane
  (G), Shift = precision, digits = exact A / degrees, LMB/Enter commit,
  RMB/Esc cancel; Shift+O edits the active object's origin gizmo with the
  same G/R scheme
- O persp/ortho, F/Home fit
"""

import math
import time
from typing import List, Optional, Tuple

import numpy as np

from OpenGL import GL
from PySide6.QtCore import (QEvent, QPoint, QPointF, QRect, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF,
                           QPainter, QPen, QPolygon, QPolygonF,
                           QSurfaceFormat)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

from .choice_popup import ChoicePopup
from ..core import (bonding, edits, elements, flight, grid as grid_mod,
                    input_map, internal,
                    manipulate, measure, meshes, picking, rotations,
                    selection2d, style as style_mod)
from ..core.camera import Camera, quat_from_mat3, quat_mul, quat_to_mat3

BG_BLENDER = grid_mod.BACKGROUND          # Blender viewport grey (default)
BG_LIGHT = (1.0, 1.0, 1.0)
# Selection is drawn Blender-style: an ORANGE OUTLINE hugging the silhouette,
# not Avogadro's translucent blue bubble (Christian's call, with a Blender
# screenshot). The bubble hid the atom it was marking — at VdW sizes it IS the
# atom, only bigger and bluer — while an outline leaves the chemistry visible
# and still reads instantly at a glance. Same hue as the edit-mode accent.
_OUTLINE_COLOR = (1.0, 0.588, 0.157, 1.0)
#: Outline thickness as a fraction of the camera distance, so it stays roughly
#: constant ON SCREEN instead of ballooning as you zoom in. Clamped, or a
#: far-away view draws an outline fatter than the molecule.
#: Round 35: divided by FIVE. The round-34 values drew a rim thick enough to
#: merge between neighbouring atoms — on cubane the eight carbons came out as
#: one orange blob with the hydrogens welded to it, which is the opposite of
#: what an outline is for. Blender's is a hairline; so is this now.
_OUTLINE_WIDTH_FRAC = 0.0012
_OUTLINE_WIDTH_RANGE = (0.004, 0.044)
_CLICK_SLOP_PX = 4
_MIN_PICK_RADIUS = 0.35
_WHEEL_TO_PX = 0.6      # legacy scale, kept for callers passing raw units
# A notched wheel reports angleDelta in 1/8 degree, ONE notch = 120 = 15 deg.
# Multiplying that by 0.6 gave 72 "pixels" = ~43 deg of rotation per event,
# which is what made scrolling feel like it jumped in fixed steps. Precision
# trackpads report pixelDelta instead, which is smooth — prefer it.
_WHEEL_DEG_TO_PX = 1.2  # rotation pixels per degree of wheel travel
_WHEEL_NOTCH = 120.0    # angleDelta units in one detent of a mouse wheel
_NOTCH_PAN_PX = 45.0    # Shift+wheel pan distance per detent
_DRAG_ZOOM_PX = 40.0    # Ctrl+MMB drag pixels per zoom step
# Atom labels: em size as a fraction of the atom's DIAMETER at scale 1.0.
# Was a bold fit-to-0.8-of-the-width, which covered the sphere it labelled.
_LABEL_FILL = 0.46
# How far a long label may spread across the atom before it is squeezed.
_LABEL_MAX_WIDTH = 1.15
# Wide, humanist sans faces in preference order — a condensed UI font at this
# size turns "8" and "B" into the same smudge.
_LABEL_FAMILIES = ["Verdana", "DejaVu Sans", "Segoe UI", "Tahoma"]
_ANCHOR_FLASH_S = 0.8   # crosshair stays visible this long after rotating
_GESTURE_GAP_S = 0.6    # scroll pause that starts a new undo-able gesture
_AXIS_COLORS = {0: QColor(226, 80, 80), 1: QColor(120, 190, 70),
                2: QColor(70, 140, 230)}
# Modifier keys generate their own press events; modal key-waits must not
# treat them as "some other key".
_MODIFIER_KEYS = (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
                  Qt.Key_AltGr, Qt.Key_CapsLock, Qt.Key_NumLock)
_ANCHOR_COLOR = QColor(255, 208, 60)      # Avogadro-1 style yellow
_MEASURE_COLOR = QColor(120, 235, 255)    # measurement overlay (cyan)
_META_GLOW = (0.62, 0.42, 0.95)           # meta-atom emissive halo (violet)
_LIGATING_COLOR = QColor(180, 120, 255)   # template 'this atom coordinates'
_SYM_COLOR = QColor(255, 170, 90)         # symmetry element glyphs
_GHOST_COLOR = QColor(150, 200, 255, 120) # symmetry-image ghosts
_MAX_GHOSTS = 48                          # a 192-op group would be a fog
#: The unit cell's eight corners in fractional coordinates — the reference
#: extent the symmetry overlay's depth cue is calibrated against.
_UNIT_CORNERS = np.array([[a, b, c] for a in (0.0, 1.0)
                          for b in (0.0, 1.0) for c in (0.0, 1.0)])
_EDIT_ACCENT = QColor(255, 150, 40)       # edit-mode border/header tint
# ---- right-mouse flight (UE5-style), see core/flight.py
_FLY_TICK_MS = 16                         # ~60 Hz integration
#: Radians of turn per pixel of mouse-look. Mouse LOOK is deliberately direct
#: (no smoothing): the inertia belongs to the movement, and a laggy crosshair
#: reads as a dropped frame rather than as weight.
_FLY_LOOK_RATE = 0.0032
_FLY_COLOR = QColor(120, 220, 255)        # flight HUD, matching the shuttle
#: Scroll-to-steer is coarser than mouse-look — a trackpad swipe covers far
#: fewer "pixels" than the equivalent drag.
_WHEEL_STEER_PX = 2.0

MODE_OBJECT = "object"
MODE_EDIT = "edit"


def cell_of(obj):
    """The unit Cell a scene object carries, or None.

    Crystallography rides in `Structure.metadata["cell"]` so it round-trips
    through savepoints and undo snapshots for free — those already deep-copy
    metadata, and a parallel attribute would have to be taught to.
    """
    from ..core import cif as cif_mod
    try:
        d = obj.structure.metadata.get("cell")
    except AttributeError:
        return None
    if not d:
        return None
    try:
        return cif_mod.Cell.from_dict(d)
    except (KeyError, TypeError, ValueError):
        return None


def set_cell_reference(structure, coords=None):
    """Pin the cell frame to the atoms as they stand RIGHT NOW.

    Call after importing or rebuilding a crystal. From here the box follows
    whatever rigid motion the atoms undergo (see `cell_corners_world`).

    `coords` pins the reference to a DIFFERENT set of positions than the ones
    the structure is currently holding, and the only correct value for it is
    the crystal in the CELL's own frame. A rebuild that preserves the user's
    rotation stores rotated atoms, so pinning against those would make the fit
    the identity — and the box would be drawn square-on while its atoms sit at
    an angle. Pin against the unrotated coordinates and the fit recovers the
    rotation, which is exactly what `cell_corners_world` needs.
    """
    from ..core import cif as cif_mod
    meta = structure.metadata
    if not meta.get("cell") or structure.n_atoms < 3:
        return
    xyz = structure.coords if coords is None else np.asarray(coords,
                                                             dtype=float)
    if len(xyz) != structure.n_atoms:
        xyz = structure.coords
    idx = cif_mod.reference_sample(xyz)
    meta["cell_ref_idx"] = [int(i) for i in idx]
    meta["cell_ref_xyz"] = [[float(v) for v in xyz[i]] for i in idx]


def cell_corners_world(obj, cell=None):
    """The 8 cell corners in world space, following the molecule.

    The cell is stored in the coordinate frame the atoms had at import, so
    the box is transported by the rigid motion recovered from a sample of
    reference atoms. That is what makes it track a grab or a rotation LIVE:
    this runs while painting, not on commit. NOT `obj.origin` — that is the
    centroid, which both offsets the box (the bug Christian photographed)
    and stays put during a plain grab.
    """
    from ..core import cif as cif_mod
    cell = cell or cell_of(obj)
    if cell is None:
        return None
    corners = cell.corners()
    meta = obj.structure.metadata
    idx = meta.get("cell_ref_idx")
    ref = meta.get("cell_ref_xyz")
    if not idx or not ref:
        return corners
    coords = obj.structure.coords
    if any(i >= len(coords) for i in idx):
        return corners           # atoms were deleted; stop pretending to fit
    fit = cif_mod.rigid_from_reference(np.asarray(ref, dtype=float),
                                       coords[list(idx)])
    if fit is None:
        return corners
    rot, trans = fit
    return corners @ rot.T + trans[None, :]

Pick = Tuple[int, int]   # (object id, local atom index)

_VERT = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in mat4 aModel;    // locations 2,3,4,5
layout(location = 6) in vec4 aColor;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vNormalView;
out vec4 vColor;
void main() {
    vec4 world = aModel * vec4(aPos, 1.0);
    gl_Position = uProj * uView * world;
    vNormalView = mat3(uView) * mat3(aModel) * aNormal;
    vColor = aColor;
}
"""

_FRAG = """
#version 330 core
in vec3 vNormalView;
in vec4 vColor;
uniform float uFlat;      // 1.0 = unlit flat colour (selection outline hull)
out vec4 fragColor;
void main() {
    if (uFlat > 0.5) { fragColor = vColor; return; }
    vec3 n = normalize(vNormalView);
    vec3 lightDir = normalize(vec3(0.4, 0.5, 1.0));
    float diff = max(dot(n, lightDir), 0.0);
    vec3 halfway = normalize(lightDir + vec3(0.0, 0.0, 1.0));
    float spec = pow(max(dot(n, halfway), 0.0), 32.0) * 0.35;
    vec3 c = vColor.rgb * (0.35 + 0.65 * diff) + vec3(spec);
    fragColor = vec4(c, vColor.a);
}
"""

#: A sphere divided into occupancy WEDGES, VESTA's way of drawing a site that
#: several species share (a substitutional solid solution: Nb 0.50 / Ti 0.25 /
#: Ni 0.15 / Co 0.10 on one position). Its own program and its own buffer
#: rather than extra attributes on the main one — an overlay that borrows the
#: scene's instance buffers is the round-35 flicker bug, and mixed sites are
#: rare enough that a second small pass costs nothing.
_SPLIT_VERT = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in mat4 aModel;    // locations 2,3,4,5
layout(location = 6) in vec4 aSeg0;     // rgb = colour, a = cumulative end
layout(location = 7) in vec4 aSeg1;
layout(location = 8) in vec4 aSeg2;
layout(location = 9) in vec4 aSeg3;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vNormalView;
out vec3 vLocal;
out vec4 vSeg0;
out vec4 vSeg1;
out vec4 vSeg2;
out vec4 vSeg3;
void main() {
    vec4 world = aModel * vec4(aPos, 1.0);
    gl_Position = uProj * uView * world;
    vNormalView = mat3(uView) * mat3(aModel) * aNormal;
    vLocal = aPos;
    vSeg0 = aSeg0; vSeg1 = aSeg1; vSeg2 = aSeg2; vSeg3 = aSeg3;
}
"""

_SPLIT_FRAG = """
#version 330 core
in vec3 vNormalView;
in vec3 vLocal;
in vec4 vSeg0;
in vec4 vSeg1;
in vec4 vSeg2;
in vec4 vSeg3;
out vec4 fragColor;
void main() {
    // The pie faces the CAMERA, as VESTA's does: a sphere's normal is its
    // radial direction, so the view-space normal's x/y is the angle round the
    // view axis. Splitting in object space instead (the first attempt) shows
    // an edge-on sliver from exactly the axis views a crystallographer uses,
    // which is where the composition most needs to be legible.
    float t = atan(vNormalView.x, vNormalView.y) * 0.15915494 + 0.5;
    t = clamp(t, 0.0, 0.999999);
    vec3 c = vSeg0.rgb;
    if (t >= vSeg0.a) c = vSeg1.rgb;
    if (t >= vSeg1.a) c = vSeg2.rgb;
    if (t >= vSeg2.a) c = vSeg3.rgb;
    vec3 n = normalize(vNormalView);
    vec3 lightDir = normalize(vec3(0.4, 0.5, 1.0));
    float diff = max(dot(n, lightDir), 0.0);
    vec3 halfway = normalize(lightDir + vec3(0.0, 0.0, 1.0));
    float spec = pow(max(dot(n, halfway), 0.0), 32.0) * 0.35;
    fragColor = vec4(c * (0.35 + 0.65 * diff) + vec3(spec), 1.0);
}
"""

_LINE_VERT = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vColor;
void main() {
    gl_Position = uProj * uView * vec4(aPos, 1.0);
    vColor = aColor;
}
"""

_LINE_FRAG = """
#version 330 core
in vec3 vColor;
uniform float uAlpha;
out vec4 fragColor;
void main() { fragColor = vec4(vColor, uAlpha); }
"""

# Procedural "infinite" floor grid: a huge z=0 quad; the fragment shader
# draws anti-aliased 1 A and 10 A lines plus the tinted X/Y axes, fading
# with distance so the plane appears to stretch to the horizon.
# The grid is a SCREEN-SPACE plane, not a big quad (round 20). A quad — even
# a 5000 A one — has an edge you can zoom out to, and its lines are locked to
# one spacing, so at distance the 1 A rulings alias into a moire that fights
# the axis lines. Instead a full-screen triangle is unprojected into a ray per
# fragment and intersected with z = 0: genuinely infinite, and the spacing can
# follow the camera by decades the way Blender's does.
_GRID_VERT = """
#version 330 core
layout(location = 0) in vec2 aPos;
uniform mat4 uInvViewProj;
out vec3 vNear;
out vec3 vFar;

vec3 unproject(vec2 ndc, float z) {
    vec4 p = uInvViewProj * vec4(ndc, z, 1.0);
    return p.xyz / p.w;
}

void main() {
    vNear = unproject(aPos, -1.0);
    vFar = unproject(aPos, 1.0);
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_GRID_FRAG = """
#version 330 core
in vec3 vNear;
in vec3 vFar;
uniform mat4 uViewProj;
uniform vec3 uCamPos;
uniform float uFade;
uniform vec3 uBase;
uniform vec3 uAxisX;
uniform vec3 uAxisY;
out vec4 fragColor;

// Coverage of the nearest ruling of `step_`, antialiased by the on-screen
// derivative so a line stays one pixel wide at any zoom.
float gridline(vec2 p, float step_) {
    vec2 q = abs(fract(p / step_ - 0.5) - 0.5) * step_ / fwidth(p);
    return 1.0 - min(min(q.x, q.y), 1.0);
}

void main() {
    // Ray-plane intersection with z = 0. Rays going the other way never meet
    // it — that is the horizon, and it costs one discard.
    float denom = vFar.z - vNear.z;
    if (abs(denom) < 1e-8) discard;
    float t = -vNear.z / denom;
    if (t <= 0.0 || t >= 1.0) discard;
    vec3 world = vNear + t * (vFar - vNear);
    vec2 p = world.xy;

    // Depth, so molecules occlude the floor exactly as before.
    vec4 clip = uViewProj * vec4(world, 1.0);
    gl_FragDepth = clamp(0.5 + 0.5 * (clip.z / clip.w), 0.0, 1.0);

    float dist = length(world - uCamPos);

    // Spacing follows the camera in powers of ten: the decade below the
    // current scale fades out as the next one fades in, so there is always
    // roughly the same number of lines on screen and the fine rulings never
    // collapse into moire.
    // TWO levels only. A third, finer one looked right on paper but at 0.1x
    // the main spacing it is ~80 rulings across the view: they alias into a
    // crosshatch that reads as a texture on the molecule rather than a floor.
    float lod = max(log(dist * 0.06) / log(10.0), 0.0);
    float fade = fract(lod);
    float s1 = pow(10.0, floor(lod));
    float s2 = s1 * 10.0;

    // The finer decade fades out across the decade, by which point the
    // coarser one has taken its place — so the line count on screen stays
    // roughly constant however far you zoom.
    float g1 = gridline(p, s1) * (1.0 - fade);
    float g2 = gridline(p, s2);
    float a = max(g1 * 0.45, g2 * 0.80);

    // Axes are drawn INSTEAD of the grid where they land, not max()'d with
    // it: blending the two is what made them look chewed up at distance.
    vec2 fw = fwidth(p);
    float ay = 1.0 - min(abs(p.x) / (1.6 * fw.x), 1.0);   // x = 0 -> Y axis
    float ax = 1.0 - min(abs(p.y) / (1.6 * fw.y), 1.0);   // y = 0 -> X axis
    vec3 col = uBase;
    if (ax > ay && ax > 0.0) { col = uAxisX; a = ax; }
    else if (ay > 0.0)       { col = uAxisY; a = ay; }

    // Distance fade — both a horizon and a performance guard: fragments past
    // uFade are thrown away before any of the above matters visually.
    a *= 1.0 - smoothstep(uFade * 0.45, uFade, dist);
    if (a <= 0.003) discard;
    fragColor = vec4(col, a);
}
"""


def _h_note(added, removed):
    """' (+2 H)' / ' (-1 H)' tail for edit status messages."""
    bits = []
    if added:
        bits.append("+{} H".format(added))
    if removed:
        bits.append("-{} H".format(removed))
    return "  ({})".format(", ".join(bits)) if bits else ""


def default_surface_format():
    # type: () -> QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSamples(4)
    fmt.setDepthBufferSize(24)
    return fmt


def _compile(src, kind):
    sh = GL.glCreateShader(kind)
    GL.glShaderSource(sh, src)
    GL.glCompileShader(sh)
    if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
        raise RuntimeError("shader compile failed:\n"
                           + GL.glGetShaderInfoLog(sh).decode("utf-8", "replace"))
    return sh


def _program(vert_src, frag_src):
    prog = GL.glCreateProgram()
    vs = _compile(vert_src, GL.GL_VERTEX_SHADER)
    fs = _compile(frag_src, GL.GL_FRAGMENT_SHADER)
    GL.glAttachShader(prog, vs)
    GL.glAttachShader(prog, fs)
    GL.glLinkProgram(prog)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        raise RuntimeError("program link failed:\n"
                           + GL.glGetProgramInfoLog(prog).decode("utf-8", "replace"))
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    return prog


class _InstancedMesh:
    """One mesh + its per-instance model matrices/colours, ready to draw."""

    def __init__(self, verts, normals, indices):
        self.n_indices = int(indices.size)
        self.n_instances = 0
        self.vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.vao)
        self.vbo = GL.glGenBuffers(1)
        inter = np.hstack([verts, normals]).astype(np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, inter.nbytes, inter, GL.GL_STATIC_DRAW)
        stride = 6 * 4
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride,
                                 GL.GLvoidp(0))
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, stride,
                                 GL.GLvoidp(12))
        GL.glEnableVertexAttribArray(1)
        self.ebo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                        indices.astype(np.uint32), GL.GL_STATIC_DRAW)
        self.ibo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.ibo)
        istride = 20 * 4
        for k in range(4):
            loc = 2 + k
            GL.glVertexAttribPointer(loc, 4, GL.GL_FLOAT, GL.GL_FALSE, istride,
                                     GL.GLvoidp(16 * k))
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribDivisor(loc, 1)
        GL.glVertexAttribPointer(6, 4, GL.GL_FLOAT, GL.GL_FALSE, istride,
                                 GL.GLvoidp(64))
        GL.glEnableVertexAttribArray(6)
        GL.glVertexAttribDivisor(6, 1)
        GL.glBindVertexArray(0)

    def upload(self, mats, colors):
        # type: (np.ndarray, np.ndarray) -> None
        n = mats.shape[0]
        self.n_instances = n
        if n == 0:
            return
        cols = np.ascontiguousarray(np.transpose(mats, (0, 2, 1))) \
            .reshape(n, 16).astype(np.float32)
        data = np.hstack([cols, colors.astype(np.float32)])
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.ibo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_DYNAMIC_DRAW)

    def draw(self):
        if self.n_instances == 0:
            return
        GL.glBindVertexArray(self.vao)
        GL.glDrawElementsInstanced(GL.GL_TRIANGLES, self.n_indices,
                                   GL.GL_UNSIGNED_INT, None, self.n_instances)
        GL.glBindVertexArray(0)


class _SplitMesh:
    """A mesh whose instances carry FOUR colours and their wedge boundaries.

    Same geometry and same model matrices as `_InstancedMesh`; the difference
    is 4 vec4 of segment data per instance instead of one colour. Four is
    enough for every solid solution anyone draws, and a site with more species
    than that keeps its three biggest and merges the tail.
    """

    SEGMENTS = 4

    def __init__(self, verts, normals, indices):
        self.n_indices = int(indices.size)
        self.n_instances = 0
        self.vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.vao)
        self.vbo = GL.glGenBuffers(1)
        inter = np.hstack([verts, normals]).astype(np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, inter.nbytes, inter,
                        GL.GL_STATIC_DRAW)
        stride = 6 * 4
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride,
                                 GL.GLvoidp(0))
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, stride,
                                 GL.GLvoidp(12))
        GL.glEnableVertexAttribArray(1)
        self.ebo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                        indices.astype(np.uint32), GL.GL_STATIC_DRAW)
        self.ibo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.ibo)
        istride = (16 + 4 * self.SEGMENTS) * 4
        for k in range(4):
            loc = 2 + k
            GL.glVertexAttribPointer(loc, 4, GL.GL_FLOAT, GL.GL_FALSE, istride,
                                     GL.GLvoidp(16 * k))
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribDivisor(loc, 1)
        for k in range(self.SEGMENTS):
            loc = 6 + k
            GL.glVertexAttribPointer(loc, 4, GL.GL_FLOAT, GL.GL_FALSE, istride,
                                     GL.GLvoidp(64 + 16 * k))
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribDivisor(loc, 1)
        GL.glBindVertexArray(0)

    def upload(self, mats, segments):
        # type: (np.ndarray, np.ndarray) -> None
        n = mats.shape[0]
        self.n_instances = n
        if n == 0:
            return
        cols = np.ascontiguousarray(np.transpose(mats, (0, 2, 1))) \
            .reshape(n, 16).astype(np.float32)
        data = np.hstack([cols, segments.reshape(n, 4 * self.SEGMENTS)
                          .astype(np.float32)])
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.ibo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data,
                        GL.GL_DYNAMIC_DRAW)

    def draw(self):
        if self.n_instances == 0:
            return
        GL.glBindVertexArray(self.vao)
        GL.glDrawElementsInstanced(GL.GL_TRIANGLES, self.n_indices,
                                   GL.GL_UNSIGNED_INT, None, self.n_instances)
        GL.glBindVertexArray(0)


class _LineBuffer:
    """A VAO/VBO for GL_LINES with per-vertex colour (wireframe bonds)."""

    def __init__(self):
        self.n_verts = 0
        self.vao = GL.glGenVertexArrays(1)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        stride = 6 * 4
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride,
                                 GL.GLvoidp(0))
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, stride,
                                 GL.GLvoidp(12))
        GL.glEnableVertexAttribArray(1)
        GL.glBindVertexArray(0)

    def upload(self, verts):
        # type: (np.ndarray) -> None
        self.n_verts = int(verts.shape[0]) if verts.size else 0
        if not self.n_verts:
            return
        data = verts.astype(np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_DYNAMIC_DRAW)

    def draw(self, mode=None):
        if not self.n_verts:
            return
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_LINES if mode is None else mode, 0,
                        self.n_verts)
        GL.glBindVertexArray(0)


class _GridQuad:
    """Full-screen triangle pair in CLIP space; the shader unprojects it."""

    def __init__(self):
        e = 1.0
        verts = np.array([[-e, -e], [e, -e], [e, e],
                          [-e, -e], [e, e], [-e, e]], dtype=np.float32)
        self.vao = GL.glGenVertexArrays(1)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, verts.nbytes, verts,
                        GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 8,
                                 GL.GLvoidp(0))
        GL.glEnableVertexAttribArray(0)
        GL.glBindVertexArray(0)

    def draw(self):
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
        GL.glBindVertexArray(0)


class MolViewport(QOpenGLWidget):
    """Scene viewport. Selection is a click-ordered list of (obj_id, atom)."""

    selection_changed = Signal(list)     # list of Pick tuples
    status_message = Signal(str)         # transient UI text (modal state)
    edit_committed = Signal()            # geometry changed and settled
    origin_active_changed = Signal(bool)  # origin handle picked up / put down

    # CLASS-level defaults, not merely `__init__` ones. `event()` is overridden
    # and calls `_keyboard_captured()` -> `modal_active()`, and Qt delivers
    # events to a widget WHILE IT IS BEING CONSTRUCTED (creating the flight
    # QTimer with `self` as parent sends a ChildAdded). The override then reads
    # state that `__init__` has not reached yet, and because the AttributeError
    # happens inside a C++ callback it does not surface as itself: the next
    # PySide call fails with "QTimer returned NULL without setting an
    # exception", which points nowhere near the real cause. Defaults on the
    # class mean the attributes exist from the first instant the object does.
    _fly = None
    _poly_key = None
    _poly_cache = None
    _poly_edge_cache = None
    _fly_pending = None
    _internal = None
    _grab = None
    _rotate = None
    _shuttle = None
    _align_wait = None
    _origin_active = False
    _draw_drag = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = None                # set via set_scene
        self.style = style_mod.BALL_AND_STICK
        self.camera = Camera()
        self.selection = []              # type: List[Pick]
        self.background = BG_BLENDER
        self.show_grid = True
        self.show_compass = True
        self.show_labels_element = False
        self.show_labels_index = False
        self.precision_factor = 0.5      # Shift-drag scale (Settings)
        # Undo hooks (set by the app): called BEFORE a model edit begins /
        # when a started edit is cancelled.
        self.on_model_edit_begin = None  # type: Optional[callable]
        self.on_model_edit_cancel = None  # type: Optional[callable]
        self._gl_ready = False
        self._needs_rebuild = False
        self._pick_dirty = True
        self._sphere = None
        self._cylinder = None
        # Overlay passes get their OWN instance buffers (round 35). They used
        # to borrow the scene's and set `_needs_rebuild` so the NEXT frame put
        # the real geometry back — which means the scene buffer only holds the
        # molecule between `_rebuild()` and the first overlay. Any frame that
        # reaches `_sphere.draw()` without a rebuild first therefore draws the
        # selection hull or the glow shells IN PLACE OF the molecule: one
        # frame of orange blobs, i.e. a flicker. See `_paint_selection`.
        self._hull_sphere = None
        self._hull_cylinder = None
        self._glow_sphere = None
        self._split_sphere = None
        self._split_prog = None
        self._prog = None
        self._line_prog = None
        self._grid_prog = None
        self._grid_quad = None
        self._wire_lines = None          # type: Optional[_LineBuffer]
        # flat pick arrays (parallel, across visible objects)
        self._atom_map = []              # type: List[Pick]
        self._flat_coords = np.zeros((0, 3))
        self._flat_pick_radii = np.zeros(0)
        self._draw_radii = np.zeros(0)   # actual drawn sphere radii
        # input state
        self._drag_last = None
        self._drag_button = None
        self._drag_moved = False
        self._press_pos = None           # drag slop measured from HERE
        self._select_tool = None         # None | 'box' | 'lasso'
        self._region_drag = None
        self._nav_drag = None            # 'orbit'|'pan'|'zoom' while dragging
        # 'auto' | 'trackpad' | 'mouse' — what a plain scroll means. Set from
        # Settings; 'auto' decides per event (see core/input_map.py).
        self.input_preset = input_map.PRESET_AUTO
        self._dbl_pos = None
        self._grab = None                # {'state','snap',...} while G active
        self._rotate = None              # {'state','snap',...} while R active
        self._origin_active = False      # edit mode: origin handle picked up
        self._draw_from = None           # edit mode: dbl-click-drag anchor
        self.last_transform = None       # for Shift+R (repeat last)
        self.transform_serial = 0        # bumped whenever last_transform is set
        self._align_wait = None          # 'axis'|'plane' while A waits for key
        self._align_previewed = None     # axis currently PREVIEWED, or None
        self._cue_range = None           # (near, far) for the depth cue
        self.on_align_key = None         # app callback: (kind, axis) -> None
        self.on_align_confirm = None     # app callback: keep the preview
        self.on_align_cancel = None      # app callback: put it back
        # edit mode (Blender's Tab): chemistry editing on ONE object
        self.mode = MODE_OBJECT
        self.edit_obj_id = None          # type: Optional[int]
        self.draw_element = "C"          # draw tool's current element
        self.draw_tool_active = False    # E arms drawing; otherwise clicks
                                         # only SELECT (accidental atoms were
                                         # the single worst edit-mode paper cut)
        self._hover_bond = None          # (obj_id, i, j) under the cursor
        self._compass_hover_item = None  # (axis, sign) actually hovered
        self._dbl_empty = False
        self.show_hbonds = False         # suspected H-bond overlay
        self.show_cell = True            # unit-cell box for CIF imports
        #: VESTA's pie-slice spheres for sites shared by several species. On
        #: by default: a solid solution drawn as its majority element is a
        #: composition the file never claimed, and the wedges are the only
        #: thing on screen that says otherwise.
        self.show_occupancy = True
        self.polyhedra_alpha = 0.55      # coordination-solid opacity
        #: How a REFUSED bond is drawn when the ❖ page's override is on. The
        #: defaults live in core.style so the viewport and the Blender export
        #: cannot drift apart; these are the live, tweakable copies.
        self.refused_bond_scale = style_mod.REFUSED_BOND_SCALE
        self.refused_bond_fade = style_mod.REFUSED_BOND_FADE
        self.render_subdiv_bonus = 2     # extra sphere subdivisions on render
        self.render_scale = 2            # resolution multiplier on render
        self.adjust_h = True             # re-dress hydrogens on edits
        self.on_edit_begin = None        # app callback: () -> None (undo)
        self.on_mode_changed = None      # app callback: (mode) -> None
        self.on_new_molecule = None      # app callback: () -> obj_id
        self.on_toggle_mode = None       # app callback: () -> None (Tab)
        self.on_tool_changed = None      # app callback: (draw_on) -> None
        self.on_element_changed = None   # app callback: (symbol) -> None
        self.meta_template = None        # armed MetaAtom, or None
        self.measure_active = False      # measurement tool armed
        self._measure_picks = []         # type: List[Pick]  click order
        self.on_measure_changed = None   # app callback: (on) -> None
        self.label_scale = 1.0           # Settings: atom-label size multiplier
        self._tumble_axis = None         # 0/1/2 world axis lock for tumbling
        self._tumble_local = False
        self._gesture_mode = None        # 'camera' | 'tumble', decided at start
        self._last_orbit_t = 0.0
        self.atom_scale = 0.9            # Settings sphere-size multiplier
        self._draw_drag = None           # Avogadro-style drag-add in progress
        self._shuttle = None             # shuttle (pilot) mode state
        self._anchor_flash_t = 0.0
        self._anchor_pos = None          # type: Optional[np.ndarray]
        self._last_model_rot_t = 0.0
        self._compass_hits = []          # [(x, y, axis, sign)] per paint
        self._compass_hover = False
        self._fly = None                 # right-mouse flight state
        # Flight tuning, live-editable from Settings and persisted there.
        # Kept on the viewport rather than baked into core/flight.py defaults
        # so a session's feel can be adjusted without a restart.
        self.fly_accel = flight.DEFAULT_ACCEL
        self.fly_damping = flight.DEFAULT_DAMPING
        self.fly_brake_factor = flight.DEFAULT_BRAKE_FACTOR
        self.fly_strafe_factor = flight.DEFAULT_STRAFE_FACTOR
        self.fly_roll_rate = flight.DEFAULT_ROLL_RATE
        self.fly_bank_angle = flight.DEFAULT_BANK_ANGLE
        self.fly_aim_expo = flight.DEFAULT_AIM_EXPO
        self.fly_turn_rate = 1.0
        self.fly_hold_ms = flight.DEFAULT_HOLD_MS
        self._fly_anchor = QPoint(0, 0)   # captured pointer home, global px
        self._cam_key = None              # see _camera_frame
        self._cam_frame = None
        self._cue_range = None            # depth-cue near/far, per overlay
        self._cue_eye = None              # eye pinned for an overlay pass
        self._pen_cache = {}              # see _cued_pen
        # A right press ARMS flight; it does not start it (round 36). See
        # `_arm_fly` for why starting on the press cost the context menu.
        self._fly_pending = None          # press position while armed
        self._fly_hold_timer = QTimer(self)
        self._fly_hold_timer.setSingleShot(True)
        self._fly_hold_timer.timeout.connect(self._fly_hold_elapsed)
        self._fly_timer = QTimer(self)
        self._fly_timer.setInterval(_FLY_TICK_MS)
        self._fly_timer.timeout.connect(self._fly_tick)
        self._internal = None            # bond-length/angle/dihedral modal
        self._context_popup = None       # right-click ChoicePopup, kept alive
        self.on_context_op = None        # app callback: (operator id) -> None
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)      # modals + compass hover need moves
        self.setMinimumSize(320, 240)

    # ------------------------------------------------------------- public API
    def set_scene(self, scene):
        self.scene = scene
        self.refresh_geometry()

    def set_style(self, st):
        self.style = st
        self.refresh_geometry()

    def refresh_geometry(self):
        self._needs_rebuild = True
        self._pick_dirty = True
        self.update()

    def fit_view(self):
        """F: frame the SELECTION when there is one, otherwise the scene."""
        if self.scene is None:
            return
        pts = [self.scene.pick_coords(p) for p in self.selection]
        pts = [p for p in pts if p is not None]
        if pts:
            arr = np.array(pts)
            center = arr.mean(axis=0)
            radius = float(np.linalg.norm(arr - center, axis=1).max()) + 1.5
            self.camera.fit(center, radius)
        elif self.scene.visible_objects():
            self.camera.fit(self.scene.centroid(), self.scene.bounding_radius())
        self.update()

    def toggle_projection(self):
        self.camera.orthographic = not self.camera.orthographic
        self.camera.auto_ortho = False      # manual choice sticks
        self.status_message.emit(
            "Orthographic" if self.camera.orthographic else "Perspective")
        self.update()

    def align_view_axis(self, axis, sign):
        # type: (int, int) -> None
        self.camera.align_view(axis, sign)
        name = ("-" if sign < 0 else "+") + "XYZ"[axis]
        self.status_message.emit(
            "View along {} (orthographic; orbit to return to perspective)"
            .format(name))
        self.update()

    def toggle_grid(self):
        self.show_grid = not self.show_grid
        self.update()

    def toggle_background(self):
        self.background = BG_LIGHT if self.background == BG_BLENDER \
            else BG_BLENDER
        self.update()

    def set_labels(self, element=None, index=None):
        if element is not None:
            self.show_labels_element = element
        if index is not None:
            self.show_labels_index = index
        self.update()

    def set_selection(self, picks):
        # type: (List[Pick]) -> None
        self.selection = list(picks)
        self.selection_changed.emit(list(self.selection))
        self.update()

    def set_select_tool(self, tool):
        # type: (Optional[str]) -> None
        self._select_tool = tool
        self.status_message.emit(
            {"box": "Box select: drag with left mouse (Esc to exit)",
             "lasso": "Lasso select: drag with left mouse (Esc to exit)",
             None: ""}[tool])
        self.update()

    def set_input_preset(self, preset):
        # type: (object) -> None
        """'auto' | 'trackpad' | 'mouse' — what a plain scroll does."""
        self.input_preset = input_map.normalize_preset(preset)

    def cancel_modes(self):
        """Esc hook: cancel any modal first, then an armed select tool."""
        # An armed-but-not-yet-flying right press is never worth reporting,
        # but it must not survive whatever comes next and take off later.
        self._cancel_fly_arm()
        if self.measure_active:
            self.set_measure_tool(False)
            return True
        if self._shuttle is not None:
            self.stop_shuttle()
            return True
        if self._grab is not None:
            self._finish_grab(commit=False)
            return True
        if self._rotate is not None:
            self._finish_rotate(commit=False)
            return True
        if self._internal is not None:
            self._finish_internal(commit=False)
            return True
        if self._origin_active:
            self.set_origin_active(False)
            return True
        if self._align_wait is not None:
            self._end_align_wait("Align cancelled")
            return True
        if self._select_tool is not None:
            self.set_select_tool(None)
            return True
        return False

    def modal_active(self):
        return (self._grab is not None or self._rotate is not None
                or self._align_wait is not None
                or self._internal is not None)

    # ---------------------------------------------------- origin handle
    def set_origin_active(self, on):
        # type: (bool) -> None
        """The edit-mode origin handle. The orange dot is always drawn on
        top; clicking it picks the origin up (gizmo appears, G/R now drive
        the origin), clicking anywhere else puts it down again."""
        on = bool(on) and self.mode == MODE_EDIT
        if on == self._origin_active:
            return
        self._origin_active = on
        obj = self.edit_object()
        if on:
            self.status_message.emit(
                "Origin of {} picked up — G moves it, R turns its frame, "
                "the transform panel now edits it, click off to set it"
                .format(obj.name if obj else "?"))
        else:
            self.status_message.emit("Origin set")
        # the transform panel must switch to (and away from) the origin
        self.origin_active_changed.emit(on)
        self.update()

    def _origin_screen(self):
        obj = self.edit_object()
        if obj is None:
            return None
        xy, front = self._project(obj.origin[None, :])
        if not front[0]:
            return None
        return float(xy[0, 0]), float(xy[0, 1])

    def _origin_dot_hit(self, pos, radius=11.0):
        s = self._origin_screen()
        if s is None:
            return False
        return (pos.x() - s[0]) ** 2 + (pos.y() - s[1]) ** 2 <= radius ** 2

    def set_atom_scale(self, scale):
        # type: (float) -> None
        """Settings slider. Only the instance buffers are rebuilt (one
        upload of a few hundred matrices), so live dragging is cheap."""
        self.atom_scale = max(0.1, float(scale))
        self.refresh_geometry()

    # ------------------------------------------------------------- flying
    #: WASD + Q/E as (right, up, forward), the layout UE5, Unity and Blender's
    #: own fly mode all share — muscle memory nobody should have to relearn.
    #: 6DoF thrust (round 35). Q/E gave up vertical thrust to ROLL, and
    #: Space/Ctrl took over elevate — the standard arcade space-sim layout
    #: Christian asked for. These are only ever read while `_fly` is live and
    #: the viewport holds the keyboard, so none of them collide with the
    #: object- or edit-mode bindings for the same letters (S, D, A and E are
    #: all bound elsewhere); see `_keyboard_captured`.
    _FLY_KEYS = {
        Qt.Key_W: (0.0, 0.0, 1.0), Qt.Key_S: (0.0, 0.0, -1.0),
        Qt.Key_D: (1.0, 0.0, 0.0), Qt.Key_A: (-1.0, 0.0, 0.0),
        Qt.Key_Space: (0.0, 1.0, 0.0), Qt.Key_Control: (0.0, -1.0, 0.0),
    }
    #: Roll about the view axis. +1 rolls LEFT (the horizon swings clockwise
    #: on screen), matching every flight sim's Q.
    _ROLL_KEYS = {Qt.Key_Q: 1.0, Qt.Key_E: -1.0}

    def flying(self):
        # type: () -> bool
        return self._fly is not None

    def _scene_scale(self):
        """A length that means "one scene" — flight speeds scale by it, so a
        3 A cell and a 300 A framework feel the same to fly through."""
        radius = 0.0
        for obj in (self.scene.visible_objects() if self.scene else []):
            if obj.structure.n_atoms:
                radius = max(radius, float(obj.structure.bounding_radius()))
        return max(radius, self.camera.distance * 0.5, 1.0) / 6.0

    def start_fly(self, obj_id=None, latched=False):
        # type: (Optional[int], bool) -> None
        """Begin flying. `obj_id` None flies the CAMERA (right-mouse); an id
        flies that molecule instead, which is what shuttle/pilot mode is.

        Both share one model, so the feel is identical and there is only one
        place to tune it. That was the point of the rewrite: the old shuttle
        moved a fixed step per key PRESS, so holding W delivered Qt's
        auto-repeat rhythm — a jump, a pause, then a stutter — which is the
        "choppy" Christian reported.

        `latched` flight survives the right button coming up — that is the
        round-35 double-click mode, where you fly with both hands free until
        a single right click or Esc lands you.
        """
        if self._fly is not None:
            if latched:                   # promote a held flight to latched
                self._fly["latched"] = True
            return
        model = flight.FlightModel(scale=self._scene_scale())
        model.accel = float(self.fly_accel)
        model.damping = float(self.fly_damping)
        model.brake_factor = float(self.fly_brake_factor)
        model.strafe_factor = float(self.fly_strafe_factor)
        model.roll_rate = float(self.fly_roll_rate)
        model.bank_angle = float(self.fly_bank_angle)
        self._fly = {
            "model": model,
            "aim": flight.AimReticle(expo=self.fly_aim_expo),
            "keys": set(),
            "roll_keys": set(),
            "obj_id": obj_id,
            "last": time.monotonic(),
            "released": False,
            "latched": bool(latched),
        }
        self._fly_timer.start()
        self.grabKeyboard()
        # The pointer is CAPTURED, not merely followed: it is hidden, held at
        # the viewport centre and re-seeded after every move, so it can never
        # reach an edge. That is what fixes steering dying against the
        # properties dock on the right and against the top and bottom — the
        # old cursor WRAP could only work where there was screen to wrap to,
        # and a wrap is visible anyway. With the reticle carrying the aim
        # there is nothing the real cursor needs to be doing.
        self.grabMouse()
        self.setCursor(Qt.BlankCursor)
        self._recentre_pointer()

    # ------------------------------------------------------ arming the button
    # The right button carries two meanings and round 35 got the arbitration
    # wrong: flight started on the PRESS, "optimistically", on the theory that
    # a click simply never travels anywhere. It does not work, because taking
    # off CAPTURES the pointer — hides it and parks it at the viewport centre.
    # By the time the button came up, the release position was the centre of
    # the screen and picked nothing, and any hand tremor in between had set
    # `_drag_moved`, so the click was not even recognised as one. The geometry
    # menu (bond length / angle / dihedral) was unreachable.
    #
    # So a press now ARMS and waits. Three ways out, and they cannot collide:
    #   * released quickly -> an ordinary right CLICK, menu if one applies;
    #   * held past `fly_hold_ms`, or dragged past the click slop -> fly;
    #   * double-clicked -> latched flight (`mouseDoubleClickEvent`).
    # That also retires the deferred context menu: nothing is opened on the
    # first click of a double-click any more, because the first click of a
    # double-click is too short to be anything.
    def _arm_fly(self, pos):
        # type: (object) -> None
        self._fly_pending = QPointF(pos.x(), pos.y())
        hold = int(max(float(self.fly_hold_ms), 0.0))
        if hold > 0:
            self._fly_hold_timer.start(hold)

    def _cancel_fly_arm(self):
        self._fly_hold_timer.stop()
        self._fly_pending = None

    def _fly_hold_elapsed(self):
        """The hold threshold passed with the button still down. (A release
        cancels the arm, so reaching here means it never came.)"""
        if self._fly_pending is None or self._fly is not None:
            return
        self._fly_pending = None
        self._begin_held_fly()

    def _begin_held_fly(self):
        self._cancel_fly_arm()
        self.start_fly()
        self.status_message.emit(
            "FLY — W/A/S/D thrust, Space/Ctrl up-down, Q/E roll, Shift boost, "
            "Alt creep; let go to land (double-click to latch)")

    def _recentre_pointer(self):
        """Park the (hidden) OS pointer in the middle of the viewport."""
        centre = self.mapToGlobal(QPoint(self.width() // 2,
                                         self.height() // 2))
        self._fly_anchor = centre
        QCursor.setPos(centre)

    def _fly_tick(self, dt=None):
        """One integration step. Runs at ~60 Hz while flying AND while the
        residual velocity bleeds off after the button comes up — letting go
        mid-glide has to coast, or there is no inertia to speak of.

        `dt` is normally taken from the wall clock; passing it explicitly is
        for tests, which drive the loop far faster than real time and would
        otherwise integrate a few microseconds per call and never observe the
        motion they are checking.
        """
        fly = self._fly
        if fly is None:
            self._fly_timer.stop()
            return
        now = time.monotonic()
        if dt is None:
            # Clamp dt: a stalled frame (a dialog, a big rebuild) must not
            # launch the camera across the scene when the clock catches up.
            dt = min(max(now - fly["last"], 0.0), 0.1)
        fly["last"] = now
        keys = (flight.keys_from_set(fly["keys"], self._FLY_KEYS)
                if not fly["released"] else (0.0, 0.0, 0.0))
        mods = QApplication.keyboardModifiers()
        # Shift boosts, ALT creeps. Ctrl used to creep and is now DESCEND
        # (Christian's call), so it must not also scale the thrust — a key
        # that both moves you and quarters your speed is unusable.
        boost = flight.BOOST_FACTOR if mods & Qt.ShiftModifier else \
            flight.PRECISION_FACTOR if mods & Qt.AltModifier else 1.0
        delta = fly["model"].step(dt, keys, self.camera.basis_rows(), boost)
        if np.any(delta):
            if fly["obj_id"] is None:
                self.camera.fly_move(delta)
            else:
                self._fly_object(fly["obj_id"], delta)
        # STEERING. The reticle is a virtual stick: its offset from centre is
        # a sustained turn RATE, so the ship keeps turning for as long as the
        # mark is out there and only stops when it is brought back. Nothing
        # here is driven by this tick's mouse delta — that is the whole
        # difference from the first cut, which stopped turning the instant
        # the mouse stopped moving.
        short = min(self.width(), self.height())
        defl = fly["aim"].deflection(short) if not fly["released"] \
            else np.zeros(2)
        rate = flight.DEFAULT_TURN_RATE * self.fly_turn_rate \
            * self.camera.rotate_speed
        d_yaw = -float(defl[0]) * rate * dt
        d_pitch = -float(defl[1]) * rate * dt
        # Automatic banking rolls into the turn and HOLDS while the reticle
        # stays out, easing back to level when it comes home.
        roll_dir = sum(self._ROLL_KEYS[k] for k in fly["roll_keys"]) \
            if not fly["released"] else 0.0
        if roll_dir:
            fly["model"].step_roll(dt, roll_dir, boost)
        fly["model"].step_bank(dt, float(defl[0]))
        if d_yaw or d_pitch or roll_dir or abs(fly["model"].bank) > 1e-6:
            self._fly_turn(d_yaw, d_pitch)
        if fly["released"] and not fly["model"].moving:
            self._end_fly()
        self.update()

    def _end_fly(self):
        """Tear down a flight session and level the horizon.

        Levelling is not a preference: the orbit camera you land back into is
        a turntable (yaw + pitch only), so a rolled pose has no representation
        there at all. Leaving the roll on would mean the next orbit silently
        snapped it away, which looks like a glitch.
        """
        if self._fly is None:
            return
        rolled = abs(self._fly["model"].roll) > 1e-9
        self._fly["model"].level()
        self._fly = None
        self._fly_timer.stop()
        self.releaseKeyboard()
        self.releaseMouse()
        self.unsetCursor()
        if rolled:
            self.camera.fly_look(0.0, 0.0, roll=0.0)
        self.update()

    def _fly_object(self, obj_id, delta):
        """Shuttle mode: the MOLECULE moves and the camera rides along."""
        obj = self.scene.get(obj_id) if self.scene else None
        if obj is None:
            self.stop_shuttle()
            return
        for k in range(obj.structure.n_frames):
            obj.structure.frames[k] = obj.structure.frames[k] + delta
        obj.origin = obj.origin + delta
        self.camera.center = obj.origin.copy()
        self.refresh_geometry()

    def _fly_eye(self):
        """Where the camera actually is — `center` is only the orbit pivot."""
        r = quat_to_mat3(self.camera.rotation)
        return self.camera.center + r.T @ np.array(
            [0.0, 0.0, self.camera.distance])

    def _fly_turn(self, d_yaw, d_pitch):
        """Turn while flying, by RADIANS (the aim reticle drives this).

        In shuttle mode the SHIP turns rather than the camera, so the same
        rotation has to be re-expressed as a rigid rotation of the molecule —
        but the yaw/pitch/roll decision is still the camera's, which keeps the
        construction in exactly one place.
        """
        fly = self._fly
        if fly is None:
            return
        roll = fly["model"].roll
        if fly["obj_id"] is None:
            # KEEP THE EYE WHERE IT IS. The camera is an orbit rig — the eye
            # sits `distance` behind `center` — so changing only the rotation
            # swings the eye around the pivot on an arc. In flight that reads
            # as looking up bodily lifting you, which is Christian's "moving
            # the cursor up and down moves the camera by a lot". A pilot's
            # head turns; it does not orbit a point in front of them. So the
            # eye is captured first and `center` is rebuilt behind it.
            eye = self._fly_eye()
            self.camera.fly_look(d_yaw, d_pitch, roll=roll)
            r = quat_to_mat3(self.camera.rotation)
            self.camera.center = eye - r.T @ np.array(
                [0.0, 0.0, self.camera.distance])
            self.update()
            return
        before = quat_to_mat3(self.camera.rotation)
        self.camera.fly_look(d_yaw, d_pitch, roll=roll)
        after = quat_to_mat3(self.camera.rotation)
        # The molecule takes the rotation the camera just made, about its own
        # origin, and the camera is put back — the cockpit view is unchanged
        # relative to the ship, which is what makes it read as piloting.
        rot = before.T @ after
        obj = self.scene.get(fly["obj_id"]) if self.scene else None
        if obj is not None:
            for k in range(obj.structure.n_frames):
                obj.structure.frames[k] = rotations.rotate_points_about(
                    obj.structure.frames[k], rot.T, obj.origin)
            obj.orientation = quat_mul(quat_from_mat3(rot.T), obj.orientation)
            self.refresh_geometry()
        self.update()

    def stop_fly(self, coast=True):
        """Button up. `coast=True` keeps integrating until the drift dies —
        stopping dead the instant the button lifts would throw away the
        inertia the whole model exists to provide."""
        fly = self._fly
        if fly is None:
            return
        fly["keys"].clear()
        fly["roll_keys"].clear()
        fly["released"] = True
        fly["latched"] = False
        fly["aim"].recentre()
        if not coast:
            fly["model"].stop()
            self._end_fly()

    # ---------------------------------------------------------- shuttle mode
    def _shuttle_eye(self):
        r = quat_to_mat3(self.camera.rotation)
        return self.camera.center + r.T @ np.array([0.0, 0.0,
                                                    self.camera.distance])

    def _shuttle_hidden(self, coords):
        """Mask of atoms too close to the cockpit to draw (they would clip
        through the near plane and fill the screen)."""
        if self._shuttle is None:
            return None
        d = np.linalg.norm(np.asarray(coords) - self._shuttle_eye(), axis=1)
        return d < self._shuttle["clip"]

    def start_shuttle(self, obj_id):
        # type: (int) -> None
        """UE5-style pilot, for whole molecules: the camera snaps into the
        molecule's origin and WASD flies it around. Turning the ship turns
        the view with it, so it reads like a cockpit. Esc lands (keeping the
        new position)."""
        if self._shuttle is not None or self.scene is None:
            return
        obj = self.scene.get(obj_id)
        if obj is None:
            self.status_message.emit("Select a molecule to shuttle")
            return
        cam = self.camera
        self._begin_model_edit()
        self._shuttle = {
            "obj_id": obj.id,
            "saved": (cam.center.copy(), float(cam.distance),
                      cam.rotation.copy(), bool(cam.orthographic)),
            "clip": max(1.2, obj.structure.bounding_radius() * 0.25),
        }
        cam.orthographic = False
        cam.auto_ortho = False
        cam.center = obj.origin.copy()
        cam.distance = 0.35
        # Shuttle is FLIGHT with the molecule as the airframe: same model,
        # same acceleration, same coast — only the thing being moved differs.
        self.start_fly(obj_id=obj.id)
        self.status_message.emit(
            "SHUTTLE {} — W/A/S/D thrust, Space/Ctrl up-down, Q/E roll "
            "(Shift boost, Alt creep), drag or scroll to steer, Esc to "
            "land".format(obj.name))
        self.refresh_geometry()

    # (`_shuttle_apply` is gone: translation and rotation both go through the
    # shared flight model now — `_fly_object` and `_fly_look` — so the
    # shuttle and the right-mouse fly cannot drift apart in feel.)

    def _shuttle_key(self, key, down=True):
        """Route a flight key into the shared model.

        Holding a key now HOLDS THRUST rather than emitting one hop per
        auto-repeat, which is the whole difference between "moved in a choppy
        way" and flying.
        """
        if self._fly is None:
            return False
        if key in self._FLY_KEYS:
            bucket = self._fly["keys"]
        elif key in self._ROLL_KEYS:
            bucket = self._fly["roll_keys"]
        else:
            return False
        if down:
            bucket.add(key)
            self._fly["released"] = False
        else:
            bucket.discard(key)
        return True

    def stop_shuttle(self, restore_camera=True):
        sh = self._shuttle
        if sh is None:
            return
        self._shuttle = None
        self.stop_fly(coast=False)
        self.releaseKeyboard()
        self.releaseMouse()
        if restore_camera:
            cam = self.camera
            cam.center, cam.distance, cam.rotation, cam.orthographic = \
                sh["saved"]
        self.status_message.emit("Shuttle landed — position kept")
        self.edit_committed.emit()
        self.refresh_geometry()

    # -------------------------------------------------------------- edit mode
    def toggle_mode(self, obj_id=None):
        # type: (Optional[int]) -> None
        """Tab: object <-> edit mode (Blender). Edit mode scopes every pick
        and every chemistry edit to ONE molecule. With nothing to edit it
        starts a NEW empty molecule, so a structure can be drawn from
        scratch on an empty scene."""
        if self.mode == MODE_EDIT:
            self.set_mode(MODE_OBJECT)
            return
        target = obj_id
        if target is None and self.selection:
            target = self.selection[0][0]
        if target is None or self.scene is None \
                or self.scene.get(target) is None:
            if self.on_new_molecule is None:
                return
            new_id = self.on_new_molecule()
            if new_id is None:
                return
            target = new_id
        self.set_mode(MODE_EDIT, target)

    def set_mode(self, mode, obj_id=None):
        # type: (str, Optional[int]) -> None
        if self.modal_active():
            self.cancel_modes()
        if mode == MODE_EDIT:
            obj = self.scene.get(obj_id) if self.scene else None
            if obj is None:
                return
            self.mode = MODE_EDIT
            self.edit_obj_id = obj.id
            # keep only this object's atoms selected (Blender scoping)
            self.set_selection([p for p in self.selection if p[0] == obj.id])
            self.status_message.emit(
                "EDIT MODE — {}   |   draw: click an atom to make it {}, "
                "type a symbol + Enter to change element, digits set bond "
                "order, Tab to leave".format(obj.name, self.draw_element))
        else:
            self.mode = MODE_OBJECT
            self.edit_obj_id = None
            # Disarm the draw tool on the way OUT. It used to survive in
            # object mode (where it does nothing and the toolbar reports
            # "select"), so Tabbing back into edit mode came up with an armed
            # tool nobody asked for — which is why the periodic table
            # "sometimes" failed to appear. The flag and the toolbar must not
            # be allowed to disagree.
            self.draw_tool_active = False
            if self.on_tool_changed is not None:
                self.on_tool_changed(False)
            self.status_message.emit("Object mode")
        if self.on_mode_changed is not None:
            self.on_mode_changed(self.mode)
        self.refresh_geometry()

    def edit_object(self):
        if self.mode != MODE_EDIT or self.scene is None:
            return None
        return self.scene.get(self.edit_obj_id)

    def set_draw_tool(self, on):
        # type: (bool) -> None
        """E / toolbar: arm the draw tool. Off, edit-mode clicks only select
        (and typing an element still converts the selection)."""
        on = bool(on) and self.mode == MODE_EDIT
        if on == self.draw_tool_active:
            return
        self.draw_tool_active = on
        self.status_message.emit(
            "Draw tool ON — click an atom to change it, click empty space or "
            "drag from an atom to add {}".format(self.draw_element)
            if on else "Draw tool off — clicks select")
        if self.on_tool_changed is not None:
            self.on_tool_changed(on)
        self.update()

    def set_measure_tool(self, on):
        # type: (bool) -> None
        """Arm the measurement tool: clicks collect up to four atoms and the
        distance / angle / dihedral is drawn IN THE VIEWPORT.

        It reads out over the molecule rather than in the status bar, where
        it was invisible behind every transient message. Picks are its own
        list — measuring must not disturb the selection.
        """
        on = bool(on)
        if on == self.measure_active:
            return
        self.measure_active = on
        self._measure_picks = []
        self.status_message.emit(
            "Measure: click 2 atoms for a distance, 3 for an angle, 4 for a "
            "dihedral (click again to unpick, Esc to finish)"
            if on else "Measure tool off")
        if self.on_measure_changed is not None:
            self.on_measure_changed(on)
        self.update()

    def _measure_click(self, pos):
        hit = self._pick_at(pos)
        if hit is None:
            self._measure_picks = []
            self.update()
            return
        pick = self._atom_map[hit]
        if pick in self._measure_picks:
            self._measure_picks.remove(pick)      # click again to unpick
        elif len(self._measure_picks) >= 4:
            self._measure_picks = [pick]          # start a new measurement
        else:
            self._measure_picks.append(pick)
        self.update()

    def measure_text(self):
        # type: () -> str
        if self.scene is None or not self._measure_picks:
            return ""
        picks = []
        for p in self._measure_picks:
            c = self.scene.pick_coords(p)
            if c is not None:
                picks.append((self.scene.pick_label(p), c))
        return measure.describe_picks(picks)

    def set_meta_template(self, meta):
        """Arm a meta atom as the thing the draw tool places.

        Picking a real element from the chart clears it again — the two are
        alternative answers to the same question ("what am I drawing?"), so
        they must not both be live at once.
        """
        from ..core import meta as meta_mod
        self.meta_template = meta
        self.draw_element = meta_mod.META_SYMBOL
        if self.on_element_changed is not None:
            self.on_element_changed(self.draw_element)
        self.update()

    def set_draw_element(self, symbol):
        # type: (str) -> None
        """Set the draw element WITHOUT touching the selection (the toolbar
        and dialogs use this; typing/the periodic table use apply_element)."""
        resolved = elements.symbol_from_text(symbol)
        if not resolved:
            self.status_message.emit("Unknown element: {!r}".format(symbol))
            return
        self.meta_template = None        # a real element disarms the meta one
        self.draw_element = resolved
        if self.on_element_changed is not None:
            self.on_element_changed(resolved)
        self.status_message.emit("Draw element: {}".format(resolved))
        self.update()

    def apply_element(self, symbol):
        # type: (str) -> None
        """Set the draw element and, if atoms of the edited molecule are
        selected, convert them right away.

        The one path shared by typing + Enter, the periodic-table panel and
        the Change element dialog — they must not drift apart.
        """
        symbol = elements.symbol_from_text(symbol)
        if not symbol:
            self.update()
            return
        self.meta_template = None        # a real element disarms the meta one
        self.draw_element = symbol
        if self.on_element_changed is not None:
            self.on_element_changed(symbol)
        obj = self.edit_object()
        rows = [i for o, i in self.selection if obj is not None and o == obj.id]
        if obj is not None and rows:
            self._begin_edit()
            added, removed = edits.set_element_adjusted(
                obj.structure, rows, symbol, adjust_h=self.adjust_h)
            # Converted atoms are DESELECTED: they are already the element
            # that was asked for, so keeping them selected turns the next
            # element pick into a second, unintended conversion of the same
            # atoms (Christian's report — draw an Li, pick Cd, lose the Li).
            self.set_selection([])
            self.status_message.emit(
                "{} atom(s) -> {}{}   (draw element is now {})".format(
                    len(rows), symbol, _h_note(added, removed), symbol))
            self.edit_committed.emit()
        else:
            self.status_message.emit("Draw element: {}".format(symbol))
        self.refresh_geometry()

    def _begin_edit(self):
        if self.on_edit_begin is not None:
            self.on_edit_begin()

    def _draw_click(self, pos, hit):
        """Draw tool: on an atom -> convert it to the draw element; on empty
        space -> add a new atom there (view-plane depth through the edited
        molecule), hydrogens re-dressed either way."""
        obj = self.edit_object()
        if obj is None:
            return
        if hit is not None:
            obj_id, idx = self._atom_map[hit]
            if obj_id != obj.id:
                return
            if obj.structure.symbols[idx] == self.draw_element:
                self.set_selection([(obj_id, idx)])
                return
            self._begin_edit()
            added, removed = edits.set_element_adjusted(
                obj.structure, [idx], self.draw_element,
                adjust_h=self.adjust_h)
            self.status_message.emit("{} -> {}{}".format(
                self.scene.pick_label((obj_id, idx)), self.draw_element,
                _h_note(added, removed)))
            self.set_selection([(obj_id, idx)])
        else:
            origin, direction = self._ray_at(pos)
            depth = obj.origin if obj.structure.n_atoms else np.zeros(3)
            p = manipulate.ray_plane(origin, direction, depth,
                                     self._view_dir())
            if p is None:
                return
            self._begin_edit()
            edits.add_atom(obj.structure, self.draw_element, p)
            new_idx = obj.structure.n_atoms - 1
            added = removed = 0
            if self.meta_template is not None:
                # CLICK-to-place must attach the meta spec too. Only the drag
                # path did, so clicking left a bare Xx with no geometry and
                # no glow — which looked like the glow was broken.
                from ..core import meta as meta_mod
                meta_mod.set_meta(obj.structure, new_idx, self.meta_template)
                added = meta_mod.dress_with_hydrogens(
                    obj.structure, new_idx, self.meta_template)
            elif self.adjust_h:
                added, removed = edits.adjust_hydrogens(obj.structure,
                                                        [new_idx])
            self.status_message.emit("Added {}{}".format(
                self.draw_element, _h_note(added, removed)))
            self.set_selection([])
        self.edit_committed.emit()
        self.refresh_geometry()

    def set_bond_order_selected(self, order):
        # type: (int) -> None
        """Digits in edit/object mode: set the order of the bond between the
        two selected atoms (0 removes it)."""
        sel = self.selection
        if len(sel) != 2 or sel[0][0] != sel[1][0]:
            self.status_message.emit(
                "Select exactly 2 atoms of one molecule to set a bond order")
            return
        obj = self.scene.get(sel[0][0])
        if obj is None:
            return
        self._begin_edit()
        if order <= 0:
            edits.remove_bond(obj.structure, sel[0][1], sel[1][1])
            note = "Bond removed"
        else:
            edits.add_bond(obj.structure, sel[0][1], sel[1][1], order)
            note = "Bond order {}".format(order)
        if self.adjust_h:                 # free valence changed -> re-dress H
            added, removed = edits.adjust_hydrogens(
                obj.structure, [sel[0][1], sel[1][1]])
            note += _h_note(added, removed)
        self.status_message.emit(note)
        self.edit_committed.emit()
        self.refresh_geometry()

    # ------------------------------------------------------------ align keys
    def arm_align_keys(self, kind):
        # type: (str) -> None
        """A pressed with a 2-atom ('axis') or 3+-atom ('plane') selection.

        This is a PREVIEW modal, the same contract G and R already have: an
        axis key applies the alignment and leaves it on screen, another axis
        key replaces it, LEFT-CLICK confirms and right-click or Esc reverts.
        It used to commit and end on the first axis key, so you could not
        press X, look at it, and change your mind — reported twice.
        """
        if self.modal_active():
            return
        self._align_wait = kind
        self._align_previewed = None       # which axis is on screen, if any
        self.grabKeyboard()
        self.update()          # the prompt is painted, not just announced

    def _end_align_wait(self, msg="", cancel=False):
        was_previewing = self._align_previewed is not None
        self._align_wait = None
        self._align_previewed = None
        self.releaseKeyboard()
        self.releaseMouse()
        self.update()
        if cancel and was_previewing and self.on_align_cancel is not None:
            self.on_align_cancel()
        if msg:
            self.status_message.emit(msg)

    def _confirm_align(self):
        """Left-click with a preview showing: keep it."""
        if self._align_previewed is None:
            self.status_message.emit(
                "Press X, Y or Z first — there is nothing to confirm yet")
            return
        self._align_wait = None
        self._align_previewed = None
        self.releaseKeyboard()
        self.releaseMouse()
        self.update()
        if self.on_align_confirm is not None:
            self.on_align_confirm()

    # --------------------------------------------------------------- helpers
    def _view_dir(self):
        # type: () -> np.ndarray
        return quat_to_mat3(self.camera.rotation).T @ np.array([0.0, 0.0, -1.0])

    def _selection_pivot(self):
        # type: () -> Optional[np.ndarray]
        pts = [self.scene.pick_coords(p) for p in self.selection]
        pts = [p for p in pts if p is not None]
        if not pts:
            return None
        return np.mean(pts, axis=0)

    def _selection_frame(self):
        """Local frame (3x3, columns = axes) of the first selected atom's
        object — what double-pressed axis locks refer to."""
        if self.selection and self.scene is not None:
            obj = self.scene.get(self.selection[0][0])
            if obj is not None:
                return obj.local_axes()
        return np.eye(3)

    def _selection_rows(self):
        """{obj_id: sorted local indices} for the current selection."""
        rows = {}
        for obj_id in {p[0] for p in self.selection}:
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            rr = sorted({i for o, i in self.selection if o == obj_id
                         and 0 <= i < obj.structure.n_atoms})
            if rr:
                rows[obj_id] = rr
        return rows

    def _snapshot_rows(self, rows):
        snap = {}
        for obj_id, rr in rows.items():
            obj = self.scene.get(obj_id)
            snap[obj_id] = (rr, [f[rr].copy() for f in obj.structure.frames])
        return snap

    def _whole_object_selected(self, obj_id, rows):
        obj = self.scene.get(obj_id)
        return obj is not None and len(rows) == obj.structure.n_atoms

    def _ray_at(self, qpos):
        w, h = max(self.width(), 1), max(self.height(), 1)
        view = self.camera.view_matrix()
        proj = self.camera.projection_matrix(w, h)
        return picking.ray_from_screen(qpos.x(), qpos.y(), w, h, view, proj)

    def _camera_frame(self):
        """Eye position and view/projection matrices, CACHED on the camera.

        None of these depends on what is being drawn, but they were being
        rebuilt per PRIMITIVE: `_eye_position` runs `quat_to_mat3` and
        `_project`/`_segment_screen` rebuild both matrices, and the symmetry
        overlay calls them through `_cued_pen` once per line segment — around
        400 times a frame on a Pbca cell. That is what made switching ghosts
        or symmetry elements on drop the framerate; it is not the drawing.

        Keyed on the camera state rather than cleared per frame, so every
        caller is safe including the picking paths that run outside paintGL.
        """
        cam = self.camera
        w, h = max(self.width(), 1), max(self.height(), 1)
        key = (cam.rotation.tobytes(), cam.center.tobytes(),
               float(cam.distance), bool(cam.orthographic), w, h)
        if self._cam_key != key:
            r = quat_to_mat3(cam.rotation)
            self._cam_frame = {
                "eye": cam.center + r.T @ np.array([0.0, 0.0, cam.distance]),
                "view": cam.view_matrix().astype(float),
                "proj": cam.projection_matrix(w, h).astype(float),
                "w": w, "h": h,
            }
            self._cam_key = key
        return self._cam_frame

    def _project(self, world_pts):
        f = self._camera_frame()
        return selection2d.project_points(
            np.asarray(world_pts, dtype=float).reshape(-1, 3),
            f["view"], f["proj"], f["w"], f["h"])

    def _segment_screen(self, a, b):
        """Project a world segment with NEAR-PLANE CLIPPING: the part in
        front of the camera still draws when the other end is behind it.
        (The old front.all() skip silently hid every long guide line in
        perspective.) Returns ((x0,y0),(x1,y1)) or None."""
        f = self._camera_frame()
        w, h, view, proj = f["w"], f["h"], f["view"], f["proj"]
        va = view @ np.append(np.asarray(a, dtype=float), 1.0)
        vb = view @ np.append(np.asarray(b, dtype=float), 1.0)
        z_clip = -max(self.camera.distance * 0.01, 0.01) * 1.5
        za, zb = va[2], vb[2]
        if za > z_clip and zb > z_clip:
            return None                      # fully behind the camera
        if za > z_clip:
            t = (z_clip - zb) / (za - zb)
            va = vb + (va - vb) * t
        elif zb > z_clip:
            t = (z_clip - za) / (zb - za)
            vb = va + (vb - va) * t
        out = []
        for v in (va, vb):
            c = proj @ v
            ndc = c[:3] / c[3] if abs(c[3]) > 1e-12 else c[:3]
            out.append(((ndc[0] + 1.0) * 0.5 * w,
                        (1.0 - ndc[1]) * 0.5 * h))
        return out[0], out[1]

    def _begin_model_edit(self):
        if self.on_model_edit_begin is not None:
            self.on_model_edit_begin()

    def _cancel_model_edit(self):
        if self.on_model_edit_cancel is not None:
            self.on_model_edit_cancel()

    # ------------------------------------------------------------------ grab
    def start_grab(self):
        if self._grab is not None or self._rotate is not None:
            return
        if self.scene is None:
            return
        # With the origin handle picked up, G moves the ORIGIN through exactly
        # the same modal (axis locks, local frames, numeric entry, precision).
        if self._origin_active:
            obj = self.edit_object()
            if obj is None:
                return
            state = manipulate.GrabState(obj.origin.copy(), self._view_dir(),
                                         frame=obj.local_axes())
            state.precision_factor = self.precision_factor
            self._begin_model_edit()
            self._grab = {"state": state, "snap": {},
                          "origin_target": obj.id, "base": obj.origin.copy()}
            self.grabKeyboard()
            self._apply_grab()
            return
        if not self.selection:
            self.status_message.emit("Nothing selected to move (G)")
            return
        rows = self._selection_rows()
        if not rows:
            return
        pivot = self._selection_pivot()
        state = manipulate.GrabState(pivot, self._view_dir(),
                                     frame=self._selection_frame())
        state.precision_factor = self.precision_factor
        self._begin_model_edit()
        self._grab = {"state": state, "snap": self._snapshot_rows(rows)}
        self.grabKeyboard()
        self.grabMouse()   # keep receiving moves past the viewport edge
        self._apply_grab()

    def _apply_grab(self):
        g = self._grab
        if g is None:
            return
        delta = g["state"].delta()
        if "origin_target" in g:
            obj = self.scene.get(g["origin_target"])
            if obj is not None:
                obj.origin = g["base"] + delta
            self.status_message.emit("Origin " + g["state"].status_text())
            self.update()
            return
        for obj_id, (rr, frame_rows) in g["snap"].items():
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            for k, saved in enumerate(frame_rows):
                obj.structure.frames[k][rr] = saved + delta
        self.status_message.emit(g["state"].status_text())
        self.refresh_geometry()

    def _finish_grab(self, commit):
        g = self._grab
        if g is None:
            return
        self._grab = None
        self.releaseKeyboard()
        self.releaseMouse()
        if "origin_target" in g:
            obj = self.scene.get(g["origin_target"])
            if obj is not None and not commit:
                obj.origin = g["base"]
                self._cancel_model_edit()
            self.status_message.emit(
                "Origin moved" if commit else "Origin move cancelled")
            self.update()
            return
        if not commit:
            for obj_id, (rr, frame_rows) in g["snap"].items():
                obj = self.scene.get(obj_id)
                if obj is None:
                    continue
                for k, saved in enumerate(frame_rows):
                    obj.structure.frames[k][rr] = saved
            self._cancel_model_edit()
            self.status_message.emit("Move cancelled")
        else:
            d = g["state"].delta()
            for obj_id, (rr, _f) in g["snap"].items():
                obj = self.scene.get(obj_id)
                if obj is None:
                    continue
                if self._whole_object_selected(obj_id, rr):
                    obj.origin = obj.origin + d   # rigid move carries origin
                # NOTE: bonds are deliberately NOT re-perceived here (round 6)
                # — pulling an atom out of a molecule must not silently break
                # its bonds. Ctrl+P re-perceives on request.
            self.last_transform = {"kind": "move", "delta": d.copy()}
            self.transform_serial += 1
            self.status_message.emit(
                "Moved by ({:+.3f}, {:+.3f}, {:+.3f}) A   (Shift+R repeats)"
                .format(*d))
            self.edit_committed.emit()
        self.refresh_geometry()

    # ------------------------------------------- internal coordinates (N-body)
    def internal_picks(self):
        """The selection as (obj_id, [indices in CLICK ORDER]), or None.

        Order is the whole point and cannot be sorted away: the middle atom of
        an angle is the VERTEX and the two inner atoms of a torsion are its
        axis, so i-j-k and j-i-k are different questions. `self.selection` is
        already kept in pick order, which is also what the measurement readout
        relies on.

        Everything must be in ONE object. Across two molecules a "bond length"
        is really a docking distance, which is what A (align) is for, and an
        angle spanning three molecules has no chemical meaning at all.
        """
        picks = list(self.selection)
        if not picks or self.scene is None:
            return None
        obj_id = picks[0][0]
        if any(o != obj_id for o, _i in picks):
            return None
        obj = self.scene.get(obj_id)
        if obj is None:
            return None
        rows = [i for _o, i in picks]
        if any(not (0 <= i < obj.structure.n_atoms) for i in rows):
            return None
        if len(set(rows)) != len(rows):
            return None
        return obj_id, rows

    def context_entries(self):
        """The right-click menu for the current selection, as ChoicePopup
        options. Split out from the popup so the contents are testable.

        Only what APPLIES is listed. A context menu whose items are mostly
        greyed out makes the user read the whole list to find the one live
        entry; a short menu that changes with the selection can be read at a
        glance, which is the entire point of putting it under the cursor.
        """
        entries = []
        found = self.internal_picks()
        if found is not None:
            obj_id, rows = found
            kind = internal.kind_for_count(len(rows))
            if kind is not None:
                obj = self.scene.get(obj_id)
                value = internal.current_value(kind, obj.structure.coords,
                                               rows)
                names = " - ".join(self.scene.pick_label((obj_id, i))
                                   for i in rows)
                entries.append((
                    "internal:" + kind,
                    "{}   {:.3f} {}".format(internal.label_for(kind), value,
                                            internal.unit_for(kind)),
                    "Set {} for {} — drag or type an exact value. The rest "
                    "of the molecule follows.".format(
                        internal.label_for(kind).lower(), names)))
            self._twist_entry(obj_id, rows, entries)
        if self.selection:
            entries.append(("op:hide_selected", "Hide  (H)",
                            "Hide the selected atoms; Alt+H shows them again"))
            entries.append(("op:delete_selected", "Delete  (Del)",
                            "Delete the selected atoms and their terminal "
                            "hydrogens"))
        return entries

    def _twist_entry(self, obj_id, rows, entries):
        """Offer the rotor, if this selection has one.

        It goes UNDER the length/angle/dihedral entry, which is chosen by the
        pick count and is therefore the more specific answer to "what did you
        select". The twist works from any number of picks, so on a two-atom
        selection it sits below "Bond length" and on a seven-atom one it is
        the only geometry entry there is.
        """
        obj = self.scene.get(obj_id) if self.scene else None
        if obj is None:
            return
        s = obj.structure
        split = internal.torsion_split(s.n_atoms, s.bonds, rows)
        if split is None:
            return
        moving, anchor, pivot = split
        about = "{} - {}".format(self.scene.pick_label((obj_id, anchor)),
                                 self.scene.pick_label((obj_id, pivot)))
        entries.append((
            "internal:" + internal.TWIST,
            "Twist about {}   (T)".format(about),
            "Spin the {}-atom group about the {} bond axis — drag, scroll or "
            "type an angle. Everything else stays exactly where it is."
            .format(len(moving), about)))

    def open_context_menu(self, pos):
        """Right-CLICK over the selection: whatever fits what is picked.

        The geometry edit at the top is chosen by selection SIZE — two atoms a
        bond length, three an angle, four a torsion — with the current value
        shown, so the menu doubles as a readout of what you are about to
        change.
        """
        if not self.selection:
            return
        # It has to be over the SELECTION, not merely over something: a
        # right-click anywhere else is the fly gesture, and stealing it would
        # make flying feel like it randomly opened menus.
        hit = self._pick_at(pos)
        if hit is None or self._atom_map[hit] not in self.selection:
            return
        entries = self.context_entries()
        if not entries:
            return
        if internal.kind_for_count(len(self.selection)) is None:
            self.status_message.emit(
                "{} atoms selected — the geometry edits need 2 (length), "
                "3 (angle) or 4 (dihedral) in ONE molecule".format(
                    len(self.selection)))
        popup = ChoicePopup("Selection", entries, self)
        popup.chosen.connect(self._run_context_action)
        self._context_popup = popup       # keep a reference or it is collected
        popup.popup_at_cursor()

    def _run_context_action(self, key):
        """Menu keys are namespaced: `internal:` starts one of our own modals,
        `op:` hands off to the operator registry through the app, so the menu
        and F3 can never drift apart on what an entry actually does."""
        if key.startswith("internal:"):
            self.start_internal(key.split(":", 1)[1])
        elif key.startswith("op:") and self.on_context_op is not None:
            self.on_context_op(key.split(":", 1)[1])

    def start_internal(self, kind):
        # type: (str) -> None
        """Begin the bond-length / angle / dihedral modal.

        The fragment split happens ONCE here, not per update: which atoms
        follow is a property of the connectivity, and re-deriving it while the
        user drags would let the moving set change under them if a stretched
        bond ever fell outside a perception cutoff.
        """
        if self.modal_active() or self.scene is None:
            return
        if kind == internal.TWIST:
            self.start_twist()
            return
        found = self.internal_picks()
        if found is None:
            self.status_message.emit(
                "Select 2, 3 or 4 atoms of one molecule first")
            return
        obj_id, rows = found
        wanted = {internal.DISTANCE: 2, internal.ANGLE: 3,
                  internal.DIHEDRAL: 4}.get(kind)
        if wanted is None or len(rows) != wanted:
            self.status_message.emit(
                "{} needs exactly {} atoms".format(internal.label_for(kind),
                                                   wanted))
            return
        obj = self.scene.get(obj_id)
        s = obj.structure
        moving, blocked = internal.split_for(kind, s.n_atoms, s.bonds, rows)
        moving = sorted(moving)
        start = internal.current_value(kind, s.coords, rows)
        unit = internal.unit_for(kind)
        # Drag sensitivity: a full window's width should cover a useful range
        # — about 4 A of bond, or a bit over half a turn of angle.
        span = 4.0 if kind == internal.DISTANCE else 240.0
        state = manipulate.ScalarState(
            start, span / max(self.width(), 1),
            minimum=0.05 if kind == internal.DISTANCE else None,
            maximum=180.0 if kind == internal.ANGLE else None,
            unit=unit, label=internal.label_for(kind))
        self._begin_model_edit()
        self._internal = {
            "kind": kind, "obj_id": obj_id, "picks": rows, "rows": moving,
            "state": state, "blocked": blocked,
            "frames": [f[moving].copy() for f in s.frames],
        }
        self.grabKeyboard()
        self.grabMouse()
        if blocked:
            self.status_message.emit(
                "No clean split (ring, or the atoms are not simply bonded) — "
                "only the last atom moves")
        self._apply_internal()

    def start_twist(self):
        """Spin a terminal group about the bond that holds it on.

        The rotor a methyl needs, and the one internal coordinate the existing
        modal could not express without four picks in the right order: here
        the SELECTION says which group, `internal.torsion_split` works out the
        axis, and the whole group turns rigidly about it.

        Deliberately NOT an axis lock inside R. R rotates the selection about
        the object origin; this rotates a fragment the selection only points
        AT, about an axis that belongs to the molecule rather than to the
        object or the world. Pressing X twice in R cycles to the OBJECT's
        local frame, which a C-R bond is no part of.
        """
        if self.modal_active() or self.scene is None:
            return
        found = self.internal_picks()
        if found is None:
            self.status_message.emit(
                "Select atoms of ONE molecule to twist")
            return
        obj_id, rows = found
        obj = self.scene.get(obj_id)
        s = obj.structure
        split = internal.torsion_split(s.n_atoms, s.bonds, rows)
        if split is None:
            self.status_message.emit(
                "No single bond frees that selection — pick a terminal group "
                "(a methyl, an OH, a substituent). A ring atom or a whole "
                "molecule has no rotor.")
            return
        moving, anchor, pivot = split
        moving = sorted(moving)
        about = "{} - {}".format(self.scene.pick_label((obj_id, anchor)),
                                 self.scene.pick_label((obj_id, pivot)))
        # A full turn per window width: the useful range of a rotor IS 360
        # degrees, unlike a bond length where most of the travel is nonsense.
        state = manipulate.ScalarState(
            0.0, 360.0 / max(self.width(), 1), unit=internal.unit_for(
                internal.TWIST), label=internal.label_for(internal.TWIST))
        state.show_start = False         # a relative angle starts at 0 always
        self._begin_model_edit()
        self._internal = {
            "kind": internal.TWIST, "obj_id": obj_id,
            "picks": [anchor, pivot], "rows": moving, "state": state,
            "blocked": False, "about": about,
            "frames": [f[moving].copy() for f in s.frames],
        }
        self.grabKeyboard()
        self.grabMouse()
        self._apply_internal()

    def _apply_internal(self):
        """Re-derive from the SNAPSHOT every update, never cumulatively.

        Applied to every frame independently, each using its own geometry, so
        a trajectory keeps the requested value throughout instead of inheriting
        one frame's rotation.
        """
        it = self._internal
        if it is None:
            return
        obj = self.scene.get(it["obj_id"]) if self.scene else None
        if obj is None:
            self._internal = None
            return
        target = it["state"].value()
        rows = it["rows"]
        for k, saved in enumerate(it["frames"]):
            if k >= obj.structure.n_frames:
                break
            coords = obj.structure.frames[k].copy()
            coords[rows] = saved
            obj.structure.frames[k] = internal.apply(
                it["kind"], coords, rows, it["picks"], target)
        self.status_message.emit(it["state"].status_text())
        self.refresh_geometry()

    def _finish_internal(self, commit):
        it = self._internal
        if it is None:
            return
        self._internal = None
        self.releaseKeyboard()
        self.releaseMouse()
        obj = self.scene.get(it["obj_id"]) if self.scene else None
        if not commit:
            if obj is not None:
                for k, saved in enumerate(it["frames"]):
                    if k < obj.structure.n_frames:
                        obj.structure.frames[k][it["rows"]] = saved
            self._cancel_model_edit()
            self.status_message.emit("{} cancelled".format(
                internal.label_for(it["kind"])))
        else:
            # Bonds are NOT re-perceived, exactly as for G and R: the point of
            # this operation is to change a length without the connectivity
            # deciding it has changed too.
            self.status_message.emit("{} set to {:.3f} {}".format(
                internal.label_for(it["kind"]), it["state"].value(),
                internal.unit_for(it["kind"])))
            self.edit_committed.emit()
        self.refresh_geometry()

    # ---------------------------------------------------------------- rotate
    def _rotation_pivot(self, rows):
        """R rotates about the OBJECT ORIGIN (a lock to X spins about the
        X-parallel THROUGH the molecule, not the world X line — Christian's
        spec); several objects -> mean of their origins."""
        origins = [self.scene.get(i).origin for i in rows
                   if self.scene.get(i) is not None]
        if not origins:
            return self._selection_pivot()
        return np.mean(origins, axis=0)

    def start_rotate(self):
        if self._grab is not None or self._rotate is not None:
            return
        if self.scene is None:
            return
        if self._origin_active:            # R spins the origin's local frame
            obj = self.edit_object()
            if obj is None:
                return
            state = manipulate.RotateState(obj.origin.copy(), self._view_dir(),
                                           frame=obj.local_axes())
            state.precision_factor = self.precision_factor
            self._begin_model_edit()
            self._rotate = {"state": state, "snap": {},
                            "origin_target": obj.id,
                            "base": obj.orientation.copy()}
            self.grabKeyboard()
            self._apply_rotate()
            return
        if not self.selection:
            self.status_message.emit("Nothing selected to rotate (R)")
            return
        rows = self._selection_rows()
        if not rows:
            return
        pivot = self._rotation_pivot(rows)
        state = manipulate.RotateState(pivot, self._view_dir(),
                                       frame=self._selection_frame())
        state.precision_factor = self.precision_factor
        self._begin_model_edit()
        self._rotate = {"state": state, "snap": self._snapshot_rows(rows)}
        self.grabKeyboard()
        self.grabMouse()   # keep receiving moves past the viewport edge
        self._apply_rotate()

    def _apply_rotate(self):
        r = self._rotate
        if r is None:
            return
        state = r["state"]
        rot = state.rotation_matrix()
        if "origin_target" in r:
            obj = self.scene.get(r["origin_target"])
            if obj is not None:
                obj.orientation = quat_mul(quat_from_mat3(rot), r["base"])
            self.status_message.emit("Origin frame " + state.status_text())
            self.update()
            return
        for obj_id, (rr, frame_rows) in r["snap"].items():
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            for k, saved in enumerate(frame_rows):
                obj.structure.frames[k][rr] = rotations.rotate_points_about(
                    saved, rot, state.pivot)
        self.status_message.emit(state.status_text())
        self.refresh_geometry()

    def _finish_rotate(self, commit):
        r = self._rotate
        if r is None:
            return
        self._rotate = None
        self.releaseKeyboard()
        self.releaseMouse()
        if "origin_target" in r:
            obj = self.scene.get(r["origin_target"])
            if obj is not None and not commit:
                obj.orientation = r["base"]
                self._cancel_model_edit()
            self.status_message.emit(
                "Origin frame rotated" if commit else "Origin rotate cancelled")
            self.update()
            return
        if not commit:
            for obj_id, (rr, frame_rows) in r["snap"].items():
                obj = self.scene.get(obj_id)
                if obj is None:
                    continue
                for k, saved in enumerate(frame_rows):
                    obj.structure.frames[k][rr] = saved
            self._cancel_model_edit()
            self.status_message.emit("Rotate cancelled")
        else:
            state = r["state"]
            rot = state.rotation_matrix()
            for obj_id, (rr, _f) in r["snap"].items():
                obj = self.scene.get(obj_id)
                if obj is None:
                    continue
                if self._whole_object_selected(obj_id, rr):
                    # rigid: origin & orientation ride along
                    obj.origin = rotations.rotate_points_about(
                        obj.origin[None, :], rot, state.pivot)[0]
                    obj.orientation = quat_mul(quat_from_mat3(rot),
                                               obj.orientation)
                # bonds are NOT re-perceived (see _finish_grab)
            self.last_transform = {"kind": "rotate", "rot": rot.copy()}
            self.transform_serial += 1
            self.status_message.emit(
                "Rotated {:+.2f} deg   (Shift+R repeats)".format(
                    np.degrees(state.angle())))
            self.edit_committed.emit()
        self.refresh_geometry()

    def repeat_last_transform(self):
        """Shift+R (Blender's Repeat Last): apply the last committed move or
        rotation again to whatever is selected now — the quick way to space
        copies evenly or turn several fragments by the same angle."""
        lt = self.last_transform
        if lt is None:
            self.status_message.emit("No transform to repeat yet")
            return
        if self.scene is None or not self.selection:
            self.status_message.emit("Nothing selected to repeat on")
            return
        rows = self._selection_rows()
        if not rows:
            return
        self._begin_model_edit()
        if lt["kind"] == "move":
            d = lt["delta"]
            for obj_id, rr in rows.items():
                obj = self.scene.get(obj_id)
                for k in range(obj.structure.n_frames):
                    obj.structure.frames[k][rr] = \
                        obj.structure.frames[k][rr] + d
                if self._whole_object_selected(obj_id, rr):
                    obj.origin = obj.origin + d
            self.status_message.emit(
                "Repeated move ({:+.3f}, {:+.3f}, {:+.3f}) A".format(*d))
        else:
            rot = lt["rot"]
            pivot = self._rotation_pivot(rows)
            for obj_id, rr in rows.items():
                obj = self.scene.get(obj_id)
                for k in range(obj.structure.n_frames):
                    obj.structure.frames[k][rr] = \
                        rotations.rotate_points_about(
                            obj.structure.frames[k][rr], rot, pivot)
                if self._whole_object_selected(obj_id, rr):
                    obj.origin = rotations.rotate_points_about(
                        obj.origin[None, :], rot, pivot)[0]
                    obj.orientation = quat_mul(quat_from_mat3(rot),
                                               obj.orientation)
            self.status_message.emit("Repeated rotation")
        self.edit_committed.emit()
        self.refresh_geometry()

    def _wrap_cursor(self, pos, margin=6):
        """Blender's infinite drag: when the pointer reaches an edge of the
        VIEWPORT during a modal, teleport it to the opposite side so the drag
        can keep going.

        BOTH axes wrap (round 32). It used to be horizontal only, on the
        theory that a vertical wrap makes rotations jump — but a grab is far
        more often vertical than a rotate is, and running out of screen
        upwards is exactly where the pointer leaves the window and the drag
        dies. Wrapping to the OPPOSITE edge rather than to the middle also
        keeps the gesture's direction unbroken: jumping to the centre halves
        the travel available before the next wrap.

        The state is `reseed()`ed rather than updated, so the teleport moves
        the reference and not the value; updating instead made the molecule
        jump back by the same amount and the drag stopped making progress.
        """
        state = self._active_modal_state()
        if state is None:
            return
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        new_x, new_y = x, y
        if x <= margin:
            new_x = w - margin - 2
        elif x >= w - margin:
            new_x = margin + 2
        if y <= margin:
            new_y = h - margin - 2
        elif y >= h - margin:
            new_y = margin + 2
        if new_x == x and new_y == y:
            return
        state.reseed()
        QCursor.setPos(self.mapToGlobal(QPoint(int(new_x), int(new_y))))
        self._drag_last = QPointF(new_x, new_y)

    def _modal_mouse(self, pos):
        if self._grab is not None:
            origin, direction = self._ray_at(pos)
            self._grab["state"].update_mouse(origin, direction)
            self._apply_grab()
        elif self._rotate is not None:
            state = self._rotate["state"]
            xy, _front = self._project(state.pivot[None, :])
            state.update_mouse((pos.x(), pos.y()), (xy[0, 0], xy[0, 1]))
            self._apply_rotate()

    def _active_modal_state(self):
        if self._grab is not None:
            return self._grab["state"]
        if self._rotate is not None:
            return self._rotate["state"]
        if self._internal is not None:
            return self._internal["state"]
        return None

    # (`_wrap_fly_cursor` is GONE, round 35. Edge-wrapping the pointer only
    # works where there is screen left to wrap TO, so it failed against the
    # properties dock on the right and against the top and bottom of the
    # window — steering simply stopped there. Flight now CAPTURES the pointer
    # instead: hidden, held at the viewport centre, re-seeded after every
    # move. There is no edge left to reach, so there is nothing to wrap, and
    # the visible teleport is gone with it.)

    def snap_origin_to_selection(self):
        """Put the edited molecule's origin on the centroid of its selected
        atoms (the phenyl-ring workflow) and pick the handle up."""
        obj = self.edit_object()
        if obj is None:
            return
        pts = [self.scene.pick_coords(p) for p in self.selection
               if p[0] == obj.id]
        pts = [p for p in pts if p is not None]
        if pts:
            self._begin_model_edit()
            obj.origin = np.mean(pts, axis=0)
        self.set_origin_active(True)

    # ---------------------------------------------------------------- GL setup
    def initializeGL(self):
        self._prog = _program(_VERT, _FRAG)
        self._line_prog = _program(_LINE_VERT, _LINE_FRAG)
        self._grid_prog = _program(_GRID_VERT, _GRID_FRAG)
        self._sphere = _InstancedMesh(*meshes.icosphere(2))
        self._cylinder = _InstancedMesh(*meshes.cylinder(24))
        # Same meshes, separate instance buffers — a few KB of duplicated
        # static vertex data buys immunity from the ordering bug above, and
        # stops a selection forcing a whole-scene rebuild every frame.
        self._hull_sphere = _InstancedMesh(*meshes.icosphere(2))
        self._hull_cylinder = _InstancedMesh(*meshes.cylinder(24))
        self._glow_sphere = _InstancedMesh(*meshes.icosphere(2))
        self._split_prog = _program(_SPLIT_VERT, _SPLIT_FRAG)
        self._split_sphere = _SplitMesh(*meshes.icosphere(2))
        self._wire_lines = _LineBuffer()
        self._poly_tris = _LineBuffer()   # same layout, GL_TRIANGLES
        self._poly_edges = _LineBuffer()  # hull outlines, GL_LINES
        self._grid_quad = _GridQuad()
        self._gl_ready = True
        self._needs_rebuild = True

    # ------------------------------------------------------- instance building
    def _object_style(self, obj):
        if obj.style_key:
            return style_mod.STYLE_BY_KEY.get(obj.style_key, self.style)
        return self.style

    def _ensure_pick_data(self):
        """Refresh the flat pick arrays if the scene changed.

        Picking must NEVER depend on a repaint having happened: a click that
        lands between an edit and the next paint would otherwise hit nothing
        (round 6 bug — the arrays used to be filled only inside paintGL).
        This is CPU-only, so it is safe to call from event handlers.
        """
        if not self._pick_dirty:
            return
        atom_map, coords, radii, drawn = [], [], [], []
        for obj in (self.scene.visible_objects() if self.scene else []):
            s = obj.structure
            if s.n_atoms == 0:
                continue
            st = self._object_style(obj)
            vdw = np.array([elements.radius_vdw(z) for z in s.atomic_numbers])
            rr = np.array([st.atom_radius(v) for v in vdw])
            if st.fixed_atom_radius is None:
                rr = rr * self.atom_scale
            xyz = s.coords
            for i in range(s.n_atoms):
                if i in obj.atom_hidden:
                    continue          # hidden atoms are not pickable either
                atom_map.append((obj.id, i))
                coords.append(xyz[i])
                scaled = float(rr[i]) * obj.atom_scale_for(i)
                radii.append(max(scaled, _MIN_PICK_RADIUS))
                # what is actually DRAWN (wireframe draws no sphere at all) —
                # label sizing and selection halos both key off this
                drawn.append(max(scaled, 0.10 if st.wireframe else 0.0))
        self._atom_map = atom_map
        self._flat_coords = (np.array(coords) if coords
                             else np.zeros((0, 3)))
        self._flat_pick_radii = (np.array(radii) if radii else np.zeros(0))
        self._draw_radii = (np.array(drawn) if drawn else np.zeros(0))
        self._pick_dirty = False

    def _occupancy_wedges(self, obj, n_drawn, n_base):
        # type: (object, int, int) -> Optional[dict]
        """`{drawn atom index: wedge array}` for this object, or None.

        **An outliner colour wins.** Painting an atom in the outliner is a
        deliberate statement about that atom, while the wedges are derived
        from the file — so a hand-set colour suppresses the split and the atom
        draws solid, which is the only way "I made this one orange" can keep
        meaning what it says. Christian's call, and it also keeps the two
        systems from fighting over one sphere.

        Modifier and boundary copies follow their base atom (`idx % n_base`),
        the same rule the colours and radii already use.
        """
        if not self.show_occupancy:
            return None
        meta = getattr(obj.structure, "metadata", None) or {}
        table = meta.get("site_occupancy") or {}
        if not table:
            return None
        base_n = max(n_base, 1)
        colour_of = lambda sym: elements.color_f(elements.atomic_number(sym))
        cache = {}
        out = {}
        for i in range(n_drawn):
            base_i = i % base_n
            if obj.atom_colors and obj.atom_colors.get(base_i) is not None:
                continue                      # hand-painted: leave it solid
            composition = table.get(str(base_i))
            if not composition:
                continue
            key = tuple((str(sym), round(float(occ), 6))
                        for sym, occ in composition)
            if key not in cache:
                wedges = style_mod.occupancy_wedges(composition, colour_of)
                cache[key] = np.array(wedges, dtype=float) if wedges else None
            if cache[key] is not None:
                out[i] = cache[key]
        return out or None

    def _rebuild(self):
        sphere_mats, sphere_cols = [], []
        split_mats, split_segs = [], []
        cyl_starts, cyl_ends, cyl_rads, cyl_cols = [], [], [], []
        wire_rows = []
        self._ensure_pick_data()

        for obj in (self.scene.visible_objects() if self.scene else []):
            s = obj.structure
            if s.n_atoms == 0:
                continue
            st = self._object_style(obj)
            # DISPLAY uses the modifier stack's output; picking and editing
            # (see _ensure_pick_data) stay on the base atoms, so a big array
            # renders without making the molecule unwieldy to work on.
            sym_e, coords, bonds_e = obj.evaluated()
            zs = np.array([elements.atomic_number(x) for x in sym_e],
                          dtype=int)
            colors = np.array([elements.color_f(z) for z in zs])
            # per-atom overrides from the outliner (VESTA-style). Modifier
            # copies inherit the base atom's colour: idx % n_base.
            if obj.atom_colors:
                base_n = max(s.n_atoms, 1)
                for i in range(len(colors)):
                    c = obj.atom_colors.get(i % base_n)
                    if c is not None:
                        colors[i] = c
            vdw = np.array([elements.radius_vdw(z) for z in zs])
            radii = np.array([st.atom_radius(v) for v in vdw])
            if st.fixed_atom_radius is None:
                # The user's sphere-size slider scales VdW-derived radii only.
                # Licorice's sphere IS the stick cap: scaling it away from
                # bond_radius leaves the cylinder's flat end poking out of a
                # too-small ball, which is the "gap" at the tip.
                radii = radii * self.atom_scale
            if st.wireframe:
                bonded = np.zeros(len(zs), dtype=bool)
                for i, j, _o in bonds_e:
                    bonded[i] = bonded[j] = True
                radii = np.where(bonded, 0.0, 0.12)
            # Per-atom size and visibility from the outliner. Modifier copies
            # follow their base atom, same rule as the colours.
            if obj.atom_scales or obj.atom_hidden:
                base_n = max(s.n_atoms, 1)
                for i in range(len(radii)):
                    base_i = i % base_n
                    if base_i in obj.atom_hidden:
                        radii[i] = 0.0
                    else:
                        radii[i] *= obj.atom_scale_for(base_i)
            hide = self._shuttle_hidden(coords)
            wedges = self._occupancy_wedges(obj, len(sym_e), s.n_atoms)
            for i in range(len(sym_e)):
                if hide is not None and hide[i]:
                    continue        # too close to the cockpit — would clip
                if radii[i] > 0.0:
                    m = np.zeros((4, 4))
                    m[0, 0] = m[1, 1] = m[2, 2] = radii[i]
                    m[:3, 3] = coords[i]
                    m[3, 3] = 1.0
                    sphere_mats.append(m)
                    sphere_cols.append((colors[i][0], colors[i][1],
                                        colors[i][2], 1.0))
                    if wedges is not None and i in wedges:
                        # Drawn TWICE on purpose: once in the ordinary pass so
                        # every other effect (picking radius, selection hull,
                        # depth) sees a normal atom, then again with the
                        # wedges at GL_LEQUAL. Same mesh and same matrix, so
                        # the second pass lands on exactly the same depth.
                        split_mats.append(m)
                        split_segs.append(wedges[i])
            if st.show_bonds:
                base_n = max(s.n_atoms, 1)
                for i, j, order in bonds_e:
                    # A bond to a hidden atom goes with it — otherwise
                    # turning hydrogens off leaves their sticks behind.
                    if obj.atom_hidden and (i % base_n in obj.atom_hidden
                                            or j % base_n in obj.atom_hidden):
                        continue
                    p1, p2 = coords[i], coords[j]
                    mid = (p1 + p2) / 2.0
                    if st.wireframe:
                        c1, c2 = colors[i], colors[j]
                        wire_rows += [list(p1) + list(c1), list(mid) + list(c1),
                                      list(mid) + list(c2), list(p2) + list(c2)]
                        continue
                    for a, b, r in style_mod.bond_cylinders(
                            p1, p2, order, bond_radius=st.bond_radius,
                            show_multiple=st.show_multiple_bonds):
                        m = (np.asarray(a) + np.asarray(b)) / 2.0
                        cyl_starts += [a, m]
                        cyl_ends += [m, b]
                        cyl_rads += [r, r]
                        cyl_cols += [colors[i], colors[j]]
            if st.show_bonds and (s.metadata or {}).get("show_refused_bonds"):
                # The visualisation override (round 43). These are contacts
                # the chemistry REFUSED — impossibly short, or past the
                # element's covalent valence — so they are drawn thinner and
                # desaturated: a render must never claim a 0.5 A contact is an
                # ordinary bond. They ride the ordinary cylinder buffer rather
                # than a pass of their own, because they ARE scene geometry;
                # only the overlays need their own buffers (round 35).
                base_n = max(s.n_atoms, 1)
                n_drawn = len(coords)
                r_ref = st.bond_radius * self.refused_bond_scale
                for i, j in (s.metadata.get("refused_bonds") or ()):
                    if not (0 <= i < n_drawn and 0 <= j < n_drawn):
                        continue
                    if obj.atom_hidden and (i % base_n in obj.atom_hidden
                                            or j % base_n in obj.atom_hidden):
                        continue
                    p1, p2 = coords[i], coords[j]
                    mid = (p1 + p2) / 2.0
                    c1 = style_mod.muted(colors[i], self.refused_bond_fade)
                    c2 = style_mod.muted(colors[j], self.refused_bond_fade)
                    if st.wireframe:
                        wire_rows += [list(p1) + list(c1), list(mid) + list(c1),
                                      list(mid) + list(c2), list(p2) + list(c2)]
                        continue
                    cyl_starts += [p1, mid]
                    cyl_ends += [mid, p2]
                    cyl_rads += [r_ref, r_ref]
                    cyl_cols += [c1, c2]

        self._sphere.upload(
            np.array(sphere_mats) if sphere_mats else np.zeros((0, 4, 4)),
            np.array(sphere_cols) if sphere_cols else np.zeros((0, 4)))
        self._split_sphere.upload(
            np.array(split_mats) if split_mats else np.zeros((0, 4, 4)),
            np.array(split_segs) if split_segs
            else np.zeros((0, _SplitMesh.SEGMENTS, 4)))
        if cyl_starts:
            mats_c = meshes.cylinder_transforms(
                np.array(cyl_starts), np.array(cyl_ends), np.array(cyl_rads))
            rgba_c = np.hstack([np.array(cyl_cols),
                                np.ones((len(cyl_cols), 1))])
            self._cylinder.upload(mats_c, rgba_c)
        else:
            self._cylinder.upload(np.zeros((0, 4, 4)), np.zeros((0, 4)))
        self._wire_lines.upload(np.array(wire_rows, dtype=np.float32)
                                if wire_rows else np.zeros((0, 6)))

    # ------------------------------------------------------------------ paint
    def paintGL(self):
        if self._needs_rebuild:
            self._rebuild()
            self._needs_rebuild = False
        # Re-assert state EVERY frame: any QPainter pass resets GL state.
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_MULTISAMPLE)
        GL.glDisable(GL.GL_BLEND)
        r, g, b = self.background
        GL.glClearColor(r, g, b, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        w, h = max(self.width(), 1), max(self.height(), 1)
        view = self.camera.view_matrix()
        proj = self.camera.projection_matrix(w, h)

        empty = self.scene is None or not self.scene.visible_objects()
        if not empty:
            GL.glUseProgram(self._prog)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._prog, "uView"),
                                  1, GL.GL_TRUE, view)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._prog, "uProj"),
                                  1, GL.GL_TRUE, proj)
            self._sphere.draw()
            self._cylinder.draw()
            self._draw_occupancy(view, proj)
            self._draw_lines(self._wire_lines, view, proj)
        if not empty:
            self._draw_polyhedra(view, proj)
        if self.show_grid:
            self._draw_grid(view, proj)
        if not empty:
            self._paint_meta_glow(view, proj)
            self._paint_selection(view, proj)
        self._paint_overlays(view, proj, empty)

    def _draw_occupancy(self, view, proj):
        """Re-draw the shared sites as pie spheres, over their solid selves.

        `GL_LEQUAL` is what makes this work: the geometry and the model matrix
        are identical to the ordinary pass, so every fragment lands at exactly
        the same depth and the second draw wins on equality. No offset, no
        z-fighting, and the atom stays a normal atom to picking, selection and
        every other pass.
        """
        if getattr(self, "_split_sphere", None) is None:
            return
        if self._split_sphere.n_instances == 0:
            return
        GL.glUseProgram(self._split_prog)
        GL.glUniformMatrix4fv(
            GL.glGetUniformLocation(self._split_prog, "uView"), 1,
            GL.GL_TRUE, view)
        GL.glUniformMatrix4fv(
            GL.glGetUniformLocation(self._split_prog, "uProj"), 1,
            GL.GL_TRUE, proj)
        GL.glDepthFunc(GL.GL_LEQUAL)
        self._split_sphere.draw()
        GL.glDepthFunc(GL.GL_LESS)
        GL.glUseProgram(self._prog)

    def _draw_grid(self, view, proj):
        """After opaque geometry: depth-TESTED so molecules occlude it, but
        depth-write off and blended, so the fade never punches holes."""
        GL.glUseProgram(self._grid_prog)
        u = lambda n: GL.glGetUniformLocation(self._grid_prog, n)
        # The shader needs both directions: viewProj to write depth, and its
        # inverse to turn each pixel back into a world-space ray.
        view_proj = np.asarray(proj, dtype=np.float64) @ np.asarray(
            view, dtype=np.float64)
        try:
            inv_view_proj = np.linalg.inv(view_proj)
        except np.linalg.LinAlgError:
            return
        GL.glUniformMatrix4fv(u("uViewProj"), 1, GL.GL_TRUE,
                              view_proj.astype(np.float32))
        GL.glUniformMatrix4fv(u("uInvViewProj"), 1, GL.GL_TRUE,
                              inv_view_proj.astype(np.float32))
        r = quat_to_mat3(self.camera.rotation)
        eye = self.camera.center + r.T @ np.array([0.0, 0.0,
                                                   self.camera.distance])
        GL.glUniform3f(u("uCamPos"), *[float(v) for v in eye])
        GL.glUniform1f(u("uFade"),
                       float(grid_mod.fade_distance(self.camera.distance)))
        GL.glUniform3f(u("uBase"), *grid_mod.GRID_GREY)
        GL.glUniform3f(u("uAxisX"), *grid_mod.AXIS_X_COLOR)
        GL.glUniform3f(u("uAxisY"), *grid_mod.AXIS_Y_COLOR)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE)
        self._grid_quad.draw()
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)

    def _draw_lines(self, buf, view, proj, mode=None, alpha=1.0):
        if buf is None or not buf.n_verts:
            return
        GL.glUseProgram(self._line_prog)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._line_prog, "uView"),
                              1, GL.GL_TRUE, view)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._line_prog, "uProj"),
                              1, GL.GL_TRUE, proj)
        GL.glUniform1f(GL.glGetUniformLocation(self._line_prog, "uAlpha"),
                       float(alpha))
        buf.draw(mode)

    def _draw_polyhedra(self, view, proj):
        """Translucent coordination solids through each metal's donors.

        Drawn AFTER the opaque geometry with depth-write off, like the grid:
        the sticks inside a polyhedron should still read through it, which is
        exactly how VESTA and every MOF figure look. Double-sided (culling
        off) so the inside face is visible when the camera is within a large
        cage.
        """
        if self.scene is None:
            return
        from ..core import polyhedra as poly_mod
        built = self._polyhedra_plan(poly_mod)
        if not built:
            if self._poly_tris is not None:
                self._poly_tris.n_verts = 0
            if self._poly_edges is not None:
                self._poly_edges.n_verts = 0
            return
        eye = self._camera_frame()["eye"]
        verts = np.vstack([poly_mod.triangle_soup([p])[0] for p in built])
        # The rim term is the only camera-dependent part, so it alone is
        # recomputed per frame; the hulls are cached above.
        cols = poly_mod.fresnel_colors(built, eye)
        self._poly_tris.upload(np.hstack([verts, cols]))
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glDisable(GL.GL_CULL_FACE)
        self._draw_lines(self._poly_tris, view, proj, mode=GL.GL_TRIANGLES,
                         alpha=self.polyhedra_alpha)
        # ...and the hull EDGES on top, which is what actually makes the
        # shape legible: a translucent solid with no outline reads as a
        # coloured smudge however it is shaded.
        edge_pts = self._poly_edge_cache
        if edge_pts is not None and len(edge_pts):
            bright = np.tile(np.array([[0.92, 0.92, 0.96]]),
                             (len(edge_pts), 1))
            self._poly_edges.upload(np.hstack([edge_pts, bright]))
            GL.glLineWidth(1.4)
            self._draw_lines(self._poly_edges, view, proj, mode=GL.GL_LINES,
                             alpha=min(1.0, self.polyhedra_alpha + 0.3))
        GL.glDepthMask(GL.GL_TRUE)

    def _polyhedra_plan(self, poly_mod):
        """Built hulls for every visible object, CACHED on their inputs.

        Rebuilding a convex hull per metal on every repaint is the round-33
        mistake (nothing camera-independent belongs in a paint path); only
        the Fresnel term above depends on the camera.
        """
        key = []
        objects = []
        for obj in self.scene.visible_objects():
            if not (obj.structure.metadata or {}).get("polyhedra"):
                continue
            sym, xyz, bonds = obj.evaluated()
            key.append((obj.id, len(sym), len(bonds),
                        float(xyz[0][0]) if len(xyz) else 0.0,
                        float(xyz[-1][-1]) if len(xyz) else 0.0))
            objects.append((obj, sym, xyz, bonds))
        key = tuple(key)
        if key == self._poly_key:
            return self._poly_cache
        built = []
        for obj, sym, xyz, bonds in objects:
            meta = obj.structure.metadata or {}
            cell = cell_of(obj)
            content = int(meta.get("cell_content") or 0)
            made = []
            if cell is not None and content:
                # From the periodic graph, so the solid is complete whatever
                # the display options are doing (Christian: "should be
                # complete no matter which combination of modes is applied").
                made = poly_mod.build_periodic(sym, xyz, cell, content)
            if not made:
                made = poly_mod.build(sym, xyz, bonds)
            built.extend(made)
        self._poly_key = key
        self._poly_cache = built
        self._poly_edge_cache = poly_mod.hull_edges(built)
        return built
        GL.glDisable(GL.GL_BLEND)

    def _paint_meta_glow(self, view, proj):
        """Layered translucent shells around every meta centre.

        A cheap stand-in for a bloom pass: three concentric additively-blended
        shells fall off outward, which reads as a glow without a second render
        target or a post-process. Meta atoms are dummies — they must not look
        like an ordinary element sitting in the structure.
        """
        from ..core import meta as meta_mod
        if self.scene is None:
            return
        mats, rgba = [], []
        for obj in self.scene.visible_objects():
            table = meta_mod.all_meta(obj.structure)
            if not table:
                continue
            st = self._object_style(obj)
            for index in table:
                if index >= obj.structure.n_atoms:
                    continue
                z = elements.atomic_number(obj.structure.symbols[index])
                base = st.atom_radius(elements.radius_vdw(z))
                if st.fixed_atom_radius is None:
                    base *= self.atom_scale
                base = max(base, 0.30)
                for shell, alpha in ((1.35, 0.30), (1.9, 0.16), (2.6, 0.07)):
                    m = np.zeros((4, 4))
                    m[0, 0] = m[1, 1] = m[2, 2] = base * shell
                    m[:3, 3] = obj.structure.coords[index]
                    m[3, 3] = 1.0
                    mats.append(m)
                    rgba.append(_META_GLOW + (alpha,))
        if not mats:
            return
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)      # additive = emissive
        GL.glDepthMask(GL.GL_FALSE)
        GL.glUseProgram(self._prog)
        self._glow_sphere.upload(np.array(mats), np.array(rgba))
        self._glow_sphere.draw()
        GL.glDepthMask(GL.GL_TRUE)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_BLEND)

    def outline_width(self):
        # type: () -> float
        """World-space thickness of the selection outline at this zoom.

        Tied to the camera distance so the ring stays about the same number
        of pixels wide however far away you are — a fixed world width is a
        hairline when zoomed out and a fat orange blob when zoomed in.
        """
        low, high = _OUTLINE_WIDTH_RANGE
        return float(np.clip(self.camera.distance * _OUTLINE_WIDTH_FRAC,
                             low, high))

    def _selection_hull(self):
        """Instance matrices for the outline hull: an enlarged copy of every
        selected atom, plus every bond with BOTH ends selected.

        Including the bonds is what makes a selected fragment read as one
        outlined object (Christian's Blender reference) instead of a string of
        separate orange rings.
        """
        width = self.outline_width()
        spheres, cylinders = [], []
        for obj_id, rows in self._selection_rows().items():
            obj = self.scene.get(obj_id)
            if obj is None or not obj.visible:
                continue
            st = self._object_style(obj)
            s = obj.structure
            chosen = set(rows)
            for i in rows:
                if i in obj.atom_hidden:
                    continue          # invisible atoms get no outline either
                z = elements.atomic_number(s.symbols[i])
                base = st.atom_radius(elements.radius_vdw(z))
                if st.fixed_atom_radius is None:
                    base *= self.atom_scale
                base *= obj.atom_scale_for(i)
                # Wireframe draws no sphere at all, so there is no silhouette
                # to hug — mark the vertex with a small bead instead.
                base = 0.10 if st.wireframe else max(base, 0.12)
                m = np.zeros((4, 4))
                m[0, 0] = m[1, 1] = m[2, 2] = base + width
                m[:3, 3] = s.coords[i]
                m[3, 3] = 1.0
                spheres.append(m)
            if st.show_bonds and not st.wireframe:
                for i, j, _order in s.bonds:
                    if i not in chosen or j not in chosen:
                        continue
                    if i in obj.atom_hidden or j in obj.atom_hidden:
                        continue
                    cylinders.append((s.coords[i], s.coords[j],
                                      st.bond_radius + width))
        return spheres, cylinders

    def _paint_selection(self, view, proj):
        """Blender's selection outline, by the inverted-hull trick.

        Draw a slightly enlarged copy of the selection in flat orange with the
        FRONT faces culled, so only the hull's back faces are rasterised. Over
        the atom itself those sit behind the real surface and fail the depth
        test; beyond the silhouette there is nothing in front of them, so they
        survive — leaving precisely a rim. One extra instanced pass, no second
        render target, and no post-process.

        Depth-write stays OFF: the hull is a wider fake, and letting it write
        depth would push real geometry out of the way behind the selection.
        """
        if not self.selection or self.scene is None:
            return
        spheres, cylinders = self._selection_hull()
        if not spheres and not cylinders:
            return
        GL.glDisable(GL.GL_BLEND)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glEnable(GL.GL_CULL_FACE)
        GL.glCullFace(GL.GL_FRONT)
        GL.glUseProgram(self._prog)
        flat = GL.glGetUniformLocation(self._prog, "uFlat")
        GL.glUniform1f(flat, 1.0)
        if spheres:
            self._hull_sphere.upload(
                np.array(spheres),
                np.tile(np.array(_OUTLINE_COLOR), (len(spheres), 1)))
            self._hull_sphere.draw()
        if cylinders:
            mats = meshes.cylinder_transforms(
                np.array([c[0] for c in cylinders]),
                np.array([c[1] for c in cylinders]),
                np.array([c[2] for c in cylinders]))
            self._hull_cylinder.upload(
                mats, np.tile(np.array(_OUTLINE_COLOR), (len(cylinders), 1)))
            self._hull_cylinder.draw()
        GL.glUniform1f(flat, 0.0)
        GL.glCullFace(GL.GL_BACK)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glDepthMask(GL.GL_TRUE)

    # ------------------------------------------------------------ 2D overlays
    def _paint_overlays(self, view, proj, empty):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self.show_cell:
            self._paint_cells(p)
        self._paint_symmetry(p)
        if not empty:
            self._paint_labels(p)
        if self.show_compass:
            self._paint_compass(p)
        if self._region_drag is not None:
            self._paint_region(p)
        state = self._active_modal_state()
        # Guides belong to the CONSTRAINED modals only. The internal-coordinate
        # modal has a single degree of freedom and therefore no axis to draw —
        # and because an exception inside paintGL is printed and swallowed
        # rather than raised, feeding it one produced a silent traceback per
        # frame and a viewport that simply stopped updating its overlays.
        if state is not None and self._internal is None:
            self._paint_modal_guides(p, state)
        if self._internal is not None \
                and self._internal["kind"] == internal.TWIST:
            self._paint_twist_axis(p)
        if self.show_hbonds:
            self._paint_hbonds(p)
        self._paint_anchor(p)
        self._paint_ligating(p)
        self._paint_measure(p)
        self._paint_modal_prompt(p)
        self._paint_tumble_lock(p)
        if self._shuttle is not None:
            self._paint_shuttle(p)
        elif self._fly is not None:
            self._paint_fly(p)
        if self._hover_bond is not None:
            self._paint_hover_bond(p)
        if self._draw_drag is not None and self._draw_drag.get("snap") is not None:
            self._paint_snap_marker(p)
        if self.mode == MODE_EDIT:
            # The origin handle is a QPainter overlay, so it is ALWAYS on top
            # of the molecule and stays clickable however the view is turned.
            if self._origin_active:
                self._paint_origin_gizmo(p)
            self._paint_origin_dot(p)
            self._paint_edit_mode(p)
        p.end()

    def _paint_fly(self, p):
        """Right-mouse flight HUD: a small reticle and the controls.

        Deliberately lighter than the shuttle's cockpit — camera flight is a
        navigation gesture you are in for a second or two, not a mode you sit
        in, so a full banner across the top would be in the way more often
        than it would help. It fades out with the coast, which also makes the
        inertia visible rather than merely felt.
        """
        fly = self._fly
        speed = float(np.linalg.norm(fly["model"].velocity))
        cx, cy = self.width() // 2, self.height() // 2
        alpha = 90 if fly["released"] else 190
        pen = QPen(QColor(_FLY_COLOR.red(), _FLY_COLOR.green(),
                          _FLY_COLOR.blue(), alpha), 1.3)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # The HULL mark sits dead centre and is where the nose actually
        # points; the RETICLE drifts behind it under turn. Separating the two
        # is what makes the rate of turn readable — one mark can only tell
        # you where you are aimed, never how hard you are pulling.
        p.drawEllipse(cx - 9, cy - 9, 18, 18)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(cx + dx * 13, cy + dy * 13, cx + dx * 19, cy + dy * 19)
        # The aim reticle: a virtual stick, so where it sits IS the turn you
        # have commanded. Its travel limit is drawn as a faint ring, because
        # a stick you cannot see the extent of is one you cannot centre.
        short = min(self.width(), self.height())
        limit = fly["aim"].limit(short)
        dx_r, dy_r = fly["aim"].offset
        faint = QColor(_FLY_COLOR.red(), _FLY_COLOR.green(),
                       _FLY_COLOR.blue(), int(alpha * 0.28))
        p.setPen(QPen(faint, 1.0))
        p.drawEllipse(int(cx - limit), int(cy - limit),
                      int(limit * 2), int(limit * 2))
        if abs(dx_r) + abs(dy_r) > 1.0:
            rx, ry = int(cx + dx_r), int(cy + dy_r)
            p.setPen(QPen(QColor(_FLY_COLOR.red(), _FLY_COLOR.green(),
                                 _FLY_COLOR.blue(), int(alpha * 0.85)), 1.4))
            p.drawEllipse(rx - 6, ry - 6, 12, 12)
            p.drawLine(cx, cy, rx, ry)
        p.setPen(pen)
        # Roll: a tick on the reticle ring showing which way is up, so a
        # rolled horizon is readable even against an empty background.
        roll = float(fly["model"].roll)
        if abs(roll) > 1e-3:
            ux, uy = np.sin(roll), -np.cos(roll)
            p.drawLine(int(cx + ux * 9), int(cy + uy * 9),
                       int(cx + ux * 15), int(cy + uy * 15))
        if fly["released"]:
            return
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        text = ("FLY{}  W/A/S/D  Space/Ctrl up-down  Q/E roll   "
                "Shift boost   Alt creep   {:.1f} A/s").format(
                    " [latched — right click or Esc to land]"
                    if fly.get("latched") else "", speed)
        fm = p.fontMetrics()
        rect = QRect(10, self.height() - fm.height() - 18,
                     fm.horizontalAdvance(text) + 16, fm.height() + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 130))
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(_FLY_COLOR)
        p.drawText(rect, Qt.AlignCenter, text)

    def _paint_shuttle(self, p):
        """Cockpit HUD: reticle + a reminder of the flight controls."""
        obj = self.scene.get(self._shuttle["obj_id"]) if self.scene else None
        cx, cy = self.width() // 2, self.height() // 2
        p.setPen(QPen(QColor(120, 220, 255, 200), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(cx - 16, cy - 16, 32, 32)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(cx + dx * 20, cy + dy * 20, cx + dx * 30, cy + dy * 30)
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        text = "SHUTTLE  |  {}  |  hold WASD + Q/E to fly, drag or scroll " \
               "to steer, Shift boost, Esc land".format(
                   obj.name if obj is not None else "?")
        # horizontalAdvance, NOT boundingRect: the tight rect ignores a bold
        # face's side bearings, so the banner cropped its own last glyph.
        fm = p.fontMetrics()
        rect = QRect(10, 8, fm.horizontalAdvance(text) + 16, fm.height() + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(QColor(120, 220, 255))
        p.drawText(rect, Qt.AlignCenter, text)

    def _paint_hover_bond(self, p):
        """Highlight the bond under the cursor with ONE STICK PER BOND ORDER
        — a double bond gets two, a triple three. No text: the stick count
        already says what the order is."""
        obj_id, i, j = self._hover_bond
        obj = self.scene.get(obj_id) if self.scene else None
        if obj is None:
            return
        s = obj.structure
        if not (0 <= i < s.n_atoms and 0 <= j < s.n_atoms):
            return
        order = next((o for a, b, o in s.bonds if (a, b) == (i, j)), 1)
        p.setPen(QPen(QColor(255, 210, 90, 225), 3.4, Qt.SolidLine,
                      Qt.RoundCap))
        # Re-use the renderer's own cylinder layout so the highlight sits
        # exactly on the drawn sticks.
        st = self._object_style(obj)
        for a, b, _r in style_mod.bond_cylinders(
                s.coords[i], s.coords[j], order,
                bond_radius=st.bond_radius * 1.35, show_multiple=True):
            seg = self._segment_screen(a, b)
            if seg is None:
                continue
            (x0, y0), (x1, y1) = seg
            p.drawLine(int(x0), int(y0), int(x1), int(y1))

    def toggle_hbonds(self):
        self.show_hbonds = not self.show_hbonds
        self.status_message.emit(
            "Suspected hydrogen bonds shown (geometric criterion, not an "
            "energy)" if self.show_hbonds else "Hydrogen bonds hidden")
        self.update()

    def _paint_hbonds(self, p):
        """Dashed cyan lines for suspected H-bonds — computed across ALL
        visible molecules together, since the interesting ones are between
        molecules you are arranging."""
        if self.scene is None:
            return
        symbols, coords, bonds, offset = [], [], [], 0
        for obj in self.scene.visible_objects():
            s = obj.structure
            if not s.n_atoms:
                continue
            symbols += list(s.symbols)
            coords.append(s.coords)
            bonds += [(i + offset, j + offset, o) for i, j, o in s.bonds]
            offset += s.n_atoms
        if offset < 3:
            return
        xyz = np.vstack(coords)
        hbs = bonding.find_hydrogen_bonds(symbols, xyz, bonds)
        if not hbs:
            return
        p.setPen(QPen(QColor(110, 225, 235, 210), 1.8, Qt.DashLine))
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        for h, a, dist in hbs:
            seg = self._segment_screen(xyz[h], xyz[a])
            if seg is None:
                continue
            (x0, y0), (x1, y1) = seg
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
            p.drawText(int((x0 + x1) / 2) + 4, int((y0 + y1) / 2) - 3,
                       "{:.2f}".format(dist))

    def _paint_snap_marker(self, p):
        """Ring around the atom a drag-draw would bond to on release."""
        d = self._draw_drag
        obj = self.scene.get(d["obj_id"]) if self.scene else None
        if obj is None:
            return
        xy, front = self._project(obj.structure.coords[d["snap"]][None, :])
        if not front[0]:
            return
        x, y = int(xy[0, 0]), int(xy[0, 1])
        p.setPen(QPen(QColor(120, 235, 140, 235), 2.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(x - 15, y - 15, 30, 30)
        p.drawEllipse(x - 8, y - 8, 16, 16)

    def _paint_origin_dot(self, p):
        s = self._origin_screen()
        if s is None:
            return
        x, y = int(s[0]), int(s[1])
        r = 6 if self._origin_active else 5
        p.setPen(QPen(QColor(255, 255, 255), 1.6))
        p.setBrush(_EDIT_ACCENT)
        p.drawEllipse(x - r, y - r, 2 * r, 2 * r)
        if self._origin_active:            # picked-up ring
            p.setPen(QPen(_EDIT_ACCENT, 1.4, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(x - r - 5, y - r - 5, 2 * r + 10, 2 * r + 10)

    def _paint_edit_mode(self, p):
        """Blender-style "you are in edit mode" cue: accent border plus a
        header naming the molecule, the draw element, and any typed symbol."""
        obj = self.edit_object()
        p.setPen(QPen(_EDIT_ACCENT, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawRect(1, 1, self.width() - 3, self.height() - 3)
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        text = "EDIT  |  {}  |  draw: {}".format(
            obj.name if obj is not None else "?", self.draw_element)
        # horizontalAdvance, NOT boundingRect: the tight rect ignores a bold
        # face's side bearings, so the banner cropped its own last glyph.
        fm = p.fontMetrics()
        rect = QRect(10, 8, fm.horizontalAdvance(text) + 16, fm.height() + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 130))
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(_EDIT_ACCENT)
        p.drawText(rect, Qt.AlignCenter, text)

    def _paint_cells(self, p):
        """Unit-cell box for every visible object that carries a cell.

        A QPainter overlay rather than GL geometry: it is 12 near-plane
        clipped segments, it needs no buffer rebuild when a molecule moves,
        and a cell outline reading THROUGH the structure is what every
        crystallography viewer does anyway. The three cell vectors from the
        origin are drawn in the axis colours (a = red, b = green, c = blue),
        which is also how the compass reads.
        """
        if self.scene is None:
            return
        for obj in self.scene.visible_objects():
            cell = cell_of(obj)
            if cell is None:
                continue
            corners = cell_corners_world(obj, cell)
            if corners is None:
                continue
            pen = QPen(QColor(200, 200, 210, 150), 1.2)
            for i, j in cell.edges():
                seg = self._segment_screen(corners[i], corners[j])
                if seg is None:
                    continue
                (x0, y0), (x1, y1) = seg
                p.setPen(pen)
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
            # a/b/c from the origin corner, in the axis colours.
            for axis, target in enumerate((1, 2, 3)):
                seg = self._segment_screen(corners[0], corners[target])
                if seg is None:
                    continue
                (x0, y0), (x1, y1) = seg
                p.setPen(QPen(_AXIS_COLORS[axis], 2.0))
                p.drawLine(int(x0), int(y0), int(x1), int(y1))

    def _paint_symmetry(self, p):
        """Symmetry elements and 'ghost' images of the asymmetric unit.

        Two complementary pictures, both optional: the GHOSTS show where each
        copy lands (usually the more immediate answer to "how does this fill
        the cell"), and the GLYPHS name the operation doing it, in the
        standard crystallographic language — a lens for a 2-fold, triangle
        for 3, square for 4, hexagon for 6, an open circle for an inversion
        centre, an outlined quad for a mirror. Screws and glides get an
        arrow for their intrinsic translation.
        """
        if self.scene is None:
            return
        for obj in self.scene.visible_objects():
            meta = obj.structure.metadata or {}
            cell = cell_of(obj)
            if cell is None or not (meta.get("show_symmetry")
                                    or meta.get("show_ghosts")):
                continue
            plan = self._symmetry_plan(obj, meta)
            fit = self._cell_fit(obj, cell)
            to_world = lambda f: (np.asarray(f) @ cell.matrix()) @ fit[0].T \
                + fit[1]

            # Calibrate the depth cue on the CELL, so the near corner is
            # always full strength and the far one always faint whatever the
            # zoom. Scaling by camera distance instead made a small cell come
            # out uniformly flat, which is "there are no depth cues".
            self.set_depth_cue_extent(to_world(_UNIT_CORNERS))

            if meta.get("show_ghosts") and plan["ghosts"] is not None:
                self._paint_ghosts(p, meta, plan["ghosts"], to_world)
            if meta.get("show_symmetry"):
                for element in plan["elements"]:
                    self._paint_symmetry_element(p, element, cell, to_world)
            self._cue_range = self._cue_eye = None

    def _symmetry_plan(self, obj, meta):
        """Parsed operators, classified elements and ghost images, CACHED.

        All three were recomputed on every repaint, and none of them depends
        on the camera: 48 operators cost ~0.9 ms to re-parse, ~8 ms to
        re-classify (an eigen-decomposition each) and ~3 ms to re-image, so
        simply having symmetry switched on burned 12 ms per frame before a
        single line was drawn. A trackpad emitting 60+ scroll events a second
        then has no chance — "it slows zooming to a crawl". The key is
        everything the result depends on, so a changed filter or a re-imported
        cell still rebuilds.
        """
        from ..core import cif as cif_mod
        from ..core import symmetry as sym_mod
        strings = tuple(meta.get("symops") or ("x,y,z",))
        kinds = meta.get("symmetry_kinds")
        asym = meta.get("asym_frac")
        key = (id(obj), strings, tuple(sorted(kinds)) if kinds else None,
               None if asym is None else np.asarray(asym).tobytes())
        cached = getattr(self, "_sym_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        ops = [cif_mod.SymOp.from_xyz(t) for t in strings]
        # ONE filtered list drives both pictures, so the glyphs and the
        # ghosts can never disagree about which operations are in play.
        active = sym_mod.filter_ops(ops, kinds)
        plan = {
            "elements": sym_mod.classify_all(active),
            "ghosts": self._ghost_images(meta, asym, active),
        }
        self._sym_cache = (key, plan)
        return plan

    def _ghost_images(self, meta, asym, ops):
        """Ghost skeletons as [(fractional coords, bond pairs), ...].

        Two corrections over "apply the operator and wrap":

        * each image is wrapped by MOLECULE, not by atom, so a copy sitting on
          a cell face stays in one piece instead of reappearing shredded on
          the far side with its bonds drawn straight across the box;
        * the bonds are re-tested AT the image's own coordinates. A periodic
          component cannot be made contiguous at all, so its cross-face
          contacts would still be drawn as long wrong-way lines — which is
          most of what "the ghost atoms are glitched" looked like.

        Both are per-image work, hence computed once here inside the cached
        plan rather than in the paint path.
        """
        if asym is None:
            return None
        from ..core import cif as cif_mod
        from ..core import symmetry as sym_mod
        base = np.asarray(asym, dtype=float)
        symbols = list(meta.get("asym_symbols") or ())
        cell = None
        try:
            cell = cif_mod.Cell.from_dict(meta["cell"])
        except (KeyError, TypeError, ValueError):
            pass
        if cell is None or len(symbols) != len(base):
            # Nothing to perceive bonds from: dots only, wrapped per atom.
            return [(img, []) for img in
                    sym_mod.images_of(base, ops)[:_MAX_GHOSTS]]

        whole = lambda f: cif_mod.unwrap_molecules(symbols, f, cell)
        images = sym_mod.images_of(base, ops, normalize=whole)[:_MAX_GHOSTS]
        adj = cif_mod.periodic_neighbours(symbols, base, cell)
        pairs = [(i, j) for i, row in enumerate(adj) for j in row if j > i]
        return [(img, cif_mod.direct_pairs(symbols, img, cell, pairs))
                for img in images]

    def _cell_fit(self, obj, cell):
        """The rigid transform carrying stored cell space to world space."""
        from ..core import cif as cif_mod
        meta = obj.structure.metadata or {}
        idx, ref = meta.get("cell_ref_idx"), meta.get("cell_ref_xyz")
        coords = obj.structure.coords
        if idx and ref and not any(i >= len(coords) for i in idx):
            fit = cif_mod.rigid_from_reference(np.asarray(ref, dtype=float),
                                               coords[list(idx)])
            if fit is not None:
                return fit
        return np.eye(3), np.zeros(3)

    def _paint_ghosts(self, p, meta, images, to_world):
        """Ghosts are FRAGMENTS, not dots — a scatter of circles says nothing
        about what the copy IS, while a faint skeleton of the asymmetric unit
        is instantly recognisable as the same thing moved.

        Each entry carries its OWN bond list (see `_ghost_images`): the copies
        are wrapped as whole molecules and their bonds re-tested in place, so
        a skeleton can no longer be drawn with lines reaching across the cell
        to the piece of itself that wrapped to the far face.

        Depth-cued like the glyphs: a dozen overlapping skeletons with no
        ordering is a hairball, and the near/far split is most of what makes
        it readable.
        """
        p.setBrush(Qt.NoBrush)
        for image, bonds in images:
            world = to_world(image)
            xy, front = self._project(world)
            for i, j in bonds:
                if not (front[i] and front[j]):
                    continue
                p.setPen(self._cued_pen(_GHOST_COLOR,
                                        (world[i] + world[j]) / 2.0, 1.3))
                p.drawLine(int(xy[i, 0]), int(xy[i, 1]),
                           int(xy[j, 0]), int(xy[j, 1]))
            for k in range(len(xy)):
                if front[k]:
                    p.setPen(self._cued_pen(_GHOST_COLOR, world[k], 1.3))
                    p.drawEllipse(int(xy[k, 0]) - 2, int(xy[k, 1]) - 2, 4, 4)

    def _eye_position(self):
        return self._camera_frame()["eye"]

    def set_depth_cue_extent(self, world_points):
        """Calibrate the depth cue against the thing being drawn.

        The cue used to be scaled by the CAMERA DISTANCE, which means a small
        cell viewed from a normal distance occupies a sliver of the range and
        every line comes out at nearly the same alpha — "the symmetry lines
        still have no depth cues, not that I can see at least". Normalising
        by the actual near-to-far spread of the overlay makes the nearest
        line always full strength and the furthest always faint, at any zoom.
        """
        pts = np.asarray(world_points, dtype=float).reshape(-1, 3)
        # Pin the eye for the whole overlay pass. `_depth_fade` needs it once
        # per segment, and going back through `_camera_frame` each time was
        # another few hundred dict lookups and key builds per frame.
        eye = self._eye_position()
        self._cue_eye = (float(eye[0]), float(eye[1]), float(eye[2]))
        if len(pts) < 2:
            self._cue_range = None
            return
        d = np.linalg.norm(pts - eye[None, :], axis=1)
        near, far = float(d.min()), float(d.max())
        self._cue_range = (near, far) if far - near > 1e-6 else None

    def _depth_fade(self, world_point):
        """0 (far) .. 1 (near) for a world point, for depth cueing.

        The symmetry overlay is 2D line art on top of a 3D scene, so nothing
        tells you which axis is in front — which defeats the purpose when the
        whole point is showing a 3D transformation. Fading and thinning the
        far ends restores the ordering without a depth buffer or a real AO
        pass, both of which would be a lot of machinery for line art.
        """
        # Plain scalar arithmetic, NOT numpy: this runs once per drawn
        # segment — a few hundred times a frame on a crystal — and at that
        # size the array allocation costs several times the maths itself.
        eye = self._cue_eye or self._eye_position()
        dx = float(world_point[0]) - eye[0]
        dy = float(world_point[1]) - eye[1]
        dz = float(world_point[2]) - eye[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        cue = self._cue_range
        if cue is not None:
            near, far = cue
            t = (dist - near) / (far - near)
            return min(max(1.0 - t, 0.06), 1.0)
        span = max(self.camera.distance, 1e-6)
        return min(max(1.0 - (dist - span * 0.4) / (span * 1.6), 0.12), 1.0)

    def _cued_pen(self, colour, world_point, width=1.6, style=Qt.SolidLine):
        """A depth-faded pen, MEMOISED on its quantised appearance.

        Constructing a QColor and a QPen per line segment was the other half
        of the symmetry overlay's cost. The fade is quantised to 64 steps —
        far finer than the eye can resolve in an alpha ramp — so a few hundred
        segments a frame collapse to a handful of distinct pens that are then
        reused for the life of the widget.
        """
        near = self._depth_fade(world_point)
        key = (colour.rgba(), int(near * 64.0), round(float(width), 2), style)
        pen = self._pen_cache.get(key)
        if pen is None:
            faded = QColor(colour)
            faded.setAlpha(int(70 + 185 * near))
            pen = QPen(faded, max(width * (0.45 + 0.55 * near), 0.7), style)
            if len(self._pen_cache) > 4096:      # paranoia, never reached
                self._pen_cache.clear()
            self._pen_cache[key] = pen
        return pen

    def _paint_symmetry_element(self, p, element, cell, to_world):
        from ..core import symmetry as sym_mod
        span = 0.5 * max(cell.a, cell.b, cell.c)
        centre_f = np.clip(element.point, -1.0, 2.0)
        if element.kind == sym_mod.INVERSION:
            world = to_world(centre_f[None, :])
            xy, front = self._project(world)
            if front[0]:
                p.setPen(self._cued_pen(_SYM_COLOR, world[0], 1.8))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(int(xy[0, 0]) - 4, int(xy[0, 1]) - 4, 8, 8)
            return
        if element.direction is None:
            return
        # Cartesian direction: a fractional axis must go through the cell
        # matrix or a non-cubic cell points it the wrong way.
        world_dir = np.asarray(element.direction, dtype=float) @ cell.matrix()
        norm = float(np.linalg.norm(world_dir))
        if norm < 1e-9:
            return
        world_dir /= norm
        centre = to_world(centre_f[None, :])[0]
        if element.is_axis:
            dashed = element.kind == sym_mod.SCREW
            style = Qt.DashLine if dashed else Qt.SolidLine
            # Drawn in depth-cued SEGMENTS so a line that recedes actually
            # fades along its length instead of being uniformly flat.
            steps = 12
            ends = None
            for k in range(steps):
                t0 = -1.0 + 2.0 * k / steps
                t1 = -1.0 + 2.0 * (k + 1) / steps
                a = centre + world_dir * span * t0
                b = centre + world_dir * span * t1
                seg = self._segment_screen(a, b)
                if seg is None:
                    continue
                (x0, y0), (x1, y1) = seg
                p.setPen(self._cued_pen(_SYM_COLOR, (a + b) / 2.0, 1.8, style))
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
                ends = (x1, y1, b)
            if ends is not None:
                p.setPen(self._cued_pen(_SYM_COLOR, ends[2], 1.6))
                self._paint_axis_glyph(p, ends[0], ends[1], element.order,
                                       dashed)
        else:
            # A plane: outline the quad where it cuts the cell.
            u = np.cross(world_dir, [0.0, 0.0, 1.0])
            if float(np.linalg.norm(u)) < 1e-6:
                u = np.cross(world_dir, [0.0, 1.0, 0.0])
            u /= np.linalg.norm(u)
            v = np.cross(world_dir, u)
            corners = [centre + u * span + v * span,
                       centre - u * span + v * span,
                       centre - u * span - v * span,
                       centre + u * span - v * span]
            dashed = element.kind == sym_mod.GLIDE
            style = Qt.DashLine if dashed else Qt.SolidLine
            for a, b in zip(corners, corners[1:] + corners[:1]):
                seg = self._segment_screen(a, b)
                if seg is None:
                    continue
                (x0, y0), (x1, y1) = seg
                p.setPen(self._cued_pen(_SYM_COLOR, (a + b) / 2.0, 1.4, style))
                p.drawLine(int(x0), int(y0), int(x1), int(y1))

    def _paint_axis_glyph(self, p, x, y, order, hollow):
        """The printed-table glyph: lens (2), triangle (3), square (4),
        hexagon (6). Hollow marks a screw axis."""
        x, y, r = int(x), int(y), 6
        p.setPen(QPen(_SYM_COLOR, 1.4))
        p.setBrush(Qt.NoBrush if hollow else _SYM_COLOR)
        if order == 2:
            p.drawEllipse(x - r, y - r // 2, 2 * r, r)
            return
        sides = {3: 3, 4: 4, 6: 6}.get(int(order))
        if sides is None:
            p.drawEllipse(x - r, y - r, 2 * r, 2 * r)
            return
        pts = []
        for k in range(sides):
            a = 2.0 * np.pi * k / sides - np.pi / 2.0
            pts.append(QPoint(int(x + r * np.cos(a)), int(y + r * np.sin(a))))
        p.drawPolygon(QPolygon(pts))

    def _paint_twist_axis(self, p):
        """The rotor's axis, drawn through the bond and out past both atoms.

        Without it the modal is a number and a molecule that moves: which bond
        it is turning about — and therefore which way the number goes — is
        exactly the thing that needs saying, and saying it in the viewport
        rather than in a banner is the round-21 lesson.
        """
        it = self._internal
        obj = self.scene.get(it["obj_id"]) if self.scene else None
        if obj is None:
            return
        c = obj.structure.coords
        anchor, pivot = it["picks"]
        if max(anchor, pivot) >= len(c):
            return
        a, b = np.asarray(c[anchor], dtype=float), np.asarray(c[pivot],
                                                              dtype=float)
        d = b - a
        n = float(np.linalg.norm(d))
        if n < 1e-9:
            return
        d = d / n
        seg = self._segment_screen(a - d * 2.5, b + d * 2.5)
        if seg is None:
            return
        (x0, y0), (x1, y1) = seg
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_ANCHOR_COLOR, 1.4, Qt.DashLine))
        p.drawLine(int(x0), int(y0), int(x1), int(y1))
        # A ring on the anchor: the end that does NOT move.
        xy, front = self._project(np.array([a]))
        if bool(front[0]):
            p.setPen(QPen(_ANCHOR_COLOR, 1.6))
            p.drawEllipse(int(xy[0, 0]) - 7, int(xy[0, 1]) - 7, 14, 14)

    def _paint_modal_prompt(self, p):
        """The active modal's instructions, drawn IN the viewport.

        These lived in the status bar, where a 4-second timeout and any
        other message wiped them out — so an align that was patiently
        waiting for an axis key looked like nothing was happening at all.
        """
        if self._internal is not None:
            it = self._internal
            text = "{}   [drag / scroll, type a number]   {}".format(
                it["state"].status_text().upper(),
                "left-click: SET    right-click / Esc: cancel")
            if it.get("about"):
                text = "{} ABOUT {}   —   {}".format(
                    it["state"].status_text().upper(), it["about"],
                    "left-click: SET    right-click / Esc: cancel")
            if it["blocked"]:
                text += "   — ring: only the last atom moves"
            self._draw_prompt(p, text)
            return
        if self._align_wait == "axis":
            text = "ALIGN PAIR TO AXIS   X / Y / Z"
        elif self._align_wait == "plane":
            text = ("ALIGN PLANE   X / Y / Z = plane perpendicular to it, "
                    "Shift+Z = XY")
        else:
            return
        # The tail changes once something is on screen, because that is when
        # the question changes from "which axis?" to "keep this?".
        if self._align_previewed is None:
            text += "    (right-click or Esc: cancel)"
        else:
            text = "{}  =  {}   [left-click: KEEP    right-click / Esc: " \
                   "revert    another key: try it]".format(
                       text.split("  ")[0], "XYZ"[self._align_previewed])
        self._draw_prompt(p, text)

    def _draw_prompt(self, p, text, colour=None):
        """One banner, centred along the bottom edge — shared by every modal
        so they cannot drift apart in position or styling."""
        f = QFont()
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        h = fm.height() + 10
        x = max((self.width() - w) // 2, 6)
        y = self.height() - h - 16
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(QRect(x, y, w, h), 5, 5)
        p.setPen(colour or _EDIT_ACCENT)
        p.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)

    def _paint_ligating(self, p):
        """Small violet dots on atoms marked as ligating, drawn on TOP like
        the origin handle: a template marker has to be findable from any
        angle, including through the molecule it sits on."""
        if self.scene is None:
            return
        from ..core import templates as tpl_mod
        for obj in self.scene.visible_objects():
            rows = tpl_mod.get_ligating(obj.structure)
            if not rows:
                continue
            coords = obj.structure.coords
            rows = [i for i in rows if i < len(coords)]
            if not rows:
                continue
            xy, front = self._project(coords[rows])
            for k in range(len(xy)):
                if not front[k]:
                    continue
                x, y = int(xy[k, 0]), int(xy[k, 1])
                p.setPen(QPen(QColor(20, 10, 30, 200), 1.2))
                p.setBrush(_LIGATING_COLOR)
                p.drawEllipse(x - 4, y - 4, 8, 8)

    def _paint_measure(self, p):
        """Ringed picks, the chain between them, and the value — drawn OVER
        the molecule, which is the one place it cannot be covered up."""
        if not self._measure_picks or self.scene is None:
            return
        pts = []
        for pick in self._measure_picks:
            c = self.scene.pick_coords(pick)
            if c is None:
                continue
            xy, front = self._project(np.asarray([c], dtype=float))
            if front[0]:
                pts.append((float(xy[0, 0]), float(xy[0, 1])))
        if not pts:
            return
        pen = QPen(_MEASURE_COLOR, 1.6, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for a, b in zip(pts, pts[1:]):
            p.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        for k, (x, y) in enumerate(pts):
            p.setPen(QPen(_MEASURE_COLOR, 2.0))
            p.drawEllipse(int(x) - 9, int(y) - 9, 18, 18)
            p.drawText(int(x) + 11, int(y) - 9, str(k + 1))
        text = self.measure_text()
        if not text:
            return
        f.setPixelSize(13)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        h = fm.height() + 8
        x = int(min(max(pts[-1][0] + 18, 8), max(self.width() - w - 8, 8)))
        y = int(min(max(pts[-1][1] + 14, 8), max(self.height() - h - 8, 8)))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 165))
        p.drawRoundedRect(QRect(x, y, w, h), 4, 4)
        p.setPen(_MEASURE_COLOR)
        p.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)

    def _paint_tumble_lock(self, p):
        """Dashed guide for an axis-locked anchored tumble (same look as the
        G/R constraint guides)."""
        e = self._tumble_axis_vector()
        if e is None or self._anchor_pos is None or len(self.selection) != 1:
            return
        anchor = self.scene.pick_coords(self.selection[0]) \
            if self.scene else None
        if anchor is None:
            return
        span = max(self.camera.distance * 25.0, 100.0)
        seg = self._segment_screen(anchor - e * span, anchor + e * span)
        if seg is None:
            return
        (x0, y0), (x1, y1) = seg
        p.setPen(QPen(_AXIS_COLORS[self._tumble_axis], 1.6, Qt.DashLine))
        p.drawLine(int(x0), int(y0), int(x1), int(y1))

    def _paint_labels(self, p):
        """Global element/index toggles PLUS the per-atom labels switched on
        in the outliner (those follow their object's label mode and may
        carry their own text and colour)."""
        if self.scene is None:
            return
        per_atom = any(o.atom_labels for o in self.scene.visible_objects())
        if not (self.show_labels_element or self.show_labels_index
                or per_atom):
            return
        self._ensure_pick_data()
        if self._flat_coords.shape[0] == 0:
            return
        xy, front = self._project(self._flat_coords)
        # Screen size of each atom: project a point one radius to the side,
        # so labels track zoom and perspective instead of staying a fixed
        # 8 pt no matter how close the camera is.
        r = quat_to_mat3(self.camera.rotation)
        right = r.T @ np.array([1.0, 0.0, 0.0])
        edge = self._flat_coords + right[None, :] * self._draw_radii[:, None]
        exy, _ef = self._project(edge)
        px_radius = np.linalg.norm(exy - xy, axis=1)

        dark_bg = sum(self.background) <= 1.5
        fg = QColor(235, 235, 235) if dark_bg else QColor(25, 25, 25)
        halo = QColor(0, 0, 0, 190) if dark_bg else QColor(255, 255, 255, 190)
        for k, (obj_id, i) in enumerate(self._atom_map):
            if not front[k]:
                continue
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            colour = fg
            if i in obj.atom_labels:
                text = obj.label_for(i)
                c = obj.atom_label_colors.get(i)
                if c is not None:
                    colour = QColor(int(c[0] * 255), int(c[1] * 255),
                                    int(c[2] * 255))
            else:
                parts = []
                if self.show_labels_element:
                    parts.append(obj.structure.symbols[i])
                if self.show_labels_index:
                    parts.append(str(i))
                text = "".join(parts)
            if not text:
                continue
            f = self._label_font(text, float(px_radius[k]))
            if f is None:
                continue
            p.setFont(f)
            fm = p.fontMetrics()
            rect = fm.boundingRect(text)
            # CENTRED on the atom, not offset diagonally off its edge
            x = int(xy[k, 0] - rect.width() / 2.0 - rect.x())
            y = int(xy[k, 1] - rect.height() / 2.0 - rect.y())
            p.setPen(halo)
            p.drawText(x + 1, y + 1, text)
            p.setPen(colour)
            p.drawText(x, y, text)

    def _label_font(self, text, px_radius, fill=_LABEL_FILL):
        """Font for an atom label. None = too small on screen to letter.

        Sized by the atom's RADIUS, not by the width of the text, so every
        label in a molecule comes out the same height — fitting each string
        to a fixed width instead made "C" 18 px and "C12" 6 px on identical
        atoms, which is what made index labels look broken. Text only shrinks
        when it would genuinely overhang the sphere.

        NOT bold, and in a naturally wide sans: bold at the old fit made
        every atom look shouted at.
        """
        size = px_radius * 2.0 * fill * self.label_scale
        if size < 6.0:                   # unreadable — don't clutter
            return None
        f = QFont()
        f.setFamilies(_LABEL_FAMILIES)
        f.setStyleHint(QFont.SansSerif)
        f.setPixelSize(int(round(size)))
        # Only long labels get squeezed, and only as far as the atom is wide.
        max_w = px_radius * 2.0 * _LABEL_MAX_WIDTH * self.label_scale
        width = QFontMetricsF(f).horizontalAdvance(text)
        if width > max_w > 0.0:
            size *= max_w / width
            if size < 6.0:
                return None
            f.setPixelSize(int(round(size)))
        return f

    def _paint_compass(self, p):
        """Blender-style axis gizmo, top-right. Hover makes the LETTERS glow
        white (fills stay put); negative balls are full-size with room for
        their '-X' labels. Clicking a ball aligns the view (hit list
        collected here, consumed in mousePressEvent)."""
        R = quat_to_mat3(self.camera.rotation)
        size = 42.0
        cx, cy = self.width() - size - 20.0, size + 20.0
        self._compass_hits = []
        items = []
        for axis in (0, 1, 2):
            e = np.zeros(3)
            e[axis] = 1.0
            d = R @ e
            for sign in (1, -1):
                items.append((axis, sign, d * sign))
        items.sort(key=lambda it: it[2][2])     # farthest first
        r = 9.5
        for axis, sign, d in items:
            x = cx + d[0] * size
            y = cy - d[1] * size
            col = _AXIS_COLORS[axis]
            self._compass_hits.append((x, y, r + 2.5, axis, sign))
            hover = self._compass_hover_item == (axis, sign)
            f = QFont()
            f.setBold(True)
            if sign > 0:
                p.setPen(QPen(col, 2.0))
                p.drawLine(int(cx), int(cy), int(x), int(y))
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawEllipse(int(x - r), int(y - r), int(2 * r), int(2 * r))
                f.setPointSize(8)
                p.setFont(f)
                p.setPen(QColor(255, 255, 255) if hover
                         else QColor(30, 30, 30))
                p.drawText(int(x - r), int(y - r), int(2 * r), int(2 * r),
                           Qt.AlignCenter, "XYZ"[axis])
            else:
                bg = QColor(int(self.background[0] * 255),
                            int(self.background[1] * 255),
                            int(self.background[2] * 255))
                p.setPen(QPen(col, 1.8))
                p.setBrush(bg)
                p.drawEllipse(int(x - r), int(y - r), int(2 * r), int(2 * r))
                if hover:                       # label (with minus) pops white
                    f.setPointSize(7)
                    p.setFont(f)
                    p.setPen(QColor(255, 255, 255))
                    p.drawText(int(x - r), int(y - r),
                               int(2 * r), int(2 * r), Qt.AlignCenter,
                               "-" + "XYZ"[axis])

    def _compass_hit_at(self, x, y):
        for hx, hy, hr, axis, sign in self._compass_hits:
            if (x - hx) ** 2 + (y - hy) ** 2 <= hr * hr:
                return axis, sign
        return None

    def _in_compass_area(self, x, y):
        size = 42.0
        cx, cy = self.width() - size - 18.0, size + 18.0
        return (x - cx) ** 2 + (y - cy) ** 2 <= (size + 14.0) ** 2

    def _paint_region(self, p):
        d = self._region_drag
        pen = QPen(QColor(255, 255, 255, 200), 1.0, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(QColor(120, 160, 255, 40))
        if d["kind"] == "box" and len(d["points"]) >= 2:
            (x0, y0), (x1, y1) = d["points"][0], d["points"][-1]
            p.drawRect(int(min(x0, x1)), int(min(y0, y1)),
                       int(abs(x1 - x0)), int(abs(y1 - y0)))
        elif d["kind"] == "lasso" and len(d["points"]) >= 2:
            poly = QPolygonF()
            for x, y in d["points"]:
                poly.append(QPointF(x, y))
            p.drawPolygon(poly)

    def _paint_modal_guides(self, p, state):
        """Blender-style constraint guides through the pivot: one line for an
        axis lock, two for a plane lock."""
        lines = []
        e = state.axis_vector() if hasattr(state, "axis_vector") else None
        # `getattr`, to match the plane branch below: not every modal state has
        # constraints (ScalarState has one degree of freedom and no axis), and
        # an AttributeError in here is invisible — paintGL swallows it and
        # prints, so the symptom is overlays that quietly stop drawing.
        if getattr(state, "axis", None) is not None and e is not None:
            lines.append((state.axis, e, state.axis_local))
        n = state.plane_normal() if hasattr(state, "plane_normal") else None
        if getattr(state, "plane_excl", None) is not None and n is not None:
            for k in (0, 1, 2):
                if k == state.plane_excl:
                    continue
                ee = (state.frame[:, k] if state.plane_local
                      else manipulate.AXES[k])
                lines.append((k, ee, state.plane_local))
        span = max(self.camera.distance * 25.0, 100.0)
        for axis_idx, e, _local in lines:
            seg = self._segment_screen(state.pivot - e * span,
                                       state.pivot + e * span)
            if seg is None:
                continue
            (x0, y0), (x1, y1) = seg
            p.setPen(QPen(_AXIS_COLORS[axis_idx], 1.6, Qt.DashLine))
            p.drawLine(int(x0), int(y0), int(x1), int(y1))

    def _paint_origin_gizmo(self, p):
        """Unreal-style transform gizmo: fat coloured axis arrows with cone
        tips plus quarter-circle arcs between each axis pair, all projected
        from 3D so it rotates with the frame."""
        obj = self.edit_object()
        if obj is None:
            return
        axes = obj.local_axes()
        L = 0.15 * self.camera.distance
        origin = obj.origin
        xy_o, front_o = self._project(origin[None, :])
        if not front_o[0]:
            return
        ox, oy = float(xy_o[0, 0]), float(xy_o[0, 1])
        # quarter-circle arcs between axis pairs, split so each half carries
        # its own axis colour (Unreal look)
        arc_r = 0.45 * L
        for i, j in ((0, 1), (1, 2), (2, 0)):
            ts = np.linspace(0.0, np.pi / 2.0, 15)
            pts3 = origin[None, :] + arc_r * (
                np.cos(ts)[:, None] * axes[:, i][None, :]
                + np.sin(ts)[:, None] * axes[:, j][None, :])
            xy, front = self._project(pts3)
            if not front.all():
                continue
            half = len(ts) // 2
            for seg, col in (((0, half + 1), _AXIS_COLORS[i]),
                             ((half, len(ts)), _AXIS_COLORS[j])):
                poly = QPolygonF()
                for k in range(seg[0], seg[1]):
                    poly.append(QPointF(xy[k, 0], xy[k, 1]))
                p.setPen(QPen(col, 2.6, Qt.SolidLine, Qt.RoundCap))
                p.setBrush(Qt.NoBrush)
                p.drawPolyline(poly)
        # axis arrows: fat shaft + filled cone head
        for k in range(3):
            tip3 = origin + axes[:, k] * L
            xy, front = self._project(np.vstack([origin, tip3]))
            if not front.all():
                continue
            x1, y1 = float(xy[1, 0]), float(xy[1, 1])
            d = np.array([x1 - ox, y1 - oy])
            n = np.linalg.norm(d)
            if n < 1e-6:
                continue                    # axis points at the camera
            d /= n
            perp = np.array([-d[1], d[0]])
            col = _AXIS_COLORS[k]
            p.setPen(QPen(col, 3.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(int(ox), int(oy),
                       int(x1 - d[0] * 9), int(y1 - d[1] * 9))
            head = QPolygonF()
            for px, py in ((x1 + d[0] * 3, y1 + d[1] * 3),
                           (x1 - d[0] * 10 + perp[0] * 5,
                            y1 - d[1] * 10 + perp[1] * 5),
                           (x1 - d[0] * 10 - perp[0] * 5,
                            y1 - d[1] * 10 - perp[1] * 5)):
                head.append(QPointF(px, py))
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawPolygon(head)
        p.setPen(QPen(QColor(240, 240, 240), 1.4))
        p.setBrush(QColor(200, 200, 200))
        p.drawEllipse(int(ox - 4), int(oy - 4), 8, 8)

    def _paint_anchor(self, p):
        """Avogadro-1 style yellow crosshair on the rotation anchor while
        (and shortly after) tumbling the molecule about it."""
        if self._anchor_pos is None or \
                time.monotonic() - self._anchor_flash_t > _ANCHOR_FLASH_S:
            return
        xy, front = self._project(self._anchor_pos[None, :])
        if not front[0]:
            return
        x, y = int(xy[0, 0]), int(xy[0, 1])
        r = 14
        p.setPen(QPen(_ANCHOR_COLOR, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(x - r, y - r, 2 * r, 2 * r)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(x + dx * (r - 4), y + dy * (r - 4),
                       x + dx * (r + 5), y + dy * (r + 5))

    # ------------------------------------------------------------------ input
    def _keyboard_captured(self):
        """True while some viewport state owns the keyboard. Shuttle counts:
        its W/A/S/D and Esc collide with the duplicate/align/cancel QActions,
        which would otherwise swallow them before keyPressEvent runs."""
        return (self.modal_active() or self._shuttle is not None
                or self._fly is not None
                or self._origin_active or self._draw_drag is not None)

    def event(self, ev):
        # During modals, keys like B/E/A/M/N must reach US, not the app's
        # single-letter QAction shortcuts.
        # (Edit mode used to swallow every unmodified letter for the element
        # buffer. Elements are picked from the periodic table now, so letters
        # are ordinary hotkeys in BOTH modes again — round 20.)
        if self._keyboard_captured():
            if ev.type() == QEvent.ShortcutOverride:
                ev.accept()
                return True
            # QWidget::event() eats Tab for focus navigation BEFORE
            # keyPressEvent runs, so route it ourselves while captured.
            if ev.type() == QEvent.KeyPress \
                    and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                self.keyPressEvent(ev)
                return True
        return super().event(ev)

    def mousePressEvent(self, ev):
        pos = ev.position()
        if self._internal is not None:
            # Same contract as G and R: left confirms, right cancels.
            self._finish_internal(commit=ev.button() == Qt.LeftButton)
            return
        if self._align_wait is not None:
            # LMB confirms the preview, RMB reverts it — the same contract as
            # G and R, which is the point of making this a preview at all.
            if ev.button() == Qt.RightButton:
                self._end_align_wait("Align cancelled", cancel=True)
            elif ev.button() == Qt.LeftButton:
                self._confirm_align()
            return
        if self._grab is not None:
            self._finish_grab(commit=ev.button() == Qt.LeftButton)
            return
        if self._rotate is not None:
            self._finish_rotate(commit=ev.button() == Qt.LeftButton)
            return
        if ev.button() == Qt.LeftButton:
            hit = self._compass_hit_at(pos.x(), pos.y())
            if hit is not None:
                self.align_view_axis(hit[0], hit[1])
                return
        self._drag_last = pos
        self._drag_button = ev.button()
        self._drag_moved = False
        self._press_pos = pos
        self._draw_from = None
        # RIGHT BUTTON = fly (UE5), but only once the press has PROVED it is
        # not a click — see `_arm_fly`.
        if ev.button() == Qt.RightButton and self._shuttle is None \
                and not self.modal_active():
            # A right press while already flying is the land gesture, whether
            # the flight is latched or still coasting after a release
            # (Christian: "cancel flight again with a single right click or
            # Esc").
            if self._fly is not None:
                self._cancel_fly_arm()
                self.stop_fly(coast=False)
                self.status_message.emit("Landed")
                return
            self._arm_fly(pos)
            return
        self._nav_drag = self._nav_drag_kind(ev.button(), ev.modifiers())
        if self._nav_drag is not None:
            return                       # a camera drag, never a pick or draw
        # Edit mode: pressing ON an atom arms the draw gesture. Dragging away
        # grows a new bonded atom (Avogadro's draw tool); releasing without
        # moving is a plain click and converts the atom instead. Arming on
        # PRESS is what keeps the two apart — a click's element change fires
        # on release, so a drag never triggers it.
        if ev.button() == Qt.LeftButton and self.mode == MODE_EDIT \
                and self.draw_tool_active and not self._origin_active \
                and not self._origin_dot_hit(pos):
            hit = self._pick_at(pos)
            obj = self.edit_object()
            if hit is not None and obj is not None \
                    and self._atom_map[hit][0] == obj.id:
                self._draw_from = self._atom_map[hit][1]

    @staticmethod
    def _nav_drag_kind(button, mods):
        """Camera drags, identical on both input presets.

        MMB is Blender's navigation button (Shift pans, Ctrl zooms); Alt+LMB
        repeats orbit for the many desktop mice whose middle button is a
        stiff scroll-wheel click.

        RMB no longer pans (round 34): it FLIES, which is what Christian asked
        for and what UE5 does. Pan is not lost — Shift+MMB and Shift+scroll
        both still pan on either input device — and hanging pan off a modified
        right-drag was rejected because every modifier that could carry it
        (Shift = boost, Ctrl = creep) already means something *inside* flight.
        Two meanings on one button, one of them shadowed by the mode it lives
        in, is worse than dropping a duplicate gesture.
        """
        if button == Qt.MiddleButton:
            if mods & Qt.ShiftModifier:
                return "pan"
            if mods & Qt.ControlModifier:
                return "zoom"
            return "orbit"
        if button == Qt.LeftButton and (mods & Qt.AltModifier):
            return "orbit"
        return None

    def mouseDoubleClickEvent(self, ev):
        # RIGHT double-click LATCHES flight: you fly with both hands free
        # until a single right click or Esc lands you, instead of holding the
        # button down. The first click of the pair already started an
        # ordinary held flight (see mousePressEvent), so this only has to
        # promote it — and cancel the context menu that first click deferred.
        if ev.button() == Qt.RightButton:
            if self._shuttle is not None or self.modal_active():
                return
            self._cancel_fly_arm()
            self.start_fly(latched=True)
            self._fly["released"] = False
            self._drag_last = ev.position()
            self._press_pos = ev.position()
            self.status_message.emit(
                "FLY (latched) — W/A/S/D thrust, Space/Ctrl up-down, Q/E "
                "roll, Shift boost, Alt creep; right click or Esc to land")
            return
        if ev.button() != Qt.LeftButton or self.modal_active():
            return
        if self._nav_drag_kind(ev.button(), ev.modifiers()) is not None:
            return
        pos = ev.position()
        if self._compass_hit_at(pos.x(), pos.y()):
            return
        self._dbl_pos = pos
        self._drag_last = pos
        self._drag_button = Qt.LeftButton
        self._drag_moved = False
        self._press_pos = pos
        # Double-click-drag draws too (same arming as a plain press-drag).
        self._draw_from = None
        self._dbl_empty = False
        if self.mode == MODE_EDIT and self.draw_tool_active \
                and not self._origin_active:
            hit = self._pick_at(pos)
            obj = self.edit_object()
            if hit is not None and obj is not None \
                    and self._atom_map[hit][0] == obj.id:
                self._draw_from = self._atom_map[hit][1]

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._fly_pending is not None:
            # Armed but not yet flying. Dragging is as clear a statement of
            # intent as waiting out the hold, so it takes off immediately —
            # otherwise a flick-and-fly would stall for a quarter second with
            # the mouse already moving.
            if self.fly_hold_ms > 0 \
                    and (abs(pos.x() - self._fly_pending.x())
                         + abs(pos.y() - self._fly_pending.y())) \
                    > _CLICK_SLOP_PX:
                self._begin_held_fly()
            return
        if self._fly is not None and not self._fly["released"]:
            # The delta is taken against the CAPTURED anchor (the viewport
            # centre), not against the previous position, and the pointer is
            # put straight back there. So the mouse can be swept as far as you
            # like in any direction without ever reaching an edge — no wrap,
            # nothing to snag on the properties dock, and steering that cannot
            # be interrupted by running out of screen.
            anchor = self.mapFromGlobal(self._fly_anchor)
            dx = pos.x() - anchor.x()
            dy = pos.y() - anchor.y()
            if dx or dy:
                self._fly["aim"].move(dx, dy,
                                      min(self.width(), self.height()))
                self._drag_moved = True
                QCursor.setPos(self._fly_anchor)
            return
        if self._internal is not None:
            self._internal["state"].set_precision(
                bool(ev.modifiers() & Qt.ShiftModifier))
            self._internal["state"].update_mouse(pos.x())
            self._apply_internal()
            self._wrap_cursor(pos)
            self._drag_last = pos
            return
        if self._grab is not None or self._rotate is not None:
            st = self._active_modal_state()
            st.set_precision(bool(ev.modifiers() & Qt.ShiftModifier))
            self._modal_mouse(pos)
            self._wrap_cursor(pos)
            return
        if self._draw_drag is not None:
            self._update_draw_drag(pos)
            return
        hover = self._in_compass_area(pos.x(), pos.y())
        # Only the ball actually under the cursor lights up (Blender), not
        # every label at once.
        ball = self._compass_hit_at(pos.x(), pos.y())
        bond = self._bond_at(pos) if self.mode == MODE_EDIT else None
        if (hover != self._compass_hover or ball != self._compass_hover_item
                or bond != self._hover_bond):
            self._compass_hover = hover
            self._compass_hover_item = ball
            self._hover_bond = bond
            self.update()
        if self._drag_last is None:
            return
        dx = pos.x() - self._drag_last.x()
        dy = pos.y() - self._drag_last.y()
        # Slop is CUMULATIVE from the press position: trackpads deliver 1-2 px
        # per event, so a per-event threshold never fired (box select bug).
        if self._press_pos is not None and \
                (abs(pos.x() - self._press_pos.x())
                 + abs(pos.y() - self._press_pos.y())) > _CLICK_SLOP_PX:
            self._drag_moved = True
        # Edit mode: double-click-drag from an atom grows a bonded atom that
        # then follows the mouse in the normal grab modal (so G/R/axis locks
        # and a click to confirm all work) — Avogadro's draw gesture with
        # Blender's confirmation model.
        if self._draw_from is not None and self._drag_moved:
            start = self._draw_from
            self._draw_from = None
            self._dbl_pos = None
            self._drag_last = None
            self._drag_button = None
            self._start_draw_drag(start, pos)
            return
        # (A double-click-drag builder on empty space was tried and removed:
        # it collided with box select, and clicking one atom then dragging
        # from it does the same job.)
        # Plain LEFT-DRAG is box select (Blender's default). This replaced the
        # double-click-drag-only trigger, which never fired reliably on a
        # trackpad; double-click-drag still works, and an armed lasso tool
        # takes over the same drag.
        if self._drag_button == Qt.LeftButton and self._drag_moved \
                and self._region_drag is None and self._nav_drag is None:
            self._region_drag = {"kind": self._select_tool or "box",
                                 "points": [(self._press_pos.x(),
                                             self._press_pos.y())],
                                 "additive": bool(ev.modifiers()
                                                  & Qt.ShiftModifier)}
        if self._region_drag is not None:
            self._region_drag["points"].append((pos.x(), pos.y()))
            self._drag_last = pos
            self.update()
            return
        w, h = max(self.width(), 1), max(self.height(), 1)
        if self._nav_drag == "orbit":
            self._orbit_input(dx, dy, cursor_pos=pos)
        elif self._nav_drag == "pan":
            self.camera.pan(dx, dy, w, h)
        elif self._nav_drag == "zoom":
            self.camera.zoom(-dy / _DRAG_ZOOM_PX)   # drag up = closer
        self._drag_last = pos
        self.update()

    def _start_chain_drag(self, pos):
        """Double-click-drag on EMPTY space: lay down a two-atom fragment and
        let the drag distance pick the bond order — pull far for a single
        bond (ethane once hydrogens fill in), squeeze for a double, squeeze
        harder for a triple. Ethyne < ethene < ethane, by feel."""
        obj = self.edit_object()
        if obj is None:
            return
        self._begin_edit()
        s = obj.structure
        origin, direction = self._ray_at(pos)
        depth = obj.origin if s.n_atoms else np.zeros(3)
        anchor = manipulate.ray_plane(origin, direction, depth,
                                      self._view_dir())
        if anchor is None:
            anchor = depth
        edits.add_atom(s, self.draw_element, anchor)
        first = s.n_atoms - 1
        edits.add_atom(s, self.draw_element,
                       anchor + np.array([1.5, 0.0, 0.0]), bond_to=first)
        self._draw_drag = {"obj_id": obj.id, "from": first,
                           "index": s.n_atoms - 1, "anchor": anchor.copy(),
                           "chain": True}
        self.set_selection([(obj.id, s.n_atoms - 1)])
        self.status_message.emit(
            "Drawing a {0}-{0} fragment — drag out for a single bond, "
            "squeeze in for double/triple".format(self.draw_element))
        self.refresh_geometry()

    def _start_draw_drag(self, from_idx, pos):
        """Avogadro-style drag-add: the new atom simply follows the cursor in
        the view plane through the anchor and is CONFIRMED on release (with
        hydrogens re-dressed). Deliberately NOT routed through the Blender
        grab modal — Christian asked for the plain Avogadro gesture, and the
        two fought each other. In an axis-aligned view the view plane is the
        screen plane, so dragging in a Z-locked view places atoms in XY."""
        obj = self.edit_object()
        if obj is None:
            return
        self._begin_edit()
        s = obj.structure
        # Dragging off a terminal HYDROGEN grows from the heavy atom it hangs
        # on, consuming the H — the new substituent takes its place, which is
        # both what a chemist means and what Avogadro does. Without this, a
        # freshly auto-filled CH4 puts hydrogens under the cursor and the
        # chain ends up bonded to an H.
        if elements.atomic_number(s.symbols[from_idx]) == 1:
            heavy = s.bonded_neighbors(from_idx)
            if len(heavy) == 1:
                anchor_idx = heavy[0]
                edits.delete_atoms(s, [from_idx])
                from_idx = anchor_idx - (1 if anchor_idx > from_idx else 0)
        start = s.coords[from_idx].copy()
        p = self._draw_plane_point(pos, start)
        edits.add_atom(s, self.draw_element, p, bond_to=from_idx)
        new_idx = s.n_atoms - 1
        self._draw_drag = {"obj_id": obj.id, "from": from_idx,
                           "index": new_idx, "anchor": start}
        self.set_selection([(obj.id, new_idx)])
        self.status_message.emit(
            "Drawing {} from {} — release to place".format(
                self.draw_element,
                self.scene.pick_label((obj.id, from_idx))))
        self.refresh_geometry()

    def _draw_plane_point(self, pos, anchor):
        """Cursor position projected onto the view plane through `anchor`.

        Only a hard floor is applied (atoms must not sit on top of each
        other); the pull toward a sensible length — and the bond order that
        comes with squeezing past it — is `_soft_snap`'s job."""
        origin, direction = self._ray_at(pos)
        p = manipulate.ray_plane(origin, direction, anchor, self._view_dir())
        if p is None:
            return anchor + np.array([1.5, 0.0, 0.0])
        v = p - anchor
        n = float(np.linalg.norm(v))
        obj = self.edit_object()
        want = 1.5
        if obj is not None and self._draw_drag is not None:
            want = edits.ideal_bond_length(obj.structure,
                                           self._draw_drag["from"],
                                           self._draw_drag["index"])
        floor = want * 0.5
        if n < floor:
            v = (v / n * floor) if n > 1e-6 else np.array([floor, 0.0, 0.0])
            p = anchor + v
        return p

    def _bond_at(self, pos, radius=0.28):
        """(obj_id, i, j) of the bond under the cursor, or None. Scoped to
        the edited molecule; used for hover-and-press-a-number."""
        obj = self.edit_object()
        if obj is None or not obj.structure.bonds:
            return None
        s = obj.structure
        p1 = np.array([s.coords[i] for i, _j, _o in s.bonds])
        p2 = np.array([s.coords[j] for _i, j, _o in s.bonds])
        origin, direction = self._ray_at(pos)
        # an atom under the cursor wins over the bonds behind it
        if self._pick_at(pos) is not None:
            return None
        k = picking.pick_segment(origin, direction, p1, p2, radius)
        if k is None:
            return None
        i, j, _o = s.bonds[k]
        return (obj.id, i, j)

    def set_hovered_bond_order(self, order):
        # type: (int) -> bool
        """Hover a bond and press 0-4: set that bond's order directly."""
        hb = self._hover_bond
        if hb is None:
            return False
        obj = self.scene.get(hb[0]) if self.scene else None
        if obj is None:
            return False
        self._begin_edit()
        if order <= 0:
            edits.remove_bond(obj.structure, hb[1], hb[2])
            note = "Bond removed"
        else:
            edits.add_bond(obj.structure, hb[1], hb[2], order=order)
            note = "Bond order {} ({}-{})".format(
                order, self.scene.pick_label((hb[0], hb[1])),
                self.scene.pick_label((hb[0], hb[2])))
        # Changing an order changes both atoms' free valence, so the hydrogen
        # count must follow — otherwise every order edit leaves the molecule
        # needing a manual H fix before it can be optimised.
        if self.adjust_h:
            added, removed = edits.adjust_hydrogens(obj.structure,
                                                    [hb[1], hb[2]])
            note += _h_note(added, removed)
        self.status_message.emit(note)
        self.edit_committed.emit()
        self.refresh_geometry()
        return True

    def _snap_target(self, pos, obj, skip_index, source_index, px=18.0):
        """Existing atom of `obj` under the cursor (ignoring the temp atom and
        the one we started from, and anything already bonded to the source) —
        this is what turns a drag onto a neighbour into a ring closure."""
        s = obj.structure
        if s.n_atoms == 0:
            return None
        xy, front = self._project(s.coords)
        bonded = set(s.bonded_neighbors(source_index))
        best, best_d = None, px * px
        for i in range(s.n_atoms):
            if i in (skip_index, source_index) or i in bonded or not front[i]:
                continue
            d = (xy[i, 0] - pos.x()) ** 2 + (xy[i, 1] - pos.y()) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    def _update_draw_drag(self, pos):
        """Follow the cursor, but with two pieces of guidance:

        * hovering an existing atom SNAPS the temp atom onto it (highlighted),
          so it is obvious the release will close a ring rather than drop an
          atom beside it;
        * otherwise the distance is soft-snapped toward the single-bond
          length — you can still squeeze in closer, and squeezing raises the
          bond order the way the geometry says it should.
        """
        d = self._draw_drag
        obj = self.scene.get(d["obj_id"]) if self.scene else None
        if obj is None:
            return
        s = obj.structure
        snap = self._snap_target(pos, obj, d["index"], d["from"])
        d["snap"] = snap
        if snap is not None:
            p = s.coords[snap].copy()
            order = 1
        else:
            p = self._draw_plane_point(pos, d["anchor"])
            p, order = self._soft_snap(p, d["anchor"], s, d["from"],
                                       d["index"])
        for k in range(s.n_frames):
            s.frames[k][d["index"]] = p
        k = s.find_bond(d["from"], d["index"])
        if k is not None and s.bonds[k][2] != order:
            a, b, _o = s.bonds[k]
            s.bonds[k] = (a, b, order)
        self.refresh_geometry()

    def _soft_snap(self, p, anchor, s, i, j):
        """Pull the length gently toward the ideal single bond and read a
        bond order off how far in the user squeezed (same length ratios the
        importer's order perception uses, so drawn and imported molecules
        agree)."""
        v = p - anchor
        n = float(np.linalg.norm(v))
        if n < 1e-6:
            return p, 1
        want = edits.ideal_bond_length(s, i, j)
        # dead zone: within 12% of ideal it locks on, further out it follows
        if abs(n - want) < want * 0.12:
            n_new = want
        else:
            n_new = n + (want - n) * 0.25
        ref = (bonding.covalent_radii([s.symbols[i]])[0]
               + bonding.covalent_radii([s.symbols[j]])[0])
        ratio = n_new / ref if ref > 0 else 1.0
        order = 3 if ratio < bonding.TRIPLE_RATIO else \
            2 if ratio < bonding.DOUBLE_RATIO else 1
        return anchor + v / n * n_new, order

    def _finish_draw_drag(self, pos=None):
        """Release: confirm the atom where it sits and re-dress hydrogens —
        unless it was dropped ON another atom, which CLOSES A RING (the temp
        atom is discarded and a bond to the target is made instead, the way
        Avogadro snaps)."""
        d = self._draw_drag
        self._draw_drag = None
        if d is None:
            return
        obj = self.scene.get(d["obj_id"]) if self.scene else None
        if obj is None:
            return
        if pos is not None:
            target = self._snap_target(pos, obj, d["index"], d["from"])
            if target is not None:
                edits.delete_atoms(obj.structure, [d["index"]])
                src = d["from"] - (1 if d["from"] > d["index"] else 0)
                tgt = target - (1 if target > d["index"] else 0)
                edits.add_bond(obj.structure, src, tgt, order=1)
                if self.adjust_h:
                    edits.adjust_hydrogens(obj.structure, [src, tgt])
                    edits.idealize_terminal_hydrogens(obj.structure, [src, tgt])
                self.set_selection([])       # see the note in the tail below
                self.status_message.emit("Ring closed: bonded {} to {}".format(
                    self.scene.pick_label((obj.id, src)),
                    self.scene.pick_label((obj.id, tgt))))
                self.edit_committed.emit()
                self.refresh_geometry()
                return
        added = removed = fixed = 0
        if self.adjust_h:
            # The SOURCE atom is included: its coordination just changed, so
            # its hydrogen count and their positions both need revisiting.
            added, removed = edits.adjust_hydrogens(
                obj.structure, [d["from"], d["index"]])
            fixed = edits.idealize_terminal_hydrogens(
                obj.structure, [d["from"], d["index"]])
        note = _h_note(added, removed)
        if fixed:
            note += "  ({} H re-placed)".format(fixed) if not note \
                else "  [{} H re-placed]".format(fixed)
        # An armed meta template makes the atom just drawn a coordination
        # centre, not merely an Xx dummy.
        if self.meta_template is not None:
            from ..core import meta as meta_mod
            meta_mod.set_meta(obj.structure, d["index"], self.meta_template)
            # Dress it immediately: a bare dummy shows nothing of the geometry
            # it enforces, so people free-draw a coordination number the spec
            # was never meant for.
            meta_mod.dress_with_hydrogens(obj.structure, d["index"],
                                          self.meta_template)
        # A drawing command leaves NOTHING selected. The atom you just drew is
        # already the element you asked for, so leaving it selected means the
        # next pick from the periodic table silently CONVERTS it instead of
        # just changing what the next atom will be — you lose the atom you
        # meant to keep and never see it happen.
        self.set_selection([])
        self.status_message.emit("Added {}{}".format(self.draw_element, note))
        self.edit_committed.emit()
        self.refresh_geometry()

    def mouseReleaseEvent(self, ev):
        if self._fly_pending is not None and ev.button() == Qt.RightButton:
            # Came up before the hold elapsed and without travelling: an
            # ordinary right CLICK. It opens the geometry menu straight away —
            # nothing is waiting on a possible double-click any more, because
            # flight is no longer something a single press can start.
            pos = self._fly_pending
            self._cancel_fly_arm()
            self._drag_last = None
            self._drag_button = None
            self._press_pos = None
            self.open_context_menu(pos)
            return
        if self._fly is not None and ev.button() == Qt.RightButton \
                and self._shuttle is None:
            # Latched flight ignores the button coming up — that is the whole
            # point of it. Landing is a fresh right PRESS, handled above.
            if self._fly.get("latched"):
                self._drag_button = None
                return
            self.stop_fly()
            self._drag_last = None
            self._drag_button = None
            self._press_pos = None
            return
        if self._draw_drag is not None:
            self._finish_draw_drag(ev.position())
            self._drag_last = None
            self._drag_button = None
            self._dbl_pos = None
            self._press_pos = None
            self._draw_from = None
            self._nav_drag = None
            return
        if self.modal_active():
            return
        if self._nav_drag is not None:
            # A camera drag never picks on release — Alt+click would
            # otherwise select whatever the orbit started over.
            self._nav_drag = None
            self._drag_last = None
            self._drag_button = None
            self._dbl_pos = None
            self._press_pos = None
            return
        if self._region_drag is not None and ev.button() == Qt.LeftButton:
            self._finish_region_select()
            self._drag_last = None
            self._drag_button = None
            self._dbl_pos = None
            self._press_pos = None
            return
        was_click = (self._drag_button == Qt.LeftButton
                     and not self._drag_moved)
        dbl = self._dbl_pos is not None
        self._drag_last = None
        self._drag_button = None
        self._dbl_pos = None
        self._press_pos = None
        self._draw_from = None
        if was_click and dbl:
            self._select_molecule_at(ev)
        elif was_click:
            self._click_pick(ev)

    def wheelEvent(self, ev):
        """Scroll: orbit on a trackpad, ZOOM on a notched mouse wheel;
        Ctrl = zoom and Shift = pan on both (see core/input_map.py).

        While the R modal runs, trackpad scroll ROTATES (the laptop path —
        Blender's move-the-mouse-around-the-pivot needs a mouse, which mouse
        users have); during any modal, plain scroll never orbits underneath
        the modal.
        """
        dx, dy = self._wheel_px(ev)
        ad = ev.angleDelta()
        mods = ev.modifiers()
        action = input_map.wheel_action(
            self.input_preset, not ev.pixelDelta().isNull(),
            ctrl=bool(mods & Qt.ControlModifier),
            shift=bool(mods & Qt.ShiftModifier))
        if self._shuttle is not None:
            # Steering by scroll, for the trackpad. Roll is NOT here: it used
            # to sit on Ctrl+scroll, was removed in round 34 because the
            # camera had no way back to level, and came back in round 35 on
            # Q/E as an explicit `FlightModel.roll` that zeroes on landing.
            # Scroll stays pure steering — one gesture, one meaning.
            if self._fly is not None:
                self._fly["aim"].move(dx * _WHEEL_STEER_PX,
                                      dy * _WHEEL_STEER_PX,
                                      min(self.width(), self.height()))
            return
        if self._fly is not None:
            # Scroll while the right button is down sets the CRUISING SPEED,
            # exactly as UE5 does. Zooming would fight the flying (both change
            # how fast the world comes at you) and steering is already the
            # mouse's job here — unlike the shuttle, where the mouse is busy.
            step = (ad.y() / _WHEEL_NOTCH) if ev.pixelDelta().isNull() \
                else dy / 40.0
            model = self._fly["model"]
            model.scale = float(np.clip(model.scale * (1.15 ** step),
                                        1e-3, 1e4))
            self.status_message.emit(
                "Flight speed x{:.2f}".format(model.scale
                                              / max(self._scene_scale(), 1e-9)))
            return
        if self._internal is not None:
            # Nudge the number, the same way scroll drives the R modal — the
            # trackpad path, where a precise horizontal drag is awkward.
            span = 0.02 if self._internal["kind"] == internal.DISTANCE else 1.0
            self._internal["state"].add_delta(np.sign(dy) * span)
            self._apply_internal()
            return
        if action == input_map.ZOOM:
            # A detent is a fixed 120 units, so a mouse zooms in even steps;
            # a trackpad's pixel deltas keep the continuous feel.
            self.camera.zoom((ad.y() / _WHEEL_NOTCH) if ev.pixelDelta().isNull()
                             else dy / 40.0)
        elif action == input_map.PAN:
            w, h = max(self.width(), 1), max(self.height(), 1)
            if ev.pixelDelta().isNull():
                sx, sy = ad.x() / _WHEEL_NOTCH, ad.y() / _WHEEL_NOTCH
                self.camera.pan(sx * _NOTCH_PAN_PX, sy * _NOTCH_PAN_PX, w, h)
            else:
                self.camera.pan(dx, dy, w, h)
        elif self._rotate is not None:
            rate = self.camera.rotate_speed * 2.0 * np.pi / Camera.PX_PER_REV
            # Sign marked for flipping if scroll-rotate feels inverted.
            self._rotate["state"].add_angle(-dy * rate)
            self._apply_rotate()
        elif self.modal_active():
            pass                        # no orbiting underneath G/origin edit
        else:
            # Sign: two-finger drag right/down turns the content the way a
            # grabbed trackball would. Flip here if it ever feels inverted.
            self._orbit_input(-dx, -dy, cursor_pos=ev.position())
        self.update()

    def render_image(self, scale=None, subdiv_bonus=None, transparent=True):
        """Offscreen render for image export.

        Differs from a framebuffer grab in three ways that matter for a
        figure: no viewport furniture (compass, origin dot, labels, grid,
        selection halos — none of it belongs in a published image), finer
        meshes (the interactive icosphere is deliberately cheap), and a
        resolution multiplier. Returns a QImage.
        """
        from PySide6.QtGui import QImage
        from PySide6.QtOpenGL import (QOpenGLFramebufferObject,
                                      QOpenGLFramebufferObjectFormat)
        scale = int(scale or self.render_scale)
        bonus = int(self.render_subdiv_bonus if subdiv_bonus is None
                    else subdiv_bonus)
        w = max(int(self.width() * scale), 1)
        h = max(int(self.height() * scale), 1)
        self.makeCurrent()
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        fmt.setSamples(4)
        fbo = QOpenGLFramebufferObject(w, h, fmt)
        fbo.bind()

        fine_sphere = fine_cyl = None
        try:
            if bonus > 0:
                fine_sphere = _InstancedMesh(*meshes.icosphere(
                    min(2 + bonus, 5)))
                fine_cyl = _InstancedMesh(*meshes.cylinder(
                    min(24 * (1 + bonus), 96)))
            saved = (self._sphere, self._cylinder)
            if fine_sphere is not None:
                self._sphere, self._cylinder = fine_sphere, fine_cyl
                self._needs_rebuild = True
                self._rebuild()
                self._needs_rebuild = True   # restore rebuilds for the screen

            GL.glViewport(0, 0, w, h)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_MULTISAMPLE)
            GL.glDisable(GL.GL_BLEND)
            if transparent:
                GL.glClearColor(0.0, 0.0, 0.0, 0.0)
            else:
                r, g, b = self.background
                GL.glClearColor(r, g, b, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            view = self.camera.view_matrix()
            proj = self.camera.projection_matrix(w, h)
            GL.glUseProgram(self._prog)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._prog, "uView"),
                                  1, GL.GL_TRUE, view)
            GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._prog, "uProj"),
                                  1, GL.GL_TRUE, proj)
            self._sphere.draw()
            self._cylinder.draw()
            image = fbo.toImage()
        finally:
            fbo.release()
            self._sphere, self._cylinder = saved
            self._needs_rebuild = True
            GL.glViewport(0, 0, max(self.width(), 1), max(self.height(), 1))
            self.doneCurrent()
            self.update()
        return image

    def enterEvent(self, ev):
        """Focus follows the cursor (Blender). Without this, a keypress after
        touching a side panel goes to that panel — pressing Space over the
        viewport would tab through the optimize dock instead of selecting the
        molecule you just optimised."""
        if not self.modal_active():
            self.setFocus(Qt.MouseFocusReason)
        super().enterEvent(ev)

    def _wheel_px(self, ev):
        """Scroll delta as smooth 'rotation pixels'.

        Precision trackpads report `pixelDelta` (fine-grained); a notched
        wheel only reports `angleDelta` in 1/8-degree units. Reading
        angleDelta as if it were pixels is what quantised every view change
        into ~40 degree jumps."""
        p = ev.pixelDelta()
        if not p.isNull():
            return float(p.x()), float(p.y())
        a = ev.angleDelta()
        return (a.x() / 8.0 * _WHEEL_DEG_TO_PX,
                a.y() / 8.0 * _WHEEL_DEG_TO_PX)

    def _tumble_axis_vector(self):
        # type: () -> Optional[np.ndarray]
        if self._tumble_axis is None:
            return None
        if self._tumble_local and self.selection and self.scene is not None:
            obj = self.scene.get(self.selection[0][0])
            if obj is not None:
                return obj.local_axes()[:, self._tumble_axis]
        return manipulate.AXES[self._tumble_axis]

    def cycle_tumble_axis(self, axis):
        # type: (int) -> None
        """X/Y/Z outside a modal with one atom selected: lock the anchored
        tumble to that axis (global -> object-local -> off, as in G/R)."""
        if self._tumble_axis != axis:
            self._tumble_axis, self._tumble_local = axis, False
        elif not self._tumble_local:
            self._tumble_local = True
        else:
            self._tumble_axis, self._tumble_local = None, False
        if self._tumble_axis is None:
            self.status_message.emit("Rotation axis lock cleared")
        else:
            self.status_message.emit(
                "Rotation locked to {}{} — scroll over the selected atom"
                .format("XYZ"[self._tumble_axis],
                        " (local)" if self._tumble_local else ""))
        self.update()

    def _cursor_on_anchor(self, cursor_pos):
        """True when the cursor is over the single selected atom. Starting a
        tumble requires this (round 6: scrolling in empty space used to spin
        the molecule from anywhere, which felt like the view had broken)."""
        if cursor_pos is None or self.scene is None or len(self.selection) != 1:
            return False
        hit = self._pick_at(cursor_pos)
        return hit is not None and self._atom_map[hit] == self.selection[0]

    def _orbit_input(self, dx_px, dy_px, cursor_pos=None):
        """Shared orbit entry (two-finger scroll and MMB drag).

        The camera-vs-tumble decision is made ONCE, when the gesture starts:
        with exactly one atom selected and the cursor already on it, the
        whole gesture tumbles that molecule; otherwise the whole gesture
        orbits the camera. Deciding per event was wrong — orbiting the view
        so that the cursor drifted onto the selected atom used to flip
        mid-gesture into rotating the molecule.
        """
        now = time.monotonic()
        if now - self._last_orbit_t > _GESTURE_GAP_S:
            self._gesture_mode = (
                "tumble" if (len(self.selection) == 1
                             and self._cursor_on_anchor(cursor_pos))
                else "camera")
            if self._gesture_mode == "tumble":
                self._begin_model_edit()   # one undo entry per gesture
        self._last_orbit_t = now
        anchor = (self._selection_pivot()
                  if self._gesture_mode == "tumble" else None)
        if anchor is None:
            self.camera.rotate(dx_px, dy_px)
            return
        self._last_model_rot_t = now
        self._anchor_flash_t = now
        self._anchor_pos = anchor.copy()
        rate = self.camera.rotate_speed * 2.0 * np.pi / Camera.PX_PER_REV
        r = quat_to_mat3(self.camera.rotation)
        locked = self._tumble_axis_vector()
        if locked is not None:
            # Locked: drag perpendicular to the axis spins it. Keeps an
            # axis-aligned ORTHOGRAPHIC view sane, where a free tumble reads
            # as random flipping.
            px = manipulate.axis_screen_drag(locked, r, dx_px, dy_px)
            rot = rotations.axis_angle_mat3(locked, px * rate)
        else:
            up_world = r.T @ np.array([0.0, 1.0, 0.0])
            right_world = r.T @ np.array([1.0, 0.0, 0.0])
            rot = (rotations.axis_angle_mat3(up_world, dx_px * rate)
                   @ rotations.axis_angle_mat3(right_world, dy_px * rate))
        for obj_id in sorted({p[0] for p in self.selection}):
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            for k in range(obj.structure.n_frames):
                obj.structure.frames[k] = rotations.rotate_points_about(
                    obj.structure.frames[k], rot, anchor)
            obj.origin = rotations.rotate_points_about(
                obj.origin[None, :], rot, anchor)[0]
            obj.orientation = quat_mul(quat_from_mat3(rot), obj.orientation)
        QTimer.singleShot(int(_ANCHOR_FLASH_S * 1000) + 60, self.update)
        self.edit_committed.emit()
        self.refresh_geometry()

    def _pick_at(self, pos):
        """Nearest atom under `pos`. In edit mode only the edited molecule's
        atoms are pickable (Blender scoping)."""
        if self.scene is None:
            return None
        self._ensure_pick_data()
        if self._flat_coords.shape[0] == 0:
            return None
        origin, direction = self._ray_at(pos)
        coords, radii, index_map = (self._flat_coords, self._flat_pick_radii,
                                    None)
        if self.mode == MODE_EDIT and self.edit_obj_id is not None:
            keep = [k for k, (o, _i) in enumerate(self._atom_map)
                    if o == self.edit_obj_id]
            if not keep:
                return None
            coords = self._flat_coords[keep]
            radii = self._flat_pick_radii[keep]
            index_map = keep
        hit = picking.pick_sphere(origin, direction, coords, radii)
        if hit is None:
            return None
        return index_map[hit] if index_map is not None else hit

    def _click_pick(self, ev):
        if self.scene is None:
            return
        pos = ev.position()
        # The measure tool owns clicks outright while it is armed, in BOTH
        # modes: it is a read-only inspection tool and must not disturb the
        # selection, the draw tool or the origin handle.
        if self.measure_active:
            self._measure_click(pos)
            return
        if self.mode == MODE_EDIT:
            # The origin handle takes clicks before anything else: on the dot
            # picks it up, anywhere else puts it down again (confirming).
            if self._origin_dot_hit(pos):
                if not self._origin_active:
                    self._begin_model_edit()
                self.set_origin_active(not self._origin_active)
                return
            if self._origin_active:
                self.set_origin_active(False)
                return
        hit = self._pick_at(pos)
        if hit is None and self.mode != MODE_EDIT \
                and not self._atom_map:
            if not (ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.set_selection([])
            return
        # In edit mode the draw tool owns plain clicks — but ONLY while it is
        # armed (E). Otherwise clicking empty space silently grew atoms.
        if self.mode == MODE_EDIT and self.draw_tool_active and not (
                ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
            self._draw_click(pos, hit)
            return
        additive = bool(ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if hit is None:
            if not additive:
                self.set_selection([])
            return
        pick = self._atom_map[hit]
        if additive:
            sel = list(self.selection)
            if pick in sel:
                sel.remove(pick)
            else:
                sel.append(pick)
            self.set_selection(sel)
        else:
            self.set_selection([pick])

    def _select_molecule_at(self, ev):
        """Double-click an atom: select its whole molecule. With Shift/Ctrl
        the molecule is ADDED to the selection instead of replacing it, so
        several molecules can be gathered for a merge or a joint transform."""
        if self.scene is None:
            return
        additive = bool(ev.modifiers() & (Qt.ControlModifier
                                          | Qt.ShiftModifier))
        hit = self._pick_at(ev.position())
        if hit is None:
            if not additive:
                self.set_selection([])
            return
        obj_id, _i = self._atom_map[hit]
        self.select_whole_molecules([obj_id], additive=additive)

    def select_whole_molecules(self, obj_ids, additive=False):
        # type: (List[int], bool) -> None
        sel = list(self.selection) if additive else []
        for obj_id in obj_ids:
            obj = self.scene.get(obj_id) if self.scene else None
            if obj is not None:
                sel += [(obj_id, i) for i in range(obj.structure.n_atoms)
                        if (obj_id, i) not in sel]
        self.set_selection(sel)

    def _finish_region_select(self):
        d = self._region_drag
        self._region_drag = None
        self.update()
        if d is None or self.scene is None or len(d["points"]) < 2:
            return
        self._ensure_pick_data()
        if self._flat_coords.shape[0] == 0:
            return
        xy, front = self._project(self._flat_coords)
        if d["kind"] == "box":
            (x0, y0), (x1, y1) = d["points"][0], d["points"][-1]
            mask = selection2d.points_in_rect(xy, x0, y0, x1, y1)
        else:
            mask = selection2d.points_in_polygon(xy, np.array(d["points"]))
        mask &= front
        picked = [self._atom_map[i] for i in np.flatnonzero(mask)]
        if d["additive"]:
            sel = list(self.selection)
            sel += [p for p in picked if p not in sel]
            self.set_selection(sel)
        else:
            self.set_selection(picked)

    def keyPressEvent(self, ev):
        key = ev.key()
        if self._shuttle is not None:
            if key == Qt.Key_Escape:
                self.stop_shuttle()
            elif not self._shuttle_key(key, down=True):
                super().keyPressEvent(ev)
            return
        # Flight thrust. Auto-repeat is IGNORED: the key set is what matters,
        # and re-adding it 30 times a second was the old step-per-press bug.
        if self._fly is not None and key in self._FLY_KEYS:
            if not ev.isAutoRepeat():
                self._fly["keys"].add(key)
                self._fly["released"] = False
            return
        if self._fly is not None and key in self._ROLL_KEYS:
            if not ev.isAutoRepeat():
                self._fly["roll_keys"].add(key)
                self._fly["released"] = False
            return
        # Esc lands a latched flight (a held one ends with the button).
        if self._fly is not None and key == Qt.Key_Escape:
            self.stop_fly(coast=False)
            self.status_message.emit("Landed")
            return
        if self._internal is not None:
            state = self._internal["state"]
            if key == Qt.Key_Escape:
                self._finish_internal(commit=False)
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._finish_internal(commit=True)
            elif key == Qt.Key_Backspace:
                state.backspace()
                self._apply_internal()
            elif state.type_char(ev.text()):
                self._apply_internal()
            return
        if self._align_wait is not None:
            # Bare modifier presses arrive as their OWN key events (holding
            # Shift for Shift+Z sends Key_Shift first) — swallow them, or the
            # wait cancels itself before the axis key ever lands.
            if key in _MODIFIER_KEYS:
                return
            if key in (Qt.Key_X, Qt.Key_Y, Qt.Key_Z):
                # PREVIEW: apply it and stay armed, so another axis key
                # simply replaces this one. The app re-applies from its own
                # snapshot, so previews never compound.
                axis = {Qt.Key_X: 0, Qt.Key_Y: 1, Qt.Key_Z: 2}[key]
                self._align_previewed = axis
                if self.on_align_key is not None:
                    self.on_align_key(self._align_wait, axis)
                self.update()
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._confirm_align()
            elif key == Qt.Key_Escape:
                self._end_align_wait("Align cancelled", cancel=True)
            # ANY OTHER KEY IS IGNORED. It used to cancel, so one stray
            # keypress silently abandoned the operation — and since the
            # prompt lived in the status bar it had usually expired by then,
            # leaving no clue what happened. Esc or right-click cancel;
            # nothing else does.
            return
        state = self._active_modal_state()
        if state is not None:
            if key == Qt.Key_Escape:
                self._finish_grab(False) if self._grab is not None \
                    else self._finish_rotate(False)
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._finish_grab(True) if self._grab is not None \
                    else self._finish_rotate(True)
            elif key in (Qt.Key_X, Qt.Key_Y, Qt.Key_Z):
                axis = {Qt.Key_X: 0, Qt.Key_Y: 1, Qt.Key_Z: 2}[key]
                if ev.modifiers() & Qt.ShiftModifier:
                    state.set_plane(axis)
                else:
                    state.set_axis(axis)
                self._reapply_modal()
            elif key == Qt.Key_Backspace:
                state.backspace()
                self._reapply_modal()
            elif state.type_char(ev.text()):
                self._reapply_modal()
            return
        if self._origin_active:
            if key in _MODIFIER_KEYS:
                return
            if key in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
                self.set_origin_active(False)
                return
            if key == Qt.Key_G:
                self.start_grab()       # full modal: locks, numbers, precision
                return
            if key == Qt.Key_R:
                self.start_rotate()
                return
        # O / Shift+O route through the app's QAction shortcuts
        # (O = origin handle in edit mode, Shift+O = projection toggle).
        if key == Qt.Key_G:
            self.start_grab()
            return
        if key == Qt.Key_R:
            self.start_rotate()
            return
        if key == Qt.Key_Escape:
            if not self.cancel_modes():
                super().keyPressEvent(ev)
            return
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            # Reaches us only while we hold the keyboard (origin handle,
            # draw drag, ...) — the app's Tab shortcut handles it otherwise.
            if self._origin_active:
                self.set_origin_active(False)
            if self.on_toggle_mode is not None:
                self.on_toggle_mode()
            else:
                self.toggle_mode()
            return
        text = ev.text()
        if self.mode == MODE_EDIT:
            # Elements are PICKED FROM THE PERIODIC TABLE, never typed
            # (round 20). Typing them meant edit mode had to swallow every
            # letter, which cost every letter hotkey and still could not spell
            # Ge (G starts a grab) — and the tool key `e` collided with the
            # tail of Ge/Fe/Be/He/Ne/Re/Se. Letters are plain hotkeys again.
            if key in _MODIFIER_KEYS:
                return
            if key == Qt.Key_Space:
                # after an edit, grab the whole molecule you are working on
                if self.edit_obj_id is not None:
                    self.select_whole_molecules([self.edit_obj_id])
                return
            if len(text) == 1 and text.isdigit():
                # a hovered bond wins over the selection
                if not self.set_hovered_bond_order(int(text)):
                    self.set_bond_order_selected(int(text))
                return
        else:
            if key in (Qt.Key_X, Qt.Key_Y, Qt.Key_Z) \
                    and len(self.selection) == 1:
                self.cycle_tumble_axis({Qt.Key_X: 0, Qt.Key_Y: 1,
                                        Qt.Key_Z: 2}[key])
                return
            if len(text) == 1 and text.isdigit() and len(self.selection) == 2:
                self.set_bond_order_selected(int(text))
                return
        if key == Qt.Key_F:     # Home/Pos1 now moves to the world origin
            self.fit_view()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if self._fly is not None and ev.key() in self._FLY_KEYS:
            # An auto-repeat release is Qt echoing the key, not the finger
            # leaving it — acting on it would cut thrust 30 times a second.
            if not ev.isAutoRepeat():
                self._fly["keys"].discard(ev.key())
            return
        if self._fly is not None and ev.key() in self._ROLL_KEYS:
            if not ev.isAutoRepeat():
                self._fly["roll_keys"].discard(ev.key())
            return
        state = self._active_modal_state()
        if state is not None and ev.key() == Qt.Key_Shift:
            state.set_precision(False)
            return
        super().keyReleaseEvent(ev)

    def _reapply_modal(self):
        if self._grab is not None:
            self._apply_grab()
        elif self._rotate is not None:
            self._apply_rotate()
