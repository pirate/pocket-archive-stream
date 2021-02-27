__package__ = 'archivebox.extractors'

import re
from pathlib import Path

from typing import Optional
from datetime import datetime

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    without_fragment,
    without_query,
    path,
    domain,
    urldecode,
)
from ..config import (
    WGET_ARGS,
    TIMEOUT,
    SAVE_WGET,
    SAVE_WARC,
    WGET_BINARY,
    WGET_VERSION,
    RESTRICT_FILE_NAMES,
    CHECK_SSL_VALIDITY,
    SAVE_WGET_REQUISITES,
    WGET_AUTO_COMPRESSION,
    WGET_USER_AGENT,
    COOKIES_FILE,
)
from ..logging_util import TimedProgress


@enforce_types
def should_save_wget(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[Path]=None) -> bool:
    output_path = wget_output_path(snapshot)
    out_dir = out_dir or Path(snapshot.snapshot_dir)
    if not overwrite output_path and (out_dir / output_path).exists():
        return False

    return SAVE_WGET


@enforce_types
def save_wget(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using wget"""

    out_dir = out_dir or snapshot.snapshot_dir
    if SAVE_WARC:
        warc_dir = out_dir / "warc"
        warc_dir.mkdir(exist_ok=True)
        warc_path = warc_dir / str(int(datetime.now().timestamp()))

    # WGET CLI Docs: https://www.gnu.org/software/wget/manual/wget.html
    output: ArchiveOutput = None
    cmd = [
        WGET_BINARY,
        # '--server-response',  # print headers for better error parsing
        *WGET_ARGS,
        '--timeout={}'.format(timeout),
        *(['--restrict-file-names={}'.format(RESTRICT_FILE_NAMES)] if RESTRICT_FILE_NAMES else []),
        *(['--warc-file={}'.format(str(warc_path))] if SAVE_WARC else []),
        *(['--page-requisites'] if SAVE_WGET_REQUISITES else []),
        *(['--user-agent={}'.format(WGET_USER_AGENT)] if WGET_USER_AGENT else []),
        *(['--load-cookies', str(COOKIES_FILE)] if COOKIES_FILE else []),
        *(['--compression=auto'] if WGET_AUTO_COMPRESSION else []),
        *([] if SAVE_WARC else ['--timestamping']),
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate', '--no-hsts']),
        snapshot.url,
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)
        output = wget_output_path(snapshot)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        files_downloaded = (
            int(output_tail[-1].strip().split(' ', 2)[1] or 0)
            if 'Downloaded:' in output_tail[-1]
            else 0
        )
        hints = (
            'Got wget response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0 and files_downloaded < 1) or output is None:
            if b'403: Forbidden' in result.stderr:
                raise ArchiveError('403 Forbidden (try changing WGET_USER_AGENT)', hints)
            if b'404: Not Found' in result.stderr:
                raise ArchiveError('404 Not Found', hints)
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise ArchiveError('500 Internal Server Error', hints)
            raise ArchiveError('Wget failed or got an error from the server', hints)
        
        if (out_dir / output).exists():
            chmod_file(output, cwd=str(out_dir))
        else:
            print(f'          {out_dir}/{output}')
            raise ArchiveError('Failed to find wget output after running', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=WGET_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )


@enforce_types
def wget_output_path(snapshot: Model) -> Optional[str]:
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension (-E)
    """

    # Wget downloads can save in a number of different ways depending on the url:
    #    https://example.com
    #       > example.com/index.html
    #    https://example.com?v=zzVa_tX1OiI
    #       > example.com/index.html?v=zzVa_tX1OiI.html
    #    https://www.example.com/?v=zzVa_tX1OiI
    #       > example.com/index.html?v=zzVa_tX1OiI.html

    #    https://example.com/abc
    #       > example.com/abc.html
    #    https://example.com/abc/
    #       > example.com/abc/index.html
    #    https://example.com/abc?v=zzVa_tX1OiI.html
    #       > example.com/abc?v=zzVa_tX1OiI.html
    #    https://example.com/abc/?v=zzVa_tX1OiI.html
    #       > example.com/abc/index.html?v=zzVa_tX1OiI.html

    #    https://example.com/abc/test.html
    #       > example.com/abc/test.html
    #    https://example.com/abc/test?v=zzVa_tX1OiI
    #       > example.com/abc/test?v=zzVa_tX1OiI.html
    #    https://example.com/abc/test/?v=zzVa_tX1OiI
    #       > example.com/abc/test/index.html?v=zzVa_tX1OiI.html

    # There's also lots of complexity around how the urlencoding and renaming
    # is done for pages with query and hash fragments or extensions like shtml / htm / php / etc

    # Since the wget algorithm for -E (appending .html) is incredibly complex
    # and there's no way to get the computed output path from wget
    # in order to avoid having to reverse-engineer how they calculate it,
    # we just look in the output folder read the filename wget used from the filesystem
    full_path = without_fragment(without_query(path(snapshot.url))).strip('/')
    search_dir = Path(snapshot.snapshot_dir) / domain(snapshot.url).replace(":", "+") / urldecode(full_path)
    for _ in range(4):
        if search_dir.exists():
            if search_dir.is_dir():
                html_files = [
                    f for f in search_dir.iterdir()
                    if re.search(".+\\.[Ss]?[Hh][Tt][Mm][Ll]?$", str(f), re.I | re.M)
                ]
                if html_files:
                    return str(html_files[0].relative_to(snapshot.snapshot_dir))

                # sometimes wget'd URLs have no ext and return non-html
                # e.g. /some/example/rss/all -> some RSS XML content)
                #      /some/other/url.o4g   -> some binary unrecognized ext)
                # test this with archivebox add --depth=1 https://getpocket.com/users/nikisweeting/feed/all
                last_part_of_url = urldecode(full_path.rsplit('/', 1)[-1])
                for file_present in search_dir.iterdir():
                    if file_present == last_part_of_url:
                        return str((search_dir / file_present).relative_to(snapshot.snapshot_dir))

        # Move up one directory level
        search_dir = search_dir.parent

        if search_dir == snapshot.snapshot_dir:
            break

    # check for literally any file present that isnt an empty folder
    domain_dir = Path(domain(snapshot.url).replace(":", "+"))
    files_within = list((Path(snapshot.snapshot_dir) / domain_dir).glob('**/*.*'))
    if files_within:
        return str((domain_dir / files_within[-1]).relative_to(snapshot.snapshot_dir))
    
    # fallback to just the domain dir, dont try to introspect further inside it
    search_dir = Path(snapshot.snapshot_dir) / domain(snapshot.url).replace(":", "+")
    if search_dir.is_dir():
        return domain(snapshot.url).replace(":", "+")

    return None
