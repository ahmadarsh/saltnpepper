"""Regenerate the original CC BY 4.0 copper bar example (coordinates in mm)."""
from pathlib import Path
import gmsh

def generate(path):
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add('Copper bar')
        for name, z, length in [('Input pad', 0, 1), ('Conductor', 1, 8), ('Output pad', 9, 1)]:
            tag = gmsh.model.occ.addBox(0, 0, z, 1, 1, length)
            gmsh.model.occ.synchronize()
            gmsh.model.setEntityName(3, tag, name)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    # OpenCASCADE's STEP writer does not preserve Gmsh entity labels.
    text = Path(path).read_text()
    for number, name in [(1, 'Input pad'), (2, 'Conductor'), (3, 'Output pad')]:
        text = text.replace(f'Open CASCADE STEP translator 7.8 1.{number}', name)
    Path(path).write_text(text)

if __name__ == '__main__':
    generate(Path(__file__).with_name('copper-bar.step'))
