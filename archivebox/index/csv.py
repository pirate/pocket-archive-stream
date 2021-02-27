__package__ = 'archivebox.index'

from typing import List, Optional, Any

from django.db.models import Model

from ..util import enforce_types
from .schema import Link


@enforce_types
def snapshots_to_csv(snapshots: List[Model],
                 cols: Optional[List[str]]=None,
                 header: bool=True,
                 separator: str=',',
                 ljust: int=0) -> str:

    cols = cols or ['timestamp', 'is_archived', 'url']
    
    header_str = ''
    if header:
        header_str = separator.join(col.ljust(ljust) for col in cols)

    row_strs = (
        snapshot.as_csv(cols=cols, ljust=ljust, separator=separator)
        for snapshot in snapshots
    )

    return '\n'.join((header_str, *row_strs))


@enforce_types
def to_csv(obj: Any, cols: List[str], separator: str=',', ljust: int=0) -> str:
    from .json import to_json

    return separator.join(
        to_json(getattr(obj, col), indent=None).ljust(ljust)
        for col in cols
    )
