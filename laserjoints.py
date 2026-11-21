#!/usr/bin/env python3
from __future__ import annotations
import itertools
from math import asin, ceil, degrees, floor, pi, tan
import pprint
import re
import sys
import typing
import inkex
from inkex import elements
from inkex.base import SvgOutputMixin
from inkex.bezier import csplength
from inkex.elements._polygons import PathElement
from inkex.elements._selected import ElementList
from inkex.paths import Line, Move, Path, ZoneClose, line
from inkex.transforms import DirectedLineSegment, Transform

debugEn = False
svg = None

# flag side
FLAG_INSIDE = "inside"
FLAG_OUTSIDE = "outside"

# collection type
COLTYPE_LINE = "line"
COLTYPE_CURVE = "curve"

# wall element type
ELEM_LINE = "Line"
ELEM_CURVE = "Curve"


def debugMsg(input):
    if debugEn:
        inkex.utils.debug(input)


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


class Drawable:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_or_create_layer(self, layerid):
        layer = self.svg.getElement(
            f"//*[@inkscape:groupmode='layer' " f"and @inkscape:label='{layerid}']"
        )
        if layer is None:
            layer = self.svg.add(inkex.Layer.new(f"{layerid}"))
        layer.set("id", f"{layerid}")
        layer.style["display"] = "inline"
        return layer


class LaserJointsHelper:
    @staticmethod
    def cleanPath(path: inkex.Path, precision: int = 4):
        # cleanup and convert to superpath
        converted_path = path.to_absolute().to_non_shorthand().to_superpath().to_path()
        # round arguments to avoid 3.0000000001 situations.
        # and remove unneeded commands.
        newPath = inkex.Path()
        for subpath in converted_path.subpath_iterator():
            # step 1: round coordinates.
            tmpPath = inkex.Path()
            for seg in subpath.proxy_iterator():
                if seg.command.letter in "LMC":
                    rounded_args = [round(a, precision) for a in seg.command.args]
                    newCmd = type(seg.command)(*rounded_args)
                else:
                    newCmd = seg.command
                tmpPath.append(newCmd)

            # step 2 : remove zero-length lines and consecutive M or Z
            for seg in tmpPath.proxy_iterator():
                if (
                    seg.command.letter in "LC"
                    and seg.previous_end_point == seg.end_point
                ) or (
                    seg.command.letter in "MZ"
                    and seg.command.letter == seg.next_command.letter
                ):
                    continue
                newPath.append(seg.command)
        return newPath

    @staticmethod
    def get_element_layer(node: inkex.BaseElement) -> inkex.BaseElement:
        layers = [n for n in node.ancestors() if n.get("inkscape:groupmode") == "layer"]
        return layers[0] if len(layers) > 0 else None

    @staticmethod
    def draw_dls(dls: DirectedLineSegment, text: str = "", color: str = "red"):

        node = LaserJointsHelper.get_dls_element(dls, text=text, color=color)
        Config().svg.get_current_layer().add(node)

    @staticmethod
    def showCSP(csp, style=None):
        csp.to_path()
        p = inkex.PathElement()
        p.set_path(csp)
        p.style = (
            {
                "stroke": "red",
                "fill": "none",
                "stroke-width": Config().stroke_width,
            }
            if style is None
            else style
        )
        Drawable().laserWalls_layer.add(p)

    @staticmethod
    def get_dls_element(dls: DirectedLineSegment, text="", color="red"):
        group = inkex.Group()

        path = inkex.Path()
        path.append(Move(dls.start))
        path.append(Line(dls.end))
        a = dls.length * 0.25
        path.append(
            line((complex(dls.end - dls.start) / dls.length) * a * (complex(-0.5, 0.5)))
        )
        path.append(Move(dls.end))
        path.append(
            line(
                (complex(dls.end - dls.start) / dls.length) * a * (complex(-0.5, -0.5))
            )
        )
        elem = inkex.PathElement()
        elem.style = inkex.Style(
            {
                "stroke": color,
                "stroke-width": Config().stroke_width,
                "fill": "none",
                "stroke-linejoin": "round",
            }
        )
        elem.set_path(path)
        textElem = inkex.TextElement()
        textElem.text = text
        mid = dls.point_at_ratio(0.5)
        textElem.set("x", mid[0])
        textElem.set("y", mid[1])

        textElem.style = {
            "font-family": "Arial",
            "font-weight": "bold",
            "font-size": "8px",
            "fill": "black",
            "text-anchor": "middle",
            "dominant-baseline": "middle",
        }

        group.add(textElem)

        group.add(elem)
        return group

    @staticmethod
    def neutral_curve_csp(curve) -> inkex.CubicSuperPath:
        neutral_curve_csp = inkex.CubicSuperPath([])

        for k in range(0, 10 + 1, 5):
            t = k / 10

            if LaserJointsHelper.is_convex(curve, 0.5):
                d = Config().thickness * Config().kFactor
            else:
                d = Config().thickness * (1 - Config().kFactor)

            neutral_curve_csp.append(
                [
                    "L",
                    curve.point(t) + curve.unit_tangent(t) * complex(0, d),
                ]
            )
        return neutral_curve_csp

    @staticmethod
    def direction(vector: complex) -> complex:
        # A zero-length guide uses the positive x-axis.
        return vector / abs(vector) if vector else 1 + 0j

    @staticmethod
    def slot_outline(origin, span, thickness, kerf, reverse_normal):
        axis = LaserJointsHelper.direction(span)
        normal = axis * (1j if reverse_normal else -1j)
        along = axis * (abs(span) + kerf)
        across = normal * (thickness - kerf)
        corner = origin + kerf / 2 * (
            LaserJointsHelper.direction(along) + LaserJointsHelper.direction(across)
        )

        return Path(
            [
                Move(corner),
                Line(corner + along),
                Line(corner + along + across),
                Line(corner + across),
                Line(corner),
                ZoneClose(),
            ]
        )

    @staticmethod
    def getDeltaAngleDegree(prevAngle, curAngle):
        deltaAngle = round(prevAngle - curAngle, 1)
        deltaAngle = deltaAngle % 360
        if deltaAngle > 180:
            deltaAngle -= 360
        return deltaAngle

    @staticmethod
    def get_joints_segments(
        seg: inkex.DirectedLineSegment, collection: LaserFlagCollection, flipside: bool
    ):
        debugMsg(f"segment : {seg.previous_end_point}, {seg.end_point}")
        segCount, surroundingspaces = LaserJointsHelper.get_joints_distribution(
            seg.length(), collection
        )
        debugMsg(f"segCount: {segCount}, surroundingspaces: {surroundingspaces}")
        start, end, closePath = (
            complex(seg.previous_end_point.x, seg.previous_end_point.y),
            complex(seg.end_point.x, seg.end_point.y),
            (seg.letter in "zZ"),
        )

        edge = end - start
        edge -= LaserJointsHelper.direction(edge) * Config().kerf
        kerfLength = 0.0 if flipside else Config().kerf
        surroundingVector = (edge / seg.length()) * (surroundingspaces + kerfLength)

        fingerVector = (edge / seg.length()) * (
            collection.finger * Config().thickness - 2 * kerfLength
        )
        spaceVector = (edge / seg.length()) * (
            collection.space * Config().thickness + 2 * kerfLength
        )

        return (
            start,
            segCount,
            surroundingVector,
            fingerVector,
            spaceVector,
            closePath,
        )

    @staticmethod
    def get_joints_distribution(l, collection):

        finger_plus_space = (collection.finger + collection.space) * Config().thickness

        segCount = int(
            (l - (2 * collection.surroundingspaces) * Config().thickness)
            / finger_plus_space
        )
        if segCount == 0:
            # try to remove the surrounding spaces
            segCount = int(l / finger_plus_space)

        surroundingspaces = (
            l - segCount * finger_plus_space + collection.space * Config().thickness
        ) / 2

        debugMsg(
            f"space={finger_plus_space} segLength={l} segCount={segCount}, surroundingspaces={surroundingspaces}"
        )

        return segCount, surroundingspaces

    @staticmethod
    def draw_flag(
        coords: inkex.Vector2d, id: LaserFlagId, radius: int, color: inkex.Color
    ) -> inkex.Group:
        node = inkex.Group()
        node.set_id(id)
        node.set("class", "laserFlag")
        node.transform = inkex.Transform(f"translate({coords.x}, {coords.y})")
        # this rectangle is just here to provide better snap behaviour
        rectangle = inkex.Rectangle.new(-radius / 2, -radius / 2, radius, radius)
        rectangle.style = {"fill": "none", "stroke": "none"}
        node.add(rectangle)

        circle = inkex.Circle()
        circle.radius = radius
        circle.style = {"fill": color}
        node.add(circle)

        textElem = inkex.TextElement()
        textElem.text = id.short()
        fontsize = int(round(radius - 1.0, 0))
        textElem.style = {
            "font-family": "Arial",
            "font-weight": "bold",
            "font-size": f"{fontsize}px",
            "fill": "white",
            "text-anchor": "middle",
            "dominant-baseline": "middle",
        }
        node.style["opacity"] = 0.75
        node.add(textElem)
        return node

    @staticmethod
    # shoelace formula (also known as the signed area method).
    def get_path_direction(path: inkex.Path):
        path = path.to_absolute()
        points = []
        for seg in path.proxy_iterator():
            if not seg.command.letter in "zZ":
                points.append((seg.end_point.x, seg.end_point.y))

        if len(points) > 2:
            n = len(points)
            area = 0.0
            for i in range(n):
                x_i, y_i = points[i]
                x_j, y_j = points[(i + 1) % n]
                area += (x_j - x_i) * (y_j + y_i)
            return "CCW" if area > 0 else "CW"

        return None

    @staticmethod
    def convexity(seg: inkex.Path.PathCommandProxy, t: float = 0.5):
        # could also have been done with csparea, but computation is heavier.
        # we only check the convexity at the middle of the curve, which should be hopefully sufficient for our needs.
        # derivative

        d1 = seg.command.cderivative(
            seg.cfirst_point, seg.cprevious_end_point, seg.cprev2_control_point, t, 1
        )
        d2 = seg.command.cderivative(
            seg.cfirst_point, seg.cprevious_end_point, seg.cprev2_control_point, t, 2
        )

        convexity = d1.real * d2.imag - d1.imag * d2.real
        return convexity

    @staticmethod
    def inflection_time(seg: inkex.Path.PathCommandProxy) -> float:
        prev_convexity = None
        for t in range(101):
            convexity = LaserJointsHelper.convexity(seg, t / 100)
            if prev_convexity is not None and prev_convexity * convexity < 0:
                return t / 100

            prev_convexity = convexity
        return None

    @staticmethod
    def is_convex(seg: inkex.Path.PathCommandProxy, t: float = 0.5):
        return LaserJointsHelper.convexity(seg, t) < 0

    # iterates through a list and returns a tuple with (previous,current,next)
    @staticmethod
    def cycle_pcn(l: list):
        n = len(l)

        for i in range(0, n):
            yield (l[n - 1 if i - 1 < 0 else i - 1], l[i], l[i + 1 if i < n - 1 else 0])


