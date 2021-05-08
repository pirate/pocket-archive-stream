class ScheduledTask(models.Models):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(max_length=128, required=True, unique=True)
    schedule = models.CharField(max_length=32, default='weekly')
    enabled = models.BooleanField(default=True)

    added = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    runs = models.IntegerField(default=0, min_value=0, editable=False)
    last_output = models.CharField(max_length=1024, default='')
    last_start_ts = models.DateTimeField(default=None, null=True, blank=True)
    last_end_ts = models.DateTimeField(default=None, null=True, blank=True)
    
    class Meta:
        abstract = True


class ScheduledAdd(ScheduledTask):
    # main task parameters
    urls = models.TextField(max_length=4096, default='', db_index=True)
    tag = models.ManyToManyField(Tag)
    
    # add behavior flags
    depth = models.IntegerField(min_value=0, max_value=1, default=0)
    resnapshot = models.BooleanField(default=False)
    overwrite = models.BooleanField(default=False)
    index_only = models.BooleanField(default=False)
    update_all = models.BooleanField(default=False)

    extractors = models.CSVField(max_length=256, default='')
    parser = models.CharField(max_length=32, default='auto', choices=PARSER_CHOICES)
    
    @cached_property
    def source_filename(self) -> str:
        return f'{self.short_id}-scheduled-import.txt'

    def save(self, **kwargs):
        self.urls_str = self.urls_str.strip()

        assert self.urls_str or self.update_all, (
            'you must either pass some urls to import, or set the task to update'
            ' all existing URLS, otherwise it will do nothing')

        assert self.schedule in ('hour', 'day', 'week', 'month', 'year') or isValidCronSchedule(self.schedule)

        assert not (self.overwrite and self.resnapshot), (
            'When snapshotting a URL thats previously snapshotted, '
            'you may either overwrite it, or re-snapshot it, but not both')

        # some more validation here...
        save_text_as_source(self.urls, filename=self.source_filename)
        self.schedule()

    def schedule(self):
        method = 'system crontab' if USE_SYSTEM_CRON else 'archivebox scheduler'
        print(f'[*] Scheduling import {self.name} to run every {self.schedule} using {method}')

        # TODO: decide whether to support system cron at all, or enforce python scheduler
        if USE_SYSTEM_CRON:
            schedule(
                every=self.schedule,
                depth=self.depth,
                overwrite=self.overwrite,
                import_path=self.urls_source_file_path,
            )
        else:
            # TODO: update yacron/celery/huey/APScheduler etc. whatever scheduler we choose
            pass

    def run(self, force: bool=False):
        if (not self.enabled) and (not force):
            print(f'[!] Refusing to run scheduled import that is disabled: {self.name}')
            return None

        # TODO: enforce "at most once" or "at least once" concurrency somehow
        
        print(f'[+] [{timezone.now().isoformat()}] Running scheduled import {self.name}...\n')

        self.last_start_ts = timezone.now()
        self.runs += 1
        try:
            all_links, new_links = add(
                urls=Path(self.urls_source_file_path),
                tag=self.tag,
                depth=self.depth,
                update_all=self.update_all,
                index_only=self.index_only,
                overwrite=self.overwrite,
                extractors=self.extractors,
                parser=self.parser,
            )
            self.last_output = f'SUCCEEDED: {len(new_links)} new snapshots ({len(all_links)} total snapshots)'
        except BaseException as err:
            self.last_output = f'FAILED: {err.__class__.__name__} {err}'

        self.last_end_ts = timezone.now()
        self.save()
