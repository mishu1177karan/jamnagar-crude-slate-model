"""
Assay-based refinery LP for the Jamnagar Merey-vs-Urals model.

A crude slate is split into distillation cuts using public assays, then a
linear program routes each cut through Jamnagar-style units (VDU, FCC,
hydrocracker, coker, reformer, product hydrotreaters) to maximise margin
subject to unit capacities. Product yields come out of the optimisation
instead of being assumed.

Volumes are kb/d. Prices are $/bbl unless noted.
"""
from dataclasses import dataclass, field
import pulp

# ---------------------------------------------------------------------------
# 1. Crude assays: volume fraction, specific gravity and sulfur (wt%) per cut
# ---------------------------------------------------------------------------
# Merey: Oil & Gas Journal "Guide to World Crudes", 9 Jun 1997 (API 14.7, S 2.74).
#   naphtha = IBP-392F, kero = 392-482F, diesel = 482-650F,
#   VGO = 650-968F, vacuum residue = 968F+ (vol%: 6.71/5.41/13.76/32.27/41.85)
# Urals: wt% yields from public spec sheets (C1-C4 2.6, naphtha 10.1, kero 8.05,
#   gasoil 25.9, atm. residue 46.9; 6.4 wt% unreported -> assigned to naphtha).
#   Atm. residue split into VGO / vacuum residue and all cut sulfurs are
#   ESTIMATES (typical Urals values); flagged in the notebook.
ASSAYS = {
    "merey": {
        "api": 14.7, "sulfur": 2.74, "source": "OGJ assay, 1997",
        "cuts": {   # cut: (vol fraction, SG, sulfur wt%)
            "lpg":    (0.000, 0.55, 0.00),
            "naphtha": (0.0671, 0.775, 0.015),
            "kero":   (0.0541, 0.844, 0.39),
            "diesel": (0.1376, 0.887, 1.36),
            "vgo":    (0.3227, 0.950, 2.40),
            "vr":     (0.4185, 1.055, 3.51),
        },
        "vr_ccr": 22.5,   # Conradson carbon of vacuum residue, wt% (estimate)
    },
    "urals": {
        "api": 31.8, "sulfur": 1.35, "source": "Public spec sheets + estimates",
        "cuts_wt": {   # cut: (wt%, SG, sulfur wt%)
            "lpg":    (2.6, 0.55, 0.00),
            "naphtha": (16.5, 0.730, 0.05),
            "kero":   (8.05, 0.800, 0.20),
            "diesel": (25.9, 0.855, 0.90),
            "vgo":    (24.4, 0.920, 1.60),
            "vr":     (22.5, 1.000, 2.60),
        },
        "vr_ccr": 17.0,
    },
}

def _urals_cuts():
    wt = ASSAYS["urals"]["cuts_wt"]
    vols = {k: w / sg for k, (w, sg, s) in wt.items()}
    tot = sum(vols.values())
    return {k: (vols[k] / tot, wt[k][1], wt[k][2]) for k in wt}

ASSAYS["urals"]["cuts"] = _urals_cuts()
BBL_M3 = 0.159

# ---------------------------------------------------------------------------
# 2. Unit capacities: Jamnagar SEZ refinery (kb/d), A Barrel Full (2012)
#    Expressed per kb/d of crude so the train can be scaled.
# ---------------------------------------------------------------------------
SEZ = dict(cdu=580, vdu=305, fcc=200, hcu=110, coker=160, reformer=85 + 42, product_ht=360)
CAP_RATIO = {k: v / SEZ["cdu"] for k, v in SEZ.items()}

# ---------------------------------------------------------------------------
# 3. Unit yields (vol fraction of feed) and costs: typical textbook values (ESTIMATES)
# ---------------------------------------------------------------------------
FCC_Y = dict(gasoline=0.60, diesel=0.18, lpg=0.12, fuel_oil=0.07)       # LCO -> diesel pool
HCU_Y = dict(diesel=0.55, jet=0.25, naphtha=0.22, lpg=0.06)             # ~8% volume gain
REF_Y = dict(gasoline=0.83, lpg=0.07)
COKER_Y = {  # liquids per bbl vacuum residue; coke from CCR
    "merey": dict(naphtha=0.12, diesel=0.22, hgo=0.28, lpg=0.05),
    "urals": dict(naphtha=0.14, diesel=0.25, hgo=0.30, lpg=0.06),
}
OPEX = dict(cdu=0.6, vdu=0.4, fcc=2.0, hcu=3.0, coker=2.5, reformer=1.5, product_ht=1.0)
H2_SCF = dict(hcu=1500.0, ht_base=150.0, ht_per_pct_s=250.0)            # scf per bbl feed
MMBTU_PER_KSCF_H2 = 0.37                                                # SMR gas use per 1,000 scf H2


