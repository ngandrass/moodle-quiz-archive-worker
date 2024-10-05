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

import logging
import os
import tarfile
import tempfile
import time

import pytest

from archiveworker.custom_types import JobStatus
from archiveworker.moodle_quiz_archive_worker import start_processing_thread
from config import Config
from .conftest import client, TestUtils
import tests.fixtures as fixtures


class TestDemoMode:

    @classmethod
    def setup_class(cls):
        cls.wait_for_readysignal_orig = Config.REPORT_WAIT_FOR_READY_SIGNAL
        Config.REPORT_WAIT_FOR_READY_SIGNAL = False
        Config.DEMO_MODE = True

    @classmethod
    def teardown_class(cls):
        Config.REPORT_WAIT_FOR_READY_SIGNAL = cls.wait_for_readysignal_orig
        Config.DEMO_MODE = False

    @pytest.mark.timeout(30)
    def test_archive_full_quiz_demomode(self, client, caplog) -> None:
        """
        Tests the full quiz archiving process with all tasks enabled. Data is
        taken from the reference quiz fixture.

        :param client: Flask test client
        :param caplog: Pytest log capturing fixture
        :return: None
        """
        caplog.set_level(logging.INFO)

        with fixtures.reference_quiz_full.MoodleAPIMock() as mock:
            # Create job and process it
            r = client.post('/archive', json=fixtures.reference_quiz_full.ARCHIVE_API_REQUEST)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_thread()

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            # Ensure that demo mode was logged
            assert "Demo mode: Only processing" in caplog.text
            assert "Demo mode: Skipping download of backup" in caplog.text

            # Validate that an artifact was uploaded
            job_uploads = mock.get_uploaded_files()
            assert len(job_uploads) == 1, 'Expected exactly one uploaded artifact'
            job_artifact = job_uploads[1]['file']
            assert job_artifact.is_file(), 'Uploaded artifact is not a valid file'

            # Extract artifact and validate contents
            with tarfile.open(job_artifact, 'r:gz') as tar:
                with tempfile.TemporaryDirectory() as tempdir:
                    tar.extractall(tempdir, filter=tarfile.tar_filter)

                    # Validate attempt reports exist
                    for attemptid in fixtures.reference_quiz_full.ARCHIVE_API_REQUEST['task_archive_quiz_attempts']['attemptids']:
                        fbase = os.path.join(tempdir, f'attempts/attempt-{attemptid}/attempt-{attemptid}')
                        TestUtils.assert_is_file_with_size(fbase+'.pdf', 200*1024, 2000*1024)

                    # Validate Moodle backups are placeholders
                    for backup in fixtures.reference_quiz_full.ARCHIVE_API_REQUEST['task_moodle_backups']:
                        backupfile = os.path.join(tempdir, 'backups/', backup['filename'])
                        TestUtils.assert_is_file_with_size(backupfile, 64, 1024)

                        with open(backupfile, 'r') as f:
                            assert "DEMO MODE" in f.read()
