# -*- coding: utf-8 -*-
"""mgt2excel のユニットテスト

実行: py -3 -m unittest test_mgt2excel -v
"""
import math
import os
import tempfile
import unittest

from mgt2excel import (FORCE_TO_KN, LEN_TO_MM, _expand_list, _pt_order,
                       build_members, merge_members, parse_anl, parse_mgt,
                       section_props)


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

    def test_imperial(self):
        self.assertAlmostEqual(FORCE_TO_KN["LBF"], 4.4482216152605e-3)
        self.assertAlmostEqual(FORCE_TO_KN["KIPS"], 4.4482216152605)
        self.assertEqual(LEN_TO_MM["IN"], 25.4)
        self.assertEqual(LEN_TO_MM["FT"], 304.8)


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

    def test_three_at_node_collinear_pair_merged(self):
        """3本集まっても、直線ペアが一意なら統合される(非直線の1本は単独)"""
        model = _make_model([(1, 10, 11, P0, P1), (2, 11, 12, P1, P2),
                             (3, 11, 13, P1, PY)])
        self.assertEqual(len(merge_members(model, log=_quiet)), 2)

    def test_x_crossing_merged_per_line(self):
        """X形交差(同断面4本)は直線ごとに1部材、計2部材に統合される"""
        C = (1000, 1000, 0)
        model = _make_model([
            (1, 10, 99, (0, 0, 0), C), (2, 99, 12, C, (2000, 2000, 0)),
            (3, 13, 99, (0, 2000, 0), C), (4, 99, 14, C, (2000, 0, 0)),
        ])
        self.assertEqual(len(merge_members(model, log=_quiet)), 2)

    def test_ambiguous_overlap_not_merged(self):
        """同一直線上の続きが2本あって曖昧な場合は統合しない"""
        model = _make_model([(1, 10, 11, P0, P1), (2, 11, 12, P1, P2),
                             (3, 11, 14, P1, P2)])
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


class TestUnitConversion(unittest.TestCase):
    """ANL の単位系が何であっても、換算ON=kN/kN·m/mm、換算OFF=元単位表示になること"""

    def _run(self, unit_line, convert):
        fd_m, mgt_p = tempfile.mkstemp(suffix=".mgt")
        fd_a, anl_p = tempfile.mkstemp(suffix=".anl")
        os.close(fd_m)
        os.close(fd_a)
        try:
            with open(mgt_p, "w", encoding="cp932") as f:
                f.write(MGT_FIXTURE)
            with open(anl_p, "w", encoding="cp932") as f:
                f.write(ANL_FIXTURE.replace("tonf , mm", unit_line))
            model = parse_mgt(mgt_p, log=_quiet)
            results = parse_anl(anl_p, log=_quiet)
            groups = merge_members(model, log=_quiet)
            rows, _, units = build_members(model, results, groups,
                                           convert_units=convert, log=_quiet)
            return rows, units
        finally:
            os.unlink(mgt_p)
            os.unlink(anl_p)

    def test_convert_kn_m(self):
        rows, units = self._run("kN , m", True)
        agg = rows[0]["agg"]
        self.assertAlmostEqual(agg[("ΣDL", "N", "max")], 1.0)      # kN のまま
        self.assertAlmostEqual(agg[("ΣDL", "Mz", "max")], 8.0)     # kN·m -> kN·m
        self.assertEqual((units["force"], units["mom"], units["len"]),
                         ("kN", "kN·m", "mm"))
        self.assertAlmostEqual(rows[0]["length"], 2000.0)          # MGT は mm

    def test_convert_tonf_mm(self):
        rows, _ = self._run("tonf , mm", True)
        agg = rows[0]["agg"]
        self.assertAlmostEqual(agg[("ΣDL", "N", "max")], 9.80665)
        self.assertAlmostEqual(agg[("ΣDL", "Mz", "max")], 8 * 9.80665e-3)

    def test_convert_kgf_cm(self):
        rows, _ = self._run("kgf , cm", True)
        agg = rows[0]["agg"]
        self.assertAlmostEqual(agg[("ΣDL", "N", "max")], 9.80665e-3)
        self.assertAlmostEqual(agg[("ΣDL", "Mz", "max")],
                               8 * 9.80665e-3 * 10 / 1000)

    def test_no_convert_keeps_values_and_labels(self):
        rows, units = self._run("kN , m", False)
        agg = rows[0]["agg"]
        self.assertAlmostEqual(agg[("ΣDL", "N", "max")], 1.0)
        self.assertAlmostEqual(agg[("ΣDL", "Mz", "max")], 8.0)
        self.assertEqual((units["force"], units["mom"], units["len"]),
                         ("kN", "kN·m", "MM"))  # 幾何は MGT の単位表示

    def test_unknown_unit_raises_when_converting(self):
        with self.assertRaises(ValueError):
            self._run("poundal , mm", True)

    def test_unknown_unit_ok_without_convert(self):
        rows, units = self._run("poundal , mm", False)
        self.assertEqual(units["force"], "poundal")
        self.assertAlmostEqual(rows[0]["agg"][("ΣDL", "N", "max")], 1.0)


