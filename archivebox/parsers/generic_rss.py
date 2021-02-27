__package__ = 'archivebox.parsers'


from typing import IO, Iterable
from datetime import datetime

from django.db.models import Model

from ..util import (
    htmldecode,
    enforce_types,
    str_between,
)

@enforce_types
def parse_generic_rss_export(rss_file: IO[str], **_kwargs) -> Iterable[Model]:
    """Parse RSS XML-format files into links"""
    from core.models import Snapshot

    rss_file.seek(0)
    items = rss_file.read().split('<item>')
    items = items[1:] if items else []
    for item in items:
        # example item:
        # <item>
        # <title><![CDATA[How JavaScript works: inside the V8 engine]]></title>
        # <category>Unread</category>
        # <link>https://blog.sessionstack.com/how-javascript-works-inside</link>
        # <guid>https://blog.sessionstack.com/how-javascript-works-inside</guid>
        # <pubDate>Mon, 21 Aug 2017 14:21:58 -0500</pubDate>
        # </item>

        trailing_removed = item.split('</item>', 1)[0]
        leading_removed = trailing_removed.split('<item>', 1)[-1].strip()
        rows = leading_removed.split('\n')

        def get_row(key):
            return [r for r in rows if r.strip().startswith('<{}>'.format(key))][0]

        url = str_between(get_row('link'), '<link>', '</link>')
        ts_str = str_between(get_row('pubDate'), '<pubDate>', '</pubDate>')
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %z")
        title = str_between(get_row('title'), '<![CDATA[', ']]').strip()

        yield Snapshot(
            url=htmldecode(url),
            timestamp=str(time.timestamp()),
            title=htmldecode(title) or None,
            #tags=None,
            #sources=[rss_file.name],
        )
