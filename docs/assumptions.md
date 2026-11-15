# Simulation assumptions (draft)

The challenge submission's assumptions and limitations (synthetic cases, no pilot, ladder misses, unpriced SMS, and so on) are in [assumptions-and-limitations.md](assumptions-and-limitations.md).

All outputs from the synthetic cohort and the simulation are **SIMULATED, not clinical evidence**.
We do not reuse any number from the external reviews. Every figure in the demo comes from our own runs.

## Injected failure rates (test settings, not statistics)
These are the shares of the 1,000 fictional patients that get each failure, chosen by the team in
PLAN_FINAL.md to exercise the workflow. They do not describe any real population.

| Injection | Share |
|---|---|
| Invalid phone | 12% |
| No appointment | 15% |
| No-show (of those with an appointment slot) | 8% of cohort |
| Transport barrier | 10% |
| Language assistance | 6% |
| Overdue | 5% |
| Urgent (critical result) | 3% |

Configurable in `api/loopcloser/synth/generator.py` (`InjectionRates`).

## Simulation (baseline vs LoopCloser), week 4
To be filled in: contact success per channel, effect of a resolved barrier, CHW fallback, and so on.
Each will be listed here with its value and why we picked it.
