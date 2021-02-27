# archivebox init
# archivebox add

import os
import subprocess
from pathlib import Path
import json, shutil
import sqlite3

from archivebox.config import OUTPUT_PERMISSIONS

from .fixtures import *

def test_init(tmp_path, process):
    assert "Initializing a new ArchiveBox collection in this folder..." in process.stdout.decode("utf-8")
    
def test_update(tmp_path, process):
    os.chdir(tmp_path)
    update_process = subprocess.run(['archivebox', 'init'], capture_output=True)
    assert "Updating existing ArchiveBox collection in this folder" in update_process.stdout.decode("utf-8")

def test_add_link(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_WGET": "true"})
    os.chdir(tmp_path)
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]

    assert "index.json" in [x.name for x in archived_item_path.iterdir()]

    with open(archived_item_path / "index.json", "r") as f:
        output_json = json.load(f)
    assert "Example Domain" == output_json['history']['title'][0]['output']

    with open(archived_item_path / "index.html", "r") as f:
        output_html = f.read()
    assert "Example Domain" in output_html


def test_add_link_support_stdin(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_WGET": "true"})
    os.chdir(tmp_path)
    stdin_process = subprocess.Popen(["archivebox", "add"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      env=disable_extractors_dict)
    stdin_process.communicate(input="http://127.0.0.1:8080/static/example.com.html".encode())
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]

    assert "index.json" in [x.name for x in archived_item_path.iterdir()]

    with open(archived_item_path / "index.json", "r") as f:
        output_json = json.load(f)
    assert "Example Domain" == output_json['history']['title'][0]['output']

def test_correct_permissions_output_folder(tmp_path, process):
    index_files = ['index.sqlite3', 'archive']
    for file in index_files:
        file_path = tmp_path / file
        assert oct(file_path.stat().st_mode)[-3:] == OUTPUT_PERMISSIONS

def test_correct_permissions_add_command_results(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True,
                                  env=disable_extractors_dict)
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    for path in archived_item_path.iterdir():
        assert oct(path.stat().st_mode)[-3:] == OUTPUT_PERMISSIONS

def test_collision_urls_different_timestamps(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True,
                     env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True,
                     env=disable_extractors_dict)
    archive_folders = [x.name for x in (tmp_path / "archive").iterdir()]
    
    first_archive = tmp_path / "archive" / str(min([float(folder) for folder in archive_folders]))
    json_index = str(first_archive / "index.json")
    with open(json_index, "r") as f:
        link_details = json.loads(f.read())

    link_details["url"] = "http://127.0.0.1:8080/static/iana.org.html"
    with open(json_index, "w") as f:
        json.dump(link_details, f)

    init_process = subprocess.run(['archivebox', 'init'], capture_output=True, env=disable_extractors_dict)
    # 1 from duplicated url, 1 from corrupted index
    assert "Skipped adding 2 invalid snapshot data directories" in init_process.stdout.decode("utf-8")
    assert init_process.returncode == 0

def test_collision_timestamps_different_urls(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True,
                     env=disable_extractors_dict)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/iana.org.html'], capture_output=True,
                     env=disable_extractors_dict)
    archive_folders = [x.name for x in (tmp_path / "archive").iterdir()]
    first_archive = tmp_path / "archive" / str(min([float(folder) for folder in archive_folders]))
    archive_folders.remove(first_archive.name)
    json_index = str(first_archive / "index.json")

    with open(json_index, "r") as f:
        link_details = json.loads(f.read())

    link_details["timestamp"] = archive_folders[0]

    with open(json_index, "w") as f:
        json.dump(link_details, f)

    init_process = subprocess.run(['archivebox', 'init'], capture_output=True, env=disable_extractors_dict)
    assert "Skipped adding 1 invalid snapshot data directories" in init_process.stdout.decode("utf-8")
    assert init_process.returncode == 0

def test_orphaned_folders(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True,
                     env=disable_extractors_dict)
    list_process = subprocess.run(["archivebox", "list", "--json", "--with-headers"], capture_output=True)
    with open(tmp_path / "index.json", "wb") as f:
        f.write(list_process.stdout)
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    c.execute("DELETE from core_snapshot")
    conn.commit()
    conn.close()

    init_process = subprocess.run(['archivebox', 'init'], capture_output=True, env=disable_extractors_dict)
    assert "Added 1 orphaned snapshots from deprecated JSON index" in init_process.stdout.decode("utf-8")
    assert init_process.returncode == 0

def test_unrecognized_folders(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True,
                     env=disable_extractors_dict)
    (tmp_path / "archive" / "some_random_folder").mkdir()

    init_process = subprocess.run(['archivebox', 'init'], capture_output=True, env=disable_extractors_dict)
    assert "Skipped adding 1 invalid snapshot data directories" in init_process.stdout.decode("utf-8")
    assert init_process.returncode == 0

def test_tags_migration(tmp_path, disable_extractors_dict):
    
    base_sqlite_path = Path(__file__).parent / 'tags_migration'
    
    if os.path.exists(tmp_path):
        shutil.rmtree(tmp_path)
    shutil.copytree(str(base_sqlite_path), tmp_path)
    os.chdir(tmp_path)

    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, tags from core_snapshot")
    snapshots = c.fetchall()
    snapshots_dict = { sn['id']: sn['tags'] for sn in snapshots}
    conn.commit()
    conn.close()
    
    init_process = subprocess.run(['archivebox', 'init'], capture_output=True, env=disable_extractors_dict)

    conn = sqlite3.connect("index.sqlite3")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT core_snapshot.id, core_tag.name from core_snapshot
        JOIN core_snapshot_tags on core_snapshot_tags.snapshot_id=core_snapshot.id
        JOIN core_tag on core_tag.id=core_snapshot_tags.tag_id
    """)
    tags = c.fetchall()
    conn.commit()
    conn.close()

    for tag in tags:
        snapshot_id = tag["id"]
        tag_name = tag["name"]
        # Check each tag migrated is in the previous field
        assert tag_name in snapshots_dict[snapshot_id]