__package__ = 'archivebox'

import os
import sys
import shutil
import platform
from pathlib import Path
from datetime import date

from typing import Dict, List, Optional, Iterable, IO, Union
from crontab import CronTab, CronSlices
from django.db.models import QuerySet, Model

from .cli import (
    list_subcommands,
    run_subcommand,
    display_first,
    meta_cmds,
    main_cmds,
    archive_cmds,
)
from .parsers import (
    save_text_as_source,
    save_file_as_source,
    parse_snapshots_memory,
)
from .index.schema import Link
from .util import enforce_types                         # type: ignore
from .system import get_dir_size, dedupe_cron_jobs, CRON_COMMENT
from .index import (
    load_main_index,
    parse_snapshots_from_source,
    filter_new_urls,
    write_main_index,
    snapshot_filter,
    get_indexed_folders,
    get_archived_folders,
    get_unarchived_folders,
    get_present_folders,
    get_valid_folders,
    get_invalid_folders,
    get_duplicate_folders,
    get_orphaned_folders,
    get_corrupted_folders,
    get_unrecognized_folders,
    fix_invalid_folder_locations,
    write_snapshot_details,
)
from .index.json import (
    parse_json_main_index,
    parse_json_snapshot_details,
    generate_json_index_from_snapshots,
)
from .index.sql import (
    get_admins,
    apply_migrations,
    remove_from_sql_main_index,
)
from .index.html import (
    generate_index_from_snapshots,
)
from .index.csv import snapshots_to_csv
from .extractors import archive_snapshots, archive_snapshot, ignore_methods
from .config import (
    stderr,
    hint,
    ConfigDict,
    ANSI,
    IS_TTY,
    IN_DOCKER,
    USER,
    ARCHIVEBOX_BINARY,
    ONLY_NEW,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    LOGS_DIR,
    CONFIG_FILE,
    ARCHIVE_DIR_NAME,
    SOURCES_DIR_NAME,
    LOGS_DIR_NAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    SQL_INDEX_FILENAME,
    ROBOTS_TXT_FILENAME,
    FAVICON_FILENAME,
    check_dependencies,
    check_data_folder,
    write_config_file,
    VERSION,
    CODE_LOCATIONS,
    EXTERNAL_LOCATIONS,
    DATA_LOCATIONS,
    DEPENDENCIES,
    load_all_config,
    CONFIG,
    USER_CONFIG,
    get_real_name,
)
from .logging_util import (
    TERM_WIDTH,
    TimedProgress,
    log_importing_started,
    log_crawl_started,
    log_removal_started,
    log_removal_finished,
    log_list_started,
    log_list_finished,
    printable_config,
    printable_folders,
    printable_filesize,
    printable_folder_status,
    printable_dependency_version,
)

from .search import flush_search_index, index_snapshots

ALLOWED_IN_OUTPUT_DIR = {
    'lost+found',
    '.DS_Store',
    '.venv',
    'venv',
    'virtualenv',
    '.virtualenv',
    'node_modules',
    'package-lock.json',
    'static',
    ARCHIVE_DIR_NAME,
    SOURCES_DIR_NAME,
    LOGS_DIR_NAME,
    SQL_INDEX_FILENAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    ROBOTS_TXT_FILENAME,
    FAVICON_FILENAME,
}

@enforce_types
def help(out_dir: Path=OUTPUT_DIR) -> None:
    """Print the ArchiveBox help message and usage"""

    all_subcommands = list_subcommands()
    COMMANDS_HELP_TEXT = '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd in meta_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd in main_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd in archive_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'{cmd.ljust(20)} {summary}'
        for cmd, summary in all_subcommands.items()
        if cmd not in display_first
    )


    if (Path(out_dir) / SQL_INDEX_FILENAME).exists():
        print('''{green}ArchiveBox v{}: The self-hosted internet archive.{reset}

{lightred}Active data directory:{reset}
    {}

{lightred}Usage:{reset}
    archivebox [command] [--help] [--version] [...args]

{lightred}Commands:{reset}
    {}

{lightred}Example Use:{reset}
    mkdir my-archive; cd my-archive/
    archivebox init
    archivebox status

    archivebox add https://example.com/some/page
    archivebox add --depth=1 ~/Downloads/bookmarks_export.html
    
    archivebox list --sort=timestamp --csv=timestamp,url,is_archived
    archivebox schedule --every=day https://example.com/some/feed.rss
    archivebox update --resume=15109948213.123

{lightred}Documentation:{reset}
    https://github.com/ArchiveBox/ArchiveBox/wiki
'''.format(VERSION, out_dir, COMMANDS_HELP_TEXT, **ANSI))
    
    else:
        print('{green}Welcome to ArchiveBox v{}!{reset}'.format(VERSION, **ANSI))
        print()
        if IN_DOCKER:
            print('When using Docker, you need to mount a volume to use as your data dir:')
            print('    docker run -v /some/path:/data archivebox ...')
            print()
        print('To import an existing archive (from a previous version of ArchiveBox):')
        print('    1. cd into your data dir OUTPUT_DIR (usually ArchiveBox/output) and run:')
        print('    2. archivebox init')
        print()
        print('To start a new archive:')
        print('    1. Create an empty directory, then cd into it and run:')
        print('    2. archivebox init')
        print()
        print('For more information, see the documentation here:')
        print('    https://github.com/ArchiveBox/ArchiveBox/wiki')


