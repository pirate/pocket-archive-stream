__package__ = 'archivebox'

import re
import os
import sys
import stat
import time
import argparse
from math import log
from multiprocessing import Process
from pathlib import Path

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Union, IO, TYPE_CHECKING

if TYPE_CHECKING:
    from .index.schema import Link, ArchiveResult

from .system import get_dir_size
from .util import enforce_types
from .config import (
    ConfigDict,
    OUTPUT_DIR,
    PYTHON_ENCODING,
    VERSION,
    ANSI,
    IS_TTY,
    IN_DOCKER,
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


def debug_dict_summary(obj: Dict[Any, Any]) -> None:
    stderr(' '.join(f'{key}={str(val).ljust(6)}' for key, val in obj.items()))


def get_fd_info(fd) -> Dict[str, Any]:
    NAME = fd.name[1:-1]
    FILENO = fd.fileno()
    MODE = os.fstat(FILENO).st_mode
    IS_TTY = hasattr(fd, 'isatty') and fd.isatty()
    IS_PIPE = stat.S_ISFIFO(MODE)
    IS_FILE = stat.S_ISREG(MODE)
    IS_TERMINAL =  not (IS_PIPE or IS_FILE)
    IS_LINE_BUFFERED = fd.line_buffering
    IS_READABLE = fd.readable()
    return {
        'NAME': NAME, 'FILENO': FILENO, 'MODE': MODE,
        'IS_TTY': IS_TTY, 'IS_PIPE': IS_PIPE, 'IS_FILE': IS_FILE,
        'IS_TERMINAL': IS_TERMINAL, 'IS_LINE_BUFFERED': IS_LINE_BUFFERED,
        'IS_READABLE': IS_READABLE,
    }
    

# # Log debug information about stdin, stdout, and stderr
# sys.stdout.write('[>&1] this is python stdout\n')
# sys.stderr.write('[>&2] this is python stderr\n')

# debug_dict_summary(get_fd_info(sys.stdin))
# debug_dict_summary(get_fd_info(sys.stdout))
# debug_dict_summary(get_fd_info(sys.stderr))



class SmartFormatter(argparse.HelpFormatter):
    """Patched formatter that prints newlines in argparse help strings"""
    def _split_lines(self, text, width):
        if '\n' in text:
            return text.splitlines()
        return argparse.HelpFormatter._split_lines(self, text, width)


def reject_stdin(caller: str, stdin: Optional[IO]=sys.stdin) -> None:
    """Tell the user they passed stdin to a command that doesn't accept it"""

    if not stdin:
        return None

    if IN_DOCKER:
        # when TTY is disabled in docker we cant tell if stdin is being piped in or not
        # if we try to read stdin when its not piped we will hang indefinitely waiting for it
        return None

    if not stdin.isatty():
        # stderr('READING STDIN TO REJECT...')
        stdin_raw_text = stdin.read()
        if stdin_raw_text.strip():
            # stderr('GOT STDIN!', len(stdin_str))
            stderr(f'[!] The "{caller}" command does not accept stdin (ignoring).', color='red')
            stderr(f'    Run archivebox "{caller} --help" to see usage and examples.')
            stderr()
            # raise SystemExit(1)
    return None


def accept_stdin(stdin: Optional[IO]=sys.stdin) -> Optional[str]:
    """accept any standard input and return it as a string or None"""
    
    if not stdin:
        return None

    if not stdin.isatty():
        # stderr('READING STDIN TO ACCEPT...')
        stdin_str = stdin.read()

        if stdin_str:
            # stderr('GOT STDIN...', len(stdin_str))
            return stdin_str

    return None


class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix=''):

        self.SHOW_PROGRESS = SHOW_PROGRESS
        if self.SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix))
            self.p.start()

        self.stats = {'start_ts': datetime.now(timezone.utc), 'end_ts': None}

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""


        end_ts = datetime.now(timezone.utc)
        self.stats['end_ts'] = end_ts
        
        if self.SHOW_PROGRESS:
            # terminate if we havent already terminated
            try:
                # kill the progress bar subprocess
                try:
                    self.p.close()   # must be closed *before* its terminnated
                except (KeyboardInterrupt, SystemExit):
                    print()
                    raise
                except BaseException:                                           # lgtm [py/catch-base-exception]
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


def log_cli_command(subcommand: str, subcommand_args: List[str], stdin: Optional[str], pwd: str):
    cmd = ' '.join(('archivebox', subcommand, *subcommand_args))
    stderr('{black}[i] [{now}] ArchiveBox v{VERSION}: {cmd}{reset}'.format(
        now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        VERSION=VERSION,
        cmd=cmd,
        **ANSI,
    ))
    stderr('{black}    > {pwd}{reset}'.format(pwd=pwd, **ANSI))
    stderr()

### Parsing Stage


