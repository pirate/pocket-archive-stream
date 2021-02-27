__package__ = 'archivebox.parsers'


import re

from typing import IO, Iterable, Optional
from datetime import datetime

from django.db.models import Model

from ..util import (
    htmldecode,
    enforce_types,
    URL_REGEX,
)
from html.parser import HTMLParser
from urllib.parse import urljoin


class HrefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href":
                    self.urls.append(value)


@enforce_types
def parse_generic_html_export(html_file: IO[str], root_url: Optional[str]=None, **_kwargs) -> Iterable[Model]:
    """Parse Generic HTML for href tags and use only the url (support for title coming later)"""
    from core.models import Snapshot

    html_file.seek(0)
    for line in html_file:
        parser = HrefParser()
        # example line
        # <li><a href="http://example.com/ time_added="1478739709" tags="tag1,tag2">example title</a></li>
        parser.feed(line)
        for url in parser.urls:
            if root_url:
                # resolve relative urls /home.html -> https://example.com/home.html
                url = urljoin(root_url, url)
            
            for archivable_url in re.findall(URL_REGEX, url):
                yield Snapshot(
                    url=htmldecode(archivable_url),
                    timestamp=str(datetime.now().timestamp()),
                    title=None,
                    #tags=None,
                    #sources=[html_file.name],
                )
