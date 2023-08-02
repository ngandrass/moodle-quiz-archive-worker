# moodle-quiz-archive-worker

[![Latest Version](https://img.shields.io/github/v/release/ngandrass/moodle-quiz-archive-worker)](https://github.com/ngandrass/moodle-quiz-archive-worker/releases)
[![Maintenance Status](https://img.shields.io/maintenance/yes/9999)](https://github.com/ngandrass/moodle-quiz-archive-worker/)
[![License](https://img.shields.io/github/license/ngandrass/moodle-quiz-archive-worker)](https://github.com/ngandrass/moodle-quiz-archive-worker/blob/master/LICENSE)
[![GitHub Issues](https://img.shields.io/github/issues/ngandrass/moodle-quiz-archive-worker)](https://github.com/ngandrass/moodle-quiz-archive-worker/issues)
[![GitHub Pull Requests](https://img.shields.io/github/issues-pr/ngandrass/moodle-quiz-archive-worker)](https://github.com/ngandrass/moodle-quiz-archive-worker/pulls)
[![Donate with PayPal](https://img.shields.io/badge/PayPal-donate-orange)](https://www.paypal.me/ngandrass)
[![Sponsor with GitHub](https://img.shields.io/badge/GitHub-sponsor-orange)](https://github.com/sponsors/ngandrass)
[![GitHub Stars](https://img.shields.io/github/stars/ngandrass/moodle-quiz-archive-worker?style=social)](https://github.com/ngandrass/moodle-quiz-archive-worker/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/ngandrass/moodle-quiz-archive-worker?style=social)](https://github.com/ngandrass/moodle-quiz-archive-worker/network/members)
[![GitHub Contributors](https://img.shields.io/github/contributors/ngandrass/moodle-quiz-archive-worker?style=social)](https://github.com/ngandrass/moodle-quiz-archive-worker/graphs/contributors)

Quiz archiver service to work in conjunction with the Moodle plugin
[quiz_archiver](https://github.com/ngandrass/moodle-quiz_archiver).

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

- `QUIZ_ARCHIVER_SERVER_HOST`: Host to bind to (default=`'0.0.0.0'`)
- `QUIZ_ARCHIVER_SERVER_PORT`: Port to bind to (default=`8080`)
- `QUIZ_ARCHIVER_LOG_LEVEL`: Logging level. One of `'CRITICAL'`, `'FATAL'`, `'ERROR'`, `'WARN'`, `'WARNING'`, `'INFO'`, `'DEBUG'` (default=`'INFO'`)
- `QUIZ_ARCHIVER_QUEUE_SIZE`: Maximum number of jobs to enqueue (default=`8`)
- `QUIZ_ARCHIVER_HISTORY_SIZE`: Maximum number of jobs to remember in job history (default=`128`)
- `QUIZ_ARCHIVER_REQUEST_TIMEOUT_SEC`: Maximum number of seconds a single job is allowed to run before it is terminated (default=`1800`)
- `QUIZ_ARCHIVER_BACKUP_STATUS_RETRY_SEC`: Number of seconds to wait between backup status queries (default=`30?)
- `QUIZ_ARCHIVER_BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES`: Maximum number of bytes Moodle backups are allowed to have (default=`(512 * 10e6)`)
- `QUIZ_ARCHIVER_REPORT_BASE_VIEWPORT_WIDTH`: Width of the viewport on attempt rendering in px (default=`1240`)
 