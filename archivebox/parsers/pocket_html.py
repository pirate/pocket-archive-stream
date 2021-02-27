__package__ = 'archivebox.parsers'


import re

from typing import IO, Iterable
from datetime import datetime

from django.db.models import Model

from ..util import (
    htmldecode,
    enforce_types,
)


@enforce_types
def parse_pocket_html_export(html_file: IO[str], **_kwargs) -> Iterable[Model]:
    """Parse Pocket-format bookmarks export files (produced by getpocket.com/export/)"""
    from core.models import Snapshot

    html_file.seek(0)
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)
    for line in html_file:
        # example line
        # <li><a href="http://example.com/ time_added="1478739709" tags="tag1,tag2">example title</a></li>
        match = pattern.search(line)
        if match:
            url = match.group(1).replace('http://www.readability.com/read?url=', '')           # remove old readability prefixes to get original url
            time = datetime.fromtimestamp(float(match.group(2)))
            tags = match.group(3)
            title = match.group(4).replace(' — Readability', '').replace('http://www.readability.com/read?url=', '')
            
            yield Snapshot(
                url=htmldecode(url),
                timestamp=str(time.timestamp()),
                title=htmldecode(title) or None,
                #tags=tags or '',
                #sources=[html_file.name],
            )
