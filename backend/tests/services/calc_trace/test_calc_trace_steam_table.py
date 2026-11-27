"""R2: the saturated steam table the steam panel interpolates in (``steam_saturated_iapws_if97.json``), checked
against IAPWS-IF97 itself.

The formulation is written out below (regions 1, 2 and 4, enthalpy only, from IAPWS R7-97(2012)) and first checked
against the release's own verification values (its Tables 5, 15 and 35), to 1e-8. Every row of the table is then that
formulation at the row's pressure or temperature, to the 0.01 Btu/lb the table is rounded to. A coefficient copied
wrong would fail the first test; a row typed wrong, the second.
"""

from __future__ import annotations

import math

import pytest

from backend.app.services.calc_trace import steam

PSI_MPA = 0.006894757293168361  # 1 psi = 6.894757293168361 kPa
ATM_MPA = 0.101325  # a standard atmosphere, 14.696 psia
KJKG_PER_BTULB = 2.326  # International Table Btu
R = 0.461526  # kJ/(kg K)
N4 = [0.11670521452767e4, -0.72421316703206e6, -0.17073846940092e2, 0.12020824702470e5, -0.32325550322333e7,
      0.14915108613530e2, -0.48232657361591e4, 0.40511340542057e6, -0.23855557567849, 0.65017534844798e3]
R1 = [(0, -2, 0.14632971213167), (0, -1, -0.84548187169114), (0, 0, -0.37563603672040e1), (0, 1, 0.33855169168385e1),
      (0, 2, -0.95791963387872), (0, 3, 0.15772038513228), (0, 4, -0.16616417199501e-1), (0, 5, 0.81214629983568e-3),
      (1, -9, 0.28319080123804e-3), (1, -7, -0.60706301565874e-3), (1, -1, -0.18990068218419e-1),
      (1, 0, -0.32529748770505e-1), (1, 1, -0.21841717175414e-1), (1, 3, -0.52838357969930e-4),
      (2, -3, -0.47184321073267e-3), (2, 0, -0.30001780793026e-3), (2, 1, 0.47661393906987e-4),
      (2, 3, -0.44141845330846e-5), (2, 17, -0.72694996297594e-15), (3, -4, -0.31679644845054e-4),
      (3, 0, -0.28270797985312e-5), (3, 6, -0.85205128120103e-9), (4, -5, -0.22425281908000e-5),
      (4, -2, -0.65171222895601e-6), (4, 10, -0.14341729937924e-12), (5, -8, -0.40516996860117e-6),
      (8, -11, -0.12734301741641e-8), (8, -6, -0.17424871230634e-9), (21, -29, -0.68762131295531e-18),
      (23, -31, 0.14478307828521e-19), (29, -38, 0.26335781662795e-22), (30, -39, -0.11947622640071e-22),
      (31, -40, 0.18228094581404e-23), (32, -41, -0.93537087292458e-25)]
R2_0 = [(0, -0.96927686500217e1), (1, 0.10086655968018e2), (-5, -0.56087911283020e-2), (-4, 0.71452738081455e-1),
        (-3, -0.40710498223928), (-2, 0.14240819171444e1), (-1, -0.43839511319450e1), (2, -0.28408632460772),
        (3, 0.21268463753307e-1)]
R2_R = [(1, 0, -0.17731742473213e-2), (1, 1, -0.17834862292358e-1), (1, 2, -0.45996013696365e-1),
        (1, 3, -0.57581259083432e-1), (1, 6, -0.50325278727930e-1), (2, 1, -0.33032641670203e-4),
        (2, 2, -0.18948987516315e-3), (2, 4, -0.39392777243355e-2), (2, 7, -0.43797295650573e-1),
        (2, 36, -0.26674547914087e-4), (3, 0, 0.20481737692309e-7), (3, 1, 0.43870667284435e-6),
        (3, 3, -0.32277677238570e-4), (3, 6, -0.15033924542148e-2), (3, 35, -0.40668253562649e-1),
        (4, 1, -0.78847309559367e-9), (4, 2, 0.12790717852285e-7), (4, 3, 0.48225372718507e-6),
        (5, 7, 0.22922076337661e-5), (6, 3, -0.16714766451061e-10), (6, 16, -0.21171472321355e-2),
        (6, 35, -0.23895741934104e2), (7, 0, -0.59059564324270e-17), (7, 11, -0.12621808899101e-5),
        (7, 25, -0.38946842435739e-1), (8, 8, 0.11256211360459e-10), (8, 36, -0.82311340897998e1),
        (9, 13, 0.19809712802088e-7), (10, 4, 0.10406965210174e-18), (10, 10, -0.10234747095929e-12),
        (10, 14, -0.10018179379511e-8), (16, 29, -0.80882908646985e-10), (16, 50, 0.10693031879409),
        (18, 57, -0.33662250574171), (20, 20, 0.89185845355421e-24), (20, 35, 0.30629316876232e-12),
        (20, 48, -0.42002467698208e-5), (21, 21, -0.59056029685639e-25), (22, 53, 0.37826947613457e-5),
        (23, 39, -0.12768608934681e-14), (24, 26, 0.73087610595061e-28), (24, 40, 0.55414715350778e-16),
        (24, 58, -0.94369707241210e-6)]


