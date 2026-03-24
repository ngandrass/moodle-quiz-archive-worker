# Moodle Quiz Archive Worker
# Copyright (C) 2026 Niels Gandraß <niels@gandrass.de>
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

from unittest.mock import patch
from uuid import UUID

from .conftest import client

import tests.fixtures.quiz_archiver as fixtures
from config import Config
from archiveworker.type import JobStatus, WorkerStatus
from archiveworker.moodle_quiz_archive_worker import start_processing_threads, current_jobs_mutex


class TestBasicAPI:
    """
    Tests for basic API endpoint behavior
    """

    def test_moodle_api_connection_probe_failure(self, client):
        """
        Tests that the API rejects the job when the Moodle API connection probe fails

        :param client: Flask test client
        :return: None
        """
        response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)

        assert response.status_code == 400
        assert 'Could not establish a connection to Moodle webservice API' in response.json['error']


class TestBasicAPIWithMockedMoodleAPI:
    """
    Tests for basic API endpoint behavior with mocked Moodle API
    """

    @classmethod
    def setup_class(cls):
        cls.parallel_jobs_orig = Config.PARALLEL_JOBS
        Config.PARALLEL_JOBS = 2

        cls.mocks = {
            'check_connection': patch('archiveworker.api.moodle.QuizArchiverMoodleAPI.check_connection', return_value=True),
        }

        for m in cls.mocks.values():
            m.start()

    @classmethod
    def teardown_class(cls):
        for m in cls.mocks.values():
            m.stop()

        Config.PARALLEL_JOBS = cls.parallel_jobs_orig

    def test_index(self, client):
        """
        Tests the index / informational endpoint
        :param client: Flask test client
        :return: None
        """
        response = client.get('/')

        assert response.status_code == 200
        assert response.json['app'] == Config.APP_NAME
        assert response.json['version'] == Config.VERSION

    def test_version(self, client):
        """
        Tests the version endpoint

        :param client: Flask test client
        :return: None
        """
        response = client.get('/version')

        assert response.status_code == 200
        assert response.json['version'] == Config.VERSION

    def test_status_idle(self, client):
        """
        Tests that the worker reports as idle when there are no running jobs
        :param client: Flask test client
        :return: None
        """
        response = client.get('/status')

        assert response.status_code == 200
        assert response.json['status'] == WorkerStatus.IDLE
        assert response.json['queue_len'] == 0
        assert response.json['queue_max'] == Config.QUEUE_SIZE
        assert response.json['jobs_max'] == Config.PARALLEL_JOBS
        assert response.json['jobs_processing'] is None

    def test_status_active(self, client):
        """
        Tests that the worker reports as active when at least one job is running

        :param client: Flask test client
        :return: None
        """
        # Ensure that the worker is idle before starting
        response = client.get('/status')
        assert response.status_code == 200
        assert response.json['status'] == WorkerStatus.IDLE

        # Enqueue a job
        response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
        assert response.status_code == 200

        # Start processing threads
        start_processing_threads(Config.PARALLEL_JOBS)

        # Check that the worker reports as active
        response = client.get('/status')
        assert response.status_code == 200
        assert response.json['status'] == WorkerStatus.ACTIVE
        assert response.json['queue_len'] == 0
        assert response.json['jobs_processing'] is not None
        assert len(response.json['jobs_processing']) == 1

    def test_status_busy(self, client):
        """
        Tests that the worker reports as busy when the queue is full

        :param client: Flask test client
        :return: None
        """
        # Ensure that the worker is idle before starting
        response = client.get('/status')
        assert response.status_code == 200
        assert response.json['status'] == WorkerStatus.IDLE

        # Enqueue jobs until all worker threads are busy plus some to queue
        plus_some = 2
        for _ in range(Config.PARALLEL_JOBS + plus_some):
            response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
            assert response.status_code == 200

        # Start processing threads
        start_processing_threads(Config.PARALLEL_JOBS)

        # Check that the worker reports as busy
        response = client.get('/status')
        assert response.status_code == 200
        assert response.json['status'] == WorkerStatus.BUSY
        assert response.json['jobs_processing'] is not None
        assert len(response.json['jobs_processing']) == Config.PARALLEL_JOBS
        assert response.json['queue_len'] == plus_some

    @pytest.mark.timeout(30)
    def test_status_timeout(self, client):
        """
        Tests that the worker timeouts status requests when locked resource is busy

        :param client: Flask test client
        :return: None
        """

        # Lock and keep resource artificially busy
        assert current_jobs_mutex.acquire(False)

        # Check if timeout is handled
        response = client.get('/status')
        assert response.status_code == 503

        # Release artificial lock
        current_jobs_mutex.release()

    def test_job_status(self, client):
        """
        Tests that the worker reports the status of a job

        :param client: Flask test client
        :return: None
        """
        # Create three test jobs
        jobids = []
        for n in range(3):
            response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
            assert response.status_code == 200
            jobids.append(response.json['jobid'])

        # Retrieve status for all test jobs
        for jobid in jobids:
            response = client.get(f'/status/{jobid}')
            assert response.status_code == 200
            assert response.json['status'] == JobStatus.AWAITING_PROCESSING

    def test_job_status_not_found(self, client):
        """
        Tests that the worker reports 404 for an unknown job during status retrieval

        :param client: Flask test client
        :return: None
        """
        response = client.get('/status/00000000-0000-0000-0000-000000000000')
        assert response.status_code == 404
        assert 'not found' in response.json['error']

    def test_queue_job(self, client):
        """
        Tests queueing a basic job

        :param client: Flask test client
        :return: None
        """
        response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
        print(f"Response: {response.json}")

        # Validate basic response structure
        assert response.status_code == 200
        assert response.json['status'] == JobStatus.AWAITING_PROCESSING
        assert response.json['jobid'] is not None

        # Try to parse given jobid as valid UUID
        uuid_obj = UUID(response.json['jobid'])
        assert str(uuid_obj) == response.json['jobid']

    def test_queue_jobs(self, client):
        """
        Tests queueing multiple jobs until the queue has reached its maximum size

        :param client: Flask test client
        :return: None
        """
        for n in range(Config.QUEUE_SIZE):
            print(f"Queueing job {n} ... ", end='')
            response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
            print(f"{response.status_code}.")

            assert response.status_code == 200

    def test_queue_overflowing(self, client):
        """
        Tests queueing a job when the queue is already full

        :param client: Flask test client
        :return: None
        """
        for n in range(Config.QUEUE_SIZE):
            print(f"Queueing job {n} ... ", end='')
            response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
            print(f"{response.status_code}.")

            assert response.status_code == 200, 'Job queueing failed while there should be capacity left.'

        # Try to queue another job
        print(f"Queueing job {Config.QUEUE_SIZE} ... ", end='')
        response = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
        print(f"{response.status_code}.")

        assert response.status_code == 429, 'Job queueing succeeded while the queue should be full.'
        assert 'Maximum number of queued jobs exceeded' in response.json['error']

    def test_queue_job_invalid_api_version(self, client):
        """
        Tests queueing a job with an invalid API version

        :param client: Flask test client
        :return: None
        """
        job = fixtures.empty_job.ARCHIVE_API_REQUEST.copy()
        job['api_version'] = 0

        response = client.post('/archive', json=job)

        assert response.status_code == 400
        assert 'API version mismatch' in response.json['error']

    @pytest.mark.parametrize('key', [
        'moodle_base_url',
        'moodle_ws_url',
        'moodle_upload_url',
        'wstoken',
        'courseid',
        'cmid',
        'quizid',
        'archive_filename',
        'task_archive_quiz_attempts',
        'task_moodle_backups'
    ])
    def test_queue_job_request_missing_parameter(self, client, key):
        """
        Tests queueing a job with an invalid request

        :param client: Flask test client
        :param key: Key to remove from the job request
        :return: None
        """
        job = fixtures.empty_job.ARCHIVE_API_REQUEST.copy()
        job.pop(key)
        response = client.post('/archive', json=job)

        assert response.status_code == 400
        assert 'missing a required parameter' in response.json['error'], 'Missing key in request JSON was not detected correctly'
