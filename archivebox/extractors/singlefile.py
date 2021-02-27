__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional
import json

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
)
from ..config import (
    TIMEOUT,
    SAVE_SINGLEFILE,
    DEPENDENCIES,
    SINGLEFILE_VERSION,
    CHROME_BINARY,
)
from ..logging_util import TimedProgress


@enforce_types
def should_save_singlefile(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[Path]=None) -> bool:
    out_dir = out_dir or Path(snapshot.snapshot_dir)
    if is_static_file(snapshot.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'singlefile.html').exists():
        return False

    return SAVE_SINGLEFILE


@enforce_types
def save_singlefile(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using single-file"""

    out_dir = out_dir or Path(snapshot.snapshot_dir)
    output = "singlefile.html"

    browser_args = chrome_args(TIMEOUT=0)

    # SingleFile CLI Docs: https://github.com/gildas-lormeau/SingleFile/tree/master/cli
    browser_args = '--browser-args={}'.format(json.dumps(browser_args[1:]))
    cmd = [
        DEPENDENCIES['SINGLEFILE_BINARY']['path'],
        '--browser-executable-path={}'.format(CHROME_BINARY),
        browser_args,
        snapshot.url,
        output
        output,
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        hints = (
            'Got single-file response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0) or not (out_dir / output).is_file():
            raise ArchiveError('SingleFile was not able to archive the page', hints)
        chmod_file(output, cwd=str(out_dir))
    except (Exception, OSError) as err:
        status = 'failed'
        # TODO: Make this prettier. This is necessary to run the command (escape JSON internal quotes).
        cmd[2] = browser_args.replace('"', "\\\"")
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=SINGLEFILE_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
