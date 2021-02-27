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
def parse_netscape_html_export(html_file: IO[str], **_kwargs) -> Iterable[Model]:
    """Parse netscape-format bookmarks export files (produced by all browsers)"""
    from core.models import Snapshot

    html_file.seek(0)
    pattern = re.compile("<a href=\"(.+?)\" add_date=\"(\\d+)\"[^>]*>(.+)</a>", re.UNICODE | re.IGNORECASE)
    for line in html_file:
        # example line
        # <DT><A HREF="https://example.com/?q=1+2" ADD_DATE="1497562974" LAST_MODIFIED="1497562974" ICON_URI="https://example.com/favicon.ico" ICON="data:image/png;base64,...">example bookmark title</A>
        
        match = pattern.search(line)
        if match:
            url = match.group(1)
            time = datetime.fromtimestamp(float(match.group(2)))
            title = match.group(3).strip()

            yield Snapshot(
                url=htmldecode(url),
                timestamp=str(time.timestamp()),
                title=htmldecode(title) or None,
                #tags=None,
                #sources=[html_file.name],
            )

