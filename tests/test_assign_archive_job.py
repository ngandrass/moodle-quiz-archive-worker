# Moodle Archiving Worker
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

import pytest

import tests.fixtures.archivingmod_assign as fixtures
from archiveworker.api.moodle import ArchivingmodAssignMoodleAPI
from archiveworker.api.worker import ArchiveJobDescriptor
from archiveworker.archive_builder import FlatArchiveOrganizer, HierarchicalArchiveOrganizer
from archiveworker.job import AssignArchiveJob
from archiveworker.type import JobStatus
from archiveworker.worker import start_processing_threads
from archiveworker.workspace import Workspace
from config import Config
from .conftest import client, TestUtils, MoodleAPIMockBase


class TestAssignArchiveJob:

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
    def _get_expected_archive_entries(
        jobjson: dict,
        moodle_api_mock: MoodleAPIMockBase
    ) -> list[str]:
        """
        Generates expected archive entries (path/name, without extension
        variants) given a job description. Attachments are filtered according
        to the job's "attachments" type selection, exactly like the job would.

        :param jobjson: Job API request
        :param moodle_api_mock: Mock of the Moodle API client
        :return: List of expected archive entry base paths (path/name)
        """
        archive_flatten = jobjson['job']['archive_flatten']
        organizer = FlatArchiveOrganizer() if archive_flatten else HierarchicalArchiveOrganizer()
        workspace = Workspace()
        attachment_types = jobjson['job']['attachments']

        def _build_archive_entry(artifact) -> str:
            path, name = organizer.organize(artifact)
            return f'{path}/{name}'.lstrip('/')

        expected_entries = []
        for submissionid in jobjson['job']['submissionids']:
            folder_name, name, _, attachments = moodle_api_mock.get_submission_data(None, None, submissionid)
            submission = workspace.submission(submissionid, name, folder_name)

            if jobjson['job']['keep_html_files']:
                expected_entries.append(_build_archive_entry(submission.html_report(f'{name}.html')))

            expected_entries.append(_build_archive_entry(submission.pdf_report(f'{name}.pdf')))

            for attachment in attachments:
                if not attachment_types.get(attachment['type'], True):
                    continue
                expected_entries.append(_build_archive_entry(
                    submission.attachment(attachment['type'], attachment['filename'])
                ))

        if jobjson['job']['fetch_metadata']:
            expected_entries.append(_build_archive_entry(workspace.file('submissions_metadata.csv')))

        return expected_entries

    @staticmethod
    def _get_all_attachment_archive_entries(
        jobjson: dict,
        moodle_api_mock: MoodleAPIMockBase
    ) -> dict[str, str]:
        """
        Generates archive entries for every attachment the Moodle API would
        return, regardless of the job's "attachments" type selection. Useful
        to assert that disabled attachment types are absent from the archive.

        :param jobjson: Job API request
        :param moodle_api_mock: Mock of the Moodle API client
        :return: Dict mapping archive entry base path (path/name) to attachment type
        """
        archive_flatten = jobjson['job']['archive_flatten']
        organizer = FlatArchiveOrganizer() if archive_flatten else HierarchicalArchiveOrganizer()
        workspace = Workspace()

        entries = {}
        for submissionid in jobjson['job']['submissionids']:
            folder_name, name, _, attachments = moodle_api_mock.get_submission_data(None, None, submissionid)
            submission = workspace.submission(submissionid, name, folder_name)

            for attachment in attachments:
                path, aname = organizer.organize(submission.attachment(attachment['type'], attachment['filename']))
                entries[f'{path}/{aname}'.lstrip('/')] = attachment['type']

        return entries

    def test_equality(self) -> None:
        """
        Tests that the job descriptor equality check works as expected for
        assignment archive jobs.

        :return: None
        """
        descriptor = ArchiveJobDescriptor(
            moodle_api=ArchivingmodAssignMoodleAPI(
                base_url="http://localhost",
                ws_rest_url="http://localhost/webservice/rest/server.php",
                ws_upload_url="http://localhost/webservice/upload.php",
                wstoken="opensesame",
                max_upload_bytes=536870912  # 512 MiB
            ),
            archive_filename="foo",
            archive_flatten=False,
            archive_filehashes=True,
            taskid=1
        )
        job1 = AssignArchiveJob(uuid.uuid1(), descriptor)
        job2 = AssignArchiveJob(uuid.uuid1(), descriptor)

        assert job1 == job1, 'The same job should be equal to itself'
        assert job1 != job2, 'Different jobs should not be equal'
        assert job1 != object(), 'Job should not be equal to an object of different type'

    @pytest.mark.timeout(5)
    def test_job_timeout(self, client) -> None:
        """
        Tests that an overdue job is terminated and marked as failed.

        Note: Unlike the quiz driver, archivingmod_assign requires at least one
        submission ID per job (enforced by ArchiveJobDescriptor.add_task_assign_submissions()),
        so an "empty" job fixture is not possible here. This is not an issue since
        Config.REQUEST_TIMEOUT_SEC = 0 causes the worker thread join to time out
        immediately regardless of job content.

        :return: None
        """
        Config.REQUEST_TIMEOUT_SEC = 0

        with fixtures.reference_assign_full.MoodleAPIMock():
            r = client.post('/archive/archivingmod_assign', json=fixtures.reference_assign_full.ARCHIVE_API_REQUEST)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                if r.json['status'] == JobStatus.TIMEOUT:
                    break
                if r.json['status'] == JobStatus.FINISHED:
                    assert False, 'Job should have timed out'

    @pytest.mark.timeout(30)
    @pytest.mark.parametrize("archive_flatten, archive_filehashes", ARCHIVE_OPTIONS_MATRIX)
    def test_archive_full_assignment(self, client, archive_flatten, archive_filehashes) -> None:
        """
        Tests the full assignment archiving process using the reference
        assignment fixture.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_assign_full.MoodleAPIMock() as mock:
            jobjson = deepcopy(fixtures.reference_assign_full.ARCHIVE_API_REQUEST)
            jobjson['job']['archive_flatten'] = archive_flatten
            jobjson['job']['archive_filehashes'] = archive_filehashes

            r = client.post('/archive/archivingmod_assign', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

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

            # Extract artifact and validate contents
            with zipfile.ZipFile(job_artifact, 'r') as zipf:
                expected_entries = self._get_expected_archive_entries(jobjson, mock)

                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                    for entry in expected_entries:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, entry), 200, 2000 * 1024)
                        if archive_filehashes:
                            TestUtils.assert_is_file_with_size(os.path.join(tempdir, entry + '.sha256'), 64, 64)

    @pytest.mark.timeout(30)
    @pytest.mark.parametrize("archive_flatten", [False, True], ids=["flatten=false", "flatten=true"])
    def test_archive_full_assignment_attachment_filtering(self, client, archive_flatten) -> None:
        """
        Tests that disabling attachment types in the job's "attachments"
        setting causes the worker to skip downloading those attachment types,
        while still downloading the enabled ones.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_assign_full.MoodleAPIMock() as mock:
            jobjson = deepcopy(fixtures.reference_assign_full.ARCHIVE_API_REQUEST)
            jobjson['job']['archive_flatten'] = archive_flatten
            jobjson['job']['attachments'] = {
                "assignment": True,
                "submission": False,
                "feedback": True,
                "annotation": False,
            }

            r = client.post('/archive/archivingmod_assign', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

            while True:
                time.sleep(0.5)
                r = client.get(f'/status/{jobid}')
                assert r.json['status'] != JobStatus.FAILED

                if r.json['status'] == JobStatus.FINISHED:
                    break

            job_uploads = mock.get_uploaded_files()
            assert len(job_uploads) == 1, 'Expected exactly one uploaded artifact'
            job_artifact = job_uploads[1]['file']

            with zipfile.ZipFile(job_artifact, 'r') as zipf:
                archive_names = set(zipf.namelist())
                expected_entries = self._get_expected_archive_entries(jobjson, mock)
                all_attachment_entries = self._get_all_attachment_archive_entries(jobjson, mock)

                # Enabled attachment types (and everything else) must be present
                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)
                    for entry in expected_entries:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, entry), 200, 2000 * 1024)

                # Disabled attachment types must be absent
                for entry, attachment_type in all_attachment_entries.items():
                    if not jobjson['job']['attachments'].get(attachment_type, True):
                        assert entry not in archive_names, \
                            f'Archive contains attachment of disabled type "{attachment_type}": {entry}'

    @pytest.mark.timeout(30)
    @pytest.mark.parametrize("archive_flatten, archive_filehashes", ARCHIVE_OPTIONS_MATRIX)
    def test_archive_name_collision(self, client, archive_flatten, archive_filehashes) -> None:
        """
        Tests the assignment archiving process with two submissions that have a
        folder name pattern that results in identical folder and file names for
        both submissions. Both should be present in the archive and not
        overwrite each other.

        :param client: Flask test client
        :return: None
        """
        with fixtures.reference_assign_foldername_collision.MoodleAPIMock() as mock:
            jobjson = deepcopy(fixtures.reference_assign_foldername_collision.ARCHIVE_API_REQUEST)
            jobjson['job']['archive_flatten'] = archive_flatten
            jobjson['job']['archive_filehashes'] = archive_filehashes

            r = client.post('/archive/archivingmod_assign', json=jobjson)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

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

            # Extract artifact and validate contents
            with zipfile.ZipFile(job_artifact, 'r') as zipf:
                expected_entries = self._get_expected_archive_entries(jobjson, mock)

                with tempfile.TemporaryDirectory() as tempdir:
                    zipf.extractall(tempdir)

                    # Validate presence of both (deduplicated) colliding submission artifacts
                    for entry in expected_entries:
                        TestUtils.assert_is_file_with_size(os.path.join(tempdir, entry), 200, 2000 * 1024)

                    # Validate submissions metadata file
                    csvpath = os.path.join(tempdir, 'submissions_metadata.csv')
                    submissionids_to_find = jobjson['job']['submissionids'].copy()
                    with open(csvpath, 'r') as f:
                        for row in csv.DictReader(f, skipinitialspace=True):
                            assert int(row['submissionid']) in submissionids_to_find, \
                                'Unexpected submission ID in submissions metadata csv file'
                            submissionids_to_find.remove(int(row['submissionid']))

                            # Ensure that the path points to one of the actual (deduplicated) submission artifacts
                            assert row['path'] in expected_entries, \
                                'Submission path in metadata does not point to an actual submission artifact'

                    assert len(submissionids_to_find) == 0, 'Not all submission IDs found in submissions metadata csv file'

    @pytest.mark.timeout(30)
    @pytest.mark.skipif(shutil.which("gs") is None and Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH is None, reason="test requires ghostscript binary to be installed")
    def test_pdfa_conversion(self, client, caplog) -> None:
        """
        Tests the assignment archiving process with PDF/A conversion enabled.

        :param client: Flask test client
        :param caplog: Pytest log capturing fixture
        :return: None
        """
        with fixtures.reference_assign_full.MoodleAPIMock():
            # Setup logging
            caplog.set_level(logging.DEBUG)

            # Setup PDFA conversion
            Config.PDFA_CONVERSION = True
            if Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH is None:
                Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH = shutil.which("gs")

            # Create job and process it
            r = client.post('/archive/archivingmod_assign', json=fixtures.reference_assign_full.ARCHIVE_API_REQUEST)
            assert r.status_code == 200
            jobid = r.json['jobid']

            start_processing_threads(1)

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
