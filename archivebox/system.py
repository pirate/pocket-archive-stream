__package__ = 'archivebox'


import os
import signal
import shutil

from json import dump
from pathlib import Path
from typing import Optional, Union, Set, Tuple
from subprocess import _mswindows, PIPE, Popen, CalledProcessError, CompletedProcess, TimeoutExpired

from crontab import CronTab
from .vendor.atomicwrites import atomic_write as lib_atomic_write

from .util import enforce_types, ExtendedEncoder
from .config import PYTHON_BINARY, OUTPUT_PERMISSIONS



def run(cmd, *args, input=None, capture_output=True, timeout=None, check=False, text=False, start_new_session=True, **kwargs):
    """Patched of subprocess.run to kill forked child subprocesses and fix blocking io making timeout=innefective
        Mostly copied from https://github.com/python/cpython/blob/master/Lib/subprocess.py
    """

    if input is not None:
        if kwargs.get('stdin') is not None:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = PIPE

    if capture_output:
        if ('stdout' in kwargs) or ('stderr' in kwargs):
            raise ValueError('stdout and stderr arguments may not be used '
                             'with capture_output.')
        kwargs['stdout'] = PIPE
        kwargs['stderr'] = PIPE

    pgid = None
    try:
        if isinstance(cmd, (list, tuple)) and cmd[0].endswith('.py'):
            cmd = (PYTHON_BINARY, *cmd)

        with Popen(cmd, *args, start_new_session=start_new_session, **kwargs) as process:
            pgid = os.getpgid(process.pid)
            try:
                stdout, stderr = process.communicate(input, timeout=timeout)
            except TimeoutExpired as exc:
                process.kill()
                if _mswindows:
                    # Windows accumulates the output in a single blocking
                    # read() call run on child threads, with the timeout
                    # being done in a join() on those threads.  communicate()
                    # _after_ kill() is required to collect that and add it
                    # to the exception.
                    exc.stdout, exc.stderr = process.communicate()
                else:
                    # POSIX _communicate already populated the output so
                    # far into the TimeoutExpired exception.
                    process.wait()
                raise
            except:  # Including KeyboardInterrupt, communicate handled that.
                process.kill()
                # We don't call process.wait() as .__exit__ does that for us.
                raise

            retcode = process.poll()
            if check and retcode:
                raise CalledProcessError(retcode, process.args,
                                         output=stdout, stderr=stderr)
    finally:
        # force kill any straggler subprocesses that were forked from the main proc
        try:
            os.killpg(pgid, signal.SIGINT)
        except Exception:
            pass

    return CompletedProcess(process.args, retcode, stdout, stderr)


@enforce_types
def atomic_write(path: Union[Path, str], contents: Union[dict, str, bytes], overwrite: bool=True) -> None:
    """Safe atomic write to filesystem by writing to temp file + atomic rename"""

    mode = 'wb+' if isinstance(contents, bytes) else 'w'
    encoding = None if isinstance(contents, bytes) else 'utf-8'  # enforce utf-8 on all text writes

    # print('\n> Atomic Write:', mode, path, len(contents), f'overwrite={overwrite}')
    try:
        with lib_atomic_write(path, mode=mode, overwrite=overwrite, encoding=encoding) as f:
            if isinstance(contents, dict):
                dump(contents, f, indent=4, sort_keys=True, cls=ExtendedEncoder)
            elif isinstance(contents, (bytes, str)):
                f.write(contents)
    except OSError as e:
        print(f"[X] OSError: Failed to write {path} with fcntl.F_FULLFSYNC. ({e})")
        print("    You can store the archive/ subfolder on a hard drive or network share that doesn't support support syncronous writes,")
        print("    but the main folder containing the index.sqlite3 and ArchiveBox.conf files must be on a filesystem that supports FSYNC.")
        raise SystemExit(1)
    os.chmod(path, int(OUTPUT_PERMISSIONS, base=8))

@enforce_types
def chmod_file(path: str, cwd: str='.', permissions: str=OUTPUT_PERMISSIONS) -> None:
    """chmod -R <permissions> <cwd>/<path>"""

    root = Path(cwd) / path
    if not root.exists():
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    if not root.is_dir():
        os.chmod(root, int(OUTPUT_PERMISSIONS, base=8))
    else:
        for subpath in Path(path).glob('**/*'):
            os.chmod(subpath, int(OUTPUT_PERMISSIONS, base=8))


@enforce_types
def copy_and_overwrite(from_path: Union[str, Path], to_path: Union[str, Path]):
    """copy a given file or directory to a given path, overwriting the destination"""
    if Path(from_path).is_dir():
        shutil.rmtree(to_path, ignore_errors=True)
        shutil.copytree(from_path, to_path)
    else:
        with open(from_path, 'rb') as src:
            contents = src.read()
        atomic_write(to_path, contents)


@enforce_types
def get_dir_size(path: Union[str, Path], recursive: bool=True, pattern: Optional[str]=None) -> Tuple[int, int, int]:
    """get the total disk size of a given directory, optionally summing up 
       recursively and limiting to a given filter list
    """
    num_bytes, num_dirs, num_files = 0, 0, 0
    for entry in os.scandir(path):
        if (pattern is not None) and (pattern not in entry.path):
            continue
        if entry.is_dir(follow_symlinks=False):
            if not recursive:
                continue
            num_dirs += 1
            bytes_inside, dirs_inside, files_inside = get_dir_size(entry.path)
            num_bytes += bytes_inside
            num_dirs += dirs_inside
            num_files += files_inside
        else:
            num_bytes += entry.stat(follow_symlinks=False).st_size
            num_files += 1
    return num_bytes, num_dirs, num_files


CRON_COMMENT = 'archivebox_schedule'


@enforce_types
def dedupe_cron_jobs(cron: CronTab) -> CronTab:
    deduped: Set[Tuple[str, str]] = set()

    for job in list(cron):
        unique_tuple = (str(job.slices), job.command)
        if unique_tuple not in deduped:
            deduped.add(unique_tuple)
        cron.remove(job)

    for schedule, command in deduped:
        job = cron.new(command=command, comment=CRON_COMMENT)
        job.setall(schedule)
        job.enable()

    return cron


class suppress_output(object):
    '''
    A context manager for doing a "deep suppression" of stdout and stderr in 
    Python, i.e. will suppress all print, even if the print originates in a 
    compiled C/Fortran sub-function.
       This will not suppress raised exceptions, since exceptions are printed
    to stderr just before a script exits, and after the context manager has
    exited (at least, I think that is why it lets exceptions through).      

    with suppress_stdout_stderr():
        rogue_function()
    '''
    def __init__(self, stdout=True, stderr=True):
        # Open a pair of null files
        # Save the actual stdout (1) and stderr (2) file descriptors.
        self.stdout, self.stderr = stdout, stderr
        if stdout:
            self.null_stdout = os.open(os.devnull, os.O_RDWR)
            self.real_stdout = os.dup(1)
        if stderr:
            self.null_stderr = os.open(os.devnull, os.O_RDWR)
            self.real_stderr = os.dup(2)

    def __enter__(self):
        # Assign the null pointers to stdout and stderr.
        if self.stdout:
            os.dup2(self.null_stdout, 1)
        if self.stderr:
            os.dup2(self.null_stderr, 2)

    def __exit__(self, *_):
        # Re-assign the real stdout/stderr back to (1) and (2)
        if self.stdout:
            os.dup2(self.real_stdout, 1)
            os.close(self.null_stdout)
        if self.stderr:
            os.dup2(self.real_stderr, 2)
            os.close(self.null_stderr)
