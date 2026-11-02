# Prepare geometry from KiCad

Use this workflow to prepare the STEP copper geometry for Salt and Pepper. KiCad board import is on the roadmap; the current application imports STEP files.

## 1. Configure the STEP export

Open the PCB in KiCad, refill the copper zones, and open the 3D export dialog from **File → Export**. Select STEP format.

Include the copper needed for the electrical path:

| Geometry / option | Setting |
| --- | --- |
| Pads | Include |
| Tracks and vias | Include |
| Copper zones | Include the filled copper |
| Inner copper layers | Include, along with front and back copper |
| Fuse shapes / merge shapes | **Off** — preserve the separate solids and pad identities |
| Fill all vias | **Off** — preserve the via holes |
| Non-copper board body | Exclude |
| Component 3D models | Exclude |

Including vias and filling their holes are separate choices: include the via copper, but leave the holes unfilled. Keep the individual shapes separate in the exported STEP.

## 2. Filter the target net and export

In the same export dialog, enter the net name you want to simulate in the **Net filter**. This limits exported conductors to the matching net; it does not replace disabling the board body and component models. Check that the pads, traces, zone copper and vias needed by that net remain included, then export the STEP file.

Apply the net filter before completing the export. Re-export if you already saved a STEP containing unrelated nets. Export option wording can differ between KiCad versions; see the [official KiCad 3D export documentation](https://docs.kicad.org/9.0/en/pcbnew/pcbnew.html#_exporting_3d_models).

## 3. Inspect the STEP in CAD

Open the exported file in FreeCAD or another CAD application. Check the copper geometry, inner layers and vias, and confirm that the dimensions are correct. Keep the original STEP file for simulation; avoid a CAD re-export that merges or renames its solids.

## 4. Record the input and output pad names

Select each intended source pad and load pad in CAD and note its STEP body/pad label and physical position. For multiple inputs or outputs, record every pad in each group.

Use labels belonging to the exported STEP, rather than a CAD application's temporary internal object identifiers. Check labels against their positions so similarly named pads are not confused.

## 5. Assign pads in Salt and Pepper and run

Import the STEP into Salt and Pepper. Search the solids list for the recorded pad names and assign the input pads with **+IN** and the output pads with **+OUT**. The list can show a shortened pad number; hover to inspect the full STEP name. Check the highlighted geometry before running: **inputs are red and outputs are blue**.

Set the voltage, total current, analysis mode and mesh size, then start the simulation. The application uses the selected solids as terminals; noting a pad name alone does not assign it. Start with a coarse mesh, inspect the result, and compare a finer mesh when checking convergence.

See [First simulation](First-simulation.md) for an example and [Solver](Solver.md) for the shared-potential and total-current assumptions used with multiple pads.
