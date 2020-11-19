import os
import time
import subprocess

import pytest
import requests

@pytest.fixture
def process(tmp_path):
    os.chdir(tmp_path)
    process = subprocess.run(['archivebox', 'init'], capture_output=True)
    return process

@pytest.fixture
def disable_extractors_dict():
    env = os.environ.copy()
    env.update({
        "USE_WGET": "false",
        "USE_SINGLEFILE": "false",
        "USE_READABILITY": "false",
        "USE_MERCURY": "false",
        "SAVE_PDF": "false",
        "SAVE_SCREENSHOT": "false",
        "SAVE_DOM": "false",
        "SAVE_HEADERS": "false",
        "USE_GIT": "false",
        "SAVE_MEDIA": "false",
        "SAVE_ARCHIVE_DOT_ORG": "false"
    })
    return env

class Server:
    base: str
    process: subprocess.Popen
    
    def start(self, base="0.0.0.0:8000"):
        self.base = base
        self.process = subprocess.Popen(["archivebox", "server", self.base])

        count = 0

        while not self._server_started():
            if count > 10:
                self.stop()
                raise Exception('Server not started in 10s')

            time.sleep(1)
            count += 1

    def stop(self):
        if self.process is not None:
            self.process.kill()

    def _server_started(self):
        try:
            response = self.get('/')
            return response.status_code == 200
        except requests.exceptions.ConnectionError:
            return False

    def get(self, url):
        return requests.get(f'http://{self.base}{url}')

@pytest.fixture
def server(tmp_path, process):
    server = Server()
    server.start()

    yield server

    server.stop()
