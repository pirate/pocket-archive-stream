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
def parse_wallabag_atom_export(rss_file: IO[str], **_kwargs) -> Iterable[Model]:
    """Parse Wallabag Atom files into links"""
    from core.models import Snapshot

    rss_file.seek(0)
    entries = rss_file.read().split('<entry>')[1:]
    for entry in entries:
        # example entry:
        # <entry>
        #       <title><![CDATA[Orient Ray vs Mako: Is There Much Difference? - iknowwatches.com]]></title>
        #       <link rel="alternate" type="text/html"
        #              href="http://wallabag.drycat.fr/view/14041"/>
        #       <link rel="via">https://iknowwatches.com/orient-ray-vs-mako/</link>
        #       <id>wallabag:wallabag.drycat.fr:milosh:entry:14041</id>
        #       <updated>2020-10-18T09:14:02+02:00</updated>
        #       <published>2020-10-18T09:13:56+02:00</published>
        #                   <category term="montres" label="montres" />
        #                       <content type="html" xml:lang="en">
        # </entry>

        trailing_removed = entry.split('</entry>', 1)[0]
        leading_removed = trailing_removed.strip()
        rows = leading_removed.split('\n')

        def get_row(key):
            return [r.strip() for r in rows if r.strip().startswith('<{}'.format(key))][0]

        title = str_between(get_row('title'), '<title><![CDATA[', ']]></title>').strip()
        url = str_between(get_row('link rel="via"'), '<link rel="via">', '</link>')
        ts_str = str_between(get_row('published'), '<published>', '</published>')
        time = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")
        try:
            tags = str_between(get_row('category'), 'label="', '" />')
        except Exception:
            tags = None

        yield Snapshot(
            url=htmldecode(url),
            timestamp=str(time.timestamp()),
            title=htmldecode(title) or None,
            #tags=tags or '',
            #sources=[rss_file.name],
        )
