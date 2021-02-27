__package__ = 'archivebox.index'

from io import StringIO
from pathlib import Path
from typing import List, Tuple, Iterator
from django.db.models import QuerySet, Model
from django.db import transaction
from datetime import datetime

from .schema import Link
from ..util import enforce_types
from ..config import OUTPUT_DIR


### Main Links Index

@enforce_types
def parse_sql_main_index(out_dir: Path=OUTPUT_DIR) -> Iterator[Link]:
    from core.models import Snapshot

    return (
        Link.from_json(page.as_json(*Snapshot.keys))
        for page in Snapshot.objects.all()
    )

@enforce_types
def remove_from_sql_main_index(snapshots: QuerySet, out_dir: Path=OUTPUT_DIR) -> None:
    with transaction.atomic():
        snapshots.delete()

@enforce_types
def write_snapshot_to_index(snapshot: Model):
    from core.models import Snapshot
    try:
        timestamp = Snapshot.objects.get(url=snapshot.url).timestamp
    except Snapshot.DoesNotExist:
        timestamp = snapshot.timestamp
        if not timestamp:
            timestamp = str(datetime.now().timestamp())
        while Snapshot.objects.filter(timestamp=timestamp).exists():
            print("the timestamp is: ", timestamp)
            timestamp = str(float(timestamp) + 1.0)

    snapshot.timestamp = timestamp
    snapshot.save()
    return snapshot


@enforce_types
def write_sql_main_index(snapshots: List[Model], out_dir: Path=OUTPUT_DIR) -> None:
    with transaction.atomic():
        for snapshot in snapshots:
            write_snapshot_to_index(snapshot)
            

@enforce_types
def write_sql_snapshot_details(snapshot: Model, out_dir: Path=OUTPUT_DIR) -> None:
    from core.models import Snapshot

    with transaction.atomic():
        try:
            snap = Snapshot.objects.get(url=snapshot.url)
        except Snapshot.DoesNotExist:
            snap = write_snapshot_to_index(snapshot)
        snap.title = snapshot.title

        # TODO: If there are actual tags, this will break
        #tag_set = (
        #    set(tag.strip() for tag in (snapshot.tags.all() or '').split(','))
        #)
        #tag_list = list(tag_set) or []

        snap.save()
        #snap.save_tags(tag_list)
        return snap



@enforce_types
def list_migrations(out_dir: Path=OUTPUT_DIR) -> List[Tuple[bool, str]]:
    from django.core.management import call_command
    out = StringIO()
    call_command("showmigrations", list=True, stdout=out)
    out.seek(0)
    migrations = []
    for line in out.readlines():
        if line.strip() and ']' in line:
            status_str, name_str = line.strip().split(']', 1)
            is_applied = 'X' in status_str
            migration_name = name_str.strip()
            migrations.append((is_applied, migration_name))

    return migrations

@enforce_types
def apply_migrations(out_dir: Path=OUTPUT_DIR) -> List[str]:
    from django.core.management import call_command
    null, out = StringIO(), StringIO()
    call_command("makemigrations", interactive=False, stdout=null)
    call_command("migrate", interactive=False, stdout=out)
    out.seek(0)

    return [line.strip() for line in out.readlines() if line.strip()]

@enforce_types
def get_admins(out_dir: Path=OUTPUT_DIR) -> List[str]:
    from django.contrib.auth.models import User
    return User.objects.filter(is_superuser=True)
