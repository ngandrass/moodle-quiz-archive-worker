# moodle-quiz-archive-worker

Quiz archiver service to work in conjunction with the Moodle plugin `quiz_archiver`.

This application processes quiz archive jobs. It renders Moodle quiz attempts
inside a headless webbrowser and exports them to PDFs and HTMLs. Moodle backups
can optionally be included in the generated archive. The checksum for each file
within the archive as well as the checksum of the archive itself is calculated
to allow integrity checks.


# Installation

1. Build the Docker image: `docker build -t quiz-archive-worker:latest`
2. Run a container: `docker run quiz-archive-worker:latest`


# Configuration

Configuration parameters are located inside `config.py` and can be overwritten
via the following environment variables:

- `QUIZ_ARCHIVER_LOG_LEVEL`: Logging level. One of `'CRITICAL'`, `'FATAL'`, `'ERROR'`, `'WARN'`, `'WARNING'`, `'INFO'`, `'DEBUG'` (default=`'INFO'`)
- `QUIZ_ARCHIVER_QUEUE_SIZE`: Maximum number of jobs to enqueue (default=`8`)
- `QUIZ_ARCHIVER_HISTORY_SIZE`: Maximum number of jobs to remember in job history (default=`128`)
- `QUIZ_ARCHIVER_REQUEST_TIMEOUT_SEC`: Maximum number of seconds a single job is allowed to run before it is terminated (default=`1800`)
- `QUIZ_ARCHIVER_BACKUP_STATUS_RETRY_SEC`: Number of seconds to wait between backup status queries (default=`30?)
- `QUIZ_ARCHIVER_BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES`: Maximum number of bytes Moodle backups are allowed to have (default=`(512 * 10e6)`)
- `QUIZ_ARCHIVER_REPORT_BASE_VIEWPORT_WIDTH`: Width of the viewport on attempt rendering in px (default=`1240`)
 