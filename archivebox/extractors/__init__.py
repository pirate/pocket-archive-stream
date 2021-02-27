__package__ = 'archivebox.extractors'

import os
from pathlib import Path

from typing import Optional, List, Iterable, Union

from django.db.models import QuerySet, Model

from ..index import (
    load_snapshot_details,
    write_snapshot_details,
)
from ..util import enforce_types
from ..logging_util import (
    log_archiving_started,
    log_archiving_paused,
    log_archiving_finished,
    log_snapshot_archiving_started,
    log_snapshot_archiving_finished,
    log_archive_method_started,
    log_archive_method_finished,
)
from ..search import write_search_index

from .title import should_save_title, save_title
from .favicon import should_save_favicon, save_favicon
from .wget import should_save_wget, save_wget
from .singlefile import should_save_singlefile, save_singlefile
from .readability import should_save_readability, save_readability
from .mercury import should_save_mercury, save_mercury
from .pdf import should_save_pdf, save_pdf
from .screenshot import should_save_screenshot, save_screenshot
from .dom import should_save_dom, save_dom
from .git import should_save_git, save_git
from .media import should_save_media, save_media
from .archive_org import should_save_archive_dot_org, save_archive_dot_org
from .headers import should_save_headers, save_headers


def get_default_archive_methods():
    return [
        ('title', should_save_title, save_title),
        ('favicon', should_save_favicon, save_favicon),
        ('wget', should_save_wget, save_wget),
        ('singlefile', should_save_singlefile, save_singlefile),
        ('pdf', should_save_pdf, save_pdf),
        ('screenshot', should_save_screenshot, save_screenshot),
        ('dom', should_save_dom, save_dom),
        ('readability', should_save_readability, save_readability), #keep readability below wget and singlefile, as it depends on them
        ('mercury', should_save_mercury, save_mercury),
        ('git', should_save_git, save_git),
        ('media', should_save_media, save_media),
        ('headers', should_save_headers, save_headers),
        ('archive_org', should_save_archive_dot_org, save_archive_dot_org),
    ]

ARCHIVE_METHODS_INDEXING_PRECEDENCE = [('readability', 1), ('singlefile', 2), ('dom', 3), ('wget', 4)]

@enforce_types
def ignore_methods(to_ignore: List[str]):
    ARCHIVE_METHODS = get_default_archive_methods()
    methods = filter(lambda x: x[0] not in to_ignore, ARCHIVE_METHODS)
    methods = map(lambda x: x[0], methods)
    return list(methods)

@enforce_types
def archive_snapshot(snapshot: Model, overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[Path]=None) -> Model:
    """download the DOM, PDF, and a screenshot into a folder named after the link's timestamp"""
    from core.models import ArchiveResult

    ARCHIVE_METHODS = get_default_archive_methods()
    
    if methods:
        ARCHIVE_METHODS = [
            method for method in ARCHIVE_METHODS
            if method[0] in methods
        ]

    out_dir = out_dir or Path(snapshot.snapshot_dir)
    try:
        is_new = not Path(out_dir).exists()
        if is_new:
            os.makedirs(out_dir)
            details = {"history": {}}
            write_snapshot_details(snapshot, out_dir=out_dir, skip_sql_index=False)
        else:
            details = snapshot.details #TODO: This can be retrieved from the sqlite database too.
                                       # If that makes more sense, it can be easily changed.

        log_snapshot_archiving_started(snapshot, out_dir, is_new)
        stats = {'skipped': 0, 'succeeded': 0, 'failed': 0}

        for method_name, should_run, method_function in ARCHIVE_METHODS:
            try:
                if method_name not in details["history"]:
                    details["history"][method_name] = []

                if should_run(snapshot, out_dir, overwrite):
                    log_archive_method_started(method_name)

                    result = method_function(snapshot=snapshot, out_dir=out_dir)

                    stats[result.status] += 1
                    log_archive_method_finished(result)
                    write_search_index(snapshot=snapshot, texts=result.index_texts)
                    ArchiveResult.objects.create(snapshot=snapshot, extractor=method_name, cmd=result.cmd, cmd_version=result.cmd_version,
                                                 output=result.output, pwd=result.pwd, start_ts=result.start_ts, end_ts=result.end_ts, status=result.status)

                else:
                    # print('{black}      X {}{reset}'.format(method_name, **ANSI))
                    stats['skipped'] += 1
            except Exception as e:
                raise Exception('Exception in archive_methods.save_{}(Snapshot(url={}))'.format(
                    method_name,
                    snapshot.url,
                )) from e

        # print('    ', stats)

        try:
            latest_title_archive_result = snapshot.archiveresult_set.filter(extractor="title")
            if latest_title_archive_result.count() > 0:
                latest_title = latest_title_archive_result.output.strip()
                if len(latest_title) >= len(snapshot.title or ''):
                    snapshot.title = latest_title
        except Exception:
            pass

        write_snapshot_details(snapshot, out_dir=out_dir, skip_sql_index=False)

        log_snapshot_archiving_finished(snapshot, snapshot.snapshot_dir, is_new, stats)

    except KeyboardInterrupt:
        try:
            write_snapshot_details(snapshot, out_dir=snapshot.snapshot_dir)
        except:
            pass
        raise

    except Exception as err:
        print('    ! Failed to archive link: {}: {}'.format(err.__class__.__name__, err))
        raise

    return snapshot

@enforce_types
def archive_snapshots(all_snapshots: Union[QuerySet, List[Model]], overwrite: bool=False, methods: Optional[Iterable[str]]=None, out_dir: Optional[Path]=None) -> QuerySet:

    all_snapshots = list(all_snapshots)
    num_snapshots: int = len(all_snapshots)

    if num_snapshots == 0:
        return []

    log_archiving_started(num_snapshots)
    idx: int = 0
    try:
        for snapshot in all_snapshots:
            idx += 1
            archive_snapshot(snapshot, overwrite=overwrite, methods=methods, out_dir=Path(snapshot.snapshot_dir))
    except KeyboardInterrupt:
        log_archiving_paused(num_snapshots, idx, snapshot.timestamp)
        raise SystemExit(0)
    except BaseException:
        print()
        raise

    log_archiving_finished(num_snapshots)
    return all_snapshots
