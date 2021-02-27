__package__ = 'archivebox.extractors'

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from django.db.models import Model

from ..index.schema import ArchiveResult, ArchiveOutput, ArchiveError
from ..util import (
    enforce_types,
    download_url,
    htmldecode,
)
from ..config import (
    TIMEOUT,
    CHECK_SSL_VALIDITY,
    SAVE_TITLE,
    CURL_BINARY,
    CURL_ARGS,
    CURL_VERSION,
    CURL_USER_AGENT,
)
from ..logging_util import TimedProgress



HTML_TITLE_REGEX = re.compile(
    r'<title.*?>'                      # start matching text after <title> tag
    r'(.[^<>]+)',                      # get everything up to these symbols
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.UNICODE,
)


class TitleParser(HTMLParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_tag = ""
        self.title_og = ""
        self.inside_title_tag = False

    @property
    def title(self):
        return self.title_tag or self.title_og or None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title" and not self.title_tag:
            self.inside_title_tag = True
        elif tag.lower() == "meta" and not self.title_og:
            attrs = dict(attrs)
            if attrs.get("property") == "og:title" and attrs.get("content"):
                self.title_og = attrs.get("content")

    def handle_data(self, data):
        if self.inside_title_tag and data:
            self.title_tag += data.strip()
    
    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.inside_title_tag = False


# output = '{title}'

@enforce_types
def should_save_title(snapshot: Model, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    # if link already has valid title, skip it
    if not overwrite and snapshot.title and not snapshot.title.lower().startswith('http'):
        return False

    return SAVE_TITLE

def extract_title_with_regex(html):
    match = re.search(HTML_TITLE_REGEX, html)
    output = htmldecode(match.group(1).strip()) if match else None
    return output

@enforce_types
def save_title(snapshot: Model, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """try to guess the page's title from its content"""

    from core.models import Snapshot

    output: ArchiveOutput = None
    cmd = [
        CURL_BINARY,
        *CURL_ARGS,
        '--max-time', str(timeout),
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        snapshot.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        html = download_url(snapshot.url, timeout=timeout)
        try:
            # try using relatively strict html parser first
            parser = TitleParser()
            parser.feed(html)
            output = parser.title
            if output is None:
                raise
        except Exception:
            # fallback to regex that can handle broken/malformed html
            output = extract_title_with_regex(html)
        
        # if title is better than the one in the db, update db with new title
        if isinstance(output, str) and output:
            if not snapshot.title or len(output) >= len(snapshot.title):
                Snapshot.objects.filter(url=snapshot.url,
                                        timestamp=snapshot.timestamp)\
                                .update(title=output)
                snapshot.title = output
        else:
            # if no content was returned, dont save a title (because it might be a temporary error)
            if not html:
                raise ArchiveError('Unable to detect page title')
            # output = html[:128]       # use first bit of content as the title
            output = link.base_url      # use the filename as the title (better UX)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
