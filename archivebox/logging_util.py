__package__ = 'archivebox'

import re
import os
import sys
import time
import argparse
from math import log
from multiprocessing import Process
from pathlib import Path

from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Union, IO, TYPE_CHECKING

if TYPE_CHECKING:
    from .index.schema import Link, ArchiveResult

from .util import enforce_types
from .config import (
    ConfigDict,
    OUTPUT_DIR,
    PYTHON_ENCODING,
    ANSI,
    IS_TTY,
    TERM_WIDTH,
    SHOW_PROGRESS,
    SOURCES_DIR_NAME,
    stderr,
)

@dataclass
class RuntimeStats:
    """mutable stats counter for logging archiving timing info to CLI output"""

    skipped: int = 0
    succeeded: int = 0
    failed: int = 0

    parse_start_ts: Optional[datetime] = None
    parse_end_ts: Optional[datetime] = None

    index_start_ts: Optional[datetime] = None
    index_end_ts: Optional[datetime] = None

    archiving_start_ts: Optional[datetime] = None
    archiving_end_ts: Optional[datetime] = None

# globals are bad, mmkay
_LAST_RUN_STATS = RuntimeStats()



class SmartFormatter(argparse.HelpFormatter):
    """Patched formatter that prints newlines in argparse help strings"""
    def _split_lines(self, text, width):
        if '\n' in text:
            return text.splitlines()
        return argparse.HelpFormatter._split_lines(self, text, width)


def reject_stdin(caller: str, stdin: Optional[IO]=sys.stdin) -> None:
    """Tell the user they passed stdin to a command that doesn't accept it"""

    if stdin and not stdin.isatty():
        stdin_raw_text = stdin.read().strip()
        if stdin_raw_text:
            stderr(f'[X] The "{caller}" command does not accept stdin.', color='red')
            stderr(f'    Run archivebox "{caller} --help" to see usage and examples.')
            stderr()
            raise SystemExit(1)


def accept_stdin(stdin: Optional[IO]=sys.stdin) -> Optional[str]:
    """accept any standard input and return it as a string or None"""
    if not stdin:
        return None
    elif stdin and not stdin.isatty():
        stdin_str = stdin.read().strip()
        return stdin_str or None
    return None


class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix=''):
        self.SHOW_PROGRESS = SHOW_PROGRESS
        if self.SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix))
            self.p.start()

        self.stats = {'start_ts': datetime.now(), 'end_ts': None}

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""

        end_ts = datetime.now()
        self.stats['end_ts'] = end_ts
        
        if self.SHOW_PROGRESS:
            # terminate if we havent already terminated
            try:
                # kill the progress bar subprocess
                try:
                    self.p.close()   # must be closed *before* its terminnated
                except:
                    pass
                self.p.terminate()
                self.p.join()


                # clear whole terminal line
                try:
                    sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH()), ANSI['reset']))
                except (IOError, BrokenPipeError):
                    # ignore when the parent proc has stopped listening to our stdout
                    pass
            except ValueError:
                pass


@enforce_types
def progress_bar(seconds: int, prefix: str='') -> None:
    """show timer in the form of progress bar, with percentage and seconds remaining"""
    chunk = '█' if PYTHON_ENCODING == 'UTF-8' else '#'
    last_width = TERM_WIDTH()
    chunks = last_width - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
    try:
        for s in range(seconds * chunks):
            max_width = TERM_WIDTH()
            if max_width < last_width:
                # when the terminal size is shrunk, we have to write a newline
                # otherwise the progress bar will keep wrapping incorrectly
                sys.stdout.write('\r\n')
                sys.stdout.flush()
            chunks = max_width - len(prefix) - 20
            pct_complete = s / chunks / seconds * 100
            log_pct = (log(pct_complete or 1, 10) / 2) * 100  # everyone likes faster progress bars ;)
            bar_width = round(log_pct/(100/chunks))
            last_width = max_width

            # ████████████████████           0.9% (1/60sec)
            sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)'.format(
                prefix,
                ANSI['green' if pct_complete < 80 else 'lightyellow'],
                (chunk * bar_width).ljust(chunks),
                ANSI['reset'],
                round(pct_complete, 1),
                round(s/chunks),
                seconds,
            ))
            sys.stdout.flush()
            time.sleep(1 / chunks)

        # ██████████████████████████████████ 100.0% (60/60sec)
        sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)'.format(
            prefix,
            ANSI['red'],
            chunk * chunks,
            ANSI['reset'],
            100.0,
            seconds,
            seconds,
        ))
        sys.stdout.flush()
        # uncomment to have it disappear when it hits 100% instead of staying full red:
        # time.sleep(0.5)
        # sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH()), ANSI['reset']))
        # sys.stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        print()
        pass


