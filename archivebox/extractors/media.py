__package__ = 'archivebox.extractors'

from pathlib import Path
from typing import Optional

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
)
from ..config import (
    MEDIA_TIMEOUT,
    SAVE_MEDIA,
    YOUTUBEDL_ARGS,
    YOUTUBEDL_BINARY,
    YOUTUBEDL_VERSION,
    CHECK_SSL_VALIDITY
)
from ..logging_util import TimedProgress


# output = 'media/'

@enforce_types
def should_save_media(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[Path]=None) -> bool:
    out_dir = out_dir or snapshot.snapshot_dir

    if is_static_file(snapshot.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'media').exists():
        return False

    return SAVE_MEDIA

@enforce_types
def save_media(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=MEDIA_TIMEOUT) -> ArchiveResult:
    """Download playlists or individual video, audio, and subtitles using youtube-dl"""

    out_dir = out_dir or Path(snapshot.snapshot_dir)
    output: ArchiveOutput = 'media'
    output_path = out_dir / output
    output_path.mkdir(exist_ok=True)
    cmd = [
        YOUTUBEDL_BINARY,
        *YOUTUBEDL_ARGS,
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate']),
        snapshot.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(output_path), timeout=timeout + 1)
        chmod_file(output, cwd=str(out_dir))
        if result.returncode:
            if (b'ERROR: Unsupported URL' in result.stderr
                or b'HTTP Error 404' in result.stderr
                or b'HTTP Error 403' in result.stderr
                or b'URL could be a direct video link' in result.stderr
                or b'Unable to extract container ID' in result.stderr):
                # These happen too frequently on non-media pages to warrant printing to console
                pass
            else:
                hints = (
                    'Got youtube-dl response code: {}.'.format(result.returncode),
                    *result.stderr.decode().split('\n'),
                )
                raise ArchiveError('Failed to save media', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=YOUTUBEDL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
