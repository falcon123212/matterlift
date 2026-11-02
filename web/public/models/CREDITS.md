# 3D models: credits and terms

These meshes are **not** covered by MatterLift's MIT license. They come from the
**Stanford 3D Scanning Repository**, Stanford University Computer Graphics Laboratory
(https://graphics.stanford.edu/data/3Dscanrep/), and are used under its terms: free for research
and non-commercial use, redistribution free of charge allowed, the source must be acknowledged;
commercial use needs Stanford's permission.

| File | Model | Source | Original | Here |
|---|---|---|---|---|
| `stanford_dragon.ply` | Stanford Dragon | Stanford Computer Graphics Laboratory | `dragon_vrip.ply`, 871,414 triangles | 150,000 triangles (meshoptimizer) |
| `happy_buddha.ply` | Happy Buddha | Stanford Computer Graphics Laboratory | `happy_vrip.ply`, 1,087,716 triangles | 150,000 triangles (fast-simplification) |
| `lucy.ply` | Lucy | Stanford Computer Graphics Laboratory | `lucy.ply`, 28,055,742 triangles | 149,998 triangles (fast-simplification) |

Changes: decimated with quadric simplification, positions and triangles only, binary little-endian
PLY. MatterLift shows them in the material preview (Dragon, Buddha, Lucy) and in Live RT.
