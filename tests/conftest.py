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
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Tuple, List, Dict, Union
from unittest.mock import patch
from uuid import UUID

import pytest

from archiveworker.custom_types import JobStatus, BackupStatus, WorkerThreadInterrupter
from archiveworker.moodle_quiz_archive_worker import app as original_app, job_queue, job_history, InterruptableThread
from config import Config


@pytest.fixture()
def app():
    app = original_app
    app.config.update({
        "TESTING": True,
    })

    # Kill all still existing threads
    for t in threading.enumerate():
        if isinstance(t, InterruptableThread):
            print(f"Cleaning up thread: {t.name} ...", end='')
            t.stop()
            job_queue.put_nowait(WorkerThreadInterrupter())
            t.join()
            print(' OK.')

    # Ensure an empty queue and history on each run
    job_queue.queue.clear()
    job_history.clear()

    # Enforce some config values for tests
    Config.UNIT_TESTS_RUNNING = True
    Config.REPORT_WAIT_FOR_READY_SIGNAL = False
    Config.REQUEST_TIMEOUT_SEC = 30

    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


class TestUtils:
    """
    Util function for tests
    """

    @classmethod
    def assert_is_file_with_size(cls, file: Union[str, Path], min_size: int = None, max_size: int = None) -> None:
        """
        Asserts that the file exists and has the expected size.

        :param file: Path to file
        :param min_size: Minimum expected file size in bytes
        :param max_size: Maximum expected file size in bytes
        :return: None
        """
        assert os.path.isfile(file), f"File not found: {file}"

        fsize = os.path.getsize(file)
        if min_size:
            assert fsize >= min_size, f"File size too small: {fsize} bytes (at least {min_size} bytes required)"
        if max_size:
            assert fsize <= max_size, f"File size too large: {fsize} bytes (max {max_size} bytes allowed)"


class MoodleAPIMockBase:
    """
    Base class for Moodle API mocks
    """

    CLS_ROOT = 'archiveworker.moodle_api.MoodleAPI'

    def __init__(self):
        self.upload_tempdir = None
        self.uploaded_files = {}
        self.upload_fileid_ptr = 1
        self.patchers = {
            'check_connection': patch(self.CLS_ROOT+'.check_connection', new=self.check_connection),
            'update_job_status': patch(self.CLS_ROOT+'.update_job_status', new=self.update_job_status),
            'get_backup_status': patch(self.CLS_ROOT+'.get_backup_status', new=self.get_backup_status),
            'get_remote_file_metadata': patch(self.CLS_ROOT+'.get_remote_file_metadata', new=self.get_remote_file_metadata),
            'download_moodle_file': patch(self.CLS_ROOT+'.download_moodle_file', new=self.download_moodle_file),
            'get_attempts_metadata': patch(self.CLS_ROOT+'.get_attempts_metadata', new=self.get_attempts_metadata),
            'get_attempt_data': patch(self.CLS_ROOT+'.get_attempt_data', new=self.get_attempt_data),
            'upload_file': patch(self.CLS_ROOT+'.upload_file', new=self.upload_file),
            'process_uploaded_artifact': patch(self.CLS_ROOT+'.process_uploaded_artifact', new=self.process_uploaded_artifact),
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def __del__(self):
        self.stop()

    def start(self) -> None:
        """
        Start all patchers. Calls to patched functions will be redirected to the
        mock methods, defined in this class.

        :return: None
        """
        self.upload_tempdir = tempfile.TemporaryDirectory()
        self.uploaded_files = {}
        self.upload_fileid_ptr = 1

        for p in self.patchers.values():
            p.start()

    def stop(self) -> None:
        """
        Stop all patchers. Calls to patched functions will be redirected to the
        original methods.

        :return: None
        """
        if self.upload_tempdir:
            self.upload_tempdir.cleanup()
            self.upload_tempdir = None

        for p in self.patchers.values():
            p.stop()

    def get_uploaded_files(self) -> Dict[int, Dict[str, Union[str, Path]]]:
        """
        Retrieves the metadata array with pointers to all uploaded files.

        Note: Files are uploaded to a temporary directory that is deleted when
        the mocking is stopped or this object is destroyed.

        :return: Dict of uploaded files
        """
        return self.uploaded_files

    # v-- API function mocks below --v

    def check_connection(self) -> bool:
        return True

    def update_job_status(self, jobid: UUID, status: JobStatus, statusextras: Dict) -> bool:
        return True

    def get_backup_status(self, jobid: UUID, backupid: str) -> BackupStatus:
        return BackupStatus.SUCCESS

    def get_remote_file_metadata(self, download_url: str) -> Tuple[str, int]:
        return 'application/vnd.moodle.backup', 1048576

    def download_moodle_file(
            self,
            download_url: str,
            target_path: Path,
            target_filename: str,
            sha1sum_expected: str = None,
            maxsize_bytes: int = Config.DOWNLOAD_MAX_FILESIZE_BYTES
    ) -> int:
        raise NotImplementedError('download_moodle_file')

    def get_attempts_metadata(self, courseid: int, cmid: int, quizid: int, attemptids: List[int]) -> List[Dict[str, str]]:
        raise NotImplementedError('get_attempts_metadata')

    def get_attempt_data(
            self,
            courseid: int,
            cmid: int,
            quizid: int,
            attemptid: int,
            sections: dict,
            filenamepattern: str,
            attachments: bool
    ) -> Tuple[str, str, List[Dict[str, str]]]:
        raise NotImplementedError('get_attempt_data')

    def upload_file(self, file: Path) -> Dict[str, str]:
        if not file.is_file():
            raise FileNotFoundError(f'File not found: {file}')

        # Copy file to local tempdir
        pathuuid = uuid.uuid4().hex
        target_path = os.path.join(self.upload_tempdir.name, pathuuid)
        os.makedirs(target_path)

        target_file = Path(os.path.join(target_path, file.name))
        shutil.copy2(file, target_file)

        # Store file metadata and generate Moodle-ish response. The field itemid
        # corresponds to the index inside self.uploaded_files.
        self.uploaded_files[self.upload_fileid_ptr] = {
            'file': target_file,
            'metadata': {
                'component': 'user',
                'contextid': 1,
                'userid': 2,
                'filearea': 'draft',
                'filename': file.name,
                'filepath': '/',
                'itemid': self.upload_fileid_ptr,
            },
        }
        self.upload_fileid_ptr += 1

        return self.uploaded_files[self.upload_fileid_ptr - 1]['metadata']

    def process_uploaded_artifact(
            self,
            jobid: UUID,
            component: str,
            contextid: int,
            userid: int,
            filearea: str,
            filename: str,
            filepath: str,
            itemid: int,
            sha256sum: str
    ) -> bool:
        return True
