__package__ = 'archivebox.index'

import os
import shutil
from pathlib import Path

from itertools import chain
from typing import List, Tuple, Dict, Optional, Iterable
from collections import OrderedDict
from contextlib import contextmanager
from urllib.parse import urlparse
from django.db.models import QuerySet, Q, Model

from ..util import (
    scheme,
    enforce_types,
    ExtendedEncoder,
)
from ..config import (
    ARCHIVE_DIR_NAME,
    SQL_INDEX_FILENAME,
    JSON_INDEX_FILENAME,
    OUTPUT_DIR,
    TIMEOUT,
    URL_BLACKLIST_PTN,
    stderr,
    OUTPUT_PERMISSIONS
)
from ..logging_util import (
    TimedProgress,
    log_indexing_process_started,
    log_indexing_process_finished,
    log_indexing_started,
    log_indexing_finished,
    log_parsing_finished,
    log_deduping_finished,
)

from .schema import Link, ArchiveResult
from .html import (
    write_html_snapshot_details,
)
from .json import (
    pyjson,
    load_json_snapshot,
    write_json_snapshot_details,
)
from .sql import (
    write_sql_main_index,
    write_sql_snapshot_details,
)

from ..search import search_backend_enabled, query_search_index

### Link filtering and checking

@enforce_types
def merge_snapshots(a: Model, b: Model) -> Model:
    """deterministially merge two snapshots, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    TODO: Check if this makes sense with the new setup
    """
    return a
    assert a.base_url == b.base_url, f'Cannot merge two links with different URLs ({a.base_url} != {b.base_url})'

    # longest url wins (because a fuzzy url will always be shorter)
    url = a.url if len(a.url) > len(b.url) else b.url

    # best title based on length and quality
    possible_titles = [
        title
        for title in (a.title, b.title)
        if title and title.strip() and '://' not in title
    ]
    title = None
    if len(possible_titles) == 2:
        title = max(possible_titles, key=lambda t: len(t))
    elif len(possible_titles) == 1:
        title = possible_titles[0]

    # earliest valid timestamp
    timestamp = (
        a.timestamp
        if float(a.timestamp or 0) < float(b.timestamp or 0) else
        b.timestamp
    )

    # all unique, truthy tags
    tags_set = (
        set(tag.strip() for tag in (a.tags or '').split(','))
        | set(tag.strip() for tag in (b.tags or '').split(','))
    )
    tags = ','.join(tags_set) or None

    # all unique source entries
    sources = list(set(a.sources + b.sources))

    # all unique history entries for the combined archive methods
    all_methods = set(list(a.history.keys()) + list(a.history.keys()))
    history = {
        method: (a.history.get(method) or []) + (b.history.get(method) or [])
        for method in all_methods
    }
    for method in all_methods:
        deduped_jsons = {
            pyjson.dumps(result, sort_keys=True, cls=ExtendedEncoder)
            for result in history[method]
        }
        history[method] = list(reversed(sorted(
            (ArchiveResult.from_json(pyjson.loads(result)) for result in deduped_jsons),
            key=lambda result: result.start_ts,
        )))

    return Snapshot(
        url=url,
        timestamp=timestamp,
        title=title,
        tags=tags,
        #sources=sources,
        #history=history,
    )


@enforce_types
def validate_snapshots(snapshots: List[Model]) -> List[Model]:
    timer = TimedProgress(TIMEOUT * 4)
    try:
        snapshots = archivable_snapshots(snapshots)  # remove chrome://, about:, mailto: etc.
        snapshots = sorted_snapshots(snapshots)      # deterministically sort the links based on timestamp, url
        snapshots = fix_duplicate_snapshots(snapshots)  # merge/dedupe duplicate timestamps & urls
    finally:
        timer.end()

    return list(snapshots)

@enforce_types
def archivable_snapshots(snapshots: Iterable[Model]) -> Iterable[Model]:
    """remove chrome://, about:// or other schemed links that cant be archived"""
    for snapshot in snapshots:
        try:
            urlparse(snapshot.url)
        except ValueError:
            continue
        if scheme(snapshot.url) not in ('http', 'https', 'ftp'):
            continue
        if URL_BLACKLIST_PTN and URL_BLACKLIST_PTN.search(snapshot.url):
            continue

        yield snapshot


@enforce_types
def fix_duplicate_snapshots(sorted_snapshots: Iterable[Model]) -> Iterable[Model]:
    """
    ensures that all non-duplicate links have monotonically increasing timestamps
    TODO: Review how to do this with the new snapshots refactor
    """
    return sorted_snapshots
    unique_urls: OrderedDict[str, Link] = OrderedDict()

    for snapshot in sorted_snapshots:
        if snapshot.url in unique_urls:
            # merge with any other links that share the same url
            link = merge_links(unique_urls[link.url], link)
        unique_urls[link.url] = link

    return unique_urls.values()


