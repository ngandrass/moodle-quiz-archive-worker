# Moodle Quiz Archive Worker
# Copyright (C) 2025 Niels Gandraß <niels@gandrass.de>
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


def parse_env_variable(name, default=None, valtype=None) -> None | bool | int | str:
    """
    Parses an environment variable and returns it cast to the desired type.
    Undefined variables will return the default value.

    :param name: Name of the environment variable to evaluate
    :param default: Default to return if the variable is not set
    :param valtype: Force return type. Pass None for automatic type detection
    :return: Parsed value
    """
    # Detect unset variables
    value = os.getenv(name, default=None)
    if value is None:
        return default

    # Forced type casts
    if valtype is bool:
        return value.lower() in ['true', '1']
    if valtype is int:
        return int(value)
    if valtype is str:
        return value

    # Automatic type detection
    if value.lower() in ['true', 'false']:
        return value.lower() == 'true'
    if value.lstrip('-+').isdigit():
        return int(value)

    # String fallback
    return value


class Config:

    APP_NAME = "moodle-quiz-archive-worker"
    """Name of this app"""

    VERSION = "3.1.0"
    """Version of this app"""

    LOG_LEVEL = logging.getLevelNamesMapping()[parse_env_variable('QUIZ_ARCHIVER_LOG_LEVEL', default='INFO', valtype=str)]
    """Python Logger logging level"""

    DEMO_MODE = parse_env_variable('QUIZ_ARCHIVER_DEMO_MODE', default=False, valtype=bool)
    """Whether the app is running in demo mode. In demo mode, a watermark will be added to all generated PDFs, only a limited number of attempts will be exported per archive job, and only placeholder Moodle backups are included."""

    UNIT_TESTS_RUNNING = False
    """Whether unit tests are currently running. This should always be kept at `False` and is only changed by pytest."""

    SERVER_HOST = parse_env_variable('QUIZ_ARCHIVER_SERVER_HOST', default='0.0.0.0', valtype=str)
    """Host for Flask to bind to"""

    SERVER_PORT = parse_env_variable('QUIZ_ARCHIVER_SERVER_PORT', default='8080', valtype=int)
    """Port for Flask to listen on"""

    SKIP_HTTPS_CERT_VALIDATION = parse_env_variable('QUIZ_ARCHIVER_SKIP_HTTPS_CERT_VALIDATION', default=False, valtype=bool)
    """Whether to skip validation of TLS / SSL certs for all HTTPS connections. WARNING: If set to true, invalid certificates are accepted without error."""

    PROXY_SERVER_URL = parse_env_variable('QUIZ_ARCHIVER_PROXY_SERVER_URL', default=None, valtype=str)
    """URL of the proxy server to use for all playwright requests. HTTP and SOCKS proxies are supported. If not set, auto-detection will be performed. If set to false, no proxy will be used."""

    PROXY_USERNAME = None
    """Optional username to authenticate at the proxy server. Will be populated based on PROXY_SERVER_URL."""

    PROXY_PASSWORD = None
    """Optional password to authenticate at the proxy server. Will be populated based on PROXY_SERVER_URL."""

    PROXY_BYPASS_DOMAINS = parse_env_variable('QUIZ_ARCHIVER_PROXY_BYPASS_DOMAINS', default=None, valtype=str)
    """Comma-separated list of domains that should always be accessed directly, bypassing the proxy"""

    QUEUE_SIZE = parse_env_variable('QUIZ_ARCHIVER_QUEUE_SIZE', default=8, valtype=int)
    """Maximum number of requests that are queued before returning an error."""

    HISTORY_SIZE = parse_env_variable('QUIZ_ARCHIVER_HISTORY_SIZE', default=128, valtype=int)
    """Maximum number of jobs to keep in the history before forgetting about them."""

    STATUS_REPORTING_INTERVAL_SEC = parse_env_variable('QUIZ_ARCHIVER_STATUS_REPORTING_INTERVAL_SEC', default=15, valtype=int)
    """Number of seconds to wait between job progress updates"""

    REQUEST_TIMEOUT_SEC = parse_env_variable('QUIZ_ARCHIVER_REQUEST_TIMEOUT_SEC', default=(60 * 60), valtype=int)
    """Number of seconds before execution of a single request is aborted."""

    BACKUP_STATUS_RETRY_SEC = parse_env_variable('QUIZ_ARCHIVER_BACKUP_STATUS_RETRY_SEC', default=30, valtype=int)
    """Number of seconds between status checks of pending backups via the Moodle API"""

    DOWNLOAD_MAX_FILESIZE_BYTES = parse_env_variable('QUIZ_ARCHIVER_DOWNLOAD_MAX_FILESIZE_BYTES', default=int(1024 * 10e6), valtype=int)
    """Maximum number of bytes a generic Moodle file is allowed to have for downloading"""

    BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES = parse_env_variable('QUIZ_ARCHIVER_BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES', default=int(512 * 10e6), valtype=int)
    """Maximum number of bytes a backup is allowed to have for downloading"""

    QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES = parse_env_variable('QUIZ_ARCHIVER_QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES', default=int(128 * 10e6), valtype=int)
    """Maximum number of bytes a question attachment is allowed to have for downloading"""

    REPORT_BASE_VIEWPORT_WIDTH = parse_env_variable('QUIZ_ARCHIVER_REPORT_BASE_VIEWPORT_WIDTH', default=1240, valtype=int)
    """Width of the viewport created for rendering quiz attempts in pixel"""

    REPORT_PAGE_MARGIN = parse_env_variable('QUIZ_ARCHIVER_REPORT_PAGE_MARGIN', default='5mm', valtype=str)
    """Margin (top, bottom, left, right) of the report PDF pages including unit (mm, cm, in, px)"""

    REPORT_WAIT_FOR_READY_SIGNAL = parse_env_variable('QUIZ_ARCHIVER_WAIT_FOR_READY_SIGNAL', default=True, valtype=bool)
    """Whether to wait for the ready signal from the report page JS before generating the export"""

    REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC = parse_env_variable('QUIZ_ARCHIVER_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC', default=30, valtype=int)
    """Number of seconds to wait for the ready signal from the report page JS before considering the export as failed"""

    REPORT_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT = parse_env_variable('QUIZ_ARCHIVER_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT', default=False, valtype=bool)
    """Whether to continue with the export if the ready signal was not received in time"""

    REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC = parse_env_variable('QUIZ_ARCHIVER_WAIT_FOR_NAVIGATION_TIMEOUT_SEC', default=30, valtype=int)
    """Number of seconds to wait for the report page to load before aborting the job"""

    PREVENT_REDIRECT_TO_LOGIN = parse_env_variable('QUIZ_ARCHIVER_PREVENT_REDIRECT_TO_LOGIN', default=True, valtype=bool)
    """Whether to supress all redirects to Moodle login pages (`/login/*.php`) after page load. This can occur, if dynamic ajax requests due to with permission errors."""


    @staticmethod
    def tostring() -> str:
        """
        Dumps the full configuration to a string.

        :return: Configuration as string
        """
        ret = "Configuration:"
        for key, value in vars(Config).items():
            if not (key.startswith('_') or key == 'tostring'):
                ret += f"\n  {key} => {value}"

        return ret
