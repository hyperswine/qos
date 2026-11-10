# Native instruction ratchet: ceilings raised to 474 and 95

10 November 2026. Owner decision.

The ratchet on `programs/system.fpr` (rv64) had ceilings of 312 for the
largest selected segment and 67 for runtime call sites per function, set on
23 October with the typed native instruction contract
([NATIVE-INSTRUCTION-ADMISSION](2026-10-23-NATIVE-INSTRUCTION-ADMISSION.md)).
It has reported segment 474 and 95 call sites at every FP-RISC pin tried
since, including the baseline `1a09f01`, and the pin trials of 3, 5 and
6 November list it as a known failure.

CI did not show it because the pinned compiler had not built on the runners
since 28 October. With that fixed (#31, #32) the host job reached this step
and stopped there, in front of the host C checks.

The ceilings are now the measured values, 474 and 95, at FP-RISC `e138e65`,
in `.github/workflows/ci.yml`, `check-all.sh` and `tests/test_check_all.py`.
The ratchet passes with no headroom, so any growth fails it. What grew
between 312/67 and 474/95 was not investigated; the ceilings record the
current state, they do not explain it.
