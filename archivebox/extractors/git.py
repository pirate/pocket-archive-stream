__package__ = 'archivebox.extractors'


from pathlib import Path
from typing import Optional

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    domain,
    extension,
    without_query,
    without_fragment,
)
from ..config import (
    TIMEOUT,
    SAVE_GIT,
    GIT_BINARY,
    GIT_ARGS,
    GIT_VERSION,
    GIT_DOMAINS,
    CHECK_SSL_VALIDITY
)
from ..logging_util import TimedProgress


# output = 'git/'
# @contents = output.glob('*.*')
# @exists = self.contents.exists()
# @size => get_size(self.contents)
# @num_files => len(self.contents)

@enforce_types
def should_save_git(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[Path]=None) -> bool:
    out_dir = out_dir or snapshot.snapshot_dir
    if is_static_file(snapshot.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'git').exists():
        return False

    is_clonable_url = (
        (domain(snapshot.url) in GIT_DOMAINS)
        or (extension(snapshot.url) == 'git')
    )
    if not is_clonable_url:
        return False

    return SAVE_GIT


@enforce_types
def save_git(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using git"""

    out_dir = out_dir or Path(snapshot.snapshot_dir)
    output: ArchiveOutput = 'git'
    output_path = out_dir / output
    output_path.mkdir(exist_ok=True)
    cmd = [
        GIT_BINARY,
        'clone',
        *GIT_ARGS,
        *([] if CHECK_SSL_VALIDITY else ['-c', 'http.sslVerify=false']),
        without_query(without_fragment(snapshot.url)),
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(output_path), timeout=timeout + 1)
        if result.returncode == 128:
            # ignore failed re-download when the folder already exists
            pass
        elif result.returncode > 0:
            hints = 'Got git response code: {}.'.format(result.returncode)
            raise ArchiveError('Failed to save git clone', hints)

        chmod_file(output, cwd=str(out_dir))

    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=GIT_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