@enforce_types
def version(quiet: bool=False,
            out_dir: Path=OUTPUT_DIR) -> None:
    """Print the ArchiveBox version and dependency information"""

    if quiet:
        print(VERSION)
    else:
        print('ArchiveBox v{}'.format(VERSION))
        p = platform.uname()
        print(sys.implementation.name.title(), p.system, platform.platform(), p.machine, '(in Docker)' if IN_DOCKER else '(not in Docker)')
        print()

        print('{white}[i] Dependency versions:{reset}'.format(**ANSI))
        for name, dependency in DEPENDENCIES.items():
            print(printable_dependency_version(name, dependency))
        
        print()
        print('{white}[i] Source-code locations:{reset}'.format(**ANSI))
        for name, folder in CODE_LOCATIONS.items():
            print(printable_folder_status(name, folder))

        print()
        print('{white}[i] Secrets locations:{reset}'.format(**ANSI))
        for name, folder in EXTERNAL_LOCATIONS.items():
            print(printable_folder_status(name, folder))

        print()
        if DATA_LOCATIONS['OUTPUT_DIR']['is_valid']:
            print('{white}[i] Data locations:{reset}'.format(**ANSI))
            for name, folder in DATA_LOCATIONS.items():
                print(printable_folder_status(name, folder))
        else:
            print()
            print('{white}[i] Data locations:{reset}'.format(**ANSI))

        print()
        check_dependencies()


@enforce_types
def run(subcommand: str,
        subcommand_args: Optional[List[str]],
        stdin: Optional[IO]=None,
        out_dir: Path=OUTPUT_DIR) -> None:
    """Run a given ArchiveBox subcommand with the given list of args"""
    run_subcommand(
        subcommand=subcommand,
        subcommand_args=subcommand_args,
        stdin=stdin,
        pwd=out_dir,
    )


