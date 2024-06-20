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


class Config:

    APP_NAME = "moodle-quiz-archive-worker"
    """Name of this app."""

    VERSION = "1.3.10"
    """Version of this app."""

    LOG_LEVEL = logging.getLevelNamesMapping()[os.getenv('QUIZ_ARCHIVER_LOG_LEVEL', default='INFO')]
    """Python Logger logging level"""

    SERVER_HOST = os.getenv('QUIZ_ARCHIVER_SERVER_HOST', default='0.0.0.0')
    """Host for Flask to bind to"""

    SERVER_PORT = os.getenv('QUIZ_ARCHIVER_SERVER_PORT', default='8080')
    """Port for Flask to listen on"""

    QUEUE_SIZE = int(os.getenv('QUIZ_ARCHIVER_QUEUE_SIZE', default=8))
    """Maximum number of requests that are queued before returning an error."""

    HISTORY_SIZE = int(os.getenv('QUIZ_ARCHIVER_HISTORY_SIZE', default=128))
    """Maximum number of jobs to keep in the history before forgetting about them."""

    REQUEST_TIMEOUT_SEC = int(os.getenv('QUIZ_ARCHIVER_REQUEST_TIMEOUT_SEC', default=(30 * 60)))
    """Number of seconds before execution of a single request is aborted."""

    BACKUP_STATUS_RETRY_SEC = int(os.getenv('QUIZ_ARCHIVER_BACKUP_STATUS_RETRY_SEC', default=30))
    """Number of seconds between status checks of pending backups via the Moodle API"""

    DOWNLOAD_MAX_FILESIZE_BYTES = int(os.getenv('QUIZ_ARCHIVER_DOWNLOAD_MAX_FILESIZE_BYTES', default=(1024 * 10e6)))
    """Maximum number of bytes a generic Moodle file is allowed to have for downloading"""

    BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES = int(os.getenv('QUIZ_ARCHIVER_BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES', default=(512 * 10e6)))
    """Maximum number of bytes a backup is allowed to have for downloading"""

    QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES = int(os.getenv('QUIZ_ARCHIVER_QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES', default=(128 * 10e6)))
    """Maximum number of bytes a question attachment is allowed to have for downloading"""

    REPORT_BASE_VIEWPORT_WIDTH = int(os.getenv('QUIZ_ARCHIVER_REPORT_BASE_VIEWPORT_WIDTH', default=1240))
    """Width of the viewport created for rendering quiz attempts in pixel"""

    REPORT_PAGE_MARGIN = os.getenv('QUIZ_ARCHIVER_REPORT_PAGE_MARGIN', default='5mm')
    """Margin (top, bottom, left, right) of the report PDF pages including unit (mm, cm, in, px)"""

    REPORT_WAIT_FOR_READY_SIGNAL = bool(os.getenv('QUIZ_ARCHIVER_WAIT_FOR_READY_SIGNAL', default=True))
    """Whether to wait for the ready signal from the report page JS before generating the export"""

    REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC = int(os.getenv('QUIZ_ARCHIVER_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC', default=15))
    """Number of seconds to wait for the ready signal from the report page JS before considering the export as failed"""

    REPORT_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT = bool(os.getenv('QUIZ_ARCHIVER_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT', default=False))
    """Whether to continue with the export if the ready signal was not received in time"""

    REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC = int(os.getenv('QUIZ_ARCHIVER_WAIT_FOR_NAVIGATION_TIMEOUT_SEC', default=30))
    """Number of seconds to wait for the report page to load before aborting the job"""

    MOODLE_WSFUNCTION_ARCHIVE = 'quiz_archiver_generate_attempt_report'
    """Name of the Moodle webservice function to call to trigger an quiz attempt export"""

    MOODLE_WSFUNCTION_PROESS_UPLOAD = 'quiz_archiver_process_uploaded_artifact'
    """Name of the Moodle webservice function to call after an artifact was uploaded successfully"""

    MOODLE_WSFUNCTION_GET_BACKUP = 'quiz_archiver_get_backup_status'
    """Name of the Moodle webservice function to call to retrieve information about a backup"""

    MOODLE_WSFUNCTION_UPDATE_JOB_STATUS = 'quiz_archiver_update_job_status'
    """Name of the Moodle webservice function to call to update the status of a job"""

    MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA = 'quiz_archiver_get_attempts_metadata'
    """Name of the Moodle webservice function to call to retrieve metadata about quiz attempts"""
