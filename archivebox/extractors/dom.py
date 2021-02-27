__package__ = 'archivebox.extractors'

from pathlib import Path
from typing import Optional

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file, atomic_write
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
)
from ..config import (
    TIMEOUT,
    SAVE_DOM,
    CHROME_VERSION,
)
from ..logging_util import TimedProgress


# output = 'output.html'


@enforce_types
def should_save_dom(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[Path]=None) -> bool:
    out_dir = out_dir or Path(snapshot.snapshot_dir)
    if is_static_file(snapshot.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'output.html').exists():
        return False

    return SAVE_DOM

@enforce_types
def save_dom(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """print HTML of site to file using chrome --dump-html"""

    out_dir = out_dir or Path(snapshot.snapshot_dir)
    output: ArchiveOutput = 'output.html'
    output_path = out_dir / output
    cmd = [
        *chrome_args(TIMEOUT=timeout),
        '--dump-dom',
        snapshot.url
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)
        atomic_write(output_path, result.stdout)

        if result.returncode:
            hints = result.stderr.decode()
            raise ArchiveError('Failed to save DOM', hints)

        chmod_file(output, cwd=str(out_dir))
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CHROME_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