def log_cli_command(subcommand: str, subcommand_args: List[str], stdin: Optional[str], pwd: str):
    from .config import VERSION, ANSI
    cmd = ' '.join(('archivebox', subcommand, *subcommand_args))
    stderr('{black}[i] [{now}] ArchiveBox v{VERSION}: {cmd}{reset}'.format(
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        VERSION=VERSION,
        cmd=cmd,
        **ANSI,
    ))
    stderr('{black}    > {pwd}{reset}'.format(pwd=pwd, **ANSI))
    stderr()

### Parsing Stage


def log_importing_started(urls: Union[str, List[str]], depth: int, index_only: bool):
    _LAST_RUN_STATS.parse_start_ts = datetime.now()
    print('{green}[+] [{}] Adding {} links to index (crawl depth={}){}...{reset}'.format(
        _LAST_RUN_STATS.parse_start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        len(urls) if isinstance(urls, list) else len(urls.split('\n')),
        depth,
        ' (index only)' if index_only else '',
        **ANSI,
    ))

def log_source_saved(source_file: str):
    print('    > Saved verbatim input to {}/{}'.format(SOURCES_DIR_NAME, source_file.rsplit('/', 1)[-1]))

def log_parsing_finished(num_parsed: int, parser_name: str):
    _LAST_RUN_STATS.parse_end_ts = datetime.now()
    print('    > Parsed {} URLs from input ({})'.format(num_parsed, parser_name))

def log_deduping_finished(num_new_links: int):
    print('    > Found {} new URLs not already in index'.format(num_new_links))


def log_crawl_started(new_links):
    print()
    print('{green}[*] Starting crawl of {} sites 1 hop out from starting point{reset}'.format(len(new_links), **ANSI))

### Indexing Stage

def log_indexing_process_started(num_links: int):
    start_ts = datetime.now()
    _LAST_RUN_STATS.index_start_ts = start_ts
    print()
    print('{black}[*] [{}] Writing {} links to main index...{reset}'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        **ANSI,
    ))


def log_indexing_process_finished():
    end_ts = datetime.now()
    _LAST_RUN_STATS.index_end_ts = end_ts


def log_indexing_started(out_path: str):
    if IS_TTY:
        sys.stdout.write(f'    > {out_path}')


def log_indexing_finished(out_path: str):
    print(f'\r    √ {out_path}')


### Archiving Stage

def log_archiving_started(num_links: int, resume: Optional[float]=None):
    start_ts = datetime.now()
    _LAST_RUN_STATS.archiving_start_ts = start_ts
    print()
    if resume:
        print('{green}[▶] [{}] Resuming archive updating for {} pages starting from {}...{reset}'.format(
             start_ts.strftime('%Y-%m-%d %H:%M:%S'),
             num_links,
             resume,
             **ANSI,
        ))
    else:
        print('{green}[▶] [{}] Starting archiving of {} snapshots in index...{reset}'.format(
             start_ts.strftime('%Y-%m-%d %H:%M:%S'),
             num_links,
             **ANSI,
        ))

def log_archiving_paused(num_links: int, idx: int, timestamp: str):
    end_ts = datetime.now()
    _LAST_RUN_STATS.archiving_end_ts = end_ts
    print()
    print('\n{lightyellow}[X] [{now}] Downloading paused on link {timestamp} ({idx}/{total}){reset}'.format(
        **ANSI,
        now=end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        idx=idx+1,
        timestamp=timestamp,
        total=num_links,
    ))
    print()
    print('    {lightred}Hint:{reset} To view your archive index, run:'.format(**ANSI))
    print('        archivebox server  # then visit http://127.0.0.1:8000')
    print('    Continue archiving where you left off by running:')
    print('        archivebox update --resume={}'.format(timestamp))

def log_archiving_finished(num_links: int):
    end_ts = datetime.now()
    _LAST_RUN_STATS.archiving_end_ts = end_ts
    assert _LAST_RUN_STATS.archiving_start_ts is not None
    seconds = end_ts.timestamp() - _LAST_RUN_STATS.archiving_start_ts.timestamp()
    if seconds > 60:
        duration = '{0:.2f} min'.format(seconds / 60)
    else:
        duration = '{0:.2f} sec'.format(seconds)

    print()
    print('{}[√] [{}] Update of {} pages complete ({}){}'.format(
        ANSI['green'],
        end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        duration,
        ANSI['reset'],
    ))
    print('    - {} links skipped'.format(_LAST_RUN_STATS.skipped))
    print('    - {} links updated'.format(_LAST_RUN_STATS.succeeded + _LAST_RUN_STATS.failed))
    print('    - {} links had errors'.format(_LAST_RUN_STATS.failed))
    print()
    print('    {lightred}Hint:{reset} To manage your archive in a Web UI, run:'.format(**ANSI))
    print('        archivebox server 0.0.0.0:8000')


