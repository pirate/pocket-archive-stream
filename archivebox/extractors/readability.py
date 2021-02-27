__package__ = 'archivebox.extractors'

from pathlib import Path
from tempfile import NamedTemporaryFile

from typing import Optional
import json

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveError
from ..system import run, atomic_write
from ..util import (
    enforce_types,
    download_url,
    is_static_file,
    
)
from ..config import (
    TIMEOUT,
    CURL_BINARY,
    SAVE_READABILITY,
    DEPENDENCIES,
    READABILITY_VERSION,
)
from ..logging_util import TimedProgress


@enforce_types
def get_html(snapshot: Model, path: Path) -> str:
    """
    Try to find wget, singlefile and then dom files.
    If none is found, download the url again.
    """
    canonical = snapshot.canonical_outputs()
    abs_path = path.absolute()
    sources = [canonical["singlefile_path"], canonical["wget_path"], canonical["dom_path"]]
    document = None
    for source in sources:
        try:
            with open(abs_path / source, "r") as f:
                document = f.read()
                break
        except (FileNotFoundError, TypeError):
            continue
    if document is None:
        return download_url(snapshot.url)
    else:
        return document


# output = 'readability/'

@enforce_types
def should_save_readability(snapshot: Model, overwrite: Optional[bool]=False, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or snapshot.link_dir
    if is_static_file(snapshot.url):
        return False

    output = Path(out_dir or snapshot.snapshot_dir) / 'readability'
    if not overwrite and output.exists():
        return False

    return SAVE_READABILITY and READABILITY_VERSION


@enforce_types
def save_readability(snapshot: Model, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download reader friendly version using @mozilla/readability"""

    out_dir = Path(out_dir or snapshot.snapshot_dir)
    output_folder = out_dir.absolute() / "readability"
    output = str(output_folder)

    # Readability Docs: https://github.com/mozilla/readability

    status = 'succeeded'
    # fake command to show the user so they have something to try debugging if get_html fails
    cmd = [
        CURL_BINARY,
        snapshot.url
    ]
    readability_content = None
    timer = TimedProgress(timeout, prefix='      ')
    try:
        document = get_html(snapshot, out_dir)
        temp_doc = NamedTemporaryFile(delete=False)
        temp_doc.write(document.encode("utf-8"))
        temp_doc.close()

        cmd = [
            DEPENDENCIES['READABILITY_BINARY']['path'],
            temp_doc.name
        ]

        result = run(cmd, cwd=out_dir, timeout=timeout)
        result_json = json.loads(result.stdout)
        output_folder.mkdir(exist_ok=True)
        readability_content = result_json.pop("textContent") 
        atomic_write(str(output_folder / "content.html"), result_json.pop("content"))
        atomic_write(str(output_folder / "content.txt"), readability_content)
        atomic_write(str(output_folder / "article.json"), result_json)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        hints = (
            'Got readability response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0):
            raise ArchiveError('Readability was not able to archive the page', hints)
    except (Exception, OSError) as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=READABILITY_VERSION,
        output=output,
        status=status,
        index_texts= [readability_content] if readability_content else [],
        **timer.stats,  
    )