class LaserFlagCollection:
    type: str
    id: int
    color: inkex.Color
    range: tuple[float, float]
    initialCount: int
    currentCount: int
    flagDiameter: float
    flags: dict[int, str]

    def __init__(self, type, id, color, range, count, surroundingspaces, finger, space):
        self.type = type
        self.id = id
        self.color = color
        self.range = (
            float(range[0]),
            float(range[1]) if range[1] is not None else None,
        )
        self.flagDiameter = Config().flagDiameter
        self.initialCount = count
        self.flags = {}

        self.currentCount = 0
        self.surroundingspaces = surroundingspaces
        self.finger = finger
        self.space = space

    def get_next_flag_num(self) -> int:
        self.currentCount = self.currentCount + 1
        return self.currentCount

    def add_flag(self, f: LaserFlag):
        if f.num not in self.flags:
            self.flags[f.num] = {}

        if f.type not in self.flags[f.num]:
            self.flags[f.num][f.type] = f

    def contains(self, f: LaserFlag):
        return f.num in self.flags and f.type in self.flags[f.num]

    def create_flags(self, x0, y0):
        x = x0
        for i in range(1, self.initialCount + 1):
            y = y0
            for t in "MFS":
                if not (i in self.flags and t in self.flags[i]):
                    f = LaserFlag(self, i, t, inkex.Vector2d((x, y)))
                    self.add_flag(f)
                    Drawable().laserFlags_layer.add(f.draw_flag())
                y = y + self.flagDiameter + 5
            x = x + self.flagDiameter + 5
        self.currentCount = self.initialCount

    def __repr__(self):
        return f"Collection {self.id}"

    def check_flags(self):
        messages = []
        for num, types in self.flags.items():
            if types is not None:
                segmentLength = None
                for t in types:
                    flag = types[t]
                    if len(flag.segments) > 1:
                        messages.add(
                            f"ERROR : flag {flag} matches multiple visible segments"
                        )

                    if flag.segment is not None:
                        if len(types) == 1:
                            messages.add(f"Warning : flag {flag} has no counterpart")

                        path, seg_id, dls = flag.segment
                        if dls is not None:
                            if segmentLength is None:
                                segmentLength = round(dls.length(), 2)
                            else:
                                if round(dls.length(), 2) != segmentLength:
                                    messages.add(
                                        f"ERROR : flags X{num:02d} match segments of different lengths {segmentLength}!={dls.length()}."
                                    )
        return messages


class LaserFlagId:
    collection_type: str
    collection_id: int
    type: str
    num: int

    def __init__(
        self,
        collection_id: LaserFlagCollection,
        type: str,
        num: int,
    ):
        self.collection_id = collection_id
        self.type = type
        self.num = num

    @staticmethod
    def from_string(strid):
        m = re.match(r"([LC][0-9])([MFS])([0-9][0-9])", strid)
        return LaserFlagId(m.group(1), m.group(2), int(m.group(3)))

    def __str__(self):
        return (
            f"{self.collection_id}{self.type}{self.num:02d}"
            if self.collection_id is not None
            else None
        )

    def short(self):
        return f"{self.type}{self.num:02d}"

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(other, LaserFlag):
            return (
                self.collection_id == other.collection_id
                and self.type == other.type
                and self.num == other.num
            )
        return False


class LaserFlag:
    collection: LaserFlagCollection
    node: inkex.Group
    id: LaserFlagId
    num: int
    type: str
    coords: inkex.Vector2d
    radius: float
    flagSide: str
    _status: str

    @property
    def status(self):
        if self.node is not None:
            return self.node.get(inkex.addNS("status", "laser"))
        return self._status

    @status.setter
    def status(self, value):
        self._status = value
        if self.node is not None:
            self.node.set(inkex.addNS("status", "laser"), self._status)

    # creates a laserflag from initial definition
    def __init__(
        self,
        collection: LaserFlagCollection,
        num: int,
        type: str,
        coords: inkex.Vector2d = None,
        dls: DirectedLineSegment = None,
        laserPart: LaserPart = None,
        flagSide: str = None,
    ):
        self.num = num
        self.type = type
        self.collection = collection
        self.node = None
        self.id = LaserFlagId(self.collection.id, self.type, self.num)
        self.flagSide = flagSide
        # radius = min(Config().flagDiameter / 2.0, dls.length / 3.0)
        if coords is None and dls is None and laserPart is None:
            raise Exception(
                "Laserflag() constructor needs either coords, seg, or laserPart"
            )

        if coords is not None:
            self.coords = coords
            self.radius = self.collection.flagDiameter / 2
        else:
            if dls is not None:
                self.radius = min(0.8 * dls.length, Config().flagDiameter) / 2
                self.coords = (
                    inkex.Vector2d(dls.point_at_ratio(0.5))
                    + (dls.vector * complex(0, 1) / dls.length)
                    * (1 if flagSide == FLAG_INSIDE else -1)
                    * self.radius
                    / 2
                )
            else:
                if laserPart is not None:
                    self.radius = (
                        min(0.8 * laserPart.length(), Config().flagDiameter) / 2
                    )
                    self.coords = (
                        laserPart.point(0.5)
                        + laserPart.unit_tangent(0.5)
                        * complex(0, 1)
                        * (1 if flagSide == FLAG_INSIDE else -1)
                        * self.radius
                        / 2
                    )

        if self.type == "M":
            self.flipside = True
        elif self.type == "F":
            self.flipside = False
        elif self.type == "S":
            self.flipside = False
        self.status = "New"

    def __eq__(self, cmp):
        return self.id == cmp.id

    def __hash__(self):
        return hash(repr(self))

    @staticmethod
    def get_flag_from_existing(
        collections: list[LaserFlagCollection], group: inkex.Group
    ):
        flagTypes = ["M", "F", "S"]
        flag = None
        id = LaserFlagId.from_string(group.get_id())
        if id.type not in flagTypes:
            debugMsg(f"flag type not recognized : {id.type}")

        # determine flag parameters.
        bbox = group.bounding_box(group.getparent().composed_transform())

        flag = LaserFlag(collections[id.collection_id], id.num, id.type, bbox.center)
        flag.radius = (
            bbox.width / 2.0
        )  # hopefully the user has kept proportions when resizing the flag :)
        flag.node = group
        return flag

    def changeType(self, newType):
        self.type = newType
        self.id = LaserFlagId(self.collection.id, self.type, self.num)
        if self.node is not None:
            self.node.set_id(str(self.id))
            n: inkex.BaseElement
            for n in self.node.getiterator():
                if isinstance(n, inkex.TextElement):
                    n.text = str(self.id.short())

    def move(self, coords):
        self.coords = coords
        self.node.transform = inkex.Transform(f"translate({coords.x}, {coords.y})")

    def __repr__(self) -> str:
        return f"C{self.collection.id}{self.type}{self.num:02d} R{self.radius:.1f} C({self.coords.x:.1f},{self.coords.y:.1f})"

    def draw_flag(self) -> inkex.Group:
        return LaserJointsHelper.draw_flag(
            self.coords, self.id, self.radius, self.collection.color
        )

    def get_mate_id(self) -> LaserFlagId:
        return LaserFlagId(
            collection_id=self.collection.id,
            type="M" if self.type in "FS" else "F",
            num=self.num,
        )


class DirectedLineSegmentExt(DirectedLineSegment):
    def perp_distance_signed(self, x, y):
        # type: (float, float) -> typing.Optional[float]
        """Perpendicular distance to the given point"""
        if self.length == 0:
            return None
        return ((self.dx * (self.y0 - y)) - ((self.x0 - x) * self.dy)) / self.length


class LaserPath(list):
    # will contain a list of LaserSubPaths
    def __init__(self, node: inkex.PathElement):
        self.node = node
        converted_path = LaserJointsHelper.cleanPath(
            node.path.transform(node.composed_transform())
        )

        for subpath in converted_path.subpath_iterator():
            self.append(LaserSubPath(subpath))

    def get_new_path(self):
        # return concat of subpaths
        newpath = []
        for laserSubPath in self:
            newpath.extend(laserSubPath.get_new_path())
        return Path(newpath)


class LaserSubPath(list):
    def __init__(self, path: inkex.Path):
        self.path = path
        self._to_parts()

    def _to_parts(self):
        curvelist = []
        self.endAngle = None

        for seg in self.path.proxy_iterator():
            if seg.command.letter == "M":
                continue

            if seg.command.letter == "C":
                if len(curvelist) > 0:
                    startAngle = degrees(
                        inkex.DirectedLineSegment(
                            seg.previous_end_point, seg.control_points[0]
                        ).angle
                    )
                    deltaAngle = LaserJointsHelper.getDeltaAngleDegree(
                        self.endAngle, startAngle
                    )
                    # debugMsg(
                    #     f"Start Angle = {startAngle}, endAngle={self.endAngle}, deltaAngle={deltaAngle}"
                    # )
                    if abs(deltaAngle) > 5:
                        self.append(LaserPartMultiCurve(curvelist))
                        self.endAngle = None
                        curvelist = []

                t = LaserJointsHelper.inflection_time(seg)
                if t is None:
                    curvelist.append(seg)
                else:
                    curvelist.extend(seg.split(t))

                self.endAngle = degrees(
                    inkex.DirectedLineSegment(
                        seg.control_points[1], seg.control_points[2]
                    ).angle
                )
                continue

            seg: Path.PathCommandProxy
            if seg.command.letter != "C":
                if len(curvelist) > 0:
                    self.append(LaserPartMultiCurve(curvelist))
                    curvelist = []

                self.append(LaserPartNonCurve(seg))

    def get_new_path(self):
        newpath = []

        for laserPart in self:
            if len(newpath) == 0:
                newpath.append(Move(laserPart.previous_end_point))
            newpath.extend(laserPart.draw_joints())
        # TODO : put again the ZoneClose.
        return newpath

    def mark(self, text):
        center = self.path.bounding_box().center
        textElem = inkex.TextElement()
        textElem.text = f"{text}"
        textElem.set("x", center.x)
        textElem.set("y", center.y)

        textElem.style = {
            "font-family": "Arial",
            "font-size": "6px",
            "fill": "black",
            "text-anchor": "middle",
            "dominant-baseline": "middle",
        }

        Drawable().laserTexts_layer.add(textElem)


