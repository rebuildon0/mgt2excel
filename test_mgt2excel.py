# -*- coding: utf-8 -*-
"""mgt2excel のユニットテスト

実行: py -3 -m unittest test_mgt2excel -v
"""
import math
import os
import tempfile
import unittest

from mgt2excel import (FORCE_TO_KN, LEN_TO_MM, _expand_list, _pt_order,
                       merge_members, parse_anl, parse_mgt)


def _make_model(elements, releases=None, supports=None):
    """merge_members 用の最小モデルを組み立てる。

    elements: [(eid, n1, n2, p1, p2), ...]
      p1, p2 は I端 / J端の座標タプル (x, y, z)
    """
    elems = {}
    for eid, n1, n2, x1, x2 in elements:
        v = (x2[0] - x1[0], x2[1] - x1[1], x2[2] - x1[2])
        ln = math.sqrt(sum(c * c for c in v))
        elems[eid] = dict(id=eid, type="BEAM", mat=1, sec=1, beta="0",
                          n1=n1, n2=n2, vec=tuple(c / ln for c in v), len=ln)
    return dict(elements=elems, releases=releases or {},
                supports=supports or set())


def _quiet(_msg):
    pass


P0, P1, P2 = (0, 0, 0), (1000, 0, 0), (2000, 0, 0)
PY = (1000, 1000, 0)


class TestExpandList(unittest.TestCase):
    def test_single(self):
        self.assertEqual(_expand_list("5"), [5])

    def test_range(self):
        self.assertEqual(_expand_list("5to8"), [5, 6, 7, 8])

    def test_range_by(self):
        self.assertEqual(_expand_list("5to10by2"), [5, 7, 9])

    def test_invalid(self):
        self.assertEqual(_expand_list("abc"), [])


class TestUnitFactors(unittest.TestCase):
    def test_force(self):
        self.assertAlmostEqual(FORCE_TO_KN["TONF"], 9.80665)
        self.assertAlmostEqual(FORCE_TO_KN["KGF"], 9.80665e-3)
        self.assertEqual(FORCE_TO_KN["KN"], 1.0)
        self.assertEqual(FORCE_TO_KN["N"], 1e-3)

    def test_length(self):
        self.assertEqual(LEN_TO_MM["MM"], 1.0)
        self.assertEqual(LEN_TO_MM["CM"], 10.0)
        self.assertEqual(LEN_TO_MM["M"], 1000.0)


class TestMergeOrientation(unittest.TestCase):
    """共有節点での I/J 端 4 パターンすべてで直線要素が統合されること"""

    def _merge_count(self, e1, e2):
        model = _make_model([e1, e2])
        return len(merge_members(model, log=_quiet))

    def test_j_meets_i(self):  # 1:(0->1) + 2:(1->2)
        self.assertEqual(self._merge_count((1, 10, 11, P0, P1),
                                           (2, 11, 12, P1, P2)), 1)

    def test_j_meets_j(self):  # 1:(0->1) + 2:(2->1)
        self.assertEqual(self._merge_count((1, 10, 11, P0, P1),
                                           (2, 12, 11, P2, P1)), 1)

    def test_i_meets_i(self):  # 1:(1->0) + 2:(1->2)
        self.assertEqual(self._merge_count((1, 11, 10, P1, P0),
                                           (2, 11, 12, P1, P2)), 1)

    def test_i_meets_j(self):  # 1:(1->0) + 2:(2->1)
        self.assertEqual(self._merge_count((1, 11, 10, P1, P0),
                                           (2, 12, 11, P2, P1)), 1)

    def test_not_collinear(self):  # 直角に折れる -> 統合しない
        self.assertEqual(self._merge_count((1, 10, 11, P0, P1),
                                           (2, 11, 12, P1, PY)), 2)

    def test_split_at_support(self):
        model = _make_model([(1, 10, 11, P0, P1), (2, 11, 12, P1, P2)],
                            supports={11})
        self.assertEqual(len(merge_members(model, log=_quiet)), 2)
        self.assertEqual(
            len(merge_members(model, split_at_supports=False, log=_quiet)), 1)

    def test_split_at_release(self):
        rel = {2: ("000011", "000000")}  # 要素2の I 端(共有節点側)にピン
        model = _make_model([(1, 10, 11, P0, P1), (2, 11, 12, P1, P2)],
                            releases=rel)
        self.assertEqual(len(merge_members(model, log=_quiet)), 2)
        self.assertEqual(
            len(merge_members(model, split_at_releases=False, log=_quiet)), 1)

    def test_three_at_node_not_merged(self):
        model = _make_model([(1, 10, 11, P0, P1), (2, 11, 12, P1, P2),
                             (3, 11, 13, P1, PY)])
        self.assertEqual(len(merge_members(model, log=_quiet)), 3)