def h1(p_mpa, t_k):
    pi, tau = p_mpa / 16.53, 1386.0 / t_k
    g_tau = sum(n * (7.1 - pi) ** i * j * (tau - 1.222) ** (j - 1) for i, j, n in R1)
    return R * t_k * tau * g_tau


def h2(p_mpa, t_k):
    pi, tau = p_mpa, 540.0 / t_k
    g0 = sum(n * j * tau ** (j - 1) for j, n in R2_0)
    gr = sum(n * pi ** i * j * (tau - 0.5) ** (j - 1) for i, j, n in R2_R)
    return R * t_k * tau * (g0 + gr)


def tsat(p_mpa):
    n = N4
    beta = p_mpa ** 0.25
    e = beta ** 2 + n[2] * beta + n[5]
    f = n[0] * beta ** 2 + n[3] * beta + n[6]
    g = n[1] * beta ** 2 + n[4] * beta + n[7]
    d = 2 * g / (-f - math.sqrt(f * f - 4 * e * g))
    return (n[9] + d - math.sqrt((n[9] + d) ** 2 - 4 * (n[8] + n[9] * d))) / 2


def psat(t_k):
    n = N4
    th = t_k + n[8] / (t_k - n[9])
    a = th ** 2 + n[0] * th + n[1]
    b = n[2] * th ** 2 + n[3] * th + n[4]
    c = n[5] * th ** 2 + n[6] * th + n[7]
    return (2 * c / (-b + math.sqrt(b * b - 4 * a * c))) ** 4


def _k(f: float) -> float:
    return (f - 32) / 1.8 + 273.15


def _f(k: float) -> float:
    return (k - 273.15) * 1.8 + 32


@pytest.mark.parametrize(("got", "want"), [
    (lambda: h1(3, 300), 0.115331273e3), (lambda: h1(80, 300), 0.184142828e3), (lambda: h1(3, 500), 0.975542239e3),
    (lambda: h2(0.0035, 300), 0.254991145e4), (lambda: h2(0.0035, 700), 0.333568375e4),
    (lambda: h2(30, 700), 0.263149474e4), (lambda: psat(300), 0.353658941e-2), (lambda: psat(500), 0.263889776e1),
    (lambda: psat(600), 0.123443146e2), (lambda: tsat(0.1), 0.372755919e3), (lambda: tsat(1), 0.453035632e3),
    (lambda: tsat(10), 0.584149488e3)])
def test_the_formulation_meets_the_releases_own_verification_values(got, want) -> None:  # noqa: ANN001
    assert math.isclose(got(), want, rel_tol=1e-8)


def test_every_saturated_steam_row_is_iapws_if97_at_its_gauge_pressure() -> None:
    rows = steam.table()["saturated_steam_by_gauge_pressure"]["rows"]
    assert [r["psig"] for r in rows] == list(range(0, 305, 5))
    for row in rows:
        p = ATM_MPA + row["psig"] * PSI_MPA
        t = tsat(p)
        assert row["t_sat_f"] == pytest.approx(_f(t), abs=0.005), row
        assert row["h_f_btu_lb"] == pytest.approx(h1(p, t) / KJKG_PER_BTULB, abs=0.005), row
        assert row["h_g_btu_lb"] == pytest.approx(h2(p, t) / KJKG_PER_BTULB, abs=0.005), row


def test_every_condensate_row_is_iapws_if97_at_its_temperature_and_32_f_is_zero_by_convention() -> None:
    rows = steam.table()["saturated_water_by_temperature"]["rows"]
    assert [r["t_f"] for r in rows] == [32, *range(40, 410, 10)]
    assert rows[0]["h_f_btu_lb"] == 0.0  # the steam-table convention; IF97 gives -0.02 here, below its triple point
    assert h1(psat(_k(32)), _k(32)) / KJKG_PER_BTULB == pytest.approx(-0.018, abs=0.001)
    for row in rows[1:]:
        t = _k(row["t_f"])
        assert row["h_f_btu_lb"] == pytest.approx(h1(psat(t), t) / KJKG_PER_BTULB, abs=0.005), row


def test_the_table_names_its_source_edition_tables_and_url() -> None:
    data = steam.table()
    assert data["source"].startswith("IAPWS R7-97(2012)")
    assert "Region 1" in data["tables"] and "Region 2" in data["tables"] and "Region 4" in data["tables"]
    assert data["url"] == "https://www.iapws.org/relguide/IF97-Rev.html"
    assert data["edition"] and data["conversions"]["btu_per_lb_kj_per_kg"] == KJKG_PER_BTULB


def test_known_printed_values_agree() -> None:
    """Spot values every steam table prints: 0 psig is 212 °F and 1,150 Btu/lb; 100 psig is 337.9 °F and 1,190."""

    assert steam.saturated(0) == pytest.approx((211.95, 1150.27), abs=0.01)
    assert steam.saturated(100) == pytest.approx((337.88, 1189.95), abs=0.01)
    assert steam.liquid(210) == pytest.approx(178.15, abs=0.05)
