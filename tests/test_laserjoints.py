#!/usr/bin/env python
# coding=utf-8

"""
Test elements extra logic from svg xml lxml custom classes.
"""

from inkex.tester import ComparisonMixin, TestCase
from inkex.tester.inx import InxMixin
from inkex.command import is_inkscape_available
from inkex.tester.svg import svg_file

from laserjoints import Laserjoints

Laserjoints.debugEn = False

import sys

sys.path.insert(0, ".")


class LaserJointsBasicTestCase(InxMixin, TestCase):
    source_file = "00_empty.svg"

    def setUp(self):
        super().setUp()
        self.svg = svg_file(self.data_file("svg", self.source_file))

    """Test INX files and other things"""

    def test_inx_file(self):
        """Get all inx files and test each of them"""
        self.assertInxIsGood("laserjoints.inx")

    def test_other_things(self):
        """Things work out"""
        pass


class LaserJointsComparisonsTestCaseCreateFlags(ComparisonMixin, TestCase):
    """Test input and output variations"""

    effect_class = Laserjoints
    compare_file = "svg/00_empty.svg"
    comparisons = [
        (
            "--tab=flags",
            "--flags_action=create",
        ),
    ]


class LaserJointsComparisonsTestCaseCreateFlagsAuto(ComparisonMixin, TestCase):
    """Test input and output variations"""

    effect_class = Laserjoints
    compare_file = "svg/40_flags_auto.svg"
    comparisons = [
        (
            "--tab=flags",
            "--flags_action=autocreate",
        ),
    ]

class LaserJointsComparisonsTestCaseCreateSimpleSlots(ComparisonMixin, TestCase):
    """Test input and output variations"""
    
    effect_class = Laserjoints
    compare_file = ["svg/10_simple.svg"]
    comparisons = [
        (
            "--tab=joints",
            "--joints_action=create",
        ),
        # ('--flagsT1color=#ff0000 --flagsT1count=7 --flagsT1numtabs=4 --flagsT2color=#ff0000 --flagsT2count=6 --flagsT2numtabs=3 --flagsT3color=blue --flagsT3count=5 --flagsT3numtabs=3 --thickness=3.000 --kerf=0.1 --units=mm --featureStart=false --featureEnd=false --action=1',)
    ]

class LaserJointsComparisonsTestCaseCreateSlots(ComparisonMixin, TestCase):
    """Test input and output variations"""

    effect_class = Laserjoints
    compare_file = ["svg/10_simple.svg","svg/15_start_points.svg","svg/20_slots.svg","svg/50_random.svg","svg/51_random.svg"]
    comparisons = [
        (
            "--tab=joints",
            "--joints_action=create",
        ),
        # ('--flagsT1color=#ff0000 --flagsT1count=7 --flagsT1numtabs=4 --flagsT2color=#ff0000 --flagsT2count=6 --flagsT2numtabs=3 --flagsT3color=blue --flagsT3count=5 --flagsT3numtabs=3 --thickness=3.000 --kerf=0.1 --units=mm --featureStart=false --featureEnd=false --action=1',)
    ]

class LaserJointsComparisonsTestCaseCreateWall(ComparisonMixin, TestCase):
    """Test input and output variations"""

    effect_class = Laserjoints
    compare_file = ["svg/30_simple_curve.svg","svg/35_complex_curve.svg","svg/60_walls.svg"]
    comparisons = [
        (
            "--tab=walls",
            "--walls_action=create",
        ),
        # ('--flagsT1color=#ff0000 --flagsT1count=7 --flagsT1numtabs=4 --flagsT2color=#ff0000 --flagsT2count=6 --flagsT2numtabs=3 --flagsT3color=blue --flagsT3count=5 --flagsT3numtabs=3 --thickness=3.000 --kerf=0.1 --units=mm --featureStart=false --featureEnd=false --action=1',)
    ]

# class LaserJointsComparisonsTestCaseRemoveAll(ComparisonMixin, TestCase):
#     """Test input and output variations"""

#     effect_class = LaserJoints
#     compare_file = "svg/test_remove.svg"
#     comparisons = [
#         (
#             "--tab=joints",
#             "--joints_action=remove",
#         ),
#     ]
