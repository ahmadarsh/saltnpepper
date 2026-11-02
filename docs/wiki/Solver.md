# Solver and pads

Gmsh imports STEP through OpenCASCADE, combines touching selected copper and generates conformal linear tetrahedra. Custom FEM assembles electrical conduction and thermal conduction/convection equations. SciPy SuperLU solves the sparse systems. The Rust shell manages the desktop window and backend lifecycle; it does not replace the numerical solver.

All input electrode faces share a potential, and all output faces share another. A unit potential difference determines conductance, then the field is scaled to the requested total current. Current division follows geometry/conductivity, not equal pad allocation. Per-pad reaction currents are reported; overlapping electrode nodes are divided for reporting. Independent output loads are not supported.

Disconnected input/output regions are rejected; unrelated isolated copper is excluded. Thermal analysis iterates temperature-dependent conductivity when enabled. It models copper and approximate convection, without FR4, radiation, solder mask or populated components. Validate boundary conditions and mesh convergence for engineering use.

Finer mesh comparison runs the same analysis at two mesh sizes in one saved run. It is not an accidental duplicate simulation.
