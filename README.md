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

You can install this application in several ways, however, the easiest and
preferred way is to use [Docker Compose](#docker-compose).

## Docker Compose

TODO


## Docker

1. Build the Docker image: `docker build -t moodle-quiz-archive-worker:latest .`
2. Run a container: `docker run --rm -it -p 8080:8080 moodle-quiz-archive-worker:latest`

You can change the host port the application is bound to by changing the first
port number in the `-p` argument of the `docker run` command. Example:

```shell
docker run --rm -it -p 9000:8080 moodle-quiz-archive-worker:latest
```

You can change configuration settings by setting the respective environment
variables. Example:

```shell
docker run --rm -it -e QUIZ_ARCHIVER_LOG_LEVEL=DEBUG -p 8080:8080 moodle-quiz-archive-worker:latest
```

For more details and all available configuration parameters see [Configuration](#configuration).


## Manual Installation

1. Install [Python](https://www.python.org/) version >= 3.11
2. Install [Poetry](https://python-poetry.org/): `pip install poetry`
3. Clone this repository: `git clone https://github.com/ngandrass/moodle-quiz-archive-worker`
4. Switch into the repository directory: `cd moodle-quiz-archive-worker`
5. Install app dependencies: `poetry install`
6. Download [playwright](https://playwright.dev/) browser binaries: `poetry run python -m playwright install chromium`
7. Run the application: `poetry run python moodle-quiz-archive-worker.py`

You can change configuration settings by prepending the respective environment
variables. Example:

```shell
QUIZ_ARCHIVER_SERVER_PORT=9000 poetry run python moodle-quiz-archive-worker.py
```

For more details and all available configuration parameters see [Configuration](#configuration).


# Configuration

Configuration parameters are located inside `config.py` and can be overwritten
using the following environment variables:

- `QUIZ_ARCHIVER_SERVER_HOST`: Host to bind to (default=`'0.0.0.0'`)
- `QUIZ_ARCHIVER_SERVER_PORT`: Port to bind to (default=`8080`)
- `QUIZ_ARCHIVER_LOG_LEVEL`: Logging level. One of `'CRITICAL'`, `'FATAL'`, `'ERROR'`, `'WARN'`, `'WARNING'`, `'INFO'`, `'DEBUG'` (default=`'INFO'`)
- `QUIZ_ARCHIVER_QUEUE_SIZE`: Maximum number of jobs to enqueue (default=`8`)
- `QUIZ_ARCHIVER_HISTORY_SIZE`: Maximum number of jobs to remember in job history (default=`128`)
- `QUIZ_ARCHIVER_REQUEST_TIMEOUT_SEC`: Maximum number of seconds a single job is allowed to run before it is terminated (default=`1800`)
- `QUIZ_ARCHIVER_BACKUP_STATUS_RETRY_SEC`: Number of seconds to wait between backup status queries (default=`30?)
- `QUIZ_ARCHIVER_BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES`: Maximum number of bytes Moodle backups are allowed to have (default=`(512 * 10e6)`)
- `QUIZ_ARCHIVER_REPORT_BASE_VIEWPORT_WIDTH`: Width of the viewport on attempt rendering in px (default=`1240`)
 