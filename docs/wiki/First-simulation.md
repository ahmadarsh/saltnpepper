# First simulation

1. Open the app and choose **Load example model**. Wait for STEP import to finish.
2. Choose **Example ports**. Input pad becomes red and Output pad becomes blue. The centre solid is the conductor.
3. Select electrical analysis, total current 0.1 A, ambient temperature 20 °C, mesh size 0.8 mm and disable finer mesh comparison for a single solve.
4. Run the simulation and wait for completion in Runs.
5. Open Results. Check the approximately 0.172414 mΩ resistance and explore voltage drop/current density.

For your own STEP file, select every relevant terminal solid with +IN or +OUT. Inputs share one potential, outputs share another. Current is the total across all inputs, not the current per pad. Copper must be connected. Check declared STEP units and displayed dimensions before running.

For mesh convergence, enable finer comparison: it performs two solves within one saved run. Smaller mesh sizes increase memory and time substantially.

Choose Salt or Pepper for white or black 3D backgrounds. The Accent selector changes interface colours; the Results Colour map selector changes field colours. Inputs stay red and outputs stay blue.

Delete individual runs or all runs from Runs. Delete imported geometry using its × control. Confirm in the in-app dialog; Cancel or Escape preserves files. Clear workspace resets tools and selections without removing saved files.