class LaserPart:
    pass


class LaserPart:
    def __init__(self):
        self.flag: LaserFlag = None
        self.flagSide = None
        self._newPath = []

    def distance(self, point):
        # returns distance between self and point
        pass

    def draw(self, svg):
        pass

    def intersects(self, point: inkex.Vector2d, radius: float) -> bool:
        pass

    def perp_distance_signed(self, point: inkex.Vector2d) -> float:
        pass

    def maybe_link_flag(self, flag: LaserFlag, defaultSide: str):
        pass

    def point(self, time):
        pass

    def unit_tangent(self, time):
        pass


# Multicurve: replicate PathCommandProxy for multicurves
class LaserPartMultiCurve(LaserPart):

    def __init__(self, curves: list[Path.PathCommandProxy]):
        super().__init__()
        self.curves: list[Path.PathCommandProxy] = curves
        self.cumlengths = []
        self.curvetimes = []

        self.previous_end_point = curves[0].previous_end_point
        self.first_point = curves[0].first_point
        self.end_point = curves[-1].end_point
        cum_length = 0
        for c in curves:
            length = c.length()
            cum_length += length
            self.cumlengths.append(cum_length)

        self._length = cum_length
        self.curvetimes = [length / self._length for length in self.cumlengths]

        dls_start = inkex.DirectedLineSegment(
            curves[0].previous_end_point, curves[0].control_points[0]
        )
        self.startAngle = degrees(dls_start.angle)

        # LaserJointsHelper.draw_dls(dls_start, color="blue")
        dls_end = inkex.DirectedLineSegment(
            curves[-1].control_points[1], curves[-1].end_point
        )
        self.endAngle = degrees(dls_end.angle)
        # LaserJointsHelper.draw_dls(dls_end, color="red")

    def __repr__(self):
        return f"Multicurve: {self.curves}"

    def draw(self, svg):
        path = inkex.Path()
        # path.append(Move(self.previous_end_point))
        for c in self.curves:
            path.append(c.command)

        node = inkex.PathElement()
        node.set_path(path)
        node.style = {"stroke": "black"}
        svg.add(node)

    # naive algorithm
    # will not work for high curvatures.
    def neutral_curve_csp(self):
        csp = inkex.CubicSuperPath([])
        for c in self.curves:
            for k in range(0, 100 + 1, 5):
                t = k / 100

                if LaserJointsHelper.is_convex(c, 0.5):
                    d = Config().thickness * Config().kFactor
                else:
                    d = Config().thickness * (1 - Config().kFactor)

                csp.append(
                    [
                        "L",
                        c.point(t) + c.unit_tangent(t) * complex(0, d),
                    ]
                )
        # LaserJointsHelper.showCSP(csp)
        return csp

    def length(self, t1=0.0, t2=1.0):

        t1_pos = t1 * self._length
        t2_pos = t2 * self._length

        # find curve index for t1_pos
        i1 = 0
        while i1 < len(self.cumlengths) and self.cumlengths[i1] < t1_pos:
            i1 += 1
        # find curve index for t2_pos
        i2 = 0
        while i2 < len(self.cumlengths) and self.cumlengths[i2] < t2_pos:
            i2 += 1

        # Compute length
        length = 0.0
        if i1 == i2:
            # same curve
            curve = self.curves[i1]
            start = (
                t1_pos - (self.cumlengths[i1 - 1] if i1 > 0 else 0)
            ) / curve.length(0, 1)
            end = (t2_pos - (self.cumlengths[i1 - 1] if i1 > 0 else 0)) / curve.length(
                0, 1
            )
            length = curve.length(start, 1.0 if end > 1.0 else end)
        else:
            # different curves

            # Length between end of curve i1 to t1_pos
            curve = self.curves[i1]
            start = (
                t1_pos - (self.cumlengths[i1 - 1] if i1 > 0 else 0)
            ) / curve.length(0, 1)
            length += curve.length(start, 1)
            # Length of intermediary curves
            for i in range(i1 + 1, i2):
                length += self.curves[i].length(0, 1)
            # Length between end of curve i2 to t2_pos
            curve = self.curves[i2]
            end = (t2_pos - (self.cumlengths[i2 - 1] if i2 > 0 else 0)) / curve.length(
                0, 1
            )
            length += curve.length(0, 1.0 if end > 1.0 else end)
        return length

    def neutral_length(self):
        inset_length = csplength(self.neutral_curve_csp())[1]
        return inset_length

    def ilength(self, l):
        if l is None:
            return None
        if round(l, 2) > round(self._length, 2):
            raise (Exception(f"selflength={self._length} but ilength asked for {l}"))
        if l <= 0:
            return 0.0
        if l >= self._length:
            return 1.0

        # Trouver l'index de la courbe qui contient l
        i = 0
        while i < len(self.cumlengths) and self.cumlengths[i] < l:
            i += 1

        # Longueur relative dans la courbe i
        prev_length = self.cumlengths[i - 1] if i > 0 else 0
        local_l = l - prev_length
        curve = self.curves[i]

        # Appeler ilength sur la courbe
        t_local = curve.ilength(local_l)

        # Calculer t_global : somme des longueurs des courbes précédentes + t_local * longueur de la courbe courante, le tout divisé par total_length
        t_global = (prev_length + t_local * curve.length(0, 1)) / self._length
        return t_global

    def point(self, time):
        prev = 0
        for i, t in enumerate(self.curvetimes):
            if time <= t:
                return self.curves[i].point((time - prev) / (t - prev))
            prev = t
        return None

    def unit_tangent(self, time):
        prev = 0
        for i, t in enumerate(self.curvetimes):
            if time <= t:
                return self.curves[i].unit_tangent((time - prev) / (t - prev))
            prev = t
        return None

    def split(self, time):
        prev = 0
        l1 = []
        l2 = []
        if time == 0:
            return (LaserPartMultiCurve([]), LaserPartMultiCurve(self.curves))

        if time == 1.0:
            return (LaserPartMultiCurve(self.curves), LaserPartMultiCurve([]))

        for i, t in enumerate(self.curvetimes):
            c = self.curves[i]
            if len(l2) == 0:
                if time <= t:
                    s1, s2 = c.split((time - prev) / (t - prev))
                    l1.append(s1)
                    l2.append(s2)
                else:
                    l1.append(c)
            else:
                l2.append(c)
            prev = t
        return (LaserPartMultiCurve(l1), LaserPartMultiCurve(l2))

    def to_curves(self):
        return [c.to_curve() for c in self.curves]

    # get a chord startint at time [time] and that has length [length]
    def chord(self, time, length) -> tuple[float, DirectedLineSegment]:
        # initial conditions : look between t and 1.
        t0 = time
        t1 = 1
        startPoint = self.point(time)
        dls = DirectedLineSegment(startPoint, self.point(t1))

        for j in range(0, 50):
            if abs(dls.length - length) > 0.05:
                m = (t0 + t1) / 2
                dls = DirectedLineSegment(startPoint, self.point(m))
                if dls.length > length:
                    t1 = m
                else:
                    t0 = m
            else:
                break

        return (m if j < 50 else None, dls)

    def _distance_calc(
        self, point: inkex.Vector2d, stopIfCloserThan: float = 0.01
    ) -> float:
        debugMsg(locals())
        coarse_steps = 20
        fine_steps = 20

        # 1. coarse grain : find closest point on curve.
        sample_dists = [
            (
                c,
                t / coarse_steps,
                inkex.bezier.pointdistance(point, c.point(t / coarse_steps)),
            )
            for c in self.curves
            for t in range(0, coarse_steps + 1)
        ]
        min_dist = min([d for _, _, d in sample_dists])

        # 2. fine grain : look around the closest point
        c, t, _ = [(c, t, d) for c, t, d in sample_dists if d == min_dist][0]

        if min_dist <= stopIfCloserThan:
            return c, t, min_dist

        t_start = max(0.0, (t - 1 / coarse_steps))
        t_end = min(1.0, (t + 1 / coarse_steps))
        dt = t_end - t_start
        min_t = t

        for t2 in range(0, fine_steps + 1):
            t3 = t_start + dt * t2 / fine_steps
            dist = inkex.bezier.pointdistance(point, c.point(t3))
            if dist <= stopIfCloserThan:
                return c, t3, dist
            if dist < min_dist:
                min_dist = dist
                min_t = t3

        return c, min_t, min_dist

    # checks intersection with flag
    # 2 pass approach.
    def intersects(self, point: inkex.Vector2d, radius: float) -> bool:
        _, _, dist = self._distance_calc(point, radius)
        return dist <= radius

    def perp_distance_signed(self, point: inkex.Vector2d) -> float:
        c, t, d = self._distance_calc(point)
        seg1 = c.point(t) - point
        seg2 = c.unit_tangent(t)
        cross = seg2.cross(seg1)
        return (1 if cross > 0 else -1) * d

    def maybe_link_flag(self, flag: LaserFlag, defaultSide: str):
        debugMsg("Test curve")
        if self.intersects(flag.coords, flag.radius):
            self.flag = flag
            self.flagSide = defaultSide
            return True
        return False

    def draw_tabs(self):
        newPath = []
        config = Config()
        length = self.length()

        segCount, _ = LaserJointsHelper.get_joints_distribution(
            length, self.flag.collection
        )

        # ideally we should take the neutral curve to place our finger holes.
        # but it gets quite complex, so the choice here is to use the existing curve as a reference
        # and adjust the space (spaceSize) between the fingers taking the neutral curve in consideraton...
        fingerSize = config.thickness * self.flag.collection.finger
        totalFingerSize = segCount * fingerSize
        kFactorAdjust = (length - totalFingerSize) / (
            self.neutral_length() - totalFingerSize
        )
        spaceSize = config.thickness * self.flag.collection.space * kFactorAdjust
        surroundingspaces = (
            length - (segCount * (fingerSize + spaceSize) - spaceSize)
        ) / 2

        endPointTime = None

        for i in range(0, segCount):
            # calculate next start point for fingers
            startPointTime = self.ilength(
                surroundingspaces + i * (fingerSize + spaceSize)
            )
            if endPointTime is not None:
                # endPointTime=previous finger endpoint.
                # we need to add the curve from this endPointTime to current startPointTime.
                # split the original curve at startPointTime
                s1, _ = self.split(startPointTime)
                _, s4 = s1.split(s1.ilength(self.length(0, endPointTime)))
                newPath.extend(s4.to_curves())
            else:
                s1, _ = self.split(startPointTime)
                newPath.extend(s1.to_curves())

            # draw a straight line from start point, that has a length=finger size
            # and that is on the curve.
            endPointTime, dls = self.chord(
                startPointTime,
                self.flag.collection.finger * config.thickness - Config().kerf,
            )
            dlsvect = dls.vector / dls.vector.length
            # take the mean between startTangent and endTangent
            newPath.append(line(dlsvect * complex(0, config.thickness)))
            newPath.append(
                line(
                    dlsvect
                    * complex(
                        self.flag.collection.finger * config.thickness - Config().kerf,
                        0,
                    )
                )
            )

            newPath.append(Line(self.point(endPointTime)))

        if endPointTime is not None:
            _, s2 = self.split(endPointTime)
            newPath.extend(s2.to_curves())
            endPointTime = None

        return newPath

    def draw_joints(self):
        if self.flag is None:
            self._newPath = [c.command for c in self.curves]
        else:
            if self.flag.type == "F" or self.flag.type == "M":
                self._newPath = self.draw_tabs()
        return self._newPath


