__package__ = 'archivebox.extractors'


from pathlib import Path
from typing import Optional, List, Dict, Tuple
from collections import defaultdict

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
)
from ..config import (
    TIMEOUT,
    CURL_ARGS,
    CHECK_SSL_VALIDITY,
    SAVE_ARCHIVE_DOT_ORG,
    CURL_BINARY,
    CURL_VERSION,
    CURL_USER_AGENT,
)
from ..logging_util import TimedProgress


# output = '{domain}/'


@enforce_types
def should_save_archive_dot_org(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[Path]=None) -> bool:
    out_dir = out_dir or Path(snapshot.snapshot_dir)
    if is_static_file(snapshot.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'archive.org.txt').exists():
        # if open(path, 'r').read().strip() != 'None':
        return False

    return SAVE_ARCHIVE_DOT_ORG

@enforce_types
def save_archive_dot_org(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """submit site to archive.org for archiving via their service, save returned archive url"""

    out_dir = out_dir or Path(snapshot.snapshot_dir)
    output: ArchiveOutput = 'archive.org.txt'
    archive_org_url = None
    submit_url = 'https://web.archive.org/save/{}'.format(snapshot.url)
    cmd = [
        CURL_BINARY,
        *CURL_ARGS,
        '--head',
        '--max-time', str(timeout),
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        submit_url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)
        content_location, errors = parse_archive_dot_org_response(result.stdout)
        if content_location:
            archive_org_url = content_location[0]
        elif len(errors) == 1 and 'RobotAccessControlException' in errors[0]:
            archive_org_url = None
            # raise ArchiveError('Archive.org denied by {}/robots.txt'.format(domain(link.url)))
        elif errors:
            raise ArchiveError(', '.join(errors))
        else:
            raise ArchiveError('Failed to find "content-location" URL header in Archive.org response.')
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    if output and not isinstance(output, Exception):
        # instead of writing None when archive.org rejects the url write the
        # url to resubmit it to archive.org. This is so when the user visits
        # the URL in person, it will attempt to re-archive it, and it'll show the
        # nicer error message explaining why the url was rejected if it fails.
        archive_org_url = archive_org_url or submit_url
        with open(str(out_dir / output), 'w', encoding='utf-8') as f:
            f.write(archive_org_url)
        chmod_file('archive.org.txt', cwd=str(out_dir))
        output = archive_org_url

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def parse_archive_dot_org_response(response: bytes) -> Tuple[List[str], List[str]]:
    # Parse archive.org response headers
    headers: Dict[str, List[str]] = defaultdict(list)

    # lowercase all the header names and store in dict
    for header in response.splitlines():
        if b':' not in header or not header.strip():
            continue
        name, val = header.decode().split(':', 1)
        headers[name.lower().strip()].append(val.strip())

    # Get successful archive url in "content-location" header or any errors
    content_location = headers.get('content-location', headers['location'])
    errors = headers['x-archive-wayback-runtime-error']
    return content_location, errors

