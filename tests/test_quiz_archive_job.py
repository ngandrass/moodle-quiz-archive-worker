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

import time

import pytest

from archiveworker.custom_types import JobStatus
from archiveworker.moodle_quiz_archive_worker import start_processing_thread
from .conftest import client
import tests.fixtures as fixtures


class TestQuizArchiveJob:

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
        with fixtures.reference_quiz_full.MoodleAPIMock():
            # Create job and process it
            r = client.post('/archive', json=fixtures.reference_quiz_full.ARCHIVE_API_REQUEST)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_thread()

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                if r.json['status'] == JobStatus.FINISHED:
                    break
