# Price-continuity hard gate

## Default thresholds

| Diagnostic | Maximum allowed |
|---|---:|
| Median absolute one-minute equity return | 2.0% |
| Fraction of absolute one-minute returns greater than 20% | 1.0% |

Either breach blocks the run. Missing or non-finite diagnostics also block the run.

## Behaviour when blocked

- Writes `outputs/data_quality.json` and `outputs/data_quality.csv` first.
- Raises `DataQualityError` for notebook users.
- The command-line entry point prints the reason and exits with status code 2.
- Does not generate new strategy signals, positions, trades, performance summaries or charts.
- Old backtest output files have been removed from this package to avoid stale results being
  mistaken for results from the gated version.

## Run and test

```bash
python run_project.py
python -m unittest discover -s tests -v
```

Correct or replace the source data before rerunning. Do not suppress the gate or clip extreme
returns just to obtain a performance report.
