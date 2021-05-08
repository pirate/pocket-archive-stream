__package__ = 'archivebox'

import os
import sys
import shutil
import platform
from pathlib import Path
from datetime import date

from typing import Dict, List, Tuple, Optional, Iterable, IO, Union
from crontab import CronTab, CronSlices
from django.db.models import QuerySet

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
    parse_links_memory,
)
from .index.schema import Link
from .util import enforce_types                         # type: ignore
from .system import get_dir_size, dedupe_cron_jobs, CRON_COMMENT
from .system import run as run_shell
from .index import (
    load_main_index,
    parse_links_from_source,
    dedupe_links,
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
    write_link_details,
)
from .index.json import (
    parse_json_main_index,
    parse_json_links_details,
    generate_json_index_from_links,
)
from .index.sql import (
    get_admins,
    apply_migrations,
    remove_from_sql_main_index,
)
from .index.html import (
    generate_index_from_links,
)
from .index.csv import links_to_csv
from .extractors import archive_links, archive_link, ignore_methods
from .config import (
    stderr,
    hint,
    ConfigDict,
    ANSI,
    IS_TTY,
    DEBUG,
    IN_DOCKER,
    USER,
    PYTHON_BINARY,
    ARCHIVEBOX_BINARY,
    ONLY_NEW,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    LOGS_DIR,
    PACKAGE_DIR,
    CONFIG_FILE,
    ARCHIVE_DIR_NAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    SQL_INDEX_FILENAME,
    ALLOWED_IN_OUTPUT_DIR,
    SEARCH_BACKEND_ENGINE,
    check_dependencies,
    check_data_folder,
    write_config_file,
    VERSION,
    CODE_LOCATIONS,
    EXTERNAL_LOCATIONS,
    DATA_LOCATIONS,
    DEPENDENCIES,
    CHROME_BINARY,
    CHROME_VERSION,
    YOUTUBEDL_BINARY,
    YOUTUBEDL_VERSION,
    SINGLEFILE_VERSION,
    READABILITY_VERSION,
    MERCURY_VERSION,
    NODE_VERSION,
    load_all_config,
    CONFIG,
    USER_CONFIG,
    get_real_name,
    setup_django,
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

from .search import flush_search_index, index_links



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
        # ArchiveBox v0.5.6
        # Cpython Linux Linux-4.19.121-linuxkit-x86_64-with-glibc2.28 x86_64 (in Docker) (in TTY)
        print('ArchiveBox v{}'.format(VERSION))
        p = platform.uname()
        print(
            sys.implementation.name.title(),
            p.system,
            platform.platform(),
            p.machine,
        )
        print(
            f'IN_DOCKER={IN_DOCKER}',
            f'DEBUG={DEBUG}',
            f'IS_TTY={IS_TTY}',
            f'TZ={os.environ.get("TZ", "UTC")}',
            f'SEARCH_BACKEND_ENGINE={SEARCH_BACKEND_ENGINE}',
        )
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
def init(force: bool=False, quick: bool=False, setup: bool=False, out_dir: Path=OUTPUT_DIR) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""
    
    from core.models import Snapshot

    out_dir.mkdir(exist_ok=True)
    is_empty = not len(set(os.listdir(out_dir)) - ALLOWED_IN_OUTPUT_DIR)

    if (out_dir / JSON_INDEX_FILENAME).exists():
        stderr("[!] This folder contains a JSON index. It is deprecated, and will no longer be kept up to date automatically.", color="lightyellow")
        stderr("    You can run `archivebox list --json --with-headers > static_index.json` to manually generate it.", color="lightyellow")

    existing_index = (out_dir / SQL_INDEX_FILENAME).exists()

    if is_empty and not existing_index:
        print('{green}[+] Initializing a new ArchiveBox v{} collection...{reset}'.format(VERSION, **ANSI))
        print('{green}----------------------------------------------------------------------{reset}'.format(**ANSI))
    elif existing_index:
        # TODO: properly detect and print the existing version in current index as well
        print('{green}[^] Verifying and updating existing ArchiveBox collection to v{}...{reset}'.format(VERSION, **ANSI))
        print('{green}----------------------------------------------------------------------{reset}'.format(**ANSI))
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
    
    print(f'    + ./{ARCHIVE_DIR.relative_to(OUTPUT_DIR)}, ./{SOURCES_DIR.relative_to(OUTPUT_DIR)}, ./{LOGS_DIR.relative_to(OUTPUT_DIR)}...')
    Path(SOURCES_DIR).mkdir(exist_ok=True)
    Path(ARCHIVE_DIR).mkdir(exist_ok=True)
    Path(LOGS_DIR).mkdir(exist_ok=True)
    print(f'    + ./{CONFIG_FILE.relative_to(OUTPUT_DIR)}...')
    write_config_file({}, out_dir=out_dir)

    if (out_dir / SQL_INDEX_FILENAME).exists():
        print('\n{green}[*] Verifying main SQL index and running any migrations needed...{reset}'.format(**ANSI))
    else:
        print('\n{green}[+] Building main SQL index and running initial migrations...{reset}'.format(**ANSI))
    
    DATABASE_FILE = out_dir / SQL_INDEX_FILENAME
    for migration_line in apply_migrations(out_dir):
        print(f'    {migration_line}')

    assert DATABASE_FILE.exists()
    print()
    print(f'    √ ./{DATABASE_FILE.relative_to(OUTPUT_DIR)}')
    
    # from django.contrib.auth.models import User
    # if IS_TTY and not User.objects.filter(is_superuser=True).exists():
    #     print('{green}[+] Creating admin user account...{reset}'.format(**ANSI))
    #     call_command("createsuperuser", interactive=True)

    print()
    print('{green}[*] Checking links from indexes and archive folders (safe to Ctrl+C)...{reset}'.format(**ANSI))

    all_links = Snapshot.objects.none()
    pending_links: Dict[str, Link] = {}

    if existing_index:
        all_links = load_main_index(out_dir=out_dir, warn=False)
        print('    √ Loaded {} links from existing main index.'.format(all_links.count()))

    if quick:
        print('    > Skipping full snapshot directory check (quick mode)')
    else:
        try:
            # Links in data folders that dont match their timestamp
            fixed, cant_fix = fix_invalid_folder_locations(out_dir=out_dir)
            if fixed:
                print('    {lightyellow}√ Fixed {} data directory locations that didn\'t match their link timestamps.{reset}'.format(len(fixed), **ANSI))
            if cant_fix:
                print('    {lightyellow}! Could not fix {} data directory locations due to conflicts with existing folders.{reset}'.format(len(cant_fix), **ANSI))

            # Links in JSON index but not in main index
            orphaned_json_links = {
                link.url: link
                for link in parse_json_main_index(out_dir)
                if not all_links.filter(url=link.url).exists()
            }
            if orphaned_json_links:
                pending_links.update(orphaned_json_links)
                print('    {lightyellow}√ Added {} orphaned links from existing JSON index...{reset}'.format(len(orphaned_json_links), **ANSI))

            # Links in data dir indexes but not in main index
            orphaned_data_dir_links = {
                link.url: link
                for link in parse_json_links_details(out_dir)
                if not all_links.filter(url=link.url).exists()
            }
            if orphaned_data_dir_links:
                pending_links.update(orphaned_data_dir_links)
                print('    {lightyellow}√ Added {} orphaned links from existing archive directories.{reset}'.format(len(orphaned_data_dir_links), **ANSI))

            # Links in invalid/duplicate data dirs
            invalid_folders = {
                folder: link
                for folder, link in get_invalid_folders(all_links, out_dir=out_dir).items()
            }
            if invalid_folders:
                print('    {lightyellow}! Skipped adding {} invalid link data directories.{reset}'.format(len(invalid_folders), **ANSI))
                print('        X ' + '\n        X '.join(f'./{Path(folder).relative_to(OUTPUT_DIR)} {link}' for folder, link in invalid_folders.items()))
                print()
                print('    {lightred}Hint:{reset} For more information about the link data directories that were skipped, run:'.format(**ANSI))
                print('        archivebox status')
                print('        archivebox list --status=invalid')

        except (KeyboardInterrupt, SystemExit):
            stderr()
            stderr('[x] Stopped checking archive directories due to Ctrl-C/SIGTERM', color='red')
            stderr('    Your archive data is safe, but you should re-run `archivebox init` to finish the process later.')
            stderr()
            stderr('    {lightred}Hint:{reset} In the future you can run a quick init without checking dirs like so:'.format(**ANSI))
            stderr('        archivebox init --quick')
            raise SystemExit(1)
        
        write_main_index(list(pending_links.values()), out_dir=out_dir)

    print('\n{green}----------------------------------------------------------------------{reset}'.format(**ANSI))
    if existing_index:
        print('{green}[√] Done. Verified and updated the existing ArchiveBox collection.{reset}'.format(**ANSI))
    else:
        # TODO: allow creating new supersuer via env vars on first init
        # if config.HTTP_USER and config.HTTP_PASS:
        #     from django.contrib.auth.models import User
        #     User.objects.create_superuser(HTTP_USER, '', HTTP_PASS)

        print('{green}[√] Done. A new ArchiveBox collection was initialized ({} links).{reset}'.format(len(all_links) + len(pending_links), **ANSI))

    json_index = out_dir / JSON_INDEX_FILENAME
    html_index = out_dir / HTML_INDEX_FILENAME
    index_name = f"{date.today()}_index_old"
    if json_index.exists():
        json_index.rename(f"{index_name}.json")
    if html_index.exists():
        html_index.rename(f"{index_name}.html")

    if setup:
        run_subcommand('setup', pwd=out_dir)

    if Snapshot.objects.count() < 25:     # hide the hints for experienced users
        print()
        print('    {lightred}Hint:{reset} To view your archive index, run:'.format(**ANSI))
        print('        archivebox server  # then visit http://127.0.0.1:8000')
        print()
        print('    To add new links, you can run:')
        print("        archivebox add ~/some/path/or/url/to/list_of_links.txt")
        print()
        print('    For more usage and examples, run:')
        print('        archivebox help')

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

    links = load_main_index(out_dir=out_dir)
    num_sql_links = links.count()
    num_link_details = sum(1 for link in parse_json_links_details(out_dir=out_dir))
    print(f'    > SQL Main Index: {num_sql_links} links'.ljust(36), f'(found in {SQL_INDEX_FILENAME})')
    print(f'    > JSON Link Details: {num_link_details} links'.ljust(36), f'(found in {ARCHIVE_DIR_NAME}/*/index.json)')
    print()
    print('{green}[*] Scanning archive data directories...{reset}'.format(**ANSI))
    print(ANSI['lightyellow'], f'   {ARCHIVE_DIR}/*', ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = printable_filesize(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')
    print(ANSI['black'])
    num_indexed = len(get_indexed_folders(links, out_dir=out_dir))
    num_archived = len(get_archived_folders(links, out_dir=out_dir))
    num_unarchived = len(get_unarchived_folders(links, out_dir=out_dir))
    print(f'    > indexed: {num_indexed}'.ljust(36), f'({get_indexed_folders.__doc__})')
    print(f'      > archived: {num_archived}'.ljust(36), f'({get_archived_folders.__doc__})')
    print(f'      > unarchived: {num_unarchived}'.ljust(36), f'({get_unarchived_folders.__doc__})')
    
    num_present = len(get_present_folders(links, out_dir=out_dir))
    num_valid = len(get_valid_folders(links, out_dir=out_dir))
    print()
    print(f'    > present: {num_present}'.ljust(36), f'({get_present_folders.__doc__})')
    print(f'      > valid: {num_valid}'.ljust(36), f'({get_valid_folders.__doc__})')
    
    duplicate = get_duplicate_folders(links, out_dir=out_dir)
    orphaned = get_orphaned_folders(links, out_dir=out_dir)
    corrupted = get_corrupted_folders(links, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(links, out_dir=out_dir)
    num_invalid = len({**duplicate, **orphaned, **corrupted, **unrecognized})
    print(f'      > invalid: {num_invalid}'.ljust(36), f'({get_invalid_folders.__doc__})')
    print(f'        > duplicate: {len(duplicate)}'.ljust(36), f'({get_duplicate_folders.__doc__})')
    print(f'        > orphaned: {len(orphaned)}'.ljust(36), f'({get_orphaned_folders.__doc__})')
    print(f'        > corrupted: {len(corrupted)}'.ljust(36), f'({get_corrupted_folders.__doc__})')
    print(f'        > unrecognized: {len(unrecognized)}'.ljust(36), f'({get_unrecognized_folders.__doc__})')
        
    print(ANSI['reset'])

    if num_indexed:
        print('    {lightred}Hint:{reset} You can list link data directories by status like so:'.format(**ANSI))
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
    for snapshot in links.order_by('-updated')[:10]:
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
    oneshot_link, _ = parse_links_memory([url])
    if len(oneshot_link) > 1:
        stderr(
                '[X] You should pass a single url to the oneshot command',
                color='red'
            )
        raise SystemExit(2)

    methods = extractors.split(",") if extractors else ignore_methods(['title'])
    archive_link(oneshot_link[0], out_dir=out_dir, methods=methods)
    return oneshot_link

@enforce_types
def add(urls: Union[str, List[str], Path],
        tag: str='',
        depth: int=0,
        update_all: bool=not ONLY_NEW,
        index_only: bool=False,
        overwrite: bool=False,
        # duplicate: bool=False,  # TODO: reuse the logic from admin.py resnapshot to allow adding multiple snapshots by appending timestamp automatically
        init: bool=False,
        extractors: str="",
        parser: str="auto",
        out_dir: Path=OUTPUT_DIR) -> Tuple[List[Link], List[Link]]:
    """Add a new URL or list of URLs to your archive"""

    from core.models import Tag

    assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'

    extractors = extractors.split(",") if extractors else []

    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)

    # Load list of links from the existing index
    check_data_folder(out_dir=out_dir)
    check_dependencies()
    new_links: List[Link] = []
    all_links = load_main_index(out_dir=out_dir)

    log_importing_started(urls=urls, depth=depth, index_only=index_only)
    if isinstance(urls, str):
        # save verbatim stdin to sources
        write_ahead_log = save_text_as_source(urls, filename='{ts}-import.txt', out_dir=out_dir)
    elif isinstance(urls, list):
        # save verbatim args to sources
        write_ahead_log = save_text_as_source('\n'.join(urls), filename='{ts}-import.txt', out_dir=out_dir)
    elif isinstance(urls, Path):
        write_ahead_log = str(urls)

    new_links += parse_links_from_source(write_ahead_log, root_url=None, parser=parser)

    # If we're going one level deeper, download each link and look for more links
    new_links_depth = []
    if new_links and depth == 1:
        log_crawl_started(new_links)
        for new_link in new_links:
            downloaded_file = save_file_as_source(new_link.url, filename=f'{new_link.timestamp}-crawl-{new_link.domain}.txt', out_dir=out_dir)
            new_links_depth += parse_links_from_source(downloaded_file, root_url=new_link.url)

    imported_links = list({link.url: link for link in (new_links + new_links_depth)}.values())
    
    new_links = dedupe_links(all_links, imported_links)

    write_main_index(links=new_links, out_dir=out_dir)
    all_links = load_main_index(out_dir=out_dir)

    if index_only:
        # mock archive all the links using the fake index_only extractor method in order to update their state
        if overwrite:
            archive_links(imported_links, overwrite=overwrite, methods=['index_only'], out_dir=out_dir)
        else:
            archive_links(new_links, overwrite=False, methods=['index_only'], out_dir=out_dir)
    else:
        # fully run the archive extractor methods for each link
        archive_kwargs = {
            "out_dir": out_dir,
        }
        if extractors:
            archive_kwargs["methods"] = extractors

        if update_all:
            archive_links(all_links, overwrite=overwrite, **archive_kwargs)
        elif overwrite:
            archive_links(imported_links, overwrite=True, **archive_kwargs)
        elif new_links:
            archive_links(new_links, overwrite=False, **archive_kwargs)


    # add any tags to imported links
    tags = [
        Tag.objects.get_or_create(name=name.strip())[0]
        for name in tag.split(',')
        if name.strip()
    ]
    if tags:
        for link in imported_links:
            snapshot = link.as_snapshot()
            snapshot.tags.add(*tags)
            snapshot.tags_str(nocache=True)
            snapshot.save()
        # print(f'    √ Tagged {len(imported_links)} Snapshots with {len(tags)} tags {tags_str}')

    return all_links, new_links

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
        snapshots = list_links(**list_kwargs)
    finally:
        timer.end()


    if not snapshots.exists():
        log_removal_finished(0, 0)
        raise SystemExit(1)


    log_links = [link.as_link() for link in snapshots]
    log_list_finished(log_links)
    log_removal_started(log_links, yes=yes, delete=delete)

    timer = TimedProgress(360, prefix='      ')
    try:
        for snapshot in snapshots:
            if delete:
                shutil.rmtree(snapshot.as_link().link_dir, ignore_errors=True)
    finally:
        timer.end()

    to_remove = snapshots.count()

    flush_search_index(snapshots=snapshots)
    remove_from_sql_main_index(snapshots=snapshots, out_dir=out_dir)
    all_snapshots = load_main_index(out_dir=out_dir)
    log_removal_finished(all_snapshots.count(), to_remove)
    
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

    check_data_folder(out_dir=out_dir)
    check_dependencies()
    new_links: List[Link] = [] # TODO: Remove input argument: only_new

    extractors = extractors.split(",") if extractors else []

    # Step 1: Filter for selected_links
    matching_snapshots = list_links(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    matching_folders = list_folders(
        links=matching_snapshots,
        status=status,
        out_dir=out_dir,
    )
    all_links = [link for link in matching_folders.values() if link]

    if index_only:
        for link in all_links:
            write_link_details(link, out_dir=out_dir, skip_sql_index=True)
        index_links(all_links, out_dir=out_dir)
        return all_links
        
    # Step 2: Run the archive methods for each link
    to_archive = new_links if only_new else all_links
    if resume:
        to_archive = [
            link for link in to_archive
            if link.timestamp >= str(resume)
        ]
        if not to_archive:
            stderr('')
            stderr(f'[√] Nothing found to resume after {resume}', color='green')
            return all_links

    archive_kwargs = {
        "out_dir": out_dir,
    }
    if extractors:
        archive_kwargs["methods"] = extractors

    archive_links(to_archive, overwrite=overwrite, **archive_kwargs)

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links = load_main_index(out_dir=out_dir)
    return all_links

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

    snapshots = list_links(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    if sort:
        snapshots = snapshots.order_by(sort)

    folders = list_folders(
        links=snapshots,
        status=status,
        out_dir=out_dir,
    )

    if json: 
        output = generate_json_index_from_links(folders.values(), with_headers)
    elif html:
        output = generate_index_from_links(folders.values(), with_headers)
    elif csv:
        output = links_to_csv(folders.values(), cols=csv.split(','), header=with_headers)
    else:
        output = printable_folders(folders, with_headers=with_headers)
    print(output)
    return folders


@enforce_types
def list_links(snapshots: Optional[QuerySet]=None,
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
        all_snapshots = all_snapshots.filter(timestamp__gte=after)
    if before is not None:
        all_snapshots = all_snapshots.filter(timestamp__lt=before)
    if filter_patterns:
        all_snapshots = snapshot_filter(all_snapshots, filter_patterns, filter_type)

    if not all_snapshots:
        stderr('[!] No Snapshots matched your filters:', filter_patterns, f'({filter_type})', color='lightyellow')

    return all_snapshots

@enforce_types
def list_folders(links: List[Link],
                 status: str,
                 out_dir: Path=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    
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
        return STATUS_FUNCTIONS[status](links, out_dir=out_dir)
    except KeyError:
        raise ValueError('Status not recognized.')

@enforce_types
def setup(out_dir: Path=OUTPUT_DIR) -> None:
    """Automatically install all ArchiveBox dependencies and extras"""

    if not (out_dir / ARCHIVE_DIR_NAME).exists():
        run_subcommand('init', stdin=None, pwd=out_dir)

    setup_django(out_dir=out_dir, check_db=True)
    from core.models import User

    if not User.objects.filter(is_superuser=True).exists():
        stderr('\n[+] Creating new admin user for the Web UI...', color='green')
        run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)

    stderr('\n[+] Installing enabled ArchiveBox dependencies automatically...', color='green')

    stderr('\n    Installing YOUTUBEDL_BINARY automatically using pip...')
    if YOUTUBEDL_VERSION:
        print(f'{YOUTUBEDL_VERSION} is already installed', YOUTUBEDL_BINARY)
    else:
        try:
            run_shell([
                PYTHON_BINARY, '-m', 'pip',
                'install',
                '--upgrade',
                '--no-cache-dir',
                '--no-warn-script-location',
                'youtube_dl',
            ], capture_output=False, cwd=out_dir)
            pkg_path = run_shell([
                PYTHON_BINARY, '-m', 'pip',
                'show',
                'youtube_dl',
            ], capture_output=True, text=True, cwd=out_dir).stdout.split('Location: ')[-1].split('\n', 1)[0]
            NEW_YOUTUBEDL_BINARY = Path(pkg_path) / 'youtube_dl' / '__main__.py'
            os.chmod(NEW_YOUTUBEDL_BINARY, 0o777)
            assert NEW_YOUTUBEDL_BINARY.exists(), f'youtube_dl must exist inside {pkg_path}'
            config(f'YOUTUBEDL_BINARY={NEW_YOUTUBEDL_BINARY}', set=True, out_dir=out_dir)
        except BaseException as e:
            stderr(f'[X] Failed to install python packages: {e}', color='red')
            raise SystemExit(1)

    stderr('\n    Installing CHROME_BINARY automatically using playwright...')
    if CHROME_VERSION:
        print(f'{CHROME_VERSION} is already installed', CHROME_BINARY)
    else:
        try:
            run_shell([
                PYTHON_BINARY, '-m', 'pip',
                'install',
                '--upgrade',
                '--no-cache-dir',
                '--no-warn-script-location',
                'playwright',
            ], capture_output=False, cwd=out_dir)
            run_shell([PYTHON_BINARY, '-m', 'playwright', 'install', 'chromium'], capture_output=False, cwd=out_dir)
            proc = run_shell([PYTHON_BINARY, '-c', 'from playwright.sync_api import sync_playwright; print(sync_playwright().start().chromium.executable_path)'], capture_output=True, text=True, cwd=out_dir)
            NEW_CHROME_BINARY = proc.stdout.decode().strip() if isinstance(proc.stdout, bytes) else proc.stdout.strip()
            assert NEW_CHROME_BINARY and len(NEW_CHROME_BINARY), 'CHROME_BINARY must contain a path'
            config(f'CHROME_BINARY={NEW_CHROME_BINARY}', set=True, out_dir=out_dir)
        except BaseException as e:
            stderr(f'[X] Failed to install chromium using playwright: {e.__class__.__name__} {e}', color='red')
            raise SystemExit(1)

    stderr('\n    Installing SINGLEFILE_BINARY, READABILITY_BINARY, MERCURY_BINARY automatically using npm...')
    if not NODE_VERSION:
        stderr('[X] You must first install node using your system package manager', color='red')
        hint([
            'curl -sL https://deb.nodesource.com/setup_15.x | sudo -E bash -',
            'or to disable all node-based modules run: archivebox config --set USE_NODE=False',
        ])
        raise SystemExit(1)

    if all((SINGLEFILE_VERSION, READABILITY_VERSION, MERCURY_VERSION)):
        print('SINGLEFILE_BINARY, READABILITY_BINARY, and MERCURURY_BINARY are already installed')
    else:
        try:
            # clear out old npm package locations
            paths = (
                out_dir / 'package.json',
                out_dir / 'package_lock.json',
                out_dir / 'node_modules',
            )
            for path in paths:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.is_file():
                    os.remove(path)

            shutil.copyfile(PACKAGE_DIR / 'package.json', out_dir / 'package.json')
            run_shell([
                'npm',
                'install',
                '--prefix', str(out_dir),
                '--force',
                '--no-save',
                '--no-audit',
                '--no-fund',
                '--loglevel', 'error',
            ], capture_output=False, cwd=out_dir)
            os.remove(out_dir / 'package.json')
        except BaseException as e:
            stderr(f'[X] Failed to install npm packages: {e}', color='red')
            hint(f'Try deleting {out_dir}/node_modules and running it again')
            raise SystemExit(1)

    stderr('\n[√] Set up ArchiveBox and its dependencies successfully.', color='green')
    
    run_shell([PYTHON_BINARY, ARCHIVEBOX_BINARY, '--version'], capture_output=False, cwd=out_dir)

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
            raise SystemExit(1)
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
             overwrite: bool=False,
             import_path: Optional[str]=None,
             out_dir: Path=OUTPUT_DIR):
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
    
    check_data_folder(out_dir=out_dir)

    Path(LOGS_DIR).mkdir(exist_ok=True)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)

    if clear:
        print(cron.remove_all(comment=CRON_COMMENT))
        cron.write()
        raise SystemExit(0)

    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if every or add:
        every = every or 'day'
        quoted = lambda s: f'"{s}"' if (s and ' ' in str(s)) else str(s)
        cmd = [
            'cd',
            quoted(out_dir),
            '&&',
            quoted(ARCHIVEBOX_BINARY),
            *([
                'add',
                *(['--overwrite'] if overwrite else []),
                f'--depth={depth}',
                f'"{import_path}"',
            ] if import_path else ['update']),
            '>>',
            quoted(Path(LOGS_DIR) / 'schedule.log'),
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
            stderr('        archivebox init --every=day --depth=1 https://example.com/some/rss/feed.xml')
            stderr('        archivebox init --every="0/5 * * * *" --depth=1 https://example.com/some/rss/feed.xml')
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
            stderr('        archivebox schedule --every=[timeperiod] --depth=1 https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)
    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if foreground or run_all:
        if not existing_jobs:
            stderr('{red}[X] You must schedule some jobs first before running in foreground mode.{reset}'.format(**ANSI))
            stderr('    archivebox schedule --every=hour --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        print('{green}[*] Running {} ArchiveBox jobs in foreground task scheduler...{reset}'.format(len(existing_jobs), **ANSI))
        if run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command.split("/archivebox ")[0].split(" && ")[0]}\n')
                    sys.stdout.write(f'    > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r    √ {job.command.split("/archivebox ")[-1]}\n')
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**ANSI))
                raise SystemExit(1)

        if foreground:
            try:
                for job in existing_jobs:
                    print(f'  > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
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
           quick_init: bool=False,
           createsuperuser: bool=False,
           out_dir: Path=OUTPUT_DIR) -> None:
    """Run the ArchiveBox HTTP server"""

    runserver_args = runserver_args or []
    
    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)
        print()
    elif quick_init:
        run_subcommand('init', subcommand_args=['--quick'], stdin=None, pwd=out_dir)
        print()

    if createsuperuser:
        run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)
        print()

    # setup config for django runserver
    from . import config
    config.SHOW_PROGRESS = False
    config.DEBUG = config.DEBUG or debug

    check_data_folder(out_dir=out_dir)

    from django.core.management import call_command
    from django.contrib.auth.models import User

    print('{green}[+] Starting ArchiveBox webserver...{reset}'.format(**ANSI))
    print('    > Logging errors to ./logs/errors.log')
    if not User.objects.filter(is_superuser=True).exists():
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