def log_snapshot_archiving_started(snapshot: Model, snapshot_dir: str, is_new: bool):
    # [*] [2019-03-22 13:46:45] "Log Structured Merge Trees - ben stopford"
    #     http://www.benstopford.com/2015/02/14/log-structured-merge-trees/
    #     > output/archive/1478739709

    print('\n[{symbol_color}{symbol}{reset}] [{symbol_color}{now}{reset}] "{title}"'.format(
        symbol_color=ANSI['green' if is_new else 'black'],
        symbol='+' if is_new else '√',
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        title=snapshot.title or snapshot.base_url,
        **ANSI,
    ))
    print('    {blue}{url}{reset}'.format(url=snapshot.url, **ANSI))
    print('    {} {}'.format(
        '>' if is_new else '√',
        pretty_path(snapshot_dir),
    ))

def log_snapshot_archiving_finished(snapshot: Model, snapshot_dir: str, is_new: bool, stats: dict):
    total = sum(stats.values())

    if stats['failed'] > 0 :
        _LAST_RUN_STATS.failed += 1
    elif stats['skipped'] == total:
        _LAST_RUN_STATS.skipped += 1
    else:
        _LAST_RUN_STATS.succeeded += 1


def log_archive_method_started(method: str):
    print('      > {}'.format(method))


def log_archive_method_finished(result: "ArchiveResult"):
    """quote the argument with whitespace in a command so the user can 
       copy-paste the outputted string directly to run the cmd
    """
    # Prettify CMD string and make it safe to copy-paste by quoting arguments
    quoted_cmd = ' '.join(
        '"{}"'.format(arg) if ' ' in arg else arg
        for arg in result.cmd
    )

    if result.status == 'failed':
        if result.output.__class__.__name__ == 'TimeoutExpired':
            duration = (result.end_ts - result.start_ts).seconds
            hint_header = [
                '{lightyellow}Extractor timed out after {}s.{reset}'.format(duration, **ANSI),
            ]
        else:
            hint_header = [
                '{lightyellow}Extractor failed:{reset}'.format(**ANSI),
                '    {reset}{} {red}{}{reset}'.format(
                    result.output.__class__.__name__.replace('ArchiveError', ''),
                    result.output, 
                    **ANSI,
                ),
            ]

        # Prettify error output hints string and limit to five lines
        hints = getattr(result.output, 'hints', None) or ()
        if hints:
            hints = hints if isinstance(hints, (list, tuple)) else hints.split('\n')
            hints = (
                '    {}{}{}'.format(ANSI['lightyellow'], line.strip(), ANSI['reset'])
                for line in hints[:5] if line.strip()
            )


        # Collect and prefix output lines with indentation
        output_lines = [
            *hint_header,
            *hints,
            '{}Run to see full output:{}'.format(ANSI['lightred'], ANSI['reset']),
            *(['    cd {};'.format(result.pwd)] if result.pwd else []),
            '    {}'.format(quoted_cmd),
        ]
        print('\n'.join(
            '        {}'.format(line)
            for line in output_lines
            if line
        ))
        print()


def log_list_started(filter_patterns: Optional[List[str]], filter_type: str):
    print('{green}[*] Finding links in the archive index matching these {} patterns:{reset}'.format(
        filter_type,
        **ANSI,
    ))
    print('    {}'.format(' '.join(filter_patterns or ())))

def log_list_finished(snapshots):
    from .index.csv import snapshots_to_csv
    print()
    print('---------------------------------------------------------------------------------------------------')
    print(snapshots_to_csv(snapshots, cols=['timestamp', 'is_archived', 'num_outputs', 'url'], header=True, ljust=16, separator=' | '))
    print('---------------------------------------------------------------------------------------------------')
    print()


def log_removal_started(snapshots: List["Snapshot"], yes: bool, delete: bool):
    print('{lightyellow}[i] Found {} matching URLs to remove.{reset}'.format(len(snapshots), **ANSI))
    if delete:
        file_counts = [snapshot.num_outputs for snapshot in snapshots if Path(snapshot.snapshot_dir).exists()]
        print(
            f'    {len(snapshots)} Snapshots will be de-listed from the main index, and their archived content folders will be deleted from disk.\n'
            f'    ({len(file_counts)} data folders with {sum(file_counts)} archived files will be deleted!)'
        )
    else:
        print(
            '    Matching snapshots will be de-listed from the main index, but their archived content folders will remain in place on disk.\n'
            '    (Pass --delete if you also want to permanently delete the data folders)'
        )

    if not yes:
        print()
        print('{lightyellow}[?] Do you want to proceed with removing these {} snapshots?{reset}'.format(len(snapshots), **ANSI))
        try:
            assert input('    y/[n]: ').lower() == 'y'
        except (KeyboardInterrupt, EOFError, AssertionError):
            raise SystemExit(0)