MGT_MIX = MGT_FIXTURE.replace(
    "*ELEMENT",
    "*ELEMENT\n    3, TENSTR,   1,    2,     1,     3,     0,     1,     0,     0,    NO")\
    .replace(
    "    1, DBUSER, H200, CC, 0, 0, 0, 0, 0, 0, YES, NO, H, 2, 200, 100, 5.5, 8, 100, 8, 0, 0, 0, 0",
    "    1, DBUSER, H200, CC, 0, 0, 0, 0, 0, 0, YES, NO, H, 2, 200, 100, 5.5, 8, 100, 8, 0, 0, 0, 0\n"
    "    2, DBUSER, PHI16, CC, 0, 0, 0, 0, 0, 0, YES, NO, SR, 2, 16, 0, 0, 0, 0, 0, 0, 0, 0, 0")

ANL_TRUSS_KN = """ トラス要素の断面力の出力                                                           単位系 : kN , m

  要素   材料   断面       LC          断面力-I    断面力-J
------ ------ ------ -------- ---- ----------- -----------
     3      1      2      ΣDL              2.0         2.0
"""


class TestMixedUnits(unittest.TestCase):
    """梁(tonf)とトラス(kN)で単位が異なる ANL、トラスのみの ANL の単位処理"""

    def _run(self, mgt_text, anl_text, convert):
        fd_m, mgt_p = tempfile.mkstemp(suffix=".mgt")
        fd_a, anl_p = tempfile.mkstemp(suffix=".anl")
        os.close(fd_m)
        os.close(fd_a)
        try:
            with open(mgt_p, "w", encoding="cp932") as f:
                f.write(mgt_text)
            with open(anl_p, "w", encoding="cp932") as f:
                f.write(anl_text)
            model = parse_mgt(mgt_p, log=_quiet)
            results = parse_anl(anl_p, log=_quiet)
            groups = merge_members(model, log=_quiet)
            rows, _, units = build_members(model, results, groups,
                                           convert_units=convert, log=_quiet)
            return rows, units
        finally:
            os.unlink(mgt_p)
            os.unlink(anl_p)

    def _truss_row(self, rows):
        return next(r for r in rows if r["type"] == "TENSTR")

    def test_mixed_units_convert_on(self):
        """梁 tonf / トラス kN -> それぞれの係数で kN へ"""
        rows, units = self._run(MGT_MIX, ANL_FIXTURE + "\n" + ANL_TRUSS_KN, True)
        beam = next(r for r in rows if r["type"] == "BEAM")
        truss = self._truss_row(rows)
        self.assertAlmostEqual(beam["agg"][("ΣDL", "N", "max")], 9.80665)
        self.assertAlmostEqual(truss["agg"][("ΣDL", "N", "max")], 2.0)  # kN のまま
        self.assertEqual(units["force"], "kN")

    def test_mixed_units_convert_off_rescales_truss(self):
        """換算OFF: トラス値を梁の単位(tonf)に揃え、見出しは tonf のまま真になる"""
        rows, units = self._run(MGT_MIX, ANL_FIXTURE + "\n" + ANL_TRUSS_KN, False)
        truss = self._truss_row(rows)
        self.assertAlmostEqual(truss["agg"][("ΣDL", "N", "max")],
                               2.0 / 9.80665, places=6)
        self.assertEqual(units["force"], "tonf")

    def test_mixed_unknown_unit_convert_off_labels_both(self):
        """換算率不明の混在: 値はそのまま、見出しに両方の単位を明記"""
        anl = ANL_FIXTURE + "\n" + ANL_TRUSS_KN.replace("kN , m", "poundal , m")
        rows, units = self._run(MGT_MIX, anl, False)
        truss = self._truss_row(rows)
        self.assertAlmostEqual(truss["agg"][("ΣDL", "N", "max")], 2.0)
        self.assertIn("tonf", units["force"])
        self.assertIn("poundal", units["force"])

    def test_truss_only_anl(self):
        """トラスセクションしか無い ANL でも単位を拾って変換できる"""
        rows, units = self._run(MGT_MIX, ANL_TRUSS_KN, True)
        truss = self._truss_row(rows)
        self.assertAlmostEqual(truss["agg"][("ΣDL", "N", "max")], 2.0)
        self.assertEqual(units["force"], "kN")

    def test_mixed_case_unit_token(self):
        """単位トークンの大文字小文字は無視して換算される"""
        anl = ANL_FIXTURE.replace("tonf , mm", "Kn , M")
        rows, units = self._run(MGT_FIXTURE, anl, True)
        self.assertAlmostEqual(rows[0]["agg"][("ΣDL", "N", "max")], 1.0)

    def test_beam_header_missing_uses_truss_unit(self):
        """梁の単位表記が無くトラスに有る場合、同一ANL内のトラス単位を適用し警告する"""
        anl = (ANL_FIXTURE.replace("単位系 : tonf , mm", "                  ")
               + "\n" + ANL_TRUSS_KN)
        fd_m, mgt_p = tempfile.mkstemp(suffix=".mgt")
        fd_a, anl_p = tempfile.mkstemp(suffix=".anl")
        os.close(fd_m)
        os.close(fd_a)
        try:
            with open(mgt_p, "w", encoding="cp932") as f:
                f.write(MGT_MIX)
            with open(anl_p, "w", encoding="cp932") as f:
                f.write(anl)
            warnings = []
            model = parse_mgt(mgt_p, log=_quiet)
            results = parse_anl(anl_p, log=warnings.append)
            self.assertTrue(any("トラスセクションの単位" in w for w in warnings))
            groups = merge_members(model, log=_quiet)
            rows, _, units = build_members(model, results, groups,
                                           convert_units=True, log=_quiet)
            beam = next(r for r in rows if r["type"] == "BEAM")
            # 梁は kN(トラス単位) として換算される。MGT(TONF) は使わない
            self.assertAlmostEqual(beam["agg"][("ΣDL", "N", "max")], 1.0)
            self.assertEqual(units["force"], "kN")
        finally:
            os.unlink(mgt_p)
            os.unlink(anl_p)

    def test_missing_unit_header_warns_and_falls_back(self):
        """単位表記が無い ANL は警告を出して MGT の単位を仮定する"""
        anl = ANL_FIXTURE.replace(
            "単位系 : tonf , mm", "                    ")
        fd_m, mgt_p = tempfile.mkstemp(suffix=".mgt")
        fd_a, anl_p = tempfile.mkstemp(suffix=".anl")
        os.close(fd_m)
        os.close(fd_a)
        try:
            with open(mgt_p, "w", encoding="cp932") as f:
                f.write(MGT_FIXTURE)
            with open(anl_p, "w", encoding="cp932") as f:
                f.write(anl)
            warnings = []
            model = parse_mgt(mgt_p, log=_quiet)
            results = parse_anl(anl_p, log=warnings.append)
            self.assertTrue(any("単位表記が見つかりません" in w for w in warnings))
            groups = merge_members(model, log=_quiet)
            rows, _, _ = build_members(model, results, groups,
                                       convert_units=True, log=_quiet)
            # MGT の TONF を仮定して換算される
            self.assertAlmostEqual(rows[0]["agg"][("ΣDL", "N", "max")], 9.80665)
        finally:
            os.unlink(mgt_p)
            os.unlink(anl_p)