MGT_FIXTURE = """*UNIT
   TONF , MM, KJ, C
*NODE
    1, 0, 0, 0
    2, 1000, 0, 0
    3, 2000, 0, 0
*ELEMENT
    1, BEAM  ,   1,    1,     1,     2,     0,     0
    2, BEAM  ,   1,    1,     2,     3,     0,     0
*MATERIAL
    1, STEEL, SS400, 0, 0, , C, NO, 0.02, 1, JIS(S), , SS400, NO, 20.9
*SECTION
    1, DBUSER, H200, CC, 0, 0, 0, 0, 0, 0, YES, NO, H, 2, 200, 100, 5.5, 8, 100, 8, 0, 0, 0, 0
*FRAME-RLS
    1,  NO, 000011, 0, 0, 0, 0, 0, 0
        000000, 0, 0, 0, 0, 0, 0,
*CONSTRAINT
   1 3, 111111,
*ENDDATA
"""


class TestParseMgt(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".mgt")
        with os.fdopen(fd, "w", encoding="cp932") as f:
            f.write(MGT_FIXTURE)

    def tearDown(self):
        os.unlink(self.path)

    def test_parse(self):
        m = parse_mgt(self.path, log=_quiet)
        self.assertEqual(len(m["nodes"]), 3)
        self.assertEqual(len(m["elements"]), 2)
        self.assertEqual(m["unit_force"], "TONF")
        self.assertEqual(m["releases"], {1: ("000011", "000000")})
        self.assertEqual(m["supports"], {1, 3})
        self.assertEqual(m["elements"][1]["len"], 1000.0)

    def test_broken_frame_rls_skipped(self):
        """ペアが崩れた FRAME-RLS はスキップされ、正常ペアは読めること"""
        broken = MGT_FIXTURE.replace(
            "*FRAME-RLS\n",
            "*FRAME-RLS\n    9, NO, BADFLAG, 0, 0, 0, 0, 0, 0\n")
        with open(self.path, "w", encoding="cp932") as f:
            f.write(broken)
        warnings = []
        m = parse_mgt(self.path, log=warnings.append)
        self.assertEqual(m["releases"], {1: ("000011", "000000")})
        self.assertTrue(any("FRAME-RLS" in w for w in warnings))


ANL_FIXTURE = """ 梁要素の断面力の出力                                                             単位系 : tonf , mm

  要素   材料   断面       LC      PT      軸力     せん断-y   せん断-z   ねじり     曲げ-y     曲げ-z

------ ------ ------ ------------ --- ---------- ---------- ---------- ---------- ---------- ----------
     1      1      1      ΣDL       I        1.0        0.0        0.0        0.0        0.0        5.0
                                  1/4        1.0        0.0        0.0        0.0        0.0        7.0
                                  CNT        1.0        0.0        0.0        0.0        0.0        8.0
                                    J        1.0        0.0        0.0        0.0        0.0        5.0

                       ΣDL+EX       I        2.0        0.0        0.0        0.0        0.0        3.0
                                  CNT        2.0        0.0        0.0        0.0        0.0        4.0
                                    J        2.0        0.0        0.0        0.0        0.0        3.0
"""


class TestParseAnlMidpoint(unittest.TestCase):
    """中間点(2/4 等)の断面力行も I/J 端と同様に読めること"""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".anl")
        with os.fdopen(fd, "w", encoding="cp932") as f:
            f.write(ANL_FIXTURE)

    def tearDown(self):
        os.unlink(self.path)

    def test_midpoint_parsed(self):
        warnings = []
        r = parse_anl(self.path, log=warnings.append)
        d = r["beam_forces"][1]
        self.assertEqual(set(d.keys()),
                         {("ΣDL", "I"), ("ΣDL", "1/4"), ("ΣDL", "CNT"),
                          ("ΣDL", "J"),
                          ("ΣDL+EX", "I"), ("ΣDL+EX", "CNT"), ("ΣDL+EX", "J")})
        self.assertEqual(d[("ΣDL", "CNT")][5], 8.0)  # 中央曲げが最大
        self.assertFalse(any("警告" in w for w in warnings))

    def test_pt_order(self):
        pts = ["J", "CNT", "I", "3/4", "1/4"]
        self.assertEqual(sorted(pts, key=_pt_order),
                         ["I", "1/4", "CNT", "3/4", "J"])


if __name__ == "__main__":
    unittest.main()
