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

import csv
import logging
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

import tests.fixtures.quiz_archiver as fixtures
from archiveworker.api.moodle import QuizArchiverMoodleAPI
from archiveworker.api.worker import ArchiveJobDescriptor
from archiveworker.moodle_quiz_archive_worker import start_processing_threads
from archiveworker.quiz_archive import FlatArchiveOrganizer, HirarchicalArchiveOrganizer
from archiveworker.quiz_archive_job import QuizArchiveJob
from archiveworker.type import JobStatus
from archiveworker.workspace import Workspace
from config import Config
from .conftest import client, TestUtils, MoodleAPIMockBase


class TestQuizArchiveJob:

    ARCHIVE_OPTIONS_MATRIX = [
        pytest.param(False, False, id="flatten=false,hash=false"),
        pytest.param(False, True, id="flatten=false,hash=true"),
        pytest.param(True, False, id="flatten=true,hash=false"),
        pytest.param(True, True, id="flatten=true,hash=true"),
    ]

    @classmethod
    def setup_class(cls):
        cls.wait_for_readysignal_orig = Config.REPORT_WAIT_FOR_READY_SIGNAL
        Config.REPORT_WAIT_FOR_READY_SIGNAL = False
        cls.pdfa_conversion_orig = Config.PDFA_CONVERSION
        Config.PDFA_CONVERSION = False

    @classmethod
    def teardown_class(cls):
        Config.REPORT_WAIT_FOR_READY_SIGNAL = cls.wait_for_readysignal_orig
        Config.PDFA_CONVERSION = cls.pdfa_conversion_orig

    @staticmethod
    def _get_un_expected_archive_entries(
        jobjson: dict,
        moodle_api_mock: MoodleAPIMockBase
    ) -> tuple[list[tuple[str, int, int]], list[str]]:
        """
        Generates expected and unexpected archive artifacts given a job description.

        :param jobjson: Job API request
        :param moodle_api_mock: Mock of the Moodle API client
        :return: List of tuples with filepath, minsize, maxsize of expected files and list with filepaths of unexpected files
        """

        archive_flatten = jobjson['archive_flatten']
        archive_filehashes = jobjson['archive_filehashes']

        organizer = FlatArchiveOrganizer() if archive_flatten else HirarchicalArchiveOrganizer()
        workspace = Workspace()

        def _build_archive_entry(organizer, artifact) -> str:
            path, name = organizer.organize(artifact)
            return f'{path}/{name}'.lstrip('/')

        expected_entries = []
        unexpected_entries = []

        task_attempts = jobjson['task_archive_quiz_attempts']
        if task_attempts is not None:

            for attempt_id in task_attempts['attemptids']:

                attempt_mock_directory, attempt_mock_name, _, _ = moodle_api_mock.get_attempt_data(None, None, attempt_id)
                attempt = workspace.attempt(attempt_id, attempt_mock_name, attempt_mock_directory)

                html_artifact = attempt.html_report(f'{attempt_mock_name}.html')
                html_artifact_path = _build_archive_entry(organizer, html_artifact)
                html_artifact_hash_path = html_artifact_path + '.sha256'
                if task_attempts['keep_html_files']:
                    expected_entries.append((html_artifact_path, 200*1024, 2000*1024))
                    if archive_filehashes:
                        expected_entries.append((html_artifact_hash_path, 64, 64))
                    else:
                        unexpected_entries.append(html_artifact_hash_path)
                else:
                    unexpected_entries.append(html_artifact_path)
                    unexpected_entries.append(html_artifact_hash_path)


                pdf_artifact = attempt.pdf_report(f'{attempt_mock_name}.pdf')
                pdf_artifact_path = _build_archive_entry(organizer, pdf_artifact)
                expected_entries.append((pdf_artifact_path, 200*1024, 2000*1024))
                pdf_artifact_hash_path = pdf_artifact_path + '.sha256'
                if archive_filehashes:
                    expected_entries.append((pdf_artifact_hash_path, 64, 64))
                else:
                    unexpected_entries.append(pdf_artifact_hash_path)

            metadata_artifact = workspace.file('attempts_metadata.csv')
            metadata_artifact_path = _build_archive_entry(organizer, metadata_artifact)
            if task_attempts['fetch_metadata']:
                expected_entries.append((metadata_artifact_path, 128, 10*1024))
            else:
                unexpected_entries.append(metadata_artifact_path)
            metadata_artifact_hash_path = metadata_artifact_path + '.sha256'
            if archive_filehashes:
                expected_entries.append((metadata_artifact_hash_path, 64, 64))
            else:
                unexpected_entries.append(metadata_artifact_hash_path)

        task_backups = jobjson['task_moodle_backups']
        if task_backups is not None:
            for backup in task_backups:
                backup_artifact = workspace.backup(backup['filename'])
                backup_artifact_path = _build_archive_entry(organizer, backup_artifact)
                expected_entries.append((backup_artifact_path, 500*1024, 10000*1024))
                backup_artifact_hash_path = backup_artifact_path + '.sha256'
                if archive_filehashes:
                    expected_entries.append((backup_artifact_hash_path, 64, 64))
                else:
                    unexpected_entries.append(backup_artifact_hash_path)

        return expected_entries, unexpected_entries

    def test_equality(self) -> None:
        """
        Tests that the job descriptor equality check works as expected.

        :return: None
        """
        descriptor = ArchiveJobDescriptor(
            moodle_api=QuizArchiverMoodleAPI(
                base_url="http://localhost",
                ws_rest_url="http://localhost/webservice/rest/server.php",
                ws_upload_url="http://localhost/webservice/upload.php",
                wstoken="opensesame",
                max_upload_bytes=536870912 # 512 MiB
            ),
            archive_filename="foo",
            archive_flatten=False,
            archive_filehashes=True,
            quizid=1,
            cmid=1,
            courseid=1
        )
        job1 = QuizArchiveJob(uuid.uuid1(), descriptor)
        job2 = QuizArchiveJob(uuid.uuid1(), descriptor)

        assert job1 == job1, 'The same job should be equal to itself'
        assert job2 == job2, 'The same job should be equal to itself'
        assert job1 == str(job1.get_id()), 'Job should be equal to its UUID'

        assert job1 != job2, 'Different jobs should not be equal'
        assert job1 != str(job2.get_id()), 'Job should not be equal to another UUID'
        assert job1 != object(), 'Job should not be equal to an object of different type'

    @pytest.mark.timeout(5)
    def test_basic_job_processing_flow(self, client) -> None:
        """
        Tests processing of "empty" jobs (no actual data to archive nor backups
        to store).

        :param client: Flask test client
        :return: None
        """
        with fixtures.empty_job.MoodleAPIMock():
            # Create new job but do not process it yet
            jobs = []
            for i in range(3):
                r = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
                assert r.status_code == 200
                assert r.json['status'] == JobStatus.AWAITING_PROCESSING
                jobs.append(r.json['jobid'])

            # Start processing thread
            start_processing_threads(1)

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

    @pytest.mark.timeout(5)
    def test_job_timeout(self, client) -> None:
        """
        Tests that an overdue job is terminated and marked as failed.

        :return: None
        """
        Config.REQUEST_TIMEOUT_SEC = 0

        # Enqueue a job
        with fixtures.empty_job.MoodleAPIMock():
            r = client.post('/archive', json=fixtures.empty_job.ARCHIVE_API_REQUEST)
            assert r.status_code == 200
            jobid = r.json['jobid']

            # Start processing thread
            start_processing_threads(1)

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                print(r.json['status'])
                if r.json['status'] == JobStatus.TIMEOUT:
                    break
                if r.json['status'] == JobStatus.FINISHED:
                    assert False, 'Job should have timed out'

    @pytest.mark.timeout(30)
    @pytest.mark.parametrize("archive_flatten, archive_filehashes", ARCHIVE_OPTIONS_MATRIX)
    def test_archive_full_quiz(self, client, archive_flatten, archive_filehashes) -> None:
        """
        Tests the full quiz archiving process with all tasks enabled. Data is
        taken from the reference quiz fixture.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_quiz_full.MoodleAPIMock() as mock:
            # Create job and process it
            jobjson = deepcopy(fixtures.reference_quiz_full.ARCHIVE_API_REQUEST)
            jobjson['archive_flatten'] = archive_flatten
            jobjson['archive_filehashes'] = archive_filehashes
            r = client.post('/archive', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

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
            assert job_artifact.is_file(), 'Uploaded artifact is not a valid file'
            assert os.path.getsize(job_artifact) > 1024*1024, 'Artifact size too small (<1 MB)'
            assert os.path.getsize(job_artifact) < 1024*1024*10, 'Artifact size too large (>10 MB)'

            # Extract artifact and validate contents
            with zipfile.ZipFile(job_artifact, 'r') as zipf:

                expected_artifacts, unexpected_artifacts = self._get_un_expected_archive_entries(jobjson, mock)

                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                    # Validate presence of expected artifacts
                    for expected_artifact in expected_artifacts:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, expected_artifact[0]), expected_artifact[1],expected_artifact[2])

                    # Validate absence of unexpected artifacts
                    for unexpected_artifact in unexpected_artifacts:
                        assert not os.path.exists(os.path.join(tempdir, unexpected_artifact)), 'Unexpected attempts artifact file in archive'

                    # Validate attempts metadata file
                    attemptsmetafile = os.path.join(tempdir, 'attempts_metadata.csv')
                    TestUtils.assert_is_file_with_size(attemptsmetafile, 128, 10*1024)
                    if archive_filehashes:
                        TestUtils.assert_is_file_with_size(attemptsmetafile+'.sha256', 64, 64)

                    attemptids_to_find = jobjson['task_archive_quiz_attempts']['attemptids'].copy()
                    with open(attemptsmetafile, 'r') as f:
                        for row in csv.DictReader(f, skipinitialspace=True):
                            for key in ["attemptid", "userid", "username", "firstname", "lastname", "timestart", "timefinish", "attempt", "state", "path"]:
                                assert key in row, f'Key "{key}" missing in attempts metadata csv file'

                            assert int(row['attemptid']) in attemptids_to_find, 'Unexpected attempt ID in attempts metadata csv file'
                            attemptids_to_find.remove(int(row['attemptid']))

                    assert len(attemptids_to_find) == 0, 'Not all attempt IDs found in attempt metadata csv file'

    @pytest.mark.timeout(5)
    @pytest.mark.parametrize("archive_flatten, archive_filehashes", ARCHIVE_OPTIONS_MATRIX)
    def test_archive_backups_only(self, client, archive_flatten, archive_filehashes) -> None:
        """
        Tests the quiz archiving process with only the backup task enabled. No
        attempt PDFs should be generated here.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_quiz_single_attempt.MoodleAPIMock() as mock:
            # Create job and process it
            jobjson = deepcopy(fixtures.reference_quiz_single_attempt.ARCHIVE_API_REQUEST)
            jobjson['archive_flatten'] = archive_flatten
            jobjson['archive_filehashes'] = archive_filehashes
            jobjson['task_archive_quiz_attempts'] = None
            r = client.post('/archive', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            # Validate that an artifact was uploaded
            job_uploads = mock.get_uploaded_files()
            job_artifact = job_uploads[1]['file']
            assert job_artifact.is_file(), 'Uploaded artifact is not a valid file'

            # Extract artifact and validate contents
            with zipfile.ZipFile(job_artifact, 'r') as zipf:
                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                expected_artifacts, unexpected_artifacts = self._get_un_expected_archive_entries(jobjson, mock)

                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                    # Validate presence of expected artifacts
                    for expected_artifact in expected_artifacts:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, expected_artifact[0]), expected_artifact[1],expected_artifact[2])

                    # Validate absence of unexpected artifacts
                    for unexpected_artifact in unexpected_artifacts:
                        assert not os.path.exists(os.path.join(tempdir, unexpected_artifact)), 'Unexpected attempts artifact file in archive'

                    # # Validate attempt reports
                    # assert not os.path.exists(os.path.join(tempdir, 'attempts/')), 'Unexpected attempts directory in artifact'
                    # assert not os.path.exists(os.path.join(tempdir, 'attempts_metadata.csv')), 'Unexpected attempts metadata file in artifact'

                    # # Validate Moodle backups
                    # for backup in fixtures.reference_quiz_single_attempt.ARCHIVE_API_REQUEST['task_moodle_backups']:
                    #     backupfile = os.path.join(tempdir, 'backups/', backup['filename'])
                    #     TestUtils.assert_is_file_with_size(backupfile, 500*1024, 10000*1024)
                    #     TestUtils.assert_is_file_with_size(backupfile+'.sha256', 64, 64, invert=not archive_filehashes)

    @pytest.mark.timeout(30)
    @pytest.mark.parametrize("archive_flatten, archive_filehashes", ARCHIVE_OPTIONS_MATRIX)
    def test_archive_attempts_only(self, client, archive_flatten, archive_filehashes) -> None:
        """
        Tests the quiz archiving process with only the attempt archiving task.
        No Moodle backups should be included in the artifact.

        Also tests that the keep_html_files option is respected.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_quiz_single_attempt_no_backups.MoodleAPIMock() as mock:
            # Create job and process it
            jobjson = deepcopy(fixtures.reference_quiz_single_attempt_no_backups.ARCHIVE_API_REQUEST)
            jobjson['archive_flatten'] = archive_flatten
            jobjson['archive_filehashes'] = archive_filehashes
            r = client.post('/archive', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            # Validate that an artifact was uploaded
            job_uploads = mock.get_uploaded_files()
            job_artifact = job_uploads[1]['file']
            assert job_artifact.is_file(), 'Uploaded artifact is not a valid file'

            # Extract artifact and validate contents
            with zipfile.ZipFile(job_artifact, 'r') as zipf:
                expected_artifacts, unexpected_artifacts = self._get_un_expected_archive_entries(jobjson, mock)

                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                    # Validate presence of expected artifacts
                    for expected_artifact in expected_artifacts:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, expected_artifact[0]), expected_artifact[1],expected_artifact[2])

                    # Validate absence of unexpected artifacts
                    for unexpected_artifact in unexpected_artifacts:
                        assert not os.path.exists(os.path.join(tempdir, unexpected_artifact)), 'Unexpected attempts artifact file in archive'

    @pytest.mark.timeout(30)
    @pytest.mark.parametrize("archive_flatten, archive_filehashes", ARCHIVE_OPTIONS_MATRIX)
    def test_archive_name_collision(self, client, archive_flatten, archive_filehashes) -> None:
        """
        Tests the quiz archiving process with two attempts that have a folder
        name pattern that results in identical folder and attempt names for both
        attempts. Both should be present in the archive and not overwrite each
        other.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_quiz_two_attempts_foldername_collision.MoodleAPIMock() as mock:
            # Create job and process it
            jobjson = deepcopy(fixtures.reference_quiz_two_attempts_foldername_collision.ARCHIVE_API_REQUEST)
            jobjson['archive_flatten'] = archive_flatten
            jobjson['archive_filehashes'] = archive_filehashes
            r = client.post('/archive', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            # Validate that an artifact was uploaded
            job_uploads = mock.get_uploaded_files()
            job_artifact = job_uploads[1]['file']
            assert job_artifact.is_file(), 'Uploaded artifact is not a valid file'

            # Extract artifact and validate contents
            with zipfile.ZipFile(job_artifact, 'r') as zipf:
                expected_artifacts, unexpected_artifacts = self._get_un_expected_archive_entries(jobjson, mock)

                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                    # Validate presence of expected artifacts
                    for expected_artifact in expected_artifacts:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, expected_artifact[0]), expected_artifact[1],expected_artifact[2])

                    # Validate absence of unexpected artifacts
                    for unexpected_artifact in unexpected_artifacts:
                        assert not os.path.exists(os.path.join(tempdir, unexpected_artifact)), 'Unexpected attempts artifact file in archive'


                    # Validate attempts metadata file
                    csvpath = os.path.join(tempdir, 'attempts_metadata.csv')

                    attemptidstofind = jobjson['task_archive_quiz_attempts']['attemptids'].copy()
                    expected_artifacts_paths = [*next(iter(zip(*expected_artifacts)))]
                    with open(csvpath, 'r') as f:
                        for row in csv.DictReader(f, skipinitialspace=True):
                            assert int(row['attemptid']) in attemptidstofind, 'Unexpected attempt ID in attempts metadata csv file'
                            attemptidstofind.remove(int(row['attemptid']))

                            # Ensure that the path points to one of the actual attempt dirs
                            assert row['path'] in expected_artifacts_paths, 'Attempt path in metadata does not point to an actual attempt directory'

    @pytest.mark.timeout(30)
    def test_archive_attempts_image_resize(self, client, caplog) -> None:
        """
        Tests the quiz archiving process with image resizing enabled. The
        reference quiz fixture contains images that should be resized.

        :param client: Flask test client
        :param caplog: Pytest log capturing fixture
        :return: None
        """
        with fixtures.reference_quiz_single_attempt.MoodleAPIMock() as mock:
            # Setup logging
            caplog.set_level(logging.DEBUG)

            # Create job and process it
            jobjson = deepcopy(fixtures.reference_quiz_single_attempt_no_backups.ARCHIVE_API_REQUEST)
            jobjson['task_archive_quiz_attempts']['image_optimize'] = {
                'width': 64,
                'height': 64,
                'quality': 85
            }
            jobjson['task_archive_quiz_attempts']['keep_html_files'] = False
            r = client.post('/archive', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            # Ensure that the image resize task was executed
            assert '-> Resizing image' in caplog.text
            assert '-> Replacing image' in caplog.text
            assert '-> Compressing PDF content streams on page' in caplog.text

    @pytest.mark.timeout(30)
    @pytest.mark.skipif(shutil.which("gs") is None and Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH is None, reason="test requires ghostscript binary to be installed")
    def test_pdfa_conversion(self, client, caplog) -> None:
        """
        Tests the quiz archiving process with PDF/A conversion enabled.

        :param client: Flask test client
        :param caplog: Pytest log capturing fixture
        :return: None
        """
        with fixtures.reference_quiz_single_attempt.MoodleAPIMock() as mock:
            # Setup logging
            caplog.set_level(logging.DEBUG)

            # Setup PDFA conversion
            Config.PDFA_CONVERSION = True
            if Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH is None:
                Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH = shutil.which("gs")

            # Create job and process it
            r = client.post('/archive', json=fixtures.reference_quiz_single_attempt_no_backups.ARCHIVE_API_REQUEST)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            # Wait for job to be processed
            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            # Ensure that the PDF/A conversion task was executed
            assert 'PDF/A conversion' in caplog.text
            assert 'Creating ghostscript subprocess' in caplog.text
            assert 'Processing pages 1 through' in caplog.text