class LaserPartNonCurve(LaserPart):
    def __init__(self, seg):
        # debugMsg(f"creating LaserPartNonCurve for {seg}")
        super().__init__()
        self._seg = seg
        self._dls = DirectedLineSegmentExt(seg.previous_end_point, seg.end_point)
        self.previous_end_point = self._dls.start
        self.end_point = seg.end_point
        # LaserJointsHelper.draw_dls(self._dls)
        self.startAngle = degrees(self._dls.angle)
        self.endAngle = self.startAngle

    def length(self, t1=0.0, t2=1.0):
        return self._dls.length

    def __repr__(self):
        return str(self._seg)

    def point(self, time):
        return self._dls.point_at_ratio(time)

    def unit_tangent(self, time):
        return self._dls.vector / self._dls.vector.length

    def intersects(self, point: inkex.Vector2d, radius: float) -> bool:
        return abs(self._dls.distance_to_point(point.x, point.y)) <= radius

    def perp_distance_signed(self, point: inkex.Vector2d) -> float:
        return self._dls.perp_distance_signed(point.x, point.y)

    def getDirectedLineSegmentExt(self):
        return self._dls

    def draw_tabs(self):
        config = Config()
        flag = self.flag
        start, count, margin, finger, gap, closes = LaserJointsHelper.get_joints_segments(
            self._seg, flag.collection, flag.flipside
        )
        axis = LaserJointsHelper.direction(finger)
        rise = axis * (-1j if flag.flipside else 1j) * config.thickness
        crest = finger + axis * config.kerf
        spacing = gap - LaserJointsHelper.direction(gap) * config.kerf
        recessed = (
            (self.flagSide == FLAG_OUTSIDE and flag.type == "F")
            or (self.flagSide == FLAG_INSIDE and flag.type == "M")
        )

        start_command = Move if self._seg.letter in "mM" else Line
        commands = [start_command(start)]
        if recessed:
            commands.append(line(-rise))
        commands.append(line(margin))

        for index in range(count):
            if index:
                commands.append(line(spacing))
            commands.extend((line(rise), line(crest), line(-rise)))

        commands.append(line(margin))
        if recessed:
            commands.append(line(rise))
        if closes:
            commands.append(ZoneClose())
        return Path(commands)

    def draw_slots(self):
        debugMsg("DRAW_SLOTS")
        config = Config()
        reverse_normal = self.flagSide == FLAG_INSIDE
        start, count, margin, finger, gap, _ = LaserJointsHelper.get_joints_segments(
            self._seg, self.flag.collection, reverse_normal
        )

        position = start + margin - LaserJointsHelper.direction(finger) * config.kerf / 2
        commands = []
        for _ in range(count):
            outline = LaserJointsHelper.slot_outline(
                position, finger, config.thickness, config.kerf, reverse_normal
            )
            commands.extend(outline)
            position = position + gap + finger
        return commands

    def draw_joints(self):
        if self.flag is None:
            self._newPath = [self._seg.command]
        else:
            if self.flag.type == "F" or self.flag.type == "M":
                self._newPath = self.draw_tabs()
            else:
                if self.flag.type == "S":
                    self._newPath = self.draw_slots()
        return self._newPath

    def maybe_link_flag(self, flag: LaserFlag, defaultSide: str):

        # first check if the flag is within the bounds of the perpendiculars of the segment ends |----|.
        dls1 = DirectedLineSegment(self._dls.start, flag.coords)
        dls2 = DirectedLineSegment(self._dls.end, flag.coords)
        d1 = self._dls.dot(dls1)
        d2 = self._dls.dot(dls2)
        if d1 * d2 < 0:
            # if yes, check the perpandicular distance
            dist = self.perp_distance_signed(flag.coords)
            if abs(dist) <= flag.radius:
                self.flag = flag
                if dist > 0.05:
                    self.flagSide = FLAG_OUTSIDE
                else:
                    self.flagSide = FLAG_INSIDE
                return True
        return False


class WallRollElement:
    def __init__(self, topLeft: inkex.Vector2d):
        self.topLeft = topLeft
        self.elements = []

    def addElement(self, length, wallFlag: LaserFlag, elementType):
        self.elements.append(
            {"length": length, "wallFlag": wallFlag, "elementType": elementType}
        )
        pass

    def draw_face(self, text):
        # TODO : rewrite that with relative coords, this will be a lot clearer !
        curveHingeRectangles = []
        path = inkex.Path()
        path.append(Move(self.topLeft))
        path.append(line(Config().walls_height, 0))
        y = self.topLeft.y
        for element in self.elements:
            path.append(line(0, element["length"]))

            if element["elementType"] == ELEM_CURVE:
                rect = inkex.Rectangle()
                rect.set("x", self.topLeft.x)
                rect.set("y", y)
                rect.set("width", Config().walls_height)
                rect.set("height", element["length"])
                rect.style = inkex.Style(
                    {
                        "stroke": "black",
                        "stroke-width": Config().stroke_width,
                        "fill": "#FFAAAA",
                        "opacity": 0.5,
                    }
                )
                curveHingeRectangles.append(
                    rect
                )  # need to stack those so that they appear on top in the end.

            y += element["length"]

        path.append(line(-Config().walls_height, 0))
        for element in reversed(self.elements):
            path.append(line(0, -element["length"]))

        elem = inkex.PathElement()
        elem.style = inkex.Style(
            {
                "stroke": "black",
                "stroke-width": Config().stroke_width,
                "fill": "#FFEEAA",
            }
        )
        elem.set_path(path)
        Drawable().laserRolls_layer.add(elem)

        textElem = inkex.TextElement()
        textElem.text = f"{text}"
        textElem.set("x", self.topLeft.x + Config().walls_height / 2)
        textElem.set("y", (self.topLeft.y + y) / 2)

        textElem.style = {
            "font-family": "Arial",
            "font-size": str(min(Config().walls_height / 12, 3)) + "mm",
            "fill": "black",
            "text-anchor": "middle",
            "dominant-baseline": "middle",
        }

        Drawable().laserTexts_layer.add(textElem)

        # draw hinge Rectangles
        for e in curveHingeRectangles:
            Drawable().laserHinges_layer.add(e)

    def closeElement(self, index):
        self.draw_face(index)
        return self.topLeft.y + sum([e["length"] for e in self.elements])


class WallRoll(list):

    currentWall: WallRollElement

    def __init__(
        self, laserjoints: Laserjoints, rollStart: inkex.Vector2d, prefix: str
    ):

        self.index = 0
        self.prefix = prefix
        self.laserjoints = laserjoints
        self.config = Config()
        self.y = rollStart.y
        self.y0 = self.y
        self.y1 = self.y
        self.x = rollStart.x
        self.spacing = 2 * self.config.flagDiameter
        self.prevType = None
        self.prevJointType = None
        self.prevElementType = None
        self.prevWallFlag = None

        self.curFlag = None
        self.curLength = None

        self.prevFlag = None
        self.startPoint: inkex.Vector2d = None
        self.veryFirstFlag = None

        self.wall_collection = self.laserjoints.get_flag_collection_for_length(
            COLTYPE_LINE, self.config.walls_height
        )
        self.currentWall: WallRollElement = None

    def start(self, startJoinSide, length):
        self.index += 1
        self.currentWall = WallRollElement(
            topLeft=inkex.Vector2d(self.x - self.config.walls_height, self.y)
        )
        self.curLength = length

        self.startPoint = inkex.Vector2d(self.x, self.y)
        self.y1 = self.y

        flagType = "F" if self.prevFlag is None or self.prevFlag.type == "M" else "M"
        if startJoinSide is not None:
            self.curFlag = self.laserjoints.create_flag_in_collection(
                self.wall_collection,
                None if self.curFlag is None else self.curFlag.num,
                flagType,
                dls=inkex.DirectedLineSegment(
                    (self.x - self.config.walls_height, self.y), (self.x, self.y)
                ),
                flagSide=startJoinSide,
            )

            if self.veryFirstFlag is None and self.y == 0:
                self.veryFirstFlag = self.curFlag

    def close(self, endJoinSide, elementClose=False, finalClose=False):
        if elementClose or finalClose:
            self.currentWall.closeElement(f"{self.prefix}{self.index:02d}")
        # roll joints
        if endJoinSide is not None:

            collection = self.laserjoints.get_flag_collection_for_length(
                COLTYPE_LINE, self.config.walls_height
            )
            # flag at the bottom.
            self.curFlag = (
                self.laserjoints.create_flag_in_collection(
                    collection,
                    (
                        None
                        if self.curFlag is None
                        else (
                            self.veryFirstFlag.num
                            if self.veryFirstFlag is not None and finalClose
                            else collection.get_next_flag_num()
                        )
                    ),
                    "M" if self.curFlag is None else self.curFlag.type,
                    dls=inkex.DirectedLineSegment(
                        (self.x, self.y), (self.x - self.config.walls_height, self.y)
                    ),
                    flagSide=endJoinSide,
                )
                if collection is not None
                else None
            )

    def add_wall_flags(self, wallFlag, length):
        if wallFlag is None:
            return

        collection = wallFlag.collection

        self.laserjoints.create_flag_in_collection(
            collection,
            wallFlag.num,
            "M" if wallFlag.type == "F" else "F",
            dls=inkex.DirectedLineSegment((self.x, self.y), (self.x, self.y + length)),
            flagSide="outside",
        )

        if self.config.walls_join_both_sides:
            self.laserjoints.create_flag_in_collection(
                collection,
                wallFlag.num,
                "M" if wallFlag.type == "F" else "F",
                dls=inkex.DirectedLineSegment(
                    (self.x - self.config.walls_height, self.y + length),
                    (self.x - self.config.walls_height, self.y),
                ),
                flagSide="outside",
            )

    def add_element(
        self,
        wallFlag: LaserFlag,
        elementType,
        startJoinSide,
        length,
        endJoinSide,
        append: bool,
    ):
        # debugMsg(f"add_element : {locals()}")

        if self.currentWall is None:
            self.start(startJoinSide, length)
            self.currentWall = WallRollElement(
                inkex.Vector2d(self.x - self.config.walls_height, self.y)
            )
            self.prevType = None
            self.prevJointType = None
        else:
            if append == False:
                # close current path and start a new one.
                # debugMsg(f"Closing with prevJointType={self.prevJointType}")

                self.close(self.prevJointType, elementClose=True)
                self.y = (
                    self.y + self.spacing
                )  # + (self.lw.thickness if startJoinSide != "none" else 0)
                self.y0 = self.y
                self.y1 = self.y
                self.prevWallFlag = wallFlag
                self.prevFlag = self.curFlag
                self.start(startJoinSide, length)

        self.currentWall.addElement(length, wallFlag, elementType)
        self.add_wall_flags(wallFlag, length)

        self.y = self.y + length
        self.prevType = elementType
        self.prevJointType = endJoinSide
        self.prevElementType = elementType
        self.prevWallFlag = wallFlag