@enforce_types
def sorted_snapshots(snapshots: Iterable[Model]) -> Iterable[Model]:
    sort_func = lambda snapshot: (snapshot.timestamp.split('.', 1)[0], snapshot.url)
    return sorted(snapshots, key=sort_func, reverse=True)


@enforce_types
def links_after_timestamp(links: Iterable[Link], resume: Optional[float]=None) -> Iterable[Link]:
    if not resume:
        yield from links
        return

    for link in links:
        try:
            if float(link.timestamp) <= resume:
                yield link
        except (ValueError, TypeError):
            print('Resume value and all timestamp values must be valid numbers.')


@enforce_types
def lowest_uniq_timestamp(used_timestamps: OrderedDict, timestamp: str) -> str:
    """resolve duplicate timestamps by appending a decimal 1234, 1234 -> 1234.1, 1234.2"""

    timestamp = timestamp.split('.')[0]
    nonce = 0

    # first try 152323423 before 152323423.0
    if timestamp not in used_timestamps:
        return timestamp

    new_timestamp = '{}.{}'.format(timestamp, nonce)
    while new_timestamp in used_timestamps:
        nonce += 1
        new_timestamp = '{}.{}'.format(timestamp, nonce)

    return new_timestamp



### Main Links Index

@contextmanager
@enforce_types
def timed_index_update(out_path: Path):
    log_indexing_started(out_path)
    timer = TimedProgress(TIMEOUT * 2, prefix='      ')
    try:
        yield
    finally:
        timer.end()

    assert out_path.exists(), f'Failed to write index file: {out_path}'
    log_indexing_finished(out_path)


@enforce_types
def write_main_index(snapshots: List[Model], out_dir: Path=OUTPUT_DIR) -> None:
    """Writes links to sqlite3 file for a given list of links"""

    log_indexing_process_started(len(snapshots))

    try:
        with timed_index_update(out_dir / SQL_INDEX_FILENAME):
            write_sql_main_index(snapshots, out_dir=out_dir)
            os.chmod(out_dir / SQL_INDEX_FILENAME, int(OUTPUT_PERMISSIONS, base=8)) # set here because we don't write it with atomic writes

    except (KeyboardInterrupt, SystemExit):
        stderr('[!] Warning: Still writing index to disk...', color='lightyellow')
        stderr('    Run archivebox init to fix any inconsistencies from an ungraceful exit.')
        with timed_index_update(out_dir / SQL_INDEX_FILENAME):
            write_sql_main_index(links, out_dir=out_dir)
            os.chmod(out_dir / SQL_INDEX_FILENAME, int(OUTPUT_PERMISSIONS, base=8)) # set here because we don't write it with atomic writes
        raise SystemExit(0)

    log_indexing_process_finished()

@enforce_types
def load_main_index(out_dir: Path=OUTPUT_DIR, warn: bool=True) -> List[Link]:
    """
    Returns all of the snapshots currently in index
    """
    from core.models import Snapshot
    try:
        return Snapshot.objects.all()

    except (KeyboardInterrupt, SystemExit):
        raise SystemExit(0)

@enforce_types
def load_main_index_meta(out_dir: Path=OUTPUT_DIR) -> Optional[dict]:
    index_path = out_dir / JSON_INDEX_FILENAME
    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            meta_dict = pyjson.load(f)
            meta_dict.pop('links')
            return meta_dict

    return None


@enforce_types
def parse_snapshots_from_source(source_path: str, root_url: Optional[str]=None) -> List[Model]:

    from ..parsers import parse_snapshots

    new_links: List[Model] = []

    # parse and validate the import file
    raw_snapshots, parser_name = parse_snapshots(source_path, root_url=root_url)
    new_snapshots = validate_snapshots(raw_snapshots)

    if parser_name:
        num_parsed = len(raw_snapshots)
        log_parsing_finished(num_parsed, parser_name)

    return new_snapshots

@enforce_types
def filter_new_urls(snapshots: QuerySet,
                 new_snapshots: List) -> List:
    """
    Returns a list of Snapshots corresponding to the urls that were not present in the index
    """
    urls = {snapshot.url: snapshot for snapshot in new_snapshots}
    filtered_snapshots = snapshots.filter(url__in=urls.keys())

    for found_snapshot in filtered_snapshots:
        urls.pop(found_snapshot.url)
    
    log_deduping_finished(len(urls.keys()))

    return list(urls.values())

### Link Details Index

