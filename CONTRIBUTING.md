# Contributing

Use the source setup in docs/wiki/Setup.md. Keep CAD work in isolated workers and do not call Gmsh from HTTP request threads. Keep input pads red and outputs blue across themes. Do not commit saved user data or STEP designs other than the documented public example.

Before a pull request, run:

```sh
python -m unittest pcb_simulator.test_server pcb_simulator.test_backend pcb_simulator.viewer.test_results
python -m simulation.test_generic_engine
```

Use your virtual environment Python. Describe the change and validation. Contributions to software are GPL-3.0-or-later; documentation/artwork/example geometry contributions are CC BY 4.0. Do not submit assets you cannot redistribute.