class TestSectionProps(unittest.TestCase):
    """断面性能の板要素計算(cm系)。圧延材はフィレット無視のためJIS規格値よりやや小さい"""

    def test_round_bar(self):
        p = section_props(dict(shape="SR", fields=["2", "20"]))
        self.assertAlmostEqual(p["A"], 3.14, places=2)
        self.assertAlmostEqual(p["iy"], 0.5, places=3)
        self.assertAlmostEqual(p["Zy"], 0.785, places=2)

    def test_round_bar_db_name(self):
        p = section_props(dict(shape="SR", fields=["1", "JIS", "SR 16"]))
        self.assertAlmostEqual(p["A"], 2.01, places=2)

    def test_h_section(self):
        # H-200x100x5.5x8: 板要素計算 A=26.12cm², Iy≈1761cm⁴ (JIS: 26.67 / 1840)
        p = section_props(dict(shape="H",
                               fields=["2", "200", "100", "5.5", "8",
                                       "100", "8", "0", "0"]))
        self.assertAlmostEqual(p["A"], 26.12, places=2)
        self.assertAlmostEqual(p["Iy"], 1760.9, delta=1.0)
        self.assertAlmostEqual(p["Zy"], 176.1, delta=0.5)
        self.assertTrue(p["iz"] < p["iy"])
        self.assertAlmostEqual(p["imin"], p["iz"], places=6)  # 対称断面

    def test_angle(self):
        # L-50x50x4: A=3.84cm² (JIS: 3.89)。最小回転半径は主軸まわり
        p = section_props(dict(shape="L", fields=["1", "JIS", "L 50x4"]))
        self.assertAlmostEqual(p["A"], 3.84, places=2)
        self.assertTrue(p["imin"] < p["iy"])  # 山形は主軸(v軸)が最小

    def test_unsupported_shape(self):
        self.assertIsNone(section_props(dict(shape="T", fields=["2", "100"])))

    def test_to_mm_scaling(self):
        """MGT が cm 単位でも to_mm 換算で mm 定義と同じ結果になること"""
        mm = section_props(dict(shape="H",
                                fields=["2", "200", "100", "5.5", "8",
                                        "100", "8"]))
        cm = section_props(dict(shape="H",
                                fields=["2", "20", "10", "0.55", "0.8",
                                        "10", "0.8"]), to_mm=10.0)
        self.assertAlmostEqual(mm["A"], cm["A"], places=6)
        self.assertAlmostEqual(mm["Iy"], cm["Iy"], places=4)


if __name__ == "__main__":
    unittest.main()