def log_importing_started(urls: Union[str, List[str]], depth: int, index_only: bool):
    _LAST_RUN_STATS.parse_start_ts = datetime.now(timezone.utc)
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
    _LAST_RUN_STATS.parse_end_ts = datetime.now(timezone.utc)
    print('    > Parsed {} URLs from input ({})'.format(num_parsed, parser_name))

def log_deduping_finished(num_new_links: int):
    print('    > Found {} new URLs not already in index'.format(num_new_links))


def log_crawl_started(new_links):
    print()
    print('{green}[*] Starting crawl of {} sites 1 hop out from starting point{reset}'.format(len(new_links), **ANSI))

### Indexing Stage

def log_indexing_process_started(num_links: int):
    start_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.index_start_ts = start_ts
    print()
    print('{black}[*] [{}] Writing {} links to main index...{reset}'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        **ANSI,
    ))


def log_indexing_process_finished():
    end_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.index_end_ts = end_ts


def log_indexing_started(out_path: str):
    if IS_TTY:
        sys.stdout.write(f'    > ./{Path(out_path).relative_to(OUTPUT_DIR)}')


def log_indexing_finished(out_path: str):
    print(f'\r    √ ./{Path(out_path).relative_to(OUTPUT_DIR)}')


### Archiving Stage

def log_archiving_started(num_links: int, resume: Optional[float]=None):

    start_ts = datetime.now(timezone.utc)
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

    end_ts = datetime.now(timezone.utc)
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
    print('    Continue archiving where you left off by running:')
    print('        archivebox update --resume={}'.format(timestamp))

def log_archiving_finished(num_links: int):

    from core.models import Snapshot

    end_ts = datetime.now(timezone.utc)
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
    
    if Snapshot.objects.count() < 50:
        print()
        print('    {lightred}Hint:{reset} To manage your archive in a Web UI, run:'.format(**ANSI))
        print('        archivebox server 0.0.0.0:8000')


def log_link_archiving_started(link: "Link", link_dir: str, is_new: bool):

    # [*] [2019-03-22 13:46:45] "Log Structured Merge Trees - ben stopford"
    #     http://www.benstopford.com/2015/02/14/log-structured-merge-trees/
    #     > output/archive/1478739709

    print('\n[{symbol_color}{symbol}{reset}] [{symbol_color}{now}{reset}] "{title}"'.format(
        symbol_color=ANSI['green' if is_new else 'black'],
        symbol='+' if is_new else '√',
        now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        title=link.title or link.base_url,
        **ANSI,
    ))
    print('    {blue}{url}{reset}'.format(url=link.url, **ANSI))
    print('    {} {}'.format(
        '>' if is_new else '√',
        pretty_path(link_dir),
    ))

def log_link_archiving_finished(link: "Link", link_dir: str, is_new: bool, stats: dict, start_ts: datetime):
    total = sum(stats.values())

    if stats['failed'] > 0 :
        _LAST_RUN_STATS.failed += 1
    elif stats['skipped'] == total:
        _LAST_RUN_STATS.skipped += 1
    else:
        _LAST_RUN_STATS.succeeded += 1

    size = get_dir_size(link_dir)
    end_ts = datetime.now(timezone.utc)
    duration = str(end_ts - start_ts).split('.')[0]
    print('        {black}{} files ({}) in {}s {reset}'.format(size[2], printable_filesize(size[0]), duration, **ANSI))


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

def log_list_finished(links):
    from .index.csv import links_to_csv
    print()
    print('---------------------------------------------------------------------------------------------------')
    print(links_to_csv(links, cols=['timestamp', 'is_archived', 'num_outputs', 'url'], header=True, ljust=16, separator=' | '))
    print('---------------------------------------------------------------------------------------------------')
    print()


def log_removal_started(links: List["Link"], yes: bool, delete: bool):
    print('{lightyellow}[i] Found {} matching URLs to remove.{reset}'.format(len(links), **ANSI))
    if delete:
        file_counts = [link.num_outputs for link in links if Path(link.link_dir).exists()]
        print(
            f'    {len(links)} Links will be de-listed from the main index, and their archived content folders will be deleted from disk.\n'
            f'    ({len(file_counts)} data folders with {sum(file_counts)} archived files will be deleted!)'
        )
    else:
        print(
            '    Matching links will be de-listed from the main index, but their archived content folders will remain in place on disk.\n'
            '    (Pass --delete if you also want to permanently delete the data folders)'
        )

    if not yes:
        print()
        print('{lightyellow}[?] Do you want to proceed with removing these {} links?{reset}'.format(len(links), **ANSI))
        try:
            assert input('    y/[n]: ').lower() == 'y'
        except (KeyboardInterrupt, EOFError, AssertionError):
            raise SystemExit(0)

def log_removal_finished(all_links: int, to_remove: int):
    if all_links == 0:
        print()
        print('{red}[X] No matching links found.{reset}'.format(**ANSI))
    else:
        print()
        print('{red}[√] Removed {} out of {} links from the archive index.{reset}'.format(
            to_remove,
            all_links,
            **ANSI,
        ))
        print('    Index now contains {} links.'.format(all_links - to_remove))


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