class LaserWalls:
    def __init__(self, laserjoints: Laserjoints):
        self.laserjoints = laserjoints

    def getFlagSide(self, deltaAngle):
        perpandicular_tolerance = Config().perpandicular_tolerance
        if abs(deltaAngle) < perpandicular_tolerance or (
            abs((deltaAngle % 90)) > perpandicular_tolerance
            and abs((deltaAngle % 90 - 90)) > perpandicular_tolerance
        ):
            flagSide = None
        else:
            if deltaAngle > 0:
                flagSide = FLAG_OUTSIDE
            else:
                flagSide = FLAG_INSIDE
        return flagSide

    # creates a grey wall along the original path.
    def createWall(self, laserpart: LaserPart, lengthOverride: float = None):
        wall_style = inkex.Style(
            {
                "fill": "gray",
                "opacity": 0.3,
                "stroke": "#000000",
                "stroke-width": Config().kerf,
            }
        )
        # for Lines
        if isinstance(laserpart, LaserPartNonCurve):
            rect = inkex.Rectangle()
            rect.set("x", 0)
            rect.set("y", 0)
            rect.set(
                "width",
                laserpart.length() if lengthOverride is None else lengthOverride,
            )
            rect.set("height", Config().thickness)
            rect.transform.add_translate(laserpart.previous_end_point)
            rect.transform.add_rotate(laserpart.startAngle)
            rect.style = wall_style
            Drawable().laserWalls_layer.add(rect)

        else:
            # for curves
            csp1 = inkex.CubicSuperPath([])
            c: inkex.Path.PathCommandProxy

            for c in laserpart.curves:
                if len(csp1) == 0:
                    csp1.append(Move(c.previous_end_point))
                csp1.append(c.command)

            csp2 = inkex.CubicSuperPath([])

            for c in reversed(laserpart.curves):
                for k in reversed(range(0, 100 + 1, 5)):
                    t = k / 100
                    csp2.append(
                        [
                            "L",
                            c.point(t)
                            + c.unit_tangent(t) * complex(0, Config().thickness),
                        ]
                    )

            csp1.append(Line(inkex.Vector2d(csp2[0][0][2])))
            csp2.append(Line(inkex.Vector2d(csp1[0][0][0])))
            csp1.extend(csp2)

            LaserJointsHelper.showCSP(csp1, style=wall_style)
            csp = laserpart.neutral_curve_csp()
            LaserJointsHelper.showCSP(
                csp,
                style={
                    "fill": "none",
                    "stroke": "red",
                    "stroke-width": Config().kerf,
                    "stroke-dasharray": "0.6,0.6",
                },
            )

        return inkex.Vector2d(laserpart.point(0.5))

    def walls(self):

        wallType = "F"
        node: inkex.PathElement

        # find intersecting segments and objects
        flag: LaserFlag
        # for each flag
        laserpath: LaserPath
        laserpaths = {}

        # add the flags to each matching LaserParts
        # and construct the list of laserpaths
        for node in self.laserjoints.all_path_nodes(self.laserjoints.selection):
            if node.is_visible():
                nodeId = node.get_id()
                laserpaths[nodeId] = LaserPath(node)
        j = 0
        # get the new paths and draw them
        for nodeId, laserpath in laserpaths.items():
            # objective here is to build the "unrolled_list"
            # which is an array of the segments with their lengths and angles.
            # we are also merging curves when possible, to make a single wall for a single curve.
            # when we have multiple curves, like in a "B" letter we need to break the curve in 2 parts.
            # we also have to consider "internal" curves like the curve at the bottom of the "R" letter.
            # the generated wall needs an additional length to cater for the curvature.

            for laserSubPath in laserpath:
                j += 1
                prefix = chr(64 + j)

                unrolled_list: list[LaserPart] = []
                rollStart = inkex.Vector2d(
                    -j * (Config().walls_height + 2 * Config().flagDiameter), 0
                )
                wallroll = WallRoll(self.laserjoints, rollStart, prefix)
                laserSubPath.mark(prefix)

                for laserPart in laserSubPath:

                    unrolled_list.append(laserPart)
                # Now build the walls with flags
                # checking the angles to determine flag sides and positions.

                for prev, cur, next in LaserJointsHelper.cycle_pcn(unrolled_list):
                    flag = None
                    if isinstance(cur, LaserPartNonCurve):
                        #                        debugMsg("# LINE")
                        startDeltaAngle = LaserJointsHelper.getDeltaAngleDegree(
                            prev.endAngle, cur.startAngle
                        )
                        endDeltaAngle = -LaserJointsHelper.getDeltaAngleDegree(
                            next.startAngle, cur.endAngle
                        )
                        startFlagSide = self.getFlagSide(startDeltaAngle)
                        endFlagSide = self.getFlagSide(endDeltaAngle)
                        # debugMsg(
                        #     f"===={prev.endAngle} {cur.startAngle} {startDeltaAngle:.02f}"
                        # )
                        # debugMsg(
                        #     f"===={next.startAngle} {cur.endAngle} {endDeltaAngle:.02f}"
                        # )

                        # create a wall
                        wallLength = cur.length()
                        if wallLength > 1e-3:
                            coords = self.createWall(cur)

                            collection = (
                                self.laserjoints.get_flag_collection_for_length(
                                    COLTYPE_LINE, wallLength
                                )
                            )

                            if collection is not None:
                                flagNum = collection.get_next_flag_num()
                                flag = self.laserjoints.create_flag_in_collection(
                                    collection, flagNum, wallType, laserPart=cur
                                )

                            wallroll.add_element(
                                flag,
                                ELEM_LINE,
                                startFlagSide,
                                wallLength,
                                endFlagSide,
                                append=abs(startDeltaAngle)
                                < Config().walls_to_curve_tolerance_degree,
                            )

                    if isinstance(cur, LaserPartMultiCurve):
                        #                        debugMsg("# CURVE")
                        length = cur.length()
                        coords = self.createWall(cur)
                        deltaAngle = LaserJointsHelper.getDeltaAngleDegree(
                            prev.endAngle, cur.startAngle
                        )

                        collection = self.laserjoints.get_flag_collection_for_length(
                            COLTYPE_CURVE, length
                        )
                        #                        debugMsg(f"###CURVE {collection.id}")

                        if collection is not None:
                            flagNum = collection.get_next_flag_num()
                            flag = self.laserjoints.create_flag_in_collection(
                                collection, flagNum, wallType, laserPart=cur
                            )

                        append = abs(deltaAngle) < 5

                        wallroll.add_element(
                            flag,
                            ELEM_CURVE,
                            None,
                            cur.neutral_length(),
                            None,
                            append=append,
                        )

                endDeltaAngle = -LaserJointsHelper.getDeltaAngleDegree(
                    next.endAngle, cur.startAngle
                )
                endFlagSide = self.getFlagSide(endDeltaAngle)
                wallroll.close(endFlagSide, finalClose=True)

class LaserDemo:
    def __init__(self,laserjoints):
        self.laserjoints=laserjoints
        
    @staticmethod
    def hide_demo():
        demoLayer=Drawable().svg.getElement(
            f"//*[@inkscape:groupmode='layer' " f"and @inkscape:label='laserDemo']"
        )
        if demoLayer is not None:
            demoLayer.style["display"] = "none"
    
    def demo(self):
        Drawable().laserDemo_Layer=Drawable().get_or_create_layer("laserDemo")
        width=50
        height=40
        fontSize=height/8
        xpadding=Config().flagDiameter
        ypadding=Config().flagDiameter
        Config().flagDiameter=Config().thickness*2
        x0=xpadding/2
        y0=ypadding/2
        collection1=self.laserjoints.get_flag_collection_for_length(COLTYPE_LINE,width)
        collection2=self.laserjoints.get_flag_collection_for_length(COLTYPE_LINE,height)
        ix,iy=(0,0)
        
        for f1side in [ FLAG_INSIDE, FLAG_OUTSIDE]:
            for f1type in ['M','F']:
                for f2side in [ FLAG_INSIDE, FLAG_OUTSIDE]:
                    for f2type in ['M','F']:
                        if ix>=iy or True:
                            rect=inkex.Rectangle().new(x0+ix*(xpadding+width),y0+iy*(ypadding+height),width,height)
                            rect.style={"fill":"none","stroke":"black","stroke-width":0.1}
                            pathElem=rect.to_path_element()
                            Drawable().laserDemo_Layer.add(pathElem)
                            for i,seg in enumerate(pathElem.path.proxy_iterator()):
                                if not seg.command.letter in 'Mm':
                                    debugMsg(seg.command)
                                    collection,flagtype,flagside=(collection1,f1type,f1side) if i % 2 ==0 else (collection2,f2type,f2side)
                                    self.laserjoints.create_flag_in_collection(
                                        collection,
                                        None,
                                        flagtype,
                                        dls=DirectedLineSegment(seg.previous_end_point,seg.end_point),
                                        flagSide=flagside
                                    )
                                    
                                    loc=seg.point(0.5)+seg.unit_tangent(0.5)*complex(0,1)*Config().thickness*2.1
                                    
                                    textElem1:inkex.TextElement=inkex.TextElement()
                                    textElem1=inkex.TextElement().new(f"{flagtype}/{'I' if flagside=='inside' else 'O'}")

                                    textElem1.set("x", loc.x)
                                    textElem1.set("y", loc.y)
                                    textElem1.style = {
                                        "font-family": "Arial",
                                        "font-size": fontSize,
                                        "fill": "black",
                                        "text-anchor": "middle",
                                        "dominant-baseline" : "middle"
                                    }


                                    Drawable().laserTexts_layer.add(textElem1)
                        ix+=1
                ix=0
                iy+=1
        
        