@enforce_types
def init(force: bool=False, out_dir: Path=OUTPUT_DIR) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""
    
    from core.models import Snapshot

    Path(out_dir).mkdir(exist_ok=True)
    is_empty = not len(set(os.listdir(out_dir)) - ALLOWED_IN_OUTPUT_DIR)

    if (Path(out_dir) / JSON_INDEX_FILENAME).exists():
        stderr("[!] This folder contains a JSON index. It is deprecated, and will no longer be kept up to date automatically.", color="lightyellow")
        stderr("    You can run `archivebox list --json --with-headers > index.json` to manually generate it.", color="lightyellow")

    existing_index = (Path(out_dir) / SQL_INDEX_FILENAME).exists()

    if is_empty and not existing_index:
        print('{green}[+] Initializing a new ArchiveBox collection in this folder...{reset}'.format(**ANSI))
        print(f'    {out_dir}')
        print('{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    elif existing_index:
        print('{green}[*] Updating existing ArchiveBox collection in this folder...{reset}'.format(**ANSI))
        print(f'    {out_dir}')
        print('{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    else:
        if force:
            stderr('[!] This folder appears to already have files in it, but no index.sqlite3 is present.', color='lightyellow')
            stderr('    Because --force was passed, ArchiveBox will initialize anyway (which may overwrite existing files).')
        else:
            stderr(
                ("{red}[X] This folder appears to already have files in it, but no index.sqlite3 present.{reset}\n\n"
                "    You must run init in a completely empty directory, or an existing data folder.\n\n"
                "    {lightred}Hint:{reset} To import an existing data folder make sure to cd into the folder first, \n"
                "    then run and run 'archivebox init' to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
                ).format(out_dir, **ANSI)
            )
            raise SystemExit(2)

    if existing_index:
        print('\n{green}[*] Verifying archive folder structure...{reset}'.format(**ANSI))
    else:
        print('\n{green}[+] Building archive folder structure...{reset}'.format(**ANSI))
    
    Path(SOURCES_DIR).mkdir(exist_ok=True)
    print(f'    √ {SOURCES_DIR}')
    
    Path(ARCHIVE_DIR).mkdir(exist_ok=True)
    print(f'    √ {ARCHIVE_DIR}')

    Path(LOGS_DIR).mkdir(exist_ok=True)
    print(f'    √ {LOGS_DIR}')

    write_config_file({}, out_dir=out_dir)
    print(f'    √ {CONFIG_FILE}')
    if (Path(out_dir) / SQL_INDEX_FILENAME).exists():
        print('\n{green}[*] Verifying main SQL index and running migrations...{reset}'.format(**ANSI))
    else:
        print('\n{green}[+] Building main SQL index and running migrations...{reset}'.format(**ANSI))
    
    DATABASE_FILE = Path(out_dir) / SQL_INDEX_FILENAME
    print(f'    √ {DATABASE_FILE}')
    print()
    for migration_line in apply_migrations(out_dir):
        print(f'    {migration_line}')


    assert DATABASE_FILE.exists()
    
    # from django.contrib.auth.models import User
    # if IS_TTY and not User.objects.filter(is_superuser=True).exists():
    #     print('{green}[+] Creating admin user account...{reset}'.format(**ANSI))
    #     call_command("createsuperuser", interactive=True)

    print()
    print('{green}[*] Collecting links from any existing indexes and archive folders...{reset}'.format(**ANSI))

    all_snapshots = Snapshot.objects.none()
    pending_snapshots: Dict[str, Snapshot] = {}

    if existing_index:
        all_snapshots = load_main_index(out_dir=out_dir, warn=False)
        print('    √ Loaded {} snapshots from existing main index.'.format(all_snapshots.count()))

    # Links in data folders that dont match their timestamp
    fixed, cant_fix = fix_invalid_folder_locations(out_dir=out_dir)
    if fixed:
        print('    {lightyellow}√ Fixed {} data directory locations that didn\'t match their link timestamps.{reset}'.format(len(fixed), **ANSI))
    if cant_fix:
        print('    {lightyellow}! Could not fix {} data directory locations due to conflicts with existing folders.{reset}'.format(len(cant_fix), **ANSI))

    # Links in JSON index but not in main index
    orphaned_json_snapshots = {
        snapshot.url: snapshot
        for snapshot in parse_json_main_index(out_dir)
        if not all_snapshots.filter(url=snapshot.url).exists()
    }
    if orphaned_json_snapshots:
        pending_snapshots.update(orphaned_json_snapshots)
        print('    {lightyellow}√ Added {} orphaned snapshots from deprecated JSON index...{reset}'.format(len(orphaned_json_snapshots), **ANSI))

    # Links in data dir indexes but not in main index
    orphaned_data_dir_snapshots = {
        snapshot.url: snapshot
        for snapshot in parse_json_snapshot_details(out_dir)
        if not all_snapshots.filter(url=snapshot.url).exists()
    }
    if orphaned_data_dir_snapshots:
        pending_snapshots.update(orphaned_data_dir_snapshots)
        print('    {lightyellow}√ Added {} orphaned snapshots from existing archive directories.{reset}'.format(len(orphaned_data_dir_snapshots), **ANSI))


    # TODO: Should we remove orphaned folders from the invalid list? With init they are being imported, but the same links that were
    # listed as just imported are listed as skipped because they are invalid. At the very least I think we should improve this message,
    # because it makes this command a little more confusing.

    # Links in invalid/duplicate data dirs
    invalid_folders = {
        folder: snapshot
        for folder, snapshot in get_invalid_folders(all_snapshots, out_dir=out_dir).items()
    }
    if invalid_folders:
        print('    {lightyellow}! Skipped adding {} invalid snapshot data directories.{reset}'.format(len(invalid_folders), **ANSI))
        print('        X ' + '\n        X '.join(f'{folder} {snapshot}' for folder, snapshot in invalid_folders.items()))
        print()
        print('    {lightred}Hint:{reset} For more information about the link data directories that were skipped, run:'.format(**ANSI))
        print('        archivebox status')
        print('        archivebox list --status=invalid')


    write_main_index(list(pending_snapshots.values()), out_dir=out_dir)

    print('\n{green}------------------------------------------------------------------{reset}'.format(**ANSI))
    if existing_index:
        print('{green}[√] Done. Verified and updated the existing ArchiveBox collection.{reset}'.format(**ANSI))
    else:
        print('{green}[√] Done. A new ArchiveBox collection was initialized ({} snapshots).{reset}'.format(len(all_snapshots), **ANSI))
    print()
    print('    {lightred}Hint:{reset} To view your archive index, run:'.format(**ANSI))
    print('        archivebox server  # then visit http://127.0.0.1:8000')
    print()
    print('    To add new links, you can run:')
    print("        archivebox add ~/some/path/or/url/to/list_of_links.txt")
    print()
    print('    For more usage and examples, run:')
    print('        archivebox help')

    json_index = Path(out_dir) / JSON_INDEX_FILENAME
    html_index = Path(out_dir) / HTML_INDEX_FILENAME
    index_name = f"{date.today()}_index_old"
    if json_index.exists():
        json_index.rename(f"{index_name}.json")
    if html_index.exists():
        html_index.rename(f"{index_name}.html")



@enforce_types
def status(out_dir: Path=OUTPUT_DIR) -> None:
    """Print out some info and statistics about the archive collection"""

    check_data_folder(out_dir=out_dir)

    from core.models import Snapshot
    from django.contrib.auth import get_user_model
    User = get_user_model()

    print('{green}[*] Scanning archive main index...{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {out_dir}/*', ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(out_dir, recursive=False, pattern='index.')
    size = printable_filesize(num_bytes)
    print(f'    Index size: {size} across {num_files} files')
    print()

    snapshots = load_main_index(out_dir=out_dir)
    num_sql_snapshots = snapshots.count()
    num_snapshot_details = sum(1 for snapshot in parse_json_snapshot_details(out_dir=out_dir))
    print(f'    > SQL Main Index: {num_sql_snapshots} snapshots'.ljust(36), f'(found in {SQL_INDEX_FILENAME})')
    print(f'    > JSON Link Details: {num_snapshot_details} snapshots'.ljust(36), f'(found in {ARCHIVE_DIR_NAME}/*/index.json)')
    print()
    print('{green}[*] Scanning archive data directories...{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {ARCHIVE_DIR}/*', ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = printable_filesize(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')
    print(ANSI['black'])
    num_indexed = len(get_indexed_folders(snapshots, out_dir=out_dir))
    num_archived = len(get_archived_folders(snapshots, out_dir=out_dir))
    num_unarchived = len(get_unarchived_folders(snapshots, out_dir=out_dir))
    print(f'    > indexed: {num_indexed}'.ljust(36), f'({get_indexed_folders.__doc__})')
    print(f'      > archived: {num_archived}'.ljust(36), f'({get_archived_folders.__doc__})')
    print(f'      > unarchived: {num_unarchived}'.ljust(36), f'({get_unarchived_folders.__doc__})')
    
    num_present = len(get_present_folders(snapshots, out_dir=out_dir))
    num_valid = len(get_valid_folders(snapshots, out_dir=out_dir))
    print()
    print(f'    > present: {num_present}'.ljust(36), f'({get_present_folders.__doc__})')
    print(f'      > valid: {num_valid}'.ljust(36), f'({get_valid_folders.__doc__})')
    
    duplicate = get_duplicate_folders(snapshots, out_dir=out_dir)
    orphaned = get_orphaned_folders(snapshots, out_dir=out_dir)
    corrupted = get_corrupted_folders(snapshots, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(snapshots, out_dir=out_dir)
    num_invalid = len({**duplicate, **orphaned, **corrupted, **unrecognized})
    print(f'      > invalid: {num_invalid}'.ljust(36), f'({get_invalid_folders.__doc__})')
    print(f'        > duplicate: {len(duplicate)}'.ljust(36), f'({get_duplicate_folders.__doc__})')
    print(f'        > orphaned: {len(orphaned)}'.ljust(36), f'({get_orphaned_folders.__doc__})')
    print(f'        > corrupted: {len(corrupted)}'.ljust(36), f'({get_corrupted_folders.__doc__})')
    print(f'        > unrecognized: {len(unrecognized)}'.ljust(36), f'({get_unrecognized_folders.__doc__})')
        
    print(ANSI['reset'])

    if num_indexed:
        print('    {lightred}Hint:{reset} You can list snapshot data directories by status like so:'.format(**ANSI))
        print('        archivebox list --status=<status>  (e.g. indexed, corrupted, archived, etc.)')

    if orphaned:
        print('    {lightred}Hint:{reset} To automatically import orphaned data directories into the main index, run:'.format(**ANSI))
        print('        archivebox init')

    if num_invalid:
        print('    {lightred}Hint:{reset} You may need to manually remove or fix some invalid data directories, afterwards make sure to run:'.format(**ANSI))
        print('        archivebox init')
    
    print()
    print('{green}[*] Scanning recent archive changes and user logins:{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {LOGS_DIR}/*', ANSI['reset'])
    users = get_admins().values_list('username', flat=True)
    print(f'    UI users {len(users)}: {", ".join(users)}')
    last_login = User.objects.order_by('last_login').last()
    if last_login:
        print(f'    Last UI login: {last_login.username} @ {str(last_login.last_login)[:16]}')
    last_updated = Snapshot.objects.order_by('updated').last()
    if last_updated:
        print(f'    Last changes: {str(last_updated.updated)[:16]}')

    if not users:
        print()
        print('    {lightred}Hint:{reset} You can create an admin user by running:'.format(**ANSI))
        print('        archivebox manage createsuperuser')

    print()
    for snapshot in snapshots.order_by('-updated')[:10]:
        if not snapshot.updated:
            continue
        print(
            ANSI['black'],
            (
                f'   > {str(snapshot.updated)[:16]} '
                f'[{snapshot.num_outputs} {("X", "√")[snapshot.is_archived]} {printable_filesize(snapshot.archive_size)}] '
                f'"{snapshot.title}": {snapshot.url}'
            )[:TERM_WIDTH()],
            ANSI['reset'],
        )
    print(ANSI['black'], '   ...', ANSI['reset'])


@enforce_types
def oneshot(url: str, extractors: str="", out_dir: Path=OUTPUT_DIR):
    """
    Create a single URL archive folder with an index.json and index.html, and all the archive method outputs.
    You can run this to archive single pages without needing to create a whole collection with archivebox init.
    """
    oneshot_snapshots, _ = parse_snapshots_memory([url])
    if len(oneshot_snapshots) > 1:
        stderr(
                '[X] You should pass a single url to the oneshot command',
                color='red'
            )
        raise SystemExit(2)

    methods = extractors.split(",") if extractors else ignore_methods(['title'])
    snapshot = oneshot_snapshots[0]
    snapshot.save() # Oneshot uses an in-memory database, so this is safe
    archive_snapshot(snapshot, out_dir=out_dir, methods=methods)
    return snapshot

@enforce_types
def add(urls: Union[str, List[str]],
        depth: int=0,
        update_all: bool=not ONLY_NEW,
        index_only: bool=False,
        overwrite: bool=False,
        init: bool=False,
        extractors: str="",
        out_dir: Path=OUTPUT_DIR) -> List[Link]:
    """Add a new URL or list of URLs to your archive"""
    from core.models import Snapshot

    assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'

    extractors = extractors.split(",") if extractors else []

    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)

    # Load list of links from the existing index
    check_data_folder(out_dir=out_dir)
    check_dependencies()
    new_snapshots: List[Snapshot] = []
    all_snapshots = load_main_index(out_dir=out_dir)

    log_importing_started(urls=urls, depth=depth, index_only=index_only)
    if isinstance(urls, str):
        # save verbatim stdin to sources
        write_ahead_log = save_text_as_source(urls, filename='{ts}-import.txt', out_dir=out_dir)
    elif isinstance(urls, list):
        # save verbatim args to sources
        write_ahead_log = save_text_as_source('\n'.join(urls), filename='{ts}-import.txt', out_dir=out_dir)
    
    new_snapshots += parse_snapshots_from_source(write_ahead_log, root_url=None)

    # If we're going one level deeper, download each link and look for more links
    new_snapshots_depth = []
    if new_snapshots and depth == 1:
        log_crawl_started(new_snapshots)
        for new_snapshot in new_snapshots:
            # TODO: Check if we need to add domain to the Snapshot model
            downloaded_file = save_file_as_source(new_snapshot.url, filename=f'{new_snapshot.timestamp}-crawl-{new_snapshot.domain}.txt', out_dir=out_dir)
            new_snapshots_depth += parse_snapshots_from_source(downloaded_file, root_url=new_snapshot.url)

    imported_snapshots = [Snapshot(url=snapshot.url) for snapshot in new_snapshots + new_snapshots_depth]
    new_snapshots = filter_new_urls(all_snapshots, imported_snapshots)

    write_main_index(snapshots=new_snapshots, out_dir=out_dir)
    all_snapshots = load_main_index(out_dir=out_dir)

    if index_only:
        return all_snapshots

    # Run the archive methods for each link
    archive_kwargs = {
        "out_dir": out_dir,
    }
    if extractors:
        archive_kwargs["methods"] = extractors
    if update_all:
        archive_snapshots(all_snapshots, overwrite=overwrite, **archive_kwargs)
    elif overwrite:
        imported_snapshots = Snapshot.objects.filter(url__in=[imported_snapshot.url for imported_snapshot in imported_snapshots])
        archive_snapshots(imported_snapshots, overwrite=True, **archive_kwargs)
    elif new_snapshots:
        archive_snapshots(new_snapshots, overwrite=False, **archive_kwargs)

    return all_snapshots

@enforce_types
def remove(filter_str: Optional[str]=None,
           filter_patterns: Optional[List[str]]=None,
           filter_type: str='exact',
           snapshots: Optional[QuerySet]=None,
           after: Optional[float]=None,
           before: Optional[float]=None,
           yes: bool=False,
           delete: bool=False,
           out_dir: Path=OUTPUT_DIR) -> List[Link]:
    """Remove the specified URLs from the archive"""
    
    check_data_folder(out_dir=out_dir)

    if snapshots is None:
        if filter_str and filter_patterns:
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin, but not both.\n',
                color='red',
            )
            raise SystemExit(2)
        elif not (filter_str or filter_patterns):
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin.',
                color='red',
            )
            stderr()
            hint(('To remove all urls you can run:',
                'archivebox remove --filter-type=regex ".*"'))
            stderr()
            raise SystemExit(2)
        elif filter_str:
            filter_patterns = [ptn.strip() for ptn in filter_str.split('\n')]

    list_kwargs = {
        "filter_patterns": filter_patterns,
        "filter_type": filter_type,
        "after": after,
        "before": before,
    }
    if snapshots:
        list_kwargs["snapshots"] = snapshots

    log_list_started(filter_patterns, filter_type)
    timer = TimedProgress(360, prefix='      ')
    try:
        snapshots = list_snapshots(**list_kwargs)
    finally:
        timer.end()


    if not snapshots.exists():
        log_removal_finished(0, 0)
        raise SystemExit(1)


    log_list_finished(snapshots)
    log_removal_started(snapshots, yes=yes, delete=delete)

    timer = TimedProgress(360, prefix='      ')
    try:
        for snapshot in snapshots:
            if delete:
                shutil.rmtree(snapshot.snapshot_dir, ignore_errors=True)
    finally:
        timer.end()

    to_remove = snapshots.count()
    all_snapshots = load_main_index(out_dir=out_dir).count()

    flush_search_index(snapshots=snapshots)
    remove_from_sql_main_index(snapshots=snapshots, out_dir=out_dir)
    log_removal_finished(all_snapshots, to_remove)
    
    return all_snapshots

@enforce_types
def update(resume: Optional[float]=None,
           only_new: bool=ONLY_NEW,
           index_only: bool=False,
           overwrite: bool=False,
           filter_patterns_str: Optional[str]=None,
           filter_patterns: Optional[List[str]]=None,
           filter_type: Optional[str]=None,
           status: Optional[str]=None,
           after: Optional[str]=None,
           before: Optional[str]=None,
           extractors: str="",
           out_dir: Path=OUTPUT_DIR) -> List[Link]:
    """Import any new links from subscriptions and retry any previously failed/skipped links"""
    from core.models import Snapshot

    check_data_folder(out_dir=out_dir)
    check_dependencies()
    new_snapshots: List[Snapshot] = [] # TODO: Remove input argument: only_new

    extractors = extractors.split(",") if extractors else []

    # Step 1: Filter for selected_links
    matching_snapshots = list_snapshots(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    matching_folders = list_folders(
        snapshots=matching_snapshots,
        status=status,
        out_dir=out_dir,
    )
    all_snapshots = [snapshot for snapshot in matching_folders.values()]

    if index_only:
        for snapshot in all_snapshots:
            write_snapshot_details(snapshot, out_dir=out_dir, skip_sql_index=True)
        index_snapshots(all_snapshots, out_dir=out_dir)
        return all_snapshots
        
    # Step 2: Run the archive methods for each link
    to_archive = new_snapshots if only_new else all_snapshots
    if resume:
        to_archive = [
            snapshot for snapshot in to_archive
            if snapshot.timestamp >= str(resume)
        ]
        if not to_archive:
            stderr('')
            stderr(f'[√] Nothing found to resume after {resume}', color='green')
            return all_snapshots

    archive_kwargs = {
        "out_dir": out_dir,
    }
    if extractors:
        archive_kwargs["methods"] = extractors

    archive_snapshots(to_archive, overwrite=overwrite, **archive_kwargs)

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_snapshots = load_main_index(out_dir=out_dir)
    return all_snapshots

@enforce_types
def list_all(filter_patterns_str: Optional[str]=None,
             filter_patterns: Optional[List[str]]=None,
             filter_type: str='exact',
             status: Optional[str]=None,
             after: Optional[float]=None,
             before: Optional[float]=None,
             sort: Optional[str]=None,
             csv: Optional[str]=None,
             json: bool=False,
             html: bool=False,
             with_headers: bool=False,
             out_dir: Path=OUTPUT_DIR) -> Iterable[Link]:
    """List, filter, and export information about archive entries"""
    
    check_data_folder(out_dir=out_dir)

    if filter_patterns and filter_patterns_str:
        stderr(
            '[X] You should either pass filter patterns as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif filter_patterns_str:
        filter_patterns = filter_patterns_str.split('\n')

    snapshots = list_snapshots(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    if sort:
        snapshots = snapshots.order_by(sort)

    folders = list_folders(
        snapshots=snapshots,
        status=status,
        out_dir=out_dir,
    )

    if json: 
        output = generate_json_index_from_snapshots(folders.values(), with_headers)
    elif html:
        output = generate_index_from_snapshots(folders.values(), with_headers)
    elif csv:
        output = snapshots_to_csv(folders.values(), cols=csv.split(','), header=with_headers)
    else:
        output = printable_folders(folders, with_headers=with_headers)
    print(output)
    return folders


@enforce_types
def list_snapshots(snapshots: Optional[QuerySet]=None,
               filter_patterns: Optional[List[str]]=None,
               filter_type: str='exact',
               after: Optional[float]=None,
               before: Optional[float]=None,
               out_dir: Path=OUTPUT_DIR) -> Iterable[Link]:
    
    check_data_folder(out_dir=out_dir)

    if snapshots:
        all_snapshots = snapshots
    else:
        all_snapshots = load_main_index(out_dir=out_dir)

    if after is not None:
        all_snapshots = all_snapshots.filter(timestamp__lt=after)
    if before is not None:
        all_snapshots = all_snapshots.filter(timestamp__gt=before)
    if filter_patterns:
        all_snapshots = snapshot_filter(all_snapshots, filter_patterns, filter_type)
    return all_snapshots

@enforce_types
def list_folders(snapshots: List[Model],
                 status: str,
                 out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Model]]:
    
    check_data_folder(out_dir=out_dir)

    STATUS_FUNCTIONS = {
        "indexed": get_indexed_folders,
        "archived": get_archived_folders,
        "unarchived": get_unarchived_folders,
        "present": get_present_folders,
        "valid": get_valid_folders,
        "invalid": get_invalid_folders,
        "duplicate": get_duplicate_folders,
        "orphaned": get_orphaned_folders,
        "corrupted": get_corrupted_folders,
        "unrecognized": get_unrecognized_folders,
    }

    try:
        return STATUS_FUNCTIONS[status](snapshots, out_dir=out_dir)
    except KeyError:
        raise ValueError('Status not recognized.')


@enforce_types
def config(config_options_str: Optional[str]=None,
           config_options: Optional[List[str]]=None,
           get: bool=False,
           set: bool=False,
           reset: bool=False,
           out_dir: Path=OUTPUT_DIR) -> None:
    """Get and set your ArchiveBox project configuration values"""

    check_data_folder(out_dir=out_dir)

    if config_options and config_options_str:
        stderr(
            '[X] You should either pass config values as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif config_options_str:
        config_options = config_options_str.split('\n')

    config_options = config_options or []

    no_args = not (get or set or reset or config_options)

    matching_config: ConfigDict = {}
    if get or no_args:
        if config_options:
            config_options = [get_real_name(key) for key in config_options]
            matching_config = {key: CONFIG[key] for key in config_options if key in CONFIG}
            failed_config = [key for key in config_options if key not in CONFIG]
            if failed_config:
                stderr()
                stderr('[X] These options failed to get', color='red')
                stderr('    {}'.format('\n    '.join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = CONFIG
        
        print(printable_config(matching_config))
        raise SystemExit(not matching_config)
    elif set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith('#') or not line.strip():
                continue
            if '=' not in line:
                stderr('[X] Config KEY=VALUE must have an = sign in it', color='red')
                stderr(f'    {line}')
                raise SystemExit(2)

            raw_key, val = line.split('=', 1)
            raw_key = raw_key.upper().strip()
            key = get_real_name(raw_key)
            if key != raw_key:
                stderr(f'[i] Note: The config option {raw_key} has been renamed to {key}, please use the new name going forwards.', color='lightyellow')

            if key in CONFIG:
                new_config[key] = val.strip()
            else:
                failed_options.append(line)

        if new_config:
            before = CONFIG
            matching_config = write_config_file(new_config, out_dir=OUTPUT_DIR)
            after = load_all_config()
            print(printable_config(matching_config))

            side_effect_changes: ConfigDict = {}
            for key, val in after.items():
                if key in USER_CONFIG and (before[key] != after[key]) and (key not in matching_config):
                    side_effect_changes[key] = after[key]

            if side_effect_changes:
                stderr()
                stderr('[i] Note: This change also affected these other options that depended on it:', color='lightyellow')
                print('    {}'.format(printable_config(side_effect_changes, prefix='    ')))
        if failed_options:
            stderr()
            stderr('[X] These options failed to set (check for typos):', color='red')
            stderr('    {}'.format('\n    '.join(failed_options)))
        raise SystemExit(bool(failed_options))
    elif reset:
        stderr('[X] This command is not implemented yet.', color='red')
        stderr('    Please manually remove the relevant lines from your config file:')
        stderr(f'        {CONFIG_FILE}')
        raise SystemExit(2)
    else:
        stderr('[X] You must pass either --get or --set, or no arguments to get the whole config.', color='red')
        stderr('    archivebox config')
        stderr('    archivebox config --get SOME_KEY')
        stderr('    archivebox config --set SOME_KEY=SOME_VALUE')
        raise SystemExit(2)


@enforce_types
def schedule(add: bool=False,
             show: bool=False,
             clear: bool=False,
             foreground: bool=False,
             run_all: bool=False,
             quiet: bool=False,
             every: Optional[str]=None,
             depth: int=0,
             import_path: Optional[str]=None,
             out_dir: Path=OUTPUT_DIR):
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
    
    check_data_folder(out_dir=out_dir)

    (Path(out_dir) / LOGS_DIR_NAME).mkdir(exist_ok=True)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)

    if clear:
        print(cron.remove_all(comment=CRON_COMMENT))
        cron.write()
        raise SystemExit(0)

    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if every or add:
        every = every or 'day'
        quoted = lambda s: f'"{s}"' if s and ' ' in str(s) else str(s)
        cmd = [
            'cd',
            quoted(out_dir),
            '&&',
            quoted(ARCHIVEBOX_BINARY),
            *(['add', f'--depth={depth}', f'"{import_path}"'] if import_path else ['update']),
            '>',
            quoted(Path(LOGS_DIR) / 'archivebox.log'),
            '2>&1',

        ]
        new_job = cron.new(command=' '.join(cmd), comment=CRON_COMMENT)

        if every in ('minute', 'hour', 'day', 'month', 'year'):
            set_every = getattr(new_job.every(), every)
            set_every()
        elif CronSlices.is_valid(every):
            new_job.setall(every)
        else:
            stderr('{red}[X] Got invalid timeperiod for cron task.{reset}'.format(**ANSI))
            stderr('    It must be one of minute/hour/day/month')
            stderr('    or a quoted cron-format schedule like:')
            stderr('        archivebox init --every=day https://example.com/some/rss/feed.xml')
            stderr('        archivebox init --every="0/5 * * * *" https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        cron = dedupe_cron_jobs(cron)
        cron.write()

        total_runs = sum(j.frequency_per_year() for j in cron)
        existing_jobs = list(cron.find_comment(CRON_COMMENT))

        print()
        print('{green}[√] Scheduled new ArchiveBox cron job for user: {} ({} jobs are active).{reset}'.format(USER, len(existing_jobs), **ANSI))
        print('\n'.join(f'  > {cmd}' if str(cmd) == str(new_job) else f'    {cmd}' for cmd in existing_jobs))
        if total_runs > 60 and not quiet:
            stderr()
            stderr('{lightyellow}[!] With the current cron config, ArchiveBox is estimated to run >{} times per year.{reset}'.format(total_runs, **ANSI))
            stderr('    Congrats on being an enthusiastic internet archiver! 👌')
            stderr()
            stderr('    Make sure you have enough storage space available to hold all the data.')
            stderr('    Using a compressed/deduped filesystem like ZFS is recommended if you plan on archiving a lot.')
            stderr('')
    elif show:
        if existing_jobs:
            print('\n'.join(str(cmd) for cmd in existing_jobs))
        else:
            stderr('{red}[X] There are no ArchiveBox cron jobs scheduled for your user ({}).{reset}'.format(USER, **ANSI))
            stderr('    To schedule a new job, run:')
            stderr('        archivebox schedule --every=[timeperiod] https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)
    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if foreground or run_all:
        if not existing_jobs:
            stderr('{red}[X] You must schedule some jobs first before running in foreground mode.{reset}'.format(**ANSI))
            stderr('    archivebox schedule --every=hour https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        print('{green}[*] Running {} ArchiveBox jobs in foreground task scheduler...{reset}'.format(len(existing_jobs), **ANSI))
        if run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command.split("/archivebox ")[0].split(" && ")[0]}\n')
                    sys.stdout.write(f'    > {job.command.split("/archivebox ")[-1].split(" > ")[0]}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r    √ {job.command.split("/archivebox ")[-1]}\n')
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)

        if foreground:
            try:
                for job in existing_jobs:
                    print(f'  > {job.command.split("/archivebox ")[-1].split(" > ")[0]}')
                for result in cron.run_scheduler():
                    print(result)
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)

    
@enforce_types
def server(runserver_args: Optional[List[str]]=None,
           reload: bool=False,
           debug: bool=False,
           init: bool=False,
           createsuperuser: bool=False,
           out_dir: Path=OUTPUT_DIR) -> None:
    """Run the ArchiveBox HTTP server"""

    runserver_args = runserver_args or []
    
    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)

    if createsuperuser:
        run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)

    # setup config for django runserver
    from . import config
    config.SHOW_PROGRESS = False
    config.DEBUG = config.DEBUG or debug

    check_data_folder(out_dir=out_dir)

    from django.core.management import call_command
    from django.contrib.auth.models import User

    admin_user = User.objects.filter(is_superuser=True).order_by('date_joined').only('username').last()

    print('{green}[+] Starting ArchiveBox webserver...{reset}'.format(**ANSI))
    if admin_user:
        hint('The admin username is{lightblue} {}{reset}\n'.format(admin_user.username, **ANSI))
    else:
        print('{lightyellow}[!] No admin users exist yet, you will not be able to edit links in the UI.{reset}'.format(**ANSI))
        print()
        print('    To create an admin user, run:')
        print('        archivebox manage createsuperuser')
        print()

    # fallback to serving staticfiles insecurely with django when DEBUG=False
    if not config.DEBUG:
        runserver_args.append('--insecure')  # TODO: serve statics w/ nginx instead
    
    # toggle autoreloading when archivebox code changes (it's on by default)
    if not reload:
        runserver_args.append('--noreload')

    config.SHOW_PROGRESS = False
    config.DEBUG = config.DEBUG or debug


    call_command("runserver", *runserver_args)


@enforce_types
def manage(args: Optional[List[str]]=None, out_dir: Path=OUTPUT_DIR) -> None:
    """Run an ArchiveBox Django management command"""

    check_data_folder(out_dir=out_dir)
    from django.core.management import execute_from_command_line

    if (args and "createsuperuser" in args) and (IN_DOCKER and not IS_TTY):
        stderr('[!] Warning: you need to pass -it to use interactive commands in docker', color='lightyellow')
        stderr('    docker run -it archivebox manage {}'.format(' '.join(args or ['...'])), color='lightyellow')
        stderr()

    execute_from_command_line([f'{ARCHIVEBOX_BINARY} manage', *(args or ['help'])])


@enforce_types
def shell(out_dir: Path=OUTPUT_DIR) -> None:
    """Enter an interactive ArchiveBox Django shell"""

    check_data_folder(out_dir=out_dir)

    from django.core.management import call_command
    call_command("shell_plus")

