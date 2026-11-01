"""pbrforge: turn one image into a tileable PBR material (pure numpy/scipy, no network)."""
from .forge import fix_albedo
from .maps import MapParams, derive

__all__ = ["fix_albedo", "MapParams", "derive"]
