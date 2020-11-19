import subprocess

import pytest
from django.urls import reverse
from rest_framework import status

from .fixtures import *

def test_get_snapshots(server, disable_extractors_dict):
    """
    Ensure we can get snaphots from the API.
    """
    url = "http://127.0.0.1:8080/static/example.com.html"
    subprocess.run(
        ["archivebox", "add", "--depth=0", url],
        capture_output=True,
        env=disable_extractors_dict
    )
    response = server.get('/api/snapshots/')

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body.get('count') == 1
    snapshot, = body.get('results')
    assert snapshot.get('url') == url
