"""

WARNING: THIS FILE IS ALL LEGACY CODE TO BE REMOVED.

DO NOT ADD ANY NEW FEATURES TO THIS FILE, NEW CODE GOES HERE: core/models.py

"""

__package__ = 'archivebox.index'

from pathlib import Path

from datetime import datetime, timedelta

from typing import List, Dict, Any, Optional, Union

from dataclasses import dataclass, asdict, field, fields


from ..system import get_dir_size

from ..config import OUTPUT_DIR, ARCHIVE_DIR_NAME

class ArchiveError(Exception):
    def __init__(self, message, hints=None):
        super().__init__(message)
        self.hints = hints

LinkDict = Dict[str, Any]

ArchiveOutput = Union[str, Exception, None]

@dataclass(frozen=True)
class ArchiveResult:
    cmd: List[str]
    pwd: Optional[str]
    cmd_version: Optional[str]
    output: ArchiveOutput
    status: str
    start_ts: datetime
    end_ts: datetime
    index_texts: Union[List[str], None] = None
    schema: str = 'ArchiveResult'

    def __post_init__(self):
        self.typecheck()

    def _asdict(self):
        return asdict(self)

    def typecheck(self) -> None:
        assert self.schema == self.__class__.__name__
        assert isinstance(self.status, str) and self.status
        assert isinstance(self.start_ts, datetime)
        assert isinstance(self.end_ts, datetime)
        assert isinstance(self.cmd, list)
        assert all(isinstance(arg, str) and arg for arg in self.cmd)

        # TODO: replace emptystrings in these three with None / remove them from the DB
        assert self.pwd is None or isinstance(self.pwd, str)
        assert self.cmd_version is None or isinstance(self.cmd_version, str)
        assert self.output is None or isinstance(self.output, (str, Exception))

    @classmethod
    def guess_ts(_cls, dict_info):
        from ..util import parse_date
        parsed_timestamp = parse_date(dict_info["timestamp"])
        start_ts = parsed_timestamp
        end_ts = parsed_timestamp + timedelta(seconds=int(dict_info["duration"]))
        return start_ts, end_ts

    @classmethod
    def from_json(cls, json_info, guess=False):
        from ..util import parse_date

        info = {
            key: val
            for key, val in json_info.items()
            if key in cls.field_names()
        }
        if guess:
            keys = info.keys()
            if "start_ts" not in keys:
                info["start_ts"], info["end_ts"] = cls.guess_ts(json_info)
            else:
                info['start_ts'] = parse_date(info['start_ts'])
                info['end_ts'] = parse_date(info['end_ts'])
            if "pwd" not in keys:
                info["pwd"] = str(Path(OUTPUT_DIR) / ARCHIVE_DIR_NAME / json_info["timestamp"])
            if "cmd_version" not in keys:
                info["cmd_version"] = "Undefined"
            if "cmd" not in keys:
                info["cmd"] = []
        else:
            info['start_ts'] = parse_date(info['start_ts'])
            info['end_ts'] = parse_date(info['end_ts'])
            info['cmd_version'] = info.get('cmd_version')
        if type(info["cmd"]) is str:
            info["cmd"] = [info["cmd"]]
        return cls(**info)

    def to_dict(self, *keys) -> dict:
        if keys:
            return {k: v for k, v in asdict(self).items() if k in keys}
        return asdict(self)

    def to_json(self, indent=4, sort_keys=True) -> str:
        from .json import to_json

        return to_json(self, indent=indent, sort_keys=sort_keys)

    def to_csv(self, cols: Optional[List[str]]=None, separator: str=',', ljust: int=0) -> str:
        from .csv import to_csv

        return to_csv(self, csv_col=cols or self.field_names(), separator=separator, ljust=ljust)
    
    @classmethod
    def field_names(cls):
        return [f.name for f in fields(cls)]

    @property
    def duration(self) -> int:
        return (self.end_ts - self.start_ts).seconds

@dataclass(frozen=True)
class Link:
    timestamp: str
    url: str
    title: Optional[str]
    tags: Optional[str]
    sources: List[str]
    history: Dict[str, List[ArchiveResult]] = field(default_factory=lambda: {})
    updated: Optional[datetime] = None
    schema: str = 'Link'


    def __str__(self) -> str:
        return f'[{self.timestamp}] {self.url} "{self.title}"'

    def __post_init__(self):
        self.typecheck()

    def overwrite(self, **kwargs):
        """pure functional version of dict.update that returns a new instance"""
        return Link(**{**self._asdict(), **kwargs})

    def __eq__(self, other):
        if not isinstance(other, Link):
            return NotImplemented
        return self.url == other.url

    def __gt__(self, other):
        if not isinstance(other, Link):
            return NotImplemented
        if not self.timestamp or not other.timestamp:
            return 
        return float(self.timestamp) > float(other.timestamp)

    def typecheck(self) -> None:
        from ..config import stderr, ANSI
        try:
            assert self.schema == self.__class__.__name__
            assert isinstance(self.timestamp, str) and self.timestamp
            assert self.timestamp.replace('.', '').isdigit()
            assert isinstance(self.url, str) and '://' in self.url
            assert self.updated is None or isinstance(self.updated, datetime)
            assert self.title is None or (isinstance(self.title, str) and self.title)
            assert self.tags is None or isinstance(self.tags, str)
            assert isinstance(self.sources, list)
            assert all(isinstance(source, str) and source for source in self.sources)
            assert isinstance(self.history, dict)
            for method, results in self.history.items():
                assert isinstance(method, str) and method
                assert isinstance(results, list)
                assert all(isinstance(result, ArchiveResult) for result in results)
        except Exception:
            stderr('{red}[X] Error while loading link! [{}] {} "{}"{reset}'.format(self.timestamp, self.url, self.title, **ANSI))
            raise
    
    def _asdict(self, extended=False):
        info = {
            'schema': 'Link',
            'url': self.url,
            'title': self.title or None,
            'timestamp': self.timestamp,
            'updated': self.updated or None,
            'tags': self.tags or None,
            'sources': self.sources or [],
            'history': self.history or {},
        }
        if extended:
            info.update({
                'link_dir': self.link_dir,
                'archive_path': self.archive_path,
                
                'hash': self.url_hash,
                'base_url': self.base_url,
                'scheme': self.scheme,
                'domain': self.domain,
                'path': self.path,
                'basename': self.basename,
                'extension': self.extension,
                'is_static': self.is_static,

                'bookmarked_date': self.bookmarked_date,
                'updated_date': self.updated_date,
                'oldest_archive_date': self.oldest_archive_date,
                'newest_archive_date': self.newest_archive_date,
        
                'is_archived': self.is_archived,
                'num_outputs': self.num_outputs,
                'num_failures': self.num_failures,
                
                'latest': self.latest_outputs(),
                'canonical': self.canonical_outputs(),
            })
        return info

    def as_snapshot(self):
        from core.models import Snapshot
        return Snapshot.objects.get(url=self.url)

    @classmethod
    def from_json(cls, json_info, guess=False):
        from ..util import parse_date
        
        info = {
            key: val
            for key, val in json_info.items()
            if key in cls.field_names()
        }
        info['updated'] = parse_date(info.get('updated'))
        info['sources'] = info.get('sources') or []

        json_history = info.get('history') or {}
        cast_history = {}

        for method, method_history in json_history.items():
            cast_history[method] = []
            for json_result in method_history:
                assert isinstance(json_result, dict), 'Items in Link["history"][method] must be dicts'
                cast_result = ArchiveResult.from_json(json_result, guess)
                cast_history[method].append(cast_result)

        info['history'] = cast_history
        return cls(**info)

    def to_json(self, indent=4, sort_keys=True) -> str:
        from .json import to_json

        return to_json(self, indent=indent, sort_keys=sort_keys)

    def to_csv(self, cols: Optional[List[str]]=None, separator: str=',', ljust: int=0) -> str:
        from .csv import to_csv

        return to_csv(self, cols=cols or self.field_names(), separator=separator, ljust=ljust)

    @classmethod
    def field_names(cls):
        return [f.name for f in fields(cls)]

    @property
    def link_dir(self) -> str:
        from ..config import CONFIG
        return str(Path(CONFIG['ARCHIVE_DIR']) / self.timestamp)

    @property
    def archive_path(self) -> str:
        from ..config import ARCHIVE_DIR_NAME
        return '{}/{}'.format(ARCHIVE_DIR_NAME, self.timestamp)
    
    @property
    def archive_size(self) -> float:
        try:
            return get_dir_size(self.archive_path)[0]
        except Exception:
            return 0

    ### URL Helpers
    @property
    def url_hash(self):
        from ..util import hashurl

        return hashurl(self.url)

    @property
    def scheme(self) -> str:
        from ..util import scheme
        return scheme(self.url)

    @property
    def extension(self) -> str:
        from ..util import extension
        return extension(self.url)

    @property
    def domain(self) -> str:
        from ..util import domain
        return domain(self.url)

    @property
    def path(self) -> str:
        from ..util import path
        return path(self.url)

    @property
    def basename(self) -> str:
        from ..util import basename
        return basename(self.url)

    @property
    def base_url(self) -> str:
        from ..util import base_url
        return base_url(self.url)

    ### Pretty Printing Helpers
    @property
    def bookmarked_date(self) -> Optional[str]:
        from ..util import ts_to_date

        max_ts = (datetime.now() + timedelta(days=30)).timestamp()

        if self.timestamp and self.timestamp.replace('.', '').isdigit():
            if 0 < float(self.timestamp) < max_ts:
                return ts_to_date(datetime.fromtimestamp(float(self.timestamp)))
            else:
                return str(self.timestamp)
        return None


    @property
    def updated_date(self) -> Optional[str]:
        from ..util import ts_to_date
        return ts_to_date(self.updated) if self.updated else None

    @property
    def archive_dates(self) -> List[datetime]:
        return [
            result.start_ts
            for method in self.history.keys()
                for result in self.history[method]
        ]

    @property
    def oldest_archive_date(self) -> Optional[datetime]:
        return min(self.archive_dates, default=None)

    @property
    def newest_archive_date(self) -> Optional[datetime]:
        return max(self.archive_dates, default=None)

    ### Archive Status Helpers
    @property
    def num_outputs(self) -> int:
        return self.as_snapshot().num_outputs

    @property
    def num_failures(self) -> int:
        return sum(1
                   for method in self.history.keys()
                       for result in self.history[method]
                            if result.status == 'failed')

    @property
    def is_static(self) -> bool:
        from ..util import is_static_file
        return is_static_file(self.url)

    @property
    def is_archived(self) -> bool:
        from ..config import ARCHIVE_DIR
        from ..util import domain

        output_paths = (
            domain(self.url),
            'output.pdf',
            'screenshot.png',
            'output.html',
            'media',
            'singlefile.html'
        )

        return any(
            (Path(ARCHIVE_DIR) / self.timestamp / path).exists()
            for path in output_paths
        )

    def latest_outputs(self, status: str=None) -> Dict[str, ArchiveOutput]:
        """get the latest output that each archive method produced for link"""
        
        ARCHIVE_METHODS = (
            'title', 'favicon', 'wget', 'warc', 'singlefile', 'pdf',
            'screenshot', 'dom', 'git', 'media', 'archive_org',
        )
        latest: Dict[str, ArchiveOutput] = {}
        for archive_method in ARCHIVE_METHODS:
            # get most recent succesful result in history for each archive method
            history = self.history.get(archive_method) or []
            history = list(filter(lambda result: result.output, reversed(history)))
            if status is not None:
                history = list(filter(lambda result: result.status == status, history))

            history = list(history)
            if history:
                latest[archive_method] = history[0].output
            else:
                latest[archive_method] = None
        return latest



    def canonical_outputs(self) -> Dict[str, Optional[str]]:
        """predict the expected output paths that should be present after archiving"""

        from ..extractors.wget import wget_output_path
        # TODO: banish this awful duplication from the codebase and import these
        # from their respective extractor files
        canonical = {
            'index_path': 'index.html',
            'favicon_path': 'favicon.ico',
            'google_favicon_path': 'https://www.google.com/s2/favicons?domain={}'.format(self.domain),
            'wget_path': wget_output_path(self),
            'warc_path': 'warc/',
            'singlefile_path': 'singlefile.html',
            'readability_path': 'readability/content.html',
            'mercury_path': 'mercury/content.html',
            'pdf_path': 'output.pdf',
            'screenshot_path': 'screenshot.png',
            'dom_path': 'output.html',
            'archive_org_path': 'https://web.archive.org/web/{}'.format(self.base_url),
            'git_path': 'git/',
            'media_path': 'media/',
            'headers_path': 'headers.json',
        }
        if self.is_static:
            # static binary files like PDF and images are handled slightly differently.
            # they're just downloaded once and aren't archived separately multiple times, 
            # so the wget, screenshot, & pdf urls should all point to the same file

            static_path = wget_output_path(self)
            canonical.update({
                'title': self.basename,
                'wget_path': static_path,
                'pdf_path': static_path,
                'screenshot_path': static_path,
                'dom_path': static_path,
                'singlefile_path': static_path,
                'readability_path': static_path,
                'mercury_path': static_path,
            })
        return canonical

