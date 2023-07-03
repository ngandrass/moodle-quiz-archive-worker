import logging


class Config:

    APP_NAME = "moodle-quiz-archive-worker"
    """Name of this app."""

    VERSION = "0.1.0"
    """Version of this app."""

    LOG_LEVEL = logging.INFO
    """Python Logger logging level"""

    QUEUE_SIZE = 8
    """Maximum number of requests that are queued before returning an error."""

    HISTORY_SIZE = 128
    """Maximum number of jobs to keep in the history before forgetting about them."""

    REQUEST_TIMEOUT_SEC = 30 * 60
    """Number of seconds before execution of a single request is aborted."""

    BACKUP_STATUS_RETRY_SEC = 30
    """Number of seconds between status checks of pending backups via the Moodle API"""

    BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES = 512 * 10e6
    """Maximum number of bytes a backup is allowed to have for downloading"""

    MOODLE_WSFUNCTION_ARCHIVE = 'quiz_archiver_generate_attempt_report'
    """Name of the Moodle webservice function to call to trigger an quiz attempt export"""

    MOODLE_WSFUNCTION_PROESS_UPLOAD = 'quiz_archiver_process_uploaded_artifact'
    """Name of the Moodle webservice function to call after an artifact was uploaded successfully"""

    MOODLE_WSFUNCTION_GET_BACKUP = 'quiz_archiver_get_backup_status'
    """Name of the Moodle webservice function to call to retrieve information about a backup"""

    MOODLE_WSFUNCTION_UPDATE_JOB_STATUS = 'quiz_archiver_update_job_status'
    """Name of the Moodle webservice function to call to update the status of a job"""

    REPORT_BASE_VIEWPORT_WIDTH = 1240
    """Width of the viewport created for rendering quiz attempts in pixel"""
