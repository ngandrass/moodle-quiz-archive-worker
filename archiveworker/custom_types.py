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
from enum import StrEnum
from typing import List


class WorkerThreadInterrupter:
    """
    Job / Task to queue for interrupting a worker thread
    """
    def execute(self) -> None:
        return


class WorkerStatus(StrEnum):
    """
    Status values that the quiz archive worker can report
    """
    IDLE = 'IDLE'
    ACTIVE = 'ACTIVE'
    BUSY = 'BUSY'
    UNKNOWN = 'UNKNOWN'


class JobStatus(StrEnum):
    """
    Status values a single quiz archive worker job can have
    """
    UNINITIALIZED = 'UNINITIALIZED'
    AWAITING_PROCESSING = 'AWAITING_PROCESSING'
    RUNNING = 'RUNNING'
    WAITING_FOR_BACKUP = 'WAITING_FOR_BACKUP'
    FINALIZING = 'FINALIZING'
    FINISHED = 'FINISHED'
    FAILED = 'FAILED'
    TIMEOUT = 'TIMEOUT'


class BackupStatus(StrEnum):
    """
    Status values a Moodle backup can have
    """
    PENDING = 'E_BACKUP_PENDING'
    FAILED = 'E_BACKUP_FAILED'
    SUCCESS = 'SUCCESS'


class ReportSignal(StrEnum):
    """
    Signals that can be emitted by the report page JS
    """
    READY_FOR_EXPORT = "x-quiz-archiver-page-ready-for-export"
    MATHJAX_FOUND = "x-quiz-archiver-mathjax-found"
    MATHJAX_NOT_FOUND = "x-quiz-archiver-mathjax-not-found"


class JobArchiveRequest:
    """
    Deserialized JSON request for creating an archive job
    """

    API_VERSION = 6

    PAPER_FORMATS = ['A0', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'Letter', 'Legal', 'Tabloid', 'Ledger']

    def __init__(self,
                 api_version: int,
                 moodle_base_url: str,
                 moodle_ws_url: str,
                 moodle_upload_url: str,
                 wstoken: str,
                 courseid: int,
                 cmid: int,
                 quizid: int,
                 archive_filename: str,
                 task_archive_quiz_attempts: any,
                 task_moodle_backups: any):
        if api_version != self.API_VERSION:
            raise ValueError(f'API version mismatch. Expected: {self.API_VERSION}, Got: {api_version}. Please update your quiz-archive-worker!')

        self.api_version = api_version
        self.moodle_base_url = moodle_base_url
        self.moodle_ws_url = moodle_ws_url
        self.moodle_upload_url = moodle_upload_url
        self.wstoken = wstoken
        self.courseid = int(courseid)
        self.cmid = int(cmid)
        self.quizid = int(quizid)
        self.archive_filename = archive_filename
        self.tasks = {
            'archive_quiz_attempts': task_archive_quiz_attempts,
            'archive_moodle_backups': task_moodle_backups
        }

        if not self._validate_self():
            raise ValueError('Validation of request payload failed')

    @staticmethod
    def from_json(json: dict) -> 'JobArchiveRequest':
        """
        Creates a new JobArchiveRequest object from a JSON dictionary

        :param json: Deserialized request JSON
        :return: JobArchiveRequest object
        """
        # Catch API version missmatch early
        if 'api_version' not in json:
            raise ValueError('API version missing in request payload')
        if not isinstance(json['api_version'], int):
            raise ValueError('API version must be an integer')
        if json['api_version'] != JobArchiveRequest.API_VERSION:
            raise ValueError(f'API version mismatch. Expected: {JobArchiveRequest.API_VERSION}, Got: {json["api_version"]}. Please update your quiz-archive-worker!')

        return JobArchiveRequest(**json)

    def _validate_self(self):
        """Validates this object based on current values"""
        if not isinstance(self.moodle_base_url, str) or self.moodle_base_url is None:
            return False

        if not isinstance(self.moodle_ws_url, str) or self.moodle_ws_url is None:
            return False

        if not isinstance(self.moodle_upload_url, str) or self.moodle_upload_url is None:
            return False

        if not isinstance(self.wstoken, str) or self.wstoken is None:
            return False

        if not isinstance(self.courseid, int) or self.courseid < 0:
            return False

        if not isinstance(self.cmid, int) or self.cmid < 0:
            return False

        if not isinstance(self.quizid, int) or self.quizid < 0:
            return False

        if not isinstance(self.archive_filename, str) or self.archive_filename is None:
            return False
        else:
            # Do not allow paths
            if not os.path.basename(self.archive_filename) == self.archive_filename:
                return False

            # Do not allow forbidden characters
            if any(c in self.archive_filename for c in ["\0", "\\", "/", ":", "*", "?", "\"", "<", ">", "|", "."]):
                return False

        if self.tasks['archive_quiz_attempts']:
            if not isinstance(self.tasks['archive_quiz_attempts']['attemptids'], List):
                return False
            if not isinstance(self.tasks['archive_quiz_attempts']['sections'], object):
                return False
            if not isinstance(self.tasks['archive_quiz_attempts']['fetch_metadata'], bool):
                return False
            if not isinstance(self.tasks['archive_quiz_attempts']['paper_format'], str) or self.tasks['archive_quiz_attempts']['paper_format'] not in self.PAPER_FORMATS:
                return False
            if not isinstance(self.tasks['archive_quiz_attempts']['keep_html_files'], bool):
                return False
            if not isinstance(self.tasks['archive_quiz_attempts']['filename_pattern'], str) or self.tasks['archive_quiz_attempts']['filename_pattern'] is None:
                return False
            if not isinstance(self.tasks['archive_quiz_attempts']['image_optimize'], object) and not self.tasks['archive_quiz_attempts']['image_optimize'] is False:
                return False
            if isinstance(self.tasks['archive_quiz_attempts']['image_optimize'], object) and self.tasks['archive_quiz_attempts']['image_optimize'] is not False:
                if not isinstance(self.tasks['archive_quiz_attempts']['image_optimize']['width'], int) or self.tasks['archive_quiz_attempts']['image_optimize']['width'] < 1:
                    return False
                if not isinstance(self.tasks['archive_quiz_attempts']['image_optimize']['height'], int) or self.tasks['archive_quiz_attempts']['image_optimize']['height'] < 1:
                    return False
                if not isinstance(self.tasks['archive_quiz_attempts']['image_optimize']['quality'], int) or not 0 <= self.tasks['archive_quiz_attempts']['image_optimize']['quality'] <= 100:
                    return False

        if self.tasks['archive_moodle_backups']:
            if not isinstance(self.tasks['archive_moodle_backups'], List):
                return False
            for backup in self.tasks['archive_moodle_backups']:
                for key in ['backupid', 'filename', 'file_download_url']:
                    if key not in backup:
                        return False

        return True
