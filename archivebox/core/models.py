__package__ = 'archivebox.core'

import uuid
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict

from django.db import models, transaction
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.db.models import Case, When, Value, IntegerField

from ..util import parse_date
from ..index.schema import Link
from ..config import CONFIG
from ..system import get_dir_size

#EXTRACTORS = [(extractor[0], extractor[0]) for extractor in get_default_archive_methods()]
EXTRACTORS = [("title", "title"), ("wget", "wget")]
STATUS_CHOICES = [
    ("succeeded", "succeeded"),
    ("failed", "failed"),
    ("skipped", "skipped")
]

try:
    JSONField = models.JSONField
except AttributeError:
    import jsonfield
    JSONField = jsonfield.JSONField

class Tag(models.Model):
    """
    Based on django-taggit model
    """
    name = models.CharField(verbose_name="name", unique=True, blank=False, max_length=100)
    slug = models.SlugField(verbose_name="slug", unique=True, max_length=100)

    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

    def __str__(self):
        return self.name

    def slugify(self, tag, i=None):
        slug = slugify(tag)
        if i is not None:
            slug += "_%d" % i
        return slug

    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
            self.slug = self.slugify(self.name)

            with transaction.atomic():
                slugs = set(
                    type(self)
                    ._default_manager.filter(slug__startswith=self.slug)
                    .values_list("slug", flat=True)
                )

                i = None
                while True:
                    slug = self.slugify(self.name, i)
                    if slug not in slugs:
                        self.slug = slug
                        return super().save(*args, **kwargs)
                    i = 1 if i is None else i+1
        else:
            return super().save(*args, **kwargs)


class Snapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    url = models.URLField(unique=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True)

    title = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    added = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(null=True, blank=True, db_index=True)
    tags = models.ManyToManyField(Tag)

    keys = ('id', 'url', 'timestamp', 'title', 'tags', 'updated', 'base_url')

    def __repr__(self) -> str:
        title = self.title or '-'
        return f'[{self.timestamp}] {self.url[:64]} ({title[:64]})'

    def __str__(self) -> str:
        title = self.title or '-'
        return f'[{self.timestamp}] {self.url[:64]} ({title[:64]})'

    def field_names():
        fields = self._meta.get_field_names()
        exclude = ["tags", "archiveresult"] # Exclude relationships for now
        return [field.name for field in fields if field.name not in exclude]


    @classmethod
    def from_json(cls, info: dict):
        info = {k: v for k, v in info.items() if k in cls.keys}
        if "tags" in info:
            # TODO: Handle tags
            info.pop("tags")
        info.pop("base_url", None) 
        return cls(**info)

    def get_history(self) -> dict:
        """
        Generates the history dictionary out of the stored ArchiveResults
        """
        history_list = self.archiveresult_set.all()
        history = defaultdict(list)
        for history_item in history_list:
            history[history_item.extractor].append(
                {
                    "cmd": history_item.cmd,
                    "cmd_version": history_item.cmd_version,
                    "end_ts": history_item.end_ts.isoformat(),
                    "start_ts": history_item.start_ts.isoformat(),
                    "pwd": history_item.pwd,
                    "output": history_item.output,
                    "schema": "ArchiveResult",
                    "status": history_item.status
                }
            )
        return dict(history)

    def as_json(self, *args) -> dict:
        """
        Returns the snapshot in json format.
        id is converted to str
        history is extracted from ArchiveResult
        """
        args = args or self.keys
        output = {
            key: getattr(self, key)
            if key != 'tags' else self.tags_str()
            for key in args
        }
        if "id" in output.keys():
            output["id"] = str(output["id"])

        output["history"] = self.get_history()
        return output

    def as_csv(self, cols: Optional[List[str]]=None, separator: str=',', ljust: int=0) -> str:
        from ..index.csv import to_csv
        return to_csv(self, cols=cols or self.field_names(), separator=separator, ljust=ljust)

    def as_link(self) -> Link:
        return Link.from_json(self.as_json())

    def as_link_with_details(self) -> Link:
        from ..index import load_link_details
        return load_link_details(self.as_link())

    def tags_str(self) -> str:
        return ','.join(self.tags.order_by('name').values_list('name', flat=True))

    @cached_property
    def bookmarked(self):
        return parse_date(self.timestamp)

    @cached_property
    def bookmarked_date(self) -> Optional[str]:
        from ..util import ts_to_date

        max_ts = (datetime.now() + timedelta(days=30)).timestamp()

        if self.timestamp and self.timestamp.replace('.', '').isdigit():
            if 0 < float(self.timestamp) < max_ts:
                return ts_to_date(datetime.fromtimestamp(float(self.timestamp)))
            else:
                return str(self.timestamp)
        return None

    @cached_property
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

    @cached_property
    def archive_dates(self) -> List[datetime]:
        return [
            result.start_ts
            for result in self.archiveresult_set.all()
        ]

    @cached_property
    def oldest_archive_date(self) -> Optional[datetime]:
        oldest = self.archiveresult_set.all().order_by("-start_ts")[:1]
        if len(oldest) > 0:
            return oldest[0].start_ts

    @cached_property
    def num_outputs(self):
        return self.archiveresult_set.filter(status='succeeded').count()

    @cached_property
    def url_hash(self):
        return self.as_link().url_hash

    @cached_property
    def base_url(self) -> str:
        from ..util import base_url
        return base_url(self.url)

    @cached_property
    def snapshot_dir(self):
        from ..config import CONFIG
        return Path(CONFIG['ARCHIVE_DIR']) / self.timestamp

    @cached_property
    def archive_path(self):
        from ..config import ARCHIVE_DIR_NAME
        return '{}/{}'.format(ARCHIVE_DIR_NAME, self.timestamp)

    @cached_property
    def archive_size(self) -> float:
        try:
            return get_dir_size(self.archive_path)[0]
        except Exception:
            return 0

    @cached_property
    def history(self):
        # TODO: use ArchiveResult for this instead of json
        return self.as_link_with_details().history

    @cached_property
    def latest_title(self):
        if ('title' in self.history
            and self.history['title']
            and (self.history['title'][-1].status == 'succeeded')
            and self.history['title'][-1].output.strip()):
            return self.history['title'][-1].output.strip()
        return None

    @cached_property
    def domain(self) -> str:
        from ..util import domain
        return domain(self.url)

    @cached_property
    def is_static(self) -> bool:
        from ..util import is_static_file
        return is_static_file(self.url)

    @cached_property
    def details(self) -> Dict:
        # TODO: Define what details are, and return them accordingly
        return {"history": {}}

    @property
    def extension(self) -> str:
        from ..util import extension
        return extension(self.url)

    def canonical_outputs(self) -> Dict[str, Optional[str]]:
        """predict the expected output paths that should be present after archiving"""

        from ..extractors.wget import wget_output_path
        canonical = {
            'index_path': 'index.html',
            'favicon_path': 'favicon.ico',
            'google_favicon_path': 'https://www.google.com/s2/favicons?domain={}'.format(self.domain),
            'wget_path': wget_output_path(self),
            'warc_path': 'warc',
            'singlefile_path': 'singlefile.html',
            'readability_path': 'readability/content.html',
            'mercury_path': 'mercury/content.html',
            'pdf_path': 'output.pdf',
            'screenshot_path': 'screenshot.png',
            'dom_path': 'output.html',
            'archive_org_path': 'https://web.archive.org/web/{}'.format(self.base_url),
            'git_path': 'git',
            'media_path': 'media',
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

    def save_tags(self, tags=()):
        tags_id = []
        for tag in tags:
            tags_id.append(Tag.objects.get_or_create(name=tag)[0].id)
        self.tags.clear()
        self.tags.add(*tags_id)


class ArchiveResultManager(models.Manager):
    def indexable(self, sorted: bool = True):
        from ..extractors import ARCHIVE_METHODS_INDEXING_PRECEDENCE
        INDEXABLE_METHODS = [ r[0] for r in ARCHIVE_METHODS_INDEXING_PRECEDENCE ]
        qs = self.get_queryset().filter(extractor__in=INDEXABLE_METHODS,status='succeeded')

        if sorted:
            precedence = [ When(extractor=method, then=Value(precedence)) for method, precedence in ARCHIVE_METHODS_INDEXING_PRECEDENCE ]
            qs = qs.annotate(indexing_precedence=Case(*precedence, default=Value(1000),output_field=IntegerField())).order_by('indexing_precedence')
        return qs


class ArchiveResult(models.Model):
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)
    cmd = JSONField()
    pwd = models.CharField(max_length=256)
    cmd_version = models.CharField(max_length=32, default=None, null=True, blank=True)
    output = models.CharField(max_length=512)
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    extractor = models.CharField(choices=EXTRACTORS, max_length=32)

    objects = ArchiveResultManager()

    def __str__(self):
        return self.extractor

    class Meta:
        ordering = ["-start_ts"]