class Laserjoints(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument(
            "-t",
            "--tab",
            default="flags",
            help="flags or joints",
        )

        pars.add_argument(
            "-fa",
            "--flags_action",
            default="create",
            help="Flag actions : create / autocreate / check",
        )
        pars.add_argument(
            "-ja",
            "--joints_action",
            default="create",
            help="Joints actions : create / remove",
        )

        defaults = {
            "L1": {
                "color": "#ff0000",
                "minLength": 15,
                "surroundingspaces": 0,
                "finger": 1,
                "space": 2,
            },
            "L2": {
                "color": "#00ff00",
                "minLength": 40,
                "surroundingspaces": 1,
                "finger": 2,
                "space": 2,
            },
            "L3": {
                "color": "#0000ff",
                "minLength": 60,
                "surroundingspaces": 1,
                "finger": 3,
                "space": 3,
            },
            "C1": {
                "color": "#ff98ff",
                "minLength": 15,
                "surroundingspaces": 0,
                "finger": 1,
                "space": 3,
            },
            "C2": {
                "color": "#ff00ff",
                "minLength": 40,
                "surroundingspaces": 1,
                "finger": 2,
                "space": 4,
            },
            "C3": {
                "color": "#800080",
                "minLength": 60,
                "surroundingspaces": 2,
                "finger": 2,
                "space": 6,
            },
        }
        for i in defaults.keys():
            pars.add_argument(
                f"-col{i}",
                f"--flags{i}color",
                type=inkex.Color,
                default=defaults[i]["color"],
                help=f"tab group {i} : color",
            )
            pars.add_argument(
                f"-minLength{i}",
                f"--flags{i}minLength",
                type=int,
                default=defaults[i]["minLength"],
                help=f"tab group {i} : minLength",
            )

            pars.add_argument(
                f"-ss{i}",
                f"--flags{i}surroundingspaces",
                type=int,
                default=defaults[i]["surroundingspaces"],
                help=f"surroundingspaces",
            )

            pars.add_argument(
                f"-finger{i}",
                f"--flags{i}finger",
                type=int,
                default=defaults[i]["finger"],
                help=f"fingers",
            )

            pars.add_argument(
                f"-space{i}",
                f"--flags{i}space",
                type=int,
                default=defaults[i]["space"],
                help=f"space",
            )

        pars.add_argument(
            "-s", "--thickness", type=float, default=3.0, help="Material thickness"
        )
        pars.add_argument(
            "-kF", "--kFactor", type=float, default=0.5, help="k-factor for bends"
        )
        pars.add_argument(
            "-k", "--kerf", type=float, default=0.10, help="Measured kerf of cutter"
        )
        pars.add_argument(
            "-fd", "--flagDiameter", type=float, default=10.0, help="Flag max diameter"
        )
        pars.add_argument(
            "-fc", "--flagCount", type=int, default=10, help="Flag diameter"
        )

        pars.add_argument(
            "-flagSide",
            "--flagSide",
            default=FLAG_INSIDE,
            help="flags location for autocreate : inside / outside",
        )

        # pars.add_argument("-u", "--units", default="mm", help="Measurement units")

        pars.add_argument(
            "-wa",
            "--walls_action",
            default="create",
            help="Walls actions : create / remove",
        )

        pars.add_argument(
            "-ta",
            "--tweaks_action",
            default="tweaks_swapMF",
            help="Tweaks actions : tweaks_swapMF, tweaks_inside, tweaks_outside",
        )

        pars.add_argument(
            "-wh", "--walls_height", type=float, default=50.0, help="Walls height"
        )

        pars.add_argument(
            "-wjs",
            "--walls_join_both_sides",
            type=inkex.Boolean,
            default=True,
            help="Walls join on both sides",
        )

        # self.debug(" ".join(sys.argv))

    def find_laser_flags(self) -> list[LaserFlag]:
        return [
            LaserFlag.get_flag_from_existing(self.collections, e)
            for e in self.svg.getElementsByClass("laserFlag")
        ]

    def nodes_sorted_by_area(self):
        nodes_by_area = {}
        # Heuristic = not necessary but works better
        # index nodes by area, as we prefer to start analyzing their segments first
        # because those will most likely be in the center of the design

        for node in self.selection.get(inkex.PathElement):
            if node.is_visible():
                nodes_by_area[node.bounding_box().area] = node

        for area in sorted(nodes_by_area.keys(), reverse=True):
            yield nodes_by_area[area]

    # def create_graph(self):
    #     # collect flag segments
    #     flags_nodes_by_nodeId = {}
    #     flags_nodes_by_flag_id = {}

    #     for flag in self.laser_flags:
    #         # find matching segments (if all is fine, only one segment should match)
    #         for node, seg_id, seg in self.flag_matching_segments(flag):
    #             flag.add_matched_laserpart(node, seg_id, seg)
    #             flags_nodes_by_flag_id[str(flag.id)] = (flag, node)
    #             nodeId = node.get_id()
    #             if nodeId not in flags_nodes_by_nodeId:
    #                 flags_nodes_by_nodeId[nodeId] = []
    #             flags_nodes_by_nodeId[nodeId].append((flag, node))

    #     # create graph
    #     graph = {}
    #     node: inkex.BaseElement
    #     for node in self.nodes_sorted_by_area():
    #         nodeId = node.get_id()
    #         if nodeId not in graph:
    #             graph[nodeId] = []
    #         flag: LaserFlag
    #         for flag, node in flags_nodes_by_nodeId[nodeId]:
    #             flag2, node2 = flags_nodes_by_flag_id[str(flag.get_mate_id())]
    #             # dls:PathCommandProxy
    #             path1, num1, cmd1 = flag.part
    #             cmd1: Path.PathCommandProxy
    #             dls1 = DirectedLineSegment(
    #                 Transform.apply_to_point(
    #                     node.composed_transform(), cmd1.previous_end_point
    #                 ),
    #                 Transform.apply_to_point(node.composed_transform(), cmd1.end_point),
    #             )

    #             path2, num2, cmd2 = flag2.segment
    #             dls2 = DirectedLineSegment(
    #                 Transform.apply_to_point(
    #                     node2.composed_transform(), cmd2.previous_end_point
    #                 ),
    #                 Transform.apply_to_point(
    #                     node2.composed_transform(), cmd2.end_point
    #                 ),
    #             )

    #             graph[nodeId].append((node2.get_id(), dls1, dls2))

    #     nodeId1 = "rect1"
    #     debugMsg(f"{nodeId1} : {graph[nodeId1]}")
    #     node1: inkex.PathElement
    #     node2: inkex.PathElement
    #     dls1: DirectedLineSegment
    #     dls2: DirectedLineSegment
    #     debugMsg(f"dls1={dls1}")
    #     debugMsg(f"dls2={dls2}")

    #     for nodeId2, dls1, dls2 in graph[nodeId1]:
    #         debugMsg(f"###### Processing {nodeId2}")
    #         # nodeId2, dls1, dls2 = graph[nodeId1][0]
    #         flag1, node1 = flags_nodes_by_nodeId[nodeId1][0]
    #         flag2, node2 = flags_nodes_by_nodeId[nodeId2][0]

    #         t2: inkex.Transform = node2.transform

    #         node2.transform = (
    #             -node2.getparent().composed_transform()
    #             @ Transform()
    #             .add_translate(dls1.x0 - dls2.x1, dls1.y0 - dls2.y1)
    #             .add_rotate(-degrees(pi + dls2.angle - dls1.angle), dls2.end)
    #             @ node2.getparent().composed_transform()
    #             @ node2.transform
    #         )

    #     # node1.transform.add_rotate(30,0,0)

    def check_laser_flags(self):
        self.msg("# Checking flags")

        for i, c in self.collections.items():
            self.msg(f"### {c}")
            messages = c.check_flags()
            for m in messages:
                self.msg(m)

        # check same segments length
        # check not multiple segment that matches for one flag
        # check for segments that match multiple flags
        # check not S+F+M

    def path_segments(self, path):
        for seg_id, seg in enumerate(path.proxy_iterator()):
            if not seg.command.letter in "mM":
                dls = DirectedLineSegmentExt(seg.previous_end_point, seg.end_point)
                if dls is not None:
                    yield seg_id, seg, dls

    # returns node segments matching a given flag.
    # sets the flag direction based on the side of the flag
    def flag_node_matching_segments(
        self, flag: LaserFlag, node: inkex.BaseElement, laserpaths
    ):
        # we need this one with the transforms applied to get the distance to the flag.

        if node.is_visible():
            # debugMsg(f"checking node {node.get_id()}")
            # bounding box coordinates will be relative to the node parent
            ptransf = node.getparent().composed_transform()
            bbox = node.bounding_box(ptransf).resize(flag.radius, flag.radius)

            # debugMsg(f"flag coords = {flag.coords}")
            # debugMsg(f"bbox = {bbox}")
            # uncomment this to debug boundingbox
            # r = inkex.Rectangle.new(
            #     bbox.left, bbox.top, bbox.width, bbox.height
            # )
            # r.style="fill:none;stroke-width: 1;stroke: #000000;"
            # self.svg.append(r)

            if (
                flag.coords.x >= bbox.left
                and flag.coords.x <= bbox.right
                and flag.coords.y <= bbox.bottom
                and flag.coords.y >= bbox.top
            ):
                # debugMsg(f"flag {flag} is inside bbox of {node.get_id()}")
                nodeId = node.get_id()
                if nodeId not in laserpaths:
                    laserpath = LaserPath(node)
                    laserpaths[nodeId] = laserpath
                else:
                    laserpath = laserpaths[nodeId]

                for laserSubPath in laserpath:
                    laserpart: LaserPart
                    for laserpart in laserSubPath:
                        if laserpart.maybe_link_flag(
                            flag, defaultSide=Config().flagSide
                        ):
                            # debugMsg("*** MATCH ***")
                            break

    def all_path_nodes(self, selection) -> typing.Iterator[inkex.BaseElement]:
        # returns all the nodes that are not in a laser* layer
        node: inkex.PathElement
        for node in selection.get(inkex.PathElement):
            layer = LaserJointsHelper.get_element_layer(node)
            if layer is None or not (layer.get_id() in self.ignore_layers):
                yield node
            # else:
            #     debugMsg(f"ignoring {node.get_id()} because it is in layer {layer.get_id()}")

    def flag_matching_segments(self, selection, flag, laserpaths):
        # process all level 1 (layers) elements
        # debugMsg(f"####### Flag {flag}")
        for node in self.all_path_nodes(selection):
            # debugMsg(f"Looking for matching segments in {node.get_id()}")
            self.flag_node_matching_segments(flag, node, laserpaths)

        return laserpaths

    def flags_swap_side(self, flagSide):
        flag: LaserFlag
        laserpath: LaserPath
        laserpaths = {}

        elementList = ElementList(self.svg)
        elementList.add("//*")

        for flag in self.laser_flags:
            self.flag_matching_segments(elementList, flag, laserpaths)

        # get the new paths and draw them
        laserpath: LaserPath
        for nodeId, laserpath in laserpaths.items():
            # debugMsg(f"NODE : {nodeId}={laserpath}")
            for lasersubpath in laserpath:
                laserpart: LaserPart
                for laserpart in lasersubpath:
                    if (
                        laserpart.flag is not None
                        and laserpart.flag.node in self.svg.selection
                    ):
                        dist = laserpart.perp_distance_signed(laserpart.flag.coords)
                        if (flagSide == FLAG_INSIDE and dist > 0) or (
                            flagSide == FLAG_OUTSIDE and dist < 0
                        ):
                            # using the tangent in the middle of the segment
                            # would be better if perp_distance_signed would return the closest point on the curve.
                            laserpart.flag.move(
                                laserpart.flag.coords
                                + laserpart.unit_tangent(0.5) * complex(0, 1) * 2 * dist
                            )

    def flags_draw_joints(self):
        # {'01': {'M': Vector2d(280.791, 129.944), 'F': Vector2d(339.074, 129.944), 'S': Vector2d(20.6687, 251.759)}}

        # find intersecting segments and objects
        flag: LaserFlag
        laserpath: LaserPath
        laserpaths = {}

        # add the flags to each matching LaserParts
        # and construct the list of laserpaths
        for flag in self.laser_flags:
            self.flag_matching_segments(self.selection, flag, laserpaths)

        # get the new paths and draw them
        for nodeId, laserpath in laserpaths.items():
            debugMsg(f"NODE : {nodeId}={laserpath}")
            new_path = laserpath.get_new_path()
            node = PathElement()
            node.set_path(new_path)
            node.style = {
                "stroke": "black",
                "stroke-width": Config().stroke_width,
                "fill": "none",
            }
            Drawable().laserJoints_layer.add(node)

    def create_flags_auto(self):
        # build a dict where key=length, value = node, segment_id, segment
        segments_by_length = {}

        for node in self.nodes_sorted_by_area():
            pathlen = sum(1 for _ in node.path.control_points)
            for seg_id, seg, dls in self.path_segments(
                node.path.transform(node.composed_transform())
            ):
                length = round(dls.length, 2)
                if length > 0:
                    if length not in segments_by_length:
                        segments_by_length[length] = []
                    if pathlen > 2:
                        segType = "M"
                    else:
                        segType = "S"

                    segments_by_length[length].append(
                        {
                            "node": node,
                            "seg_id": seg_id,
                            "dls": dls,
                            "pathlen": pathlen,
                            "type": segType,
                            "status": "new",
                        }
                    )

        # remove entries where there is only one segment
        for key in list(segments_by_length.keys()):
            if len(segments_by_length[key]) < 2:
                del segments_by_length[key]

        # propose assignment

        for key, candidates in segments_by_length.items():
            debugMsg(f"length: {key}")
            for seg1 in candidates:
                if seg1["status"] == "new":
                    debugMsg(
                        f"- {seg1['node'].get_id()},{seg1['seg_id']},{seg1['dls'].length}"
                    )
                    node: inkex.BaseElement = seg1["node"]
                    seg_id: int = seg1["seg_id"]
                    dls: DirectedLineSegment = seg1["dls"]
                    seg1_center = inkex.Vector2d(dls.point_at_ratio(0.5))

                    # now try to assign female part.
                    # find closest candidate that is not on the same path.
                    mindist = 100000.0
                    seg2 = None
                    for seg in candidates:
                        if (
                            seg != seg1
                            and seg["status"] == "new"
                            and not (seg["node"].get_id() == seg1["node"].get_id())
                            and not (
                                seg1["type"] == "S"
                                and seg2 is not None
                                and seg2["type"] == "S"
                            )
                        ):
                            dls: DirectedLineSegment = seg["dls"]
                            dist = dls.distance_to_point(seg1_center.x, seg1_center.y)
                            if dist < mindist:
                                mindist = dist
                                seg2 = seg

                    if seg2 is not None:
                        seg1["status"] = "assigned"

                        collection1 = self.get_flag_collection_for_length(
                            COLTYPE_LINE, key
                        )
                        flag1 = (
                            self.create_flag_in_collection(
                                collection1,
                                None,
                                seg1["type"],
                                dls=seg1["dls"],
                                flagSide=Config().flagSide,
                            )
                            if collection1 is not None
                            else None
                        )
                        if flag1 is not None:
                            seg1["flagid"] = flag1.id  # used only for report at the end
                            if seg2["type"] != "S":
                                if seg1["type"] == "M":
                                    segType2 = "F"
                                else:
                                    segType2 = "M"
                            else:
                                segType2 = "S"
                            seg2["type"] = segType2
                            seg2["status"] = "assigned"

                            node: inkex.BaseElement = seg2["node"]
                            seg_id: int = seg2["seg_id"]
                            dls: DirectedLineSegment = seg2["dls"]
                            collection2 = self.get_flag_collection_for_length(
                                COLTYPE_LINE, key
                            )

                            if collection2 is not None:
                                flag2 = self.create_flag_in_collection(
                                    collection2,
                                    flag1.num,
                                    seg2["type"],
                                    dls=seg2["dls"],
                                    flagSide=Config().flagSide,
                                )
                                seg2["flagid"] = (
                                    flag2.id
                                )  # used only for report at the end

        for key, candidates in segments_by_length.items():
            debugMsg("----------------------------")
            debugMsg(f"Length = {key}")
            for seg in candidates:
                if seg["status"] == "assigned":
                    if "flagid" in seg:
                        debugMsg(
                            f"{seg['flagid']} : node={seg['node'].get_id()},seg_id={seg['seg_id']}, pathlen={pathlen}"
                        )

    def init_doc(self):
        drawable = Drawable()
        drawable.laserConfig_layer = drawable.get_or_create_layer("laserConfig")
        drawable.laserWalls_layer = drawable.get_or_create_layer("laserWalls")
        drawable.laserRolls_layer = drawable.get_or_create_layer("laserRolls")
        drawable.laserHinges_layer = drawable.get_or_create_layer("laserHinges")
        drawable.laserFlags_layer = drawable.get_or_create_layer("laserFlags")
        drawable.laserJoints_layer = drawable.get_or_create_layer("laserJoints")
        drawable.laserTexts_layer = drawable.get_or_create_layer("laserTexts")
        self.ignore_layers = ["laserFlags", "laserWalls"]
        self.svg.add_namespace("laser", "https://github.com/chgarde/laserjoints")
        self.dump_config_to_layer()
        drawable.laserConfig_layer.style["display"] = "none"

    def get_flag_collection_for_length(
        self, type, segment_length
    ) -> LaserFlagCollection:
        c: LaserFlagCollection
        keys_for_type = [id for id, c in self.collections.items() if c.type == type]

        for id in keys_for_type:
            c = self.collections[id]
            min, max = c.range
            if (segment_length >= min) and (max is None or segment_length < max):
                return c

        return None

    def create_flag_in_collection(
        self,
        collection: LaserFlagCollection,
        num,
        type,
        dls: DirectedLineSegment = None,
        laserPart: LaserPart = None,
        flagSide: str = FLAG_INSIDE,
    ):
        if num is None:
            num = collection.get_next_flag_num()

        flag = LaserFlag(
            collection, num, type, dls=dls, laserPart=laserPart, flagSide=flagSide
        )
        collection.add_flag(flag)
        Drawable().laserFlags_layer.add(flag.draw_flag())
        debugMsg(f"flag created {flag.id}")
        return flag

    def fix_path_direction(self):
        for node in self.all_path_nodes(self.selection):
            dir = LaserJointsHelper.get_path_direction(node.path)
            if dir is not None:
                if dir == "CCW":
                    node.path = node.path.reverse()

    # swap Males and Females
    def swapMF(self):
        laser_flags_by_id = {}
        for f in self.laser_flags:
            laser_flags_by_id[str(f.id)] = f

        for flag1 in self.laser_flags:
            if flag1.node in self.selection:
                flag1Type = flag1.type

                if flag1Type not in "MF":
                    continue

                flag1Id = str(flag1.id)
                flag2Id = str(flag1.get_mate_id())

                if flag2Id in laser_flags_by_id:
                    # if flag has a mate then swap both of them
                    flag2 = laser_flags_by_id[flag2Id]
                    flag1.changeType("S")  # temporarily to avoid conflicts
                    flag2.changeType("M" if flag2.type == "F" else "F")
                    flag1.changeType("M" if flag1Type == "F" else "F")

                    # do not reprocess
                    del laser_flags_by_id[str(flag1Id)]
                    del laser_flags_by_id[str(flag2Id)]
                else:
                    # flag has no mate: switch it.
                    flag1.changeType("M" if flag1Type == "F" else "F")
                    del laser_flags_by_id[str(flag1Id)]

    # dump configs to a layer
    # all configs will be recorded.
    def dump_config_to_layer(self):
        single_options = [
            "flagCount",
            "flagDiameter",
            "kFactor",
            "kerf",
            "thickness",
            "walls_height",
            "walls_join_both_sides",
        ]

        configs = self.svg.xpath("//*[starts-with(@id,'config')]")
        lastConfig = (
            0
            if configs is None or len(configs) == 0
            else max([int(c.get_id()[6:]) for c in configs])
        )
        id = f"config{lastConfig+1}"
        config_group = inkex.Group.new(id)
        config_group.set_id(id)
        Drawable().laserConfig_layer.add(config_group)
        options = {x: self.options.__dict__[x] for x in single_options}

        flag_options = {
            "color": [
                "flagsL1color",
                "flagsL2color",
                "flagsL3color",
                "flagsC1color",
                "flagsC2color",
                "flagsC3color",
            ],
            "min length": [
                "flagsL1minLength",
                "flagsL2minLength",
                "flagsL3minLength",
                "flagsC1minLength",
                "flagsC2minLength",
                "flagsC3minLength",
            ],
            "surrounding space": [
                "flagsL1surroundingspaces",
                "flagsL2surroundingspaces",
                "flagsL3surroundingspaces",
                "flagsC1surroundingspaces",
                "flagsC2surroundingspaces",
                "flagsC3surroundingspaces",
            ],
            "finger size": [
                "flagsL1finger",
                "flagsL2finger",
                "flagsL3finger",
                "flagsC1finger",
                "flagsC2finger",
                "flagsC3finger",
            ],
            "space size": [
                "flagsL1space",
                "flagsL2space",
                "flagsL3space",
                "flagsC1space",
                "flagsC2space",
                "flagsC3space",
            ],
        }
        # SVG table parameters
        start_x, start_y = 10, 10  # Starting position of the table
        cell_width = 70  # Width of each cell
        cell_height = 20  # Height of each cell
        cell_xpadding = 5
        cell_ypadding = 15
        header_height = 20  # Height of the header row

        # Create a group for the table
        table_group = inkex.Group.new("flagsConfig")
        config_group.add(table_group)

        # Draw header row
        x = start_x
        for header in flag_options.keys():
            # Draw header cell background
            header_rect = inkex.Rectangle.new(
                left=x,
                top=start_y,
                width=cell_width,
                height=header_height,
                fill="lightgray",
                stroke="black",
            )
            table_group.add(header_rect)

            # Add header text
            header_text = inkex.TextElement.new(
                x=x + cell_xpadding, y=start_y + cell_ypadding
            )
            header_text.text = header
            table_group.add(header_text)

            x += cell_width

        # Draw data rows
        y = start_y + header_height
        for row_idx in range(len(next(iter(flag_options.values())))):
            x = start_x
            for header in flag_options.keys():
                # Draw cell background
                cell_rect = inkex.Rectangle.new(
                    left=x,
                    top=y,
                    width=cell_width,
                    height=cell_height,
                    fill="white",
                    stroke="black",
                )
                table_group.add(cell_rect)

                # Add cell text
                cell_text = inkex.TextElement.new(
                    x=x + cell_xpadding,
                    y=y + cell_ypadding,
                )
                cell_text.text = str(
                    self.options.__dict__[flag_options[header][row_idx]]
                )
                table_group.add(cell_text)

                x += cell_width
            y += cell_height

        y += cell_height
        group = inkex.Group()
        for option, value in options.items():
            if not option.startswith("flags"):
                textElem = inkex.TextElement()
                textElem.text = f"{option}: {value}"
                textElem.set("x", start_x)
                textElem.set("y", y)
                group.add(textElem)
                y += 12

        config_group.add(group)




    def effect(self):
        # c=inkex.Vector2d(302.8,59.6)
        # dls=inkex.DirectedLineSegment((243.516, 62.1469), (362.16, 62.1469))

        # debugMsg(c)
        # debugMsg(dls.distance_to_point(c.x,c.y))
        # debugMsg(dls.perp_distance(c.x,c.y))
        # debugMsg(self.svg.selection)
        # return

        drawable = Drawable()
        drawable.svg = self.svg

        config = Config()
        config.svg = self.svg
        config.walls_to_curve_tolerance_degree = 5
        config.perpandicular_tolerance = 0.5
        config.thickness = self.options.thickness
        config.kFactor = self.options.kFactor
        config.kerf = self.options.kerf
        config.stroke_width = abs(self.options.kerf) if self.options.kerf > 0 else 0.1
        config.flagDiameter = self.options.flagDiameter
        config.flagCount = self.options.flagCount
        config.flagSide = self.options.flagSide
        config.walls_height = self.options.walls_height
        config.walls_join_both_sides = self.options.walls_join_both_sides
        tabActions = {
            "flags": self.options.flags_action,
            "joints": self.options.joints_action,
            "walls": self.options.walls_action,
            "tweaks": self.options.tweaks_action,
        }
        config.action = f"{self.options.tab}.{tabActions[self.options.tab]}"

        if self.svg.selection is not None and len(self.svg.selection) > 0:
            self.selection = self.svg.selection
        else:
            self.selection = inkex.elements._selected.ElementList(self.svg)
            self.selection.set(self.svg)

        self.flagOptions = []
        self.flagOptions.append(
            {
                "color": self.options.flagsL1color,
                "flagsL1minLength": self.options.flagsL1minLength,
                "surroundingspaces": self.options.flagsL1surroundingspaces,
                "finger": self.options.flagsL1finger,
                "space": self.options.flagsL1space,
            }
        )
        self.flagOptions.append(
            {
                "color": self.options.flagsL2color,
                "flagsL2minLength": self.options.flagsL2minLength,
                "surroundingspaces": self.options.flagsL2surroundingspaces,
                "finger": self.options.flagsL2finger,
                "space": self.options.flagsL2space,
            }
        )
        self.flagOptions.append(
            {
                "color": self.options.flagsL3color,
                "flagsL3minLength": self.options.flagsL3minLength,
                "surroundingspaces": self.options.flagsL3surroundingspaces,
                "finger": self.options.flagsL3finger,
                "space": self.options.flagsL3space,
            }
        )
        self.flagOptions.append(
            {
                "color": self.options.flagsC1color,
                "flagsL3minLength": self.options.flagsC1minLength,
                "surroundingspaces": self.options.flagsC1surroundingspaces,
                "finger": self.options.flagsC1finger,
                "space": self.options.flagsC1space,
            }
        )

        tmp_collections = [
            LaserFlagCollection(
                COLTYPE_LINE,
                "L1",
                self.options.flagsL1color,
                (self.options.flagsL1minLength, self.options.flagsL2minLength),
                config.flagCount,
                self.options.flagsL1surroundingspaces,
                self.options.flagsL1finger,
                self.options.flagsL1space,
            ),
            LaserFlagCollection(
                COLTYPE_LINE,
                "L2",
                self.options.flagsL2color,
                (
                    self.options.flagsL2minLength,
                    self.options.flagsL3minLength,
                ),
                config.flagCount,
                self.options.flagsL2surroundingspaces,
                self.options.flagsL2finger,
                self.options.flagsL2space,
            ),
            LaserFlagCollection(
                COLTYPE_LINE,
                "L3",
                self.options.flagsL3color,
                (self.options.flagsL3minLength, None),
                config.flagCount,
                self.options.flagsL3surroundingspaces,
                self.options.flagsL3finger,
                self.options.flagsL3space,
            ),
            LaserFlagCollection(
                COLTYPE_CURVE,
                "C1",
                self.options.flagsC1color,
                (self.options.flagsC1minLength, self.options.flagsC2minLength),
                config.flagCount,
                self.options.flagsC1surroundingspaces,
                self.options.flagsC1finger,
                self.options.flagsC1space,
            ),
            LaserFlagCollection(
                COLTYPE_CURVE,
                "C2",
                self.options.flagsC2color,
                (self.options.flagsC2minLength, self.options.flagsC3minLength),
                config.flagCount,
                self.options.flagsC2surroundingspaces,
                self.options.flagsC2finger,
                self.options.flagsC2space,
            ),
            LaserFlagCollection(
                COLTYPE_CURVE,
                "C3",
                self.options.flagsC3color,
                (self.options.flagsC3minLength, None),
                config.flagCount,
                self.options.flagsC3surroundingspaces,
                self.options.flagsC3finger,
                self.options.flagsC3space,
            ),
        ]

        # find existing flags
        self.collections = {c.id: c for c in tmp_collections}
        self.laser_flags: list[LaserFlag] = self.find_laser_flags()
        # add existing flags to collections.
        for f in self.laser_flags:
            if f.collection.id in self.collections:
                self.collections[f.collection.id].add_flag(f)
        if config.action == "flags.create":
            self.init_doc()

            # create missing flags.
            for i, (_, c) in enumerate(self.collections.items()):
                c.create_flags(
                    self.svg.viewbox_width + 25,
                    10 + (i - 1) * (3 * config.flagDiameter + 20),
                )

        if config.action == "flags.autocreate":
            self.init_doc()
            self.create_flags_auto()

        # if config.action == "flags.check":
        #     self.init_doc()
        #     self.check_laser_flags()

        # if config.action == "flags.3D":
        #     self.init_doc()
        #     self.create_graph()

        if config.action == "joints.create":
            self.init_doc()
            self.fix_path_direction()
            self.flags_draw_joints()
            Drawable().laserTexts_layer.style["display"] = "inline"
            Drawable().laserWalls_layer.style["display"] = "none"
            Drawable().laserRolls_layer.style["display"] = "none"
            Drawable().laserHinges_layer.style["display"] = "inline"
            Drawable().laserFlags_layer.style["display"] = "none"
            Drawable().laserJoints_layer.style["display"] = "inline"
            LaserDemo.hide_demo()

        if config.action == "walls.create":
            self.init_doc()
            self.fix_path_direction()
            laserwalls = LaserWalls(self)
            laserwalls.walls()

        if config.action == "tweaks.tweaks_swapMF":
            self.swapMF()

        if config.action == "tweaks.tweaks_outside":
            self.init_doc()
            self.flags_swap_side(FLAG_OUTSIDE)

        if config.action == "tweaks.tweaks_inside":
            self.init_doc()
            self.flags_swap_side(FLAG_INSIDE)

        if config.action == "tweaks.tweaks_demo":
            self.init_doc()
            demo=LaserDemo(self)
            demo.demo()


if __name__ == "__main__":
    Laserjoints().run()
