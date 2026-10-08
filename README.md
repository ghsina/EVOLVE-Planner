# EVOLVE Planner

Lowest-cost design of a floating (or bottom-fixed) offshore energy island and its onshore plant, for
electricity, hydrogen or both, on one year of hourly data reduced with topological data analysis (TDA).

**What it sizes:** offshore wind, floating PV, electrolysers (island and onshore), desalination, compressors,
fuel cells, batteries, hydrogen tanks, the export cable (HVAC or HVDC by route length) and the hydrogen
pipeline (new or repurposed classes).
**What it delivers:** capacities, annualised costs, revenues, net cost of electricity and hydrogen, the
8,760-hour operation, and a drawing of the island, export routes and onshore plant.

## How a run works

1. **Reduce.** The cumulative surplus-and-deficit curve of each hourly series is analysed with 0-dimensional
   persistent homology. Persistent extrema (deep lulls, long surpluses) become fixed cuts; neighbouring hours are
   merged where the curve stays within a chord error. Default: 1,460 variable-length blocks.
2. **Size.** A Pyomo capacity-expansion LP is solved on the blocks, with storage tracked across the whole
   year (min/max-bounded state of charge). Pipeline classes are handled exactly.
3. **Check.** The design is operated on all 8,760 hours. If an hour falls short, capacities are scaled by the
   smallest group factor that delivers every contract and the year is re-optimised.

In the Step 2 tests (Belle-Île, 2019 and 2024, three cases) the cost stayed within 0.3 % of the full-year
optimum and every contract was delivered.

## Run it on your computer

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

GLPK is optional (`packages.txt` installs it on Streamlit Cloud; locally `apt install glpk-utils` or
`conda install glpk`). HiGHS is installed with `highspy` and is the default.

## Inputs

Everything can be typed in the app or loaded from one Excel workbook (sidebar, "Open an inputs workbook").
The workbook has an `Inputs` sheet (one row per parameter, edit the `value` column) and a `TimeSeries` sheet
with 8,760 rows: `wind_cf`, `pv_cf` (0–1), `price_eur_mwh`, `elec_demand_mw`, `h2_demand_kgh` (the last two
only for profile delivery). A leap year (8,784 rows) is accepted; 29 February is removed.

Without files, the app can download wind and solar capacity factors from ERA5 (Open-Meteo archive API) and
day-ahead prices from Energy-Charts (Fraunhofer ISE) for the island coordinates.

Cost values flagged "placeholder" will be replaced with referenced values in Step 3.

## Repository layout

```
app.py                      Streamlit app (wizard: Site, Use case, Data, Technologies, Run, Results)
evolve_planner/
  params.py                 every input: label, unit, default, help; derived quantities
  tda.py                    topology-preserving chronological aggregation (TPCA)
  timestructure.py          variable-length time steps
  model.py                  Pyomo capacity-expansion model
  workflow.py               reduce -> size -> check on the full year
  weather.py                uploads, ERA5 and price downloads, CF conversion
  workbook.py, report.py    input and results workbooks
ui/                         theme, Plotly charts, island drawing (SVG)
examples/belle_ile/         2019 and 2024 hourly series and presets
tests/                      TDA properties and an end-to-end check
```

## Tests

```bash
pip install pytest
pytest -q                 # about one minute
```

## Hosting

Streamlit Community Cloud: connect the GitHub repository, main file `app.py`, Python 3.12. The free tier
has limited memory; the app runs one solve at a time and queues the next. For heavier use, the `Dockerfile`
runs the same app on any server: `docker build -t evolve-planner . && docker run -p 8501:8501 evolve-planner`.
