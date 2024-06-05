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

import csv
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


class TestQuizArchiveJob:

    @classmethod
    def setup_class(cls):
        cls.wait_for_readysignal_orig = Config.REPORT_WAIT_FOR_READY_SIGNAL
        Config.REPORT_WAIT_FOR_READY_SIGNAL = False

    @classmethod
    def teardown_class(cls):
        Config.REPORT_WAIT_FOR_READY_SIGNAL = cls.wait_for_readysignal_orig

    @pytest.mark.timeout(5)
    def test_basic_job_processing_flow(self, client, job_valid_empty):
        with fixtures.empty_job.MoodleAPIMock():
            # Create new job but do not process it yet
            jobs = []
            for i in range(3):
                r = client.post('/archive', json=job_valid_empty)
                assert r.status_code == 200
                assert r.json['status'] == JobStatus.AWAITING_PROCESSING
                jobs.append(r.json['jobid'])

            # Start processing thread
            start_processing_thread()

            # Wait for all jobs to be processed
            while jobs:
                time.sleep(0.2)
                for jobid in jobs:
                    r = client.get(f'/status/{jobid}')
                    if r.json['status'] == JobStatus.FINISHED:
                        jobs.remove(jobid)
                        continue
                    if r.json['status'] not in (JobStatus.RUNNING, JobStatus.AWAITING_PROCESSING):
                        assert False, f"Unexpected status: {r.json['status']}"

    @pytest.mark.timeout(30)
    def test_render_quiz_attempt(self, client):
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

            # Validate that an artifact was uploaded
            job_uploads = mock.get_uploaded_files()
            assert len(job_uploads) == 1, 'Expected exactly one uploaded artifact'
            job_artifact = job_uploads[1]['file']
            assert job_artifact.is_file(), 'Uploaded artifact is not a vailid file'
            assert os.path.getsize(job_artifact) > 1024*1024, 'Artifact size too small (<1 MB)'
            assert os.path.getsize(job_artifact) < 1024*1024*10, 'Artifact size too large (>10 MB)'

            # Extract artifact and validate contents
            with tarfile.open(job_artifact, 'r:gz') as tar:
                with tempfile.TemporaryDirectory() as tempdir:
                    tar.extractall(tempdir, filter=tarfile.tar_filter)

                    # Validate attempt reports
                    for attemptid in fixtures.reference_quiz_full.ARCHIVE_API_REQUEST['task_archive_quiz_attempts']['attemptids']:
                        fbase = os.path.join(tempdir, f'attempts/attempt-{attemptid}/attempt-{attemptid}')
                        TestUtils.assert_is_file_with_size(fbase+'.pdf', 200*1024, 2000*1024)
                        TestUtils.assert_is_file_with_size(fbase+'.html', 200*1024, 2000*1024)
                        TestUtils.assert_is_file_with_size(fbase+'.pdf.sha256', 64, 64)
                        TestUtils.assert_is_file_with_size(fbase+'.html.sha256', 64, 64)

                    # Validate Moodle backups
                    for backup in fixtures.reference_quiz_full.ARCHIVE_API_REQUEST['task_moodle_backups']:
                        backupfile = os.path.join(tempdir, 'backups/', backup['filename'])
                        TestUtils.assert_is_file_with_size(backupfile, 500*1024, 10000*1024)
                        TestUtils.assert_is_file_with_size(backupfile+'.sha256', 64, 64)

                    # Validate attempts metadata file
                    attemptsmetafile = os.path.join(tempdir, 'attempts_metadata.csv')
                    TestUtils.assert_is_file_with_size(attemptsmetafile, 128, 10*1024)
                    TestUtils.assert_is_file_with_size(attemptsmetafile+'.sha256', 64, 64)

                    attemptids_to_find = fixtures.reference_quiz_full.ARCHIVE_API_REQUEST['task_archive_quiz_attempts']['attemptids']
                    with open(attemptsmetafile, 'r') as f:
                        for row in csv.DictReader(f, skipinitialspace=True):
                            for key in ["attemptid", "userid", "username", "firstname", "lastname", "timestart", "timefinish", "attempt", "state", "path"]:
                                assert key in row, f'Key "{key}" missing in attempts metadata csv file'

                            assert int(row['attemptid']) in attemptids_to_find, 'Unexpected attempt ID in attempts metadata csv file'
                            attemptids_to_find.remove(int(row['attemptid']))

                    assert len(attemptids_to_find) == 0, 'Not all attempt IDs found in attempt metadata csv file'