@dataclass
class Prices:
    brent: float
    cracks: dict                 # lpg, gasoline, jet, diesel, fuel_oil, naphtha
    crude_cost: dict             # delivered $/bbl per crude
    lng: float                   # $/MMBtu
    sulfur_usd_t: float          # realised
    petcoke_usd_t: float
    hsgo_discount: float = 15.0  # unhydrotreated gasoil vs diesel


@dataclass
class Result:
    status: str
    margin_usd_k_day: float
    products: dict
    units: dict
    coke_t_day: float
    sulfur_t_day: float
    detail: dict = field(default_factory=dict)


def solve(slate: dict, p: Prices, cap_scale: float = 1.0, coker_extra: float = 0.0) -> Result:
    """slate = {"urals": kb/d, "merey": kb/d}. Returns optimal margin and flows."""
    crude_total = sum(slate.values())
    cap = {k: CAP_RATIO[k] * crude_total * cap_scale for k in CAP_RATIO}
    cap["coker"] *= (1 + coker_extra)
    m = pulp.LpProblem("refinery", pulp.LpMaximize)
    V = lambda name: pulp.LpVariable(name, lowBound=0)   # PuLP 2.x API

    price = {k: p.brent + v for k, v in p.cracks.items()}
    h2_usd_per_scf = p.lng * MMBTU_PER_KSCF_H2 / 1000
    crudes = [c for c, v in slate.items() if v > 0]

    cut = {c: {k: slate[c] * ASSAYS[c]["cuts"][k][0] for k in ASSAYS[c]["cuts"]} for c in crudes}

    # --- atmospheric residue -> VDU or straight to fuel oil
    ar = {c: cut[c]["vgo"] + cut[c]["vr"] for c in crudes}
    ar_vdu = {c: V(f"ar_vdu_{c}") for c in crudes}
    ar_fo = {c: V(f"ar_fo_{c}") for c in crudes}
    for c in crudes:
        m += ar_vdu[c] + ar_fo[c] == ar[c]
    m += pulp.lpSum(ar_vdu.values()) <= cap["vdu"]
    vgo = {c: ar_vdu[c] * cut[c]["vgo"] / ar[c] for c in crudes}
    vr = {c: ar_vdu[c] * cut[c]["vr"] / ar[c] for c in crudes}

    # --- vacuum residue -> coker or fuel oil
    vr_cok = {c: V(f"vr_cok_{c}") for c in crudes}
    vr_fo = {c: V(f"vr_fo_{c}") for c in crudes}
    for c in crudes:
        m += vr_cok[c] + vr_fo[c] == vr[c]
    m += pulp.lpSum(vr_cok.values()) <= cap["coker"]
    cok = {k: pulp.lpSum(vr_cok[c] * COKER_Y[c][k] for c in crudes) for k in ["naphtha", "diesel", "hgo", "lpg"]}
    coke_t = pulp.lpSum(vr_cok[c] * ASSAYS[c]["cuts"]["vr"][1] * BBL_M3 * 1.6 * ASSAYS[c]["vr_ccr"] / 100 for c in crudes)

    # --- cracker feed pool (VGO + coker heavy gasoil) -> FCC, HCU or fuel oil
    feed_fcc, feed_hcu, feed_fo = V("feed_fcc"), V("feed_hcu"), V("feed_fo")
    m += feed_fcc + feed_hcu + feed_fo == pulp.lpSum(vgo.values()) + cok["hgo"]
    m += feed_fcc <= cap["fcc"]
    m += feed_hcu <= cap["hcu"]

    # --- naphtha pool -> reformer/isom or sold as naphtha
    naph_pool = pulp.lpSum(cut[c]["naphtha"] for c in crudes) + cok["naphtha"] + HCU_Y["naphtha"] * feed_hcu
    naph_ref, naph_sell = V("naph_ref"), V("naph_sell")
    m += naph_ref + naph_sell == naph_pool
    m += naph_ref <= cap["reformer"]

    # --- distillate pool -> hydrotreated (ULSD/jet) or sold as high-sulfur gasoil
    kero = pulp.lpSum(cut[c]["kero"] for c in crudes)
    dsl_raw = pulp.lpSum(cut[c]["diesel"] for c in crudes) + cok["diesel"] + FCC_Y["diesel"] * feed_fcc
    dsl_ht, dsl_hs = V("dsl_ht"), V("dsl_hs")
    m += dsl_ht + dsl_hs == dsl_raw
    m += kero + dsl_ht <= cap["product_ht"]

    # average sulfur of hydrotreater feed (fixed estimate from straight-run cuts, for H2 use)
    sr_s = {c: ASSAYS[c]["cuts"]["diesel"][2] for c in crudes}
    ht_s = sum(slate[c] * sr_s[c] for c in crudes) / crude_total

    # --- products
    prod = {
        "lpg": pulp.lpSum(cut[c]["lpg"] for c in crudes) + cok["lpg"] + FCC_Y["lpg"] * feed_fcc
               + HCU_Y["lpg"] * feed_hcu + REF_Y["lpg"] * naph_ref,
        "gasoline": REF_Y["gasoline"] * naph_ref + FCC_Y["gasoline"] * feed_fcc,
        "naphtha": naph_sell,
        "jet": kero + HCU_Y["jet"] * feed_hcu,
        "diesel": dsl_ht + HCU_Y["diesel"] * feed_hcu,
        "hsgo": dsl_hs,
        "fuel_oil": pulp.lpSum(ar_fo.values()) + pulp.lpSum(vr_fo.values()) + feed_fo + FCC_Y["fuel_oil"] * feed_fcc,
    }
    revenue = (pulp.lpSum(prod[k] * price[k] for k in ["lpg", "gasoline", "naphtha", "jet", "diesel", "fuel_oil"])
               + prod["hsgo"] * (price["diesel"] - p.hsgo_discount)
               + coke_t * p.petcoke_usd_t)

    # --- sulfur recovered = crude S - S left in fuel oil - S in coke - S in sold naphtha/hsgo
    def s_t(c, k, vol):   # tonnes of sulfur in `vol` kbbl of cut k
        return vol * ASSAYS[c]["cuts"][k][1] * BBL_M3 * ASSAYS[c]["cuts"][k][2] / 100
    s_total = sum(s_t(c, k, cut[c][k]) for c in crudes for k in cut[c])
    s_fo = pulp.lpSum(ar_fo[c] * ASSAYS[c]["sulfur"] / 100 * ASSAYS[c]["cuts"]["vr"][1] * BBL_M3 for c in crudes) \
         + pulp.lpSum(s_t(c, "vr", vr_fo[c]) for c in crudes)
    s_coke = pulp.lpSum(s_t(c, "vr", vr_cok[c]) * 0.30 for c in crudes)   # ~30% of VR sulfur stays in coke
    s_hsgo = dsl_hs * 0.87 * BBL_M3 * ht_s / 100
    sulfur = (s_total - s_fo - s_coke - s_hsgo) * 0.97

    opex = (OPEX["cdu"] * crude_total + OPEX["vdu"] * pulp.lpSum(ar_vdu.values())
            + OPEX["fcc"] * feed_fcc + OPEX["hcu"] * feed_hcu + OPEX["coker"] * pulp.lpSum(vr_cok.values())
            + OPEX["reformer"] * naph_ref + OPEX["product_ht"] * (kero + dsl_ht))
    h2 = (H2_SCF["hcu"] * feed_hcu + (H2_SCF["ht_base"] + H2_SCF["ht_per_pct_s"] * ht_s) * (kero + dsl_ht)) * h2_usd_per_scf
    crude_cost = sum(slate[c] * p.crude_cost[c] for c in crudes)

    m += revenue + sulfur * p.sulfur_usd_t - opex - h2 - crude_cost
    m.solve(pulp.PULP_CBC_CMD(msg=False))   # CBC ships with PuLP 2.x

    val = lambda e: pulp.value(e) or 0.0
    return Result(
        status=pulp.LpStatus[m.status],
        margin_usd_k_day=val(m.objective),
        products={k: val(v) for k, v in prod.items()},
        units={"vdu": val(pulp.lpSum(ar_vdu.values())), "coker": val(pulp.lpSum(vr_cok.values())),
               "fcc": val(feed_fcc), "hcu": val(feed_hcu), "reformer": val(naph_ref),
               "product_ht": val(kero + dsl_ht), "fuel_oil_from_ar": val(pulp.lpSum(ar_fo.values())),
               "fuel_oil_from_vr": val(pulp.lpSum(vr_fo.values()))},
        coke_t_day=val(coke_t) * 1000,
        sulfur_t_day=val(sulfur) * 1000,
        detail={"cap": cap, "revenue": val(revenue), "opex": val(opex), "h2": val(h2),
                "crude_cost": crude_cost, "sulfur_credit": val(sulfur) * p.sulfur_usd_t},
    )