def log_removal_finished(all_snapshots: int, to_remove: int):
    if to_remove == 0:
        print()
        print('{red}[X] No matching snapshots found.{reset}'.format(**ANSI))
    else:
        print()
        print('{red}[√] Removed {} out of {} snapshots from the archive index.{reset}'.format(
            to_remove,
            all_snapshots,
            **ANSI,
        ))
        print('    Index now contains {} snapshots.'.format(all_snapshots - to_remove))


def log_shell_welcome_msg():
    from .cli import list_subcommands

    print('{green}# ArchiveBox Imports{reset}'.format(**ANSI))
    print('{green}from core.models import Snapshot, User{reset}'.format(**ANSI))
    print('{green}from archivebox import *\n    {}{reset}'.format("\n    ".join(list_subcommands().keys()), **ANSI))
    print()
    print('[i] Welcome to the ArchiveBox Shell!')
    print('    https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Shell-Usage')
    print()
    print('    {lightred}Hint:{reset} Example use:'.format(**ANSI))
    print('        print(Snapshot.objects.filter(is_archived=True).count())')
    print('        Snapshot.objects.get(url="https://example.com").as_json()')
    print('        add("https://example.com/some/new/url")')



### Helpers

@enforce_types
def pretty_path(path: Union[Path, str]) -> str:
    """convert paths like .../ArchiveBox/archivebox/../output/abc into output/abc"""
    pwd = Path('.').resolve()
    # parent = os.path.abspath(os.path.join(pwd, os.path.pardir))
    return str(path).replace(str(pwd) + '/', './')


@enforce_types
def printable_filesize(num_bytes: Union[int, float]) -> str:
    for count in ['Bytes','KB','MB','GB']:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return '%3.1f %s' % (num_bytes, count)
        num_bytes /= 1024.0
    return '%3.1f %s' % (num_bytes, 'TB')


@enforce_types
def printable_folders(folders: Dict[str, Optional["Link"]],
                      with_headers: bool=False) -> str:
    return '\n'.join(
        f'{folder} {link and link.url} "{link and link.title}"'
        for folder, link in folders.items()
    )



@enforce_types
def printable_config(config: ConfigDict, prefix: str='') -> str:
    return f'\n{prefix}'.join(
        f'{key}={val}'
        for key, val in config.items()
        if not (isinstance(val, dict) or callable(val))
    )


@enforce_types
def printable_folder_status(name: str, folder: Dict) -> str:
    if folder['enabled']:
        if folder['is_valid']:
            color, symbol, note = 'green', '√', 'valid'
        else:
            color, symbol, note, num_files = 'red', 'X', 'invalid', '?'
    else:
        color, symbol, note, num_files = 'lightyellow', '-', 'disabled', '-'

    if folder['path']:
        if Path(folder['path']).exists():
            num_files = (
                f'{len(os.listdir(folder["path"]))} files'
                if Path(folder['path']).is_dir() else
                printable_filesize(Path(folder['path']).stat().st_size)
            )
        else:
            num_files = 'missing'

    path = str(folder['path']).replace(str(OUTPUT_DIR), '.') if folder['path'] else ''
    if path and ' ' in path:
        path = f'"{path}"'

    # if path is just a plain dot, replace it back with the full path for clarity
    if path == '.':
        path = str(OUTPUT_DIR)

    return ' '.join((
        ANSI[color],
        symbol,
        ANSI['reset'],
        name.ljust(21),
        num_files.ljust(14),
        ANSI[color],
        note.ljust(8),
        ANSI['reset'],
        path.ljust(76),
    ))


@enforce_types
def printable_dependency_version(name: str, dependency: Dict) -> str:
    version = None
    if dependency['enabled']:
        if dependency['is_valid']:
            color, symbol, note, version = 'green', '√', 'valid', ''

            parsed_version_num = re.search(r'[\d\.]+', dependency['version'])
            if parsed_version_num:
                version = f'v{parsed_version_num[0]}'

        if not version:
            color, symbol, note, version = 'red', 'X', 'invalid', '?'
    else:
        color, symbol, note, version = 'lightyellow', '-', 'disabled', '-'

    path = str(dependency["path"]).replace(str(OUTPUT_DIR), '.') if dependency["path"] else ''
    if path and ' ' in path:
        path = f'"{path}"'

    return ' '.join((
        ANSI[color],
        symbol,
        ANSI['reset'],
        name.ljust(21),
        version.ljust(14),
        ANSI[color],
        note.ljust(8),
        ANSI['reset'],
        path.ljust(76),
    ))
