# Copper bar example

Original geometry by Arsh Ahmad, licensed CC BY 4.0. Attribute “Salt and Pepper copper bar example — Arsh Ahmad”. The generator is GPL-3.0-or-later.

`copper-bar.step` contains three touching solids with STEP units in millimetres: Input pad (z=0–1), Conductor (z=1–9), Output pad (z=9–10). Each has a 1 × 1 mm cross-section. Use **Example ports** after import, or manually select Input pad as IN and Output pad as OUT.

At 58 MS/m and temperature-independent conductivity, R = L/(σA) = 0.01/(58e6 × 1e-6) = 0.000172413793 Ω. At 0.1 A the drop is approximately 17.2414 µV. This educational solid is deliberately thick for a fast, verifiable simulation; it is not a production PCB design.

Regenerate with `python examples/generate.py` in the project environment. Electrical analysis, mesh 0.8 mm, finer comparison off is a quick first run. For thermal analysis set alpha=0 to compare constant-conductivity behaviour, and inspect the convection assumptions.