@enforce_types
def write_snapshot_details(snapshot: List[Model], out_dir: Optional[str]=None, skip_sql_index: bool=False) -> None:
    out_dir = out_dir or snapshot.snapshot_dir

    write_json_snapshot_details(snapshot, out_dir=out_dir)
    write_html_snapshot_details(snapshot, out_dir=out_dir)
    if not skip_sql_index:
        write_sql_snapshot_details(snapshot)


@enforce_types
def load_snapshot_details(snapshot: Model, out_dir: Optional[str]=None) -> Model:
    """check for an existing link archive in the given directory, 
       and load+merge it into the given link dict
    """
    out_dir = out_dir or Path(snapshot.snapshot_dir)

    existing_snapshot = load_json_snapshot(Path(out_dir))
    if existing_snapshot:
        return merge_snapshots(existing_snapshot, snapshot)

    return snapshot



LINK_FILTERS = {
    'exact': lambda pattern: Q(url=pattern),
    'substring': lambda pattern: Q(url__icontains=pattern),
    'regex': lambda pattern: Q(url__iregex=pattern),
    'domain': lambda pattern: Q(url__istartswith=f"http://{pattern}") | Q(url__istartswith=f"https://{pattern}") | Q(url__istartswith=f"ftp://{pattern}"),
    'tag': lambda pattern: Q(tags__name=pattern),
}

@enforce_types
def q_filter(snapshots: QuerySet, filter_patterns: List[str], filter_type: str='exact') -> QuerySet:
    q_filter = Q()
    for pattern in filter_patterns:
        try:
            q_filter = q_filter | LINK_FILTERS[filter_type](pattern)
        except KeyError:
            stderr()
            stderr(
                f'[X] Got invalid pattern for --filter-type={filter_type}:',
                color='red',
            )
            stderr(f'    {pattern}')
            raise SystemExit(2)
    return snapshots.filter(q_filter)

def search_filter(snapshots: QuerySet, filter_patterns: List[str], filter_type: str='search') -> QuerySet:
    if not search_backend_enabled():
        stderr()
        stderr(
                '[X] The search backend is not enabled, set config.USE_SEARCHING_BACKEND = True',
                color='red',
            )
        raise SystemExit(2)
    from core.models import Snapshot

    qsearch = Snapshot.objects.none()
    for pattern in filter_patterns:
        try:
            qsearch |= query_search_index(pattern)
        except:
            raise SystemExit(2)
    
    return snapshots & qsearch

@enforce_types
def snapshot_filter(snapshots: QuerySet, filter_patterns: List[str], filter_type: str='exact') -> QuerySet:
    if filter_type != 'search':
        return q_filter(snapshots, filter_patterns, filter_type)
    else:
        return search_filter(snapshots, filter_patterns, filter_type)


def get_indexed_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """indexed links without checking archive status or data directory validity"""
    return {snapshot.snapshot_dir: snapshot for snapshot in snapshots}

def get_archived_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """indexed links that are archived with a valid data directory"""
    return {snapshot.snapshot_dir: snapshot for snapshot in filter(is_archived, snapshots)}

def get_unarchived_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """indexed links that are unarchived with no data directory or an empty data directory"""
    return {snapshot.snapshot_dir: snapshot for snapshot in filter(is_unarchived, snapshots)}

def get_present_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs that actually exist in the archive/ folder"""
    from core.models import Snapshot

    all_folders = {}

    for entry in (out_dir / ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            snapshot = None
            try:
                snapshot = load_json_snapshot(Path(entry.path))
            except Exception:
                pass

            all_folders[entry.name] = snapshot

    return all_folders

def get_valid_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs with a valid index matched to the main index and archived content"""
    return {snapshot.snapshot_dir: snapshot for snapshot in filter(is_valid, snapshots)}

def get_invalid_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs that are invalid for any reason: corrupted/duplicate/orphaned/unrecognized"""
    duplicate = get_duplicate_folders(snapshots, out_dir=OUTPUT_DIR)
    orphaned = get_orphaned_folders(snapshots, out_dir=OUTPUT_DIR)
    corrupted = get_corrupted_folders(snapshots, out_dir=OUTPUT_DIR)
    unrecognized = get_unrecognized_folders(snapshots, out_dir=OUTPUT_DIR)
    return {**duplicate, **orphaned, **corrupted, **unrecognized}


def get_duplicate_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs that conflict with other directories that have the same link URL or timestamp"""
    by_url = {}
    by_timestamp = {}
    duplicate_folders = {}

    data_folders = (
        str(entry)
        for entry in (Path(out_dir) / ARCHIVE_DIR_NAME).iterdir()
            if entry.is_dir() and not snapshots.filter(timestamp=entry.name).exists()
    )

    for path in chain(snapshots.iterator(), data_folders):
        snapshot = None
        if type(path) is not str:
            path = path.snapshot_dir

        try:
            snapshot = load_json_snapshot(Path(path))
        except Exception:
            pass

        if snapshot:
            # snapshot folder has same timestamp as different link folder
            by_timestamp[snapshot.timestamp] = by_timestamp.get(snapshot.timestamp, 0) + 1
            if by_timestamp[snapshot.timestamp] > 1:
                duplicate_folders[path] = snapshot

            # link folder has same url as different link folder
            by_url[snapshot.url] = by_url.get(snapshot.url, 0) + 1
            if by_url[snapshot.url] > 1:
                duplicate_folders[path] = snapshot
    return duplicate_folders

