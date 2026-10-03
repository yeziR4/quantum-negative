# Simulator vs quantum hardware

**Prompt:** `the last negative of a dying star, developed in the dark`

Same prompt, same seed (`7808021261148314384`), rendered twice — the only difference is where the creative budget was measured.

| | simulator (Aer) | hardware (IBM) |
|---|---|---|
| device | `aer` | `ibm_fez` |
| shots | 8192 | 8192 |
| values sent | 512 | 256 |
| values changed | 510 | 256 |
| mean absolute change | 0.010051 | **0.085943** |
| max absolute change | 0.041217 | **0.441521** |
| IBM job id | — | `db0ap9s92g1c739a6cq0` |
| QPU seconds | — | 4 |
| wall clock | 833.9s | 278.4s |

## What this shows

Two differences are worth separating. First, **payload size**: the simulator encoded 512 values while the device accepts only 256, because `ibm_fez` refuses the larger array (its data-qubit capacity is 448). That is a genuine constraint of the hardware rather than a choice on our part.

Second, and more importantly, **the quantum error itself**. The engine encodes a caller-supplied array into a quantum circuit, measures it, and returns the decoded values. On the simulator the round-trip perturbs those values by a mean of **0.010051**. On `ibm_fez` it perturbs them by a mean of **0.085943** — **8.6x** more, and up to **0.441521** on a single value.

That difference is decoherence, gate error and readout error — the physical behaviour of the device. It is not a bug and not noise we added: it is the measurement.

### The shot count is the interesting variable

Shot count changes the comparison, and *how* it changes is itself the evidence:

| shots | simulator mean | hardware mean | ratio |
|---|---|---|---|
| 256 | 0.0643 | 0.0954 | 1.5x |
| 8192 | 0.0101 | 0.0859 | **8.6x** |

At low shot counts **statistical** noise dominates both runs, so they look similar. As shots increase the simulator converges toward the exact circuit answer — 0.064 down to 0.010 — while the hardware settles at an **error floor near 0.086 that more sampling cannot remove**, because that floor is the device's own error rather than sampling error.

The consequence for this project: a hardware render is reproducible, but it is not *the same image* as the simulated one, and it cannot be made so. That is the difference between simulating a quantum computer and using one.

The two finished films differ by a mean of **0.026369** per pixel.

## Files

- `simulator/` — film, score, poster, receipt for the emulated run
- `hardware/` — the same for the hardware run
- `comparison.json` — the figures above, machine-readable

Both receipts record every creative decision and the engine that produced it, so either render can be audited independently.
