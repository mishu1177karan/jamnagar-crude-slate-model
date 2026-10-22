# Jamnagar Crude Slate Model: Venezuelan Merey vs Russian Urals

Does heavy, high-sulfur Venezuelan **Merey** make Reliance's Jamnagar refinery more money per barrel than Russian **Urals**? And what discount does Merey need to be worth running?

This notebook answers that with a bottom-up refinery margin model, priced with live market data from **22 October 2026**.

![Margin bridge](charts/1_margin_bridge.png)

## Key findings (22 Oct 2026 prices)

| Metric | Result |
|---|---|
| Merey advantage over Urals | **+$2.00/bbl** (~$205M a year at 280 kb/d) |
| Break-even Merey discount | **Brent −$14.50/bbl** |
| Probability Merey wins (10,000-run Monte Carlo) | **87%** |
| Merey advantage at September pricing (Urals at +$8) | **+$10.00/bbl** |
| Value of Merey's extra sulfur ($835/t) | +$1.00/bbl |
| Freight at which the advantage disappears | ~$12/bbl |

- **Timing explains October's import surge.** October cargoes were priced in September, when Urals traded at a premium of about $8.
- **Petcoke is a hidden driver.** With Asian LNG near $30/MMBtu, Merey's extra petcoke is valuable as gasifier feed that replaces imported LNG.
- **Two sourced prices drive the answer:** the Urals delivered premium and the Merey discount. The estimated inputs move the result only between +$0.25 and +$3.14/bbl.

## Method

```
Net margin = Product slate value − Delivered crude cost − Processing cost + Sulfur credit
```

1. Per-barrel margin for each crude: yield-weighted product value, delivered cost (FOB differential + freight + insurance), processing cost scaled by sulfur and API gravity, and a sulfur byproduct credit.
2. A margin bridge from Urals to Merey.
3. An implied break-even discount, solved with a root-finder.
4. Low, base and high cases for every estimated input, plus named stress scenarios.
5. A tornado sensitivity across each input's range.
6. A heatmap of the Merey discount against freight.
7. A 10,000-run Monte Carlo with triangular (low, base, high) distributions.

## Data

Every input is listed in [`inputs.csv`](inputs.csv) with its base, low and high values, and is tagged **Sourced** (published market figure, with source and date) or **Estimate** (not publicly available).

**Sourced (16):** Brent, Merey differential, freight, Urals delivered differential, gasoline, diesel and fuel oil cracks, JKM LNG, sulfur price, crude assays, USD/INR.

**Estimated (6) and yield vectors:** Jamnagar's yields and unit processing costs aren't public, so these are my estimates, each with a low/high range.

Main sources: Oilprice.com, EIA, Quantum Commodity Intelligence, Reuters (via Rio Times and Baird Maritime), Business Standard, Argus Media, and Kpler (via Business Today). The full list is at the end of the notebook.

## Run it

```bash
pip install -r requirements.txt
jupyter notebook jamnagar_merey_vs_urals.ipynb
```

To update the model, edit the input table in Section 1 of the notebook and re-run. A rendered copy, [`jamnagar_merey_vs_urals.html`](jamnagar_merey_vs_urals.html), can be opened without Python.

## Limitations

- Yields and processing costs are estimates. A crude-assay-based linear program (e.g. AMPL or PuLP) would make them more realistic.
- Jet and LPG cracks are approximations, because exact Asian values are behind paywalls.
- Prices are a snapshot from 22 Oct 2026, and refining margins move daily.
- Reliance's actual PDVSA contract price isn't disclosed. The break-even analysis infers a floor for it.

## Author

**Mishu Kumar**: PGDM (Insurance & Risk Management), National Insurance Academy, Pune.

*Educational research only. Not investment advice.*