def get_orphaned_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs that contain a valid index but aren't listed in the main index"""
    orphaned_folders = {}

    for entry in (Path(out_dir) / ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            snapshot = None
            try:
                snapshot = load_json_snapshot(entry)
            except Exception:
                pass

            if snapshot and not snapshots.filter(timestamp=entry.name).exists():
                # folder is a valid link data dir with index details, but it's not in the main index
                orphaned_folders[str(entry)] = snapshot

    return orphaned_folders

def get_corrupted_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs that don't contain a valid index and aren't listed in the main index"""
    corrupted = {}
    for snapshot in snapshots.iterator():
        if is_corrupt(snapshot):
            corrupted[snapshot.snapshot_dir] = snapshot
    return corrupted

def get_unrecognized_folders(snapshots, out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    """dirs that don't contain recognizable archive data and aren't listed in the main index"""
    unrecognized_folders: Dict[str, Optional[Model]] = {}

    for entry in (Path(out_dir) / ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            index_exists = (entry / "index.json").exists()
            snapshot = None
            try:
                snapshot = load_json_snapshot(entry)
            except KeyError:
                # Try to fix index
                if index_exists:
                    pass
                    # TODO: Implement the `guess` bit for snapshots
                    # try:
                        # Last attempt to repair the detail index
                        # link_guessed = parse_json_snapshot_details(str(entry), guess=True)
                        # write_json_snapshot_details(link_guessed, out_dir=str(entry))
                        # link = parse_json_link_details(str(entry))
                    # except Exception:
                    #     pass

            if index_exists and snapshot is None:
                # index exists but it's corrupted or unparseable
                unrecognized_folders[str(entry)] = snapshot
            
            elif not index_exists:
                # link details index doesn't exist and the folder isn't in the main index
                timestamp = entry.name
                if not snapshots.filter(timestamp=timestamp).exists():
                    unrecognized_folders[str(entry)] = snapshot

    return unrecognized_folders


def is_valid(snapshot: Model) -> bool:
    dir_exists = Path(snapshot.snapshot_dir).exists()
    index_exists = (Path(snapshot.snapshot_dir) / "index.json").exists()
    if not dir_exists:
        # unarchived links are not included in the valid list
        return False
    if dir_exists and not index_exists:
        return False
    if dir_exists and index_exists:
        try:
            # TODO: review if the `guess` was necessary here
            parsed_snapshot = load_json_snapshot(snapshot.snapshot_dir)
            return snapshot.url == parsed_snapshot.url
        except Exception:
            pass
    return False

def is_corrupt(snapshot: Model) -> bool:
    if not Path(snapshot.snapshot_dir).exists():
        # unarchived links are not considered corrupt
        return False

    if is_valid(snapshot):
        return False

    return True

def is_archived(snapshot: Model) -> bool:
    return is_valid(snapshot) and snapshot.is_archived
    
def is_unarchived(snapshot: Model) -> bool:
    if not Path(snapshot.snapshot_dir).exists():
        return True
    return not snapshot.is_archived


def fix_invalid_folder_locations(out_dir: Path=OUTPUT_DIR) -> Tuple[List[str], List[str]]:
    fixed = []
    cant_fix = []
    for entry in os.scandir(out_dir / ARCHIVE_DIR_NAME):
        if entry.is_dir(follow_symlinks=True):
            if (Path(entry.path) / 'index.json').exists():
                try:
                    snapshot = load_json_snapshot(Path(entry.path))
                except KeyError:
                    snapshot = None
                if not snapshot:
                    continue

                if not entry.path.endswith(f'/{snapshot.timestamp}'):
                    dest = out_dir / ARCHIVE_DIR_NAME / snapshot.timestamp
                    if dest.exists():
                        cant_fix.append(entry.path)
                    else:
                        shutil.move(entry.path, dest)
                        fixed.append(dest)
                        timestamp = entry.path.rsplit('/', 1)[-1]
                        assert snapshot.snapshot_dir == entry.path
                        assert snapshot.timestamp == timestamp
                        write_json_snapshot_details(snapshot, out_dir=entry.path)

    return fixed, cant_fix
