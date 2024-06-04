# Moodle Quiz Archive Worker
# Copyright (C) 2024 Niels Gandraß <niels@gandrass.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import pytest

from archiveworker.custom_types import JobArchiveRequest
from archiveworker.moodle_quiz_archive_worker import app as original_app, job_queue, job_history


@pytest.fixture()
def app():
    app = original_app
    app.config.update({
        "TESTING": True,
    })

    # Ensure an empty queue and history on each run
    job_queue.queue.clear()
    job_history.clear()

    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture()
def job_valid_empty():
    return {
        'api_version': JobArchiveRequest.API_VERSION,
        'moodle_base_url': 'http://localhost',
        'moodle_ws_url': 'http://localhost/webservice/rest/server.php',
        'moodle_upload_url': 'http://localhost/webservice/upload.php',
        'wstoken': 'opensesame',
        'courseid': 1,
        'cmid': 1,
        'quizid': 1,
        'archive_filename': 'archive',
        'task_archive_quiz_attempts': None,
        'task_moodle_backups': None,
    }
