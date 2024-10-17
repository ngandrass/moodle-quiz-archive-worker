# moodle-quiz-archive-worker

[![Latest Version](https://img.shields.io/github/v/release/ngandrass/moodle-quiz-archive-worker)](https://github.com/ngandrass/moodle-quiz-archive-worker/releases)
[![Docker Image Version (latest semver)](https://img.shields.io/docker/v/ngandrass/moodle-quiz-archive-worker/latest?label=Docker%20image)](https://hub.docker.com/r/ngandrass/moodle-quiz-archive-worker)
[![GitHub Workflow Status (with event)](https://img.shields.io/github/actions/workflow/status/ngandrass/moodle-quiz-archive-worker/docker-build-and-push-releases.yml)](https://github.com/ngandrass/moodle-quiz-archive-worker/actions)
[![Maintenance Status](https://img.shields.io/maintenance/yes/9999)](https://github.com/ngandrass/moodle-quiz-archive-worker/)
[![License](https://img.shields.io/github/license/ngandrass/moodle-quiz-archive-worker)](https://github.com/ngandrass/moodle-quiz-archive-worker/blob/master/LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/ngandrass/moodle-quiz-archive-worker)](https://hub.docker.com/r/ngandrass/moodle-quiz-archive-worker)
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
inside a headless webbrowser and exports them to PDF/HTML files, including
MathJax formulas and other complex elements that require JS processing. Moodle
backups can optionally be included in the generated archive. The checksum for
each file within the archive as well as the checksum of the archive itself is
calculated to allow integrity checks.


# Installation

You can install this application in several ways, however, the easiest and
preferred way is to use [Docker Compose](#docker-compose).

Detailed installation and configuration instructions can be found within the
[official documentation](https://quizarchiver.gandrass.de/).

[![Quiz Archiver: Official Documentation](docs/assets/docs-button.png)](https://quizarchiver.gandrass.de/)

If you have problems installing the Quiz Archiver or the Quiz Archive Worker
Service, or you have further questions, please feel free to open an issue within
the [GitHub issue tracker](https://github.com/ngandrass/moodle-quiz_archiver/issues).
         

## Docker Compose

1. Install [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)
2. Create a `docker-compose.yml` inside a `moodle-quiz-archive-worker` folder
   with the following content:
   ```yaml
   services:
     moodle-quiz-archive-worker:
       image: ngandrass/moodle-quiz-archive-worker:latest
       container_name: moodle-quiz-archive-worker
       restart: always
       ports:
         - "8080:8080"
       environment:
         - QUIZ_ARCHIVER_LOG_LEVEL=INFO
   ```
3. From inside the `moodle-quiz-archive-worker` folder, run the application:
   `docker compose up`

You can change the host port by replacing the first port number in the `ports`
argument and configuration values by setting the respective `environment`
variables inside `docker-compose.yml`. For more details and all available
configuration parameters see [Configuration](#configuration).

### Running the application in the background

To run the application in the background, append the `-d` argument:

```shell
docker compose up -d
```

### Removing the application

To remove all created containers, networks and volumes, run the following
command from inside the `moodle-quiz-archive-worker` folder:

```shell
docker compose down
```


## Docker

1. Install [Docker](https://www.docker.com/)
2. Run a container: `docker run -p 8080:8080 ngandrass/moodle-quiz-archive-worker:latest`

You can change the host port the application is bound to by changing the first
port number in the `-p` argument of the `docker run` command. Example:

```shell
docker run -p 9000:8080 moodle-quiz-archive-worker:latest
```

You can change configuration values by setting the respective environment
variables. Example:

```shell
docker run -e QUIZ_ARCHIVER_LOG_LEVEL=DEBUG -p 8080:8080 moodle-quiz-archive-worker:latest
```

For more details and all available configuration parameters see [Configuration](#configuration).


### Building the image locally

1. Install [Docker](https://www.docker.com/)
2. Clone this repository: `git clone https://github.com/ngandrass/moodle-quiz-archive-worker`
3. Switch into the repository directory: `cd moodle-quiz-archive-worker`
4. Build the Docker image: `docker build -t moodle-quiz-archive-worker:latest .`
5. Run a container: `docker run -p 8080:8080 moodle-quiz-archive-worker:latest`


## Manual Installation

1. Install [Python](https://www.python.org/) version >= 3.11
2. Install [Poetry](https://python-poetry.org/): `pip install poetry`
3. Clone this repository: `git clone https://github.com/ngandrass/moodle-quiz-archive-worker`
4. Switch into the repository directory: `cd moodle-quiz-archive-worker`
5. Install app dependencies: `poetry install`
6. Download [playwright](https://playwright.dev/) browser binaries: `poetry run python -m playwright install chromium`
7. Run the application: `poetry run python main.py`

You can change configuration values by prepending the respective environment
variables. Example:

```text
QUIZ_ARCHIVER_SERVER_PORT=9000 poetry run python moodle-quiz-archive-worker.py
```

For more details and all available configuration parameters see [Configuration](#configuration).


# Versioning and Compatibility

The [Quiz Archive Worker](https://github.com/ngandrass/moodle-quiz-archive-worker)
and its corresponding [quiz_archiver Moodle Plugin](https://github.com/ngandrass/moodle-quiz_archiver)
both use [Semantic Versioning 2.0.0](https://semver.org/).

This means that their version numbers are structured as `MAJOR.MINOR.PATCH`. The
Moodle plugin and the archive worker service are compatible as long as they use
the same `MAJOR` version number. Minor and patch versions can differ between the
two components without breaking compatibility.

However, it is **recommended to always use the latest version** of both the
Moodle plugin and the archive worker service to ensure you get all the latest
bug fixes, features, and optimizations.


### Compatibility Examples

| Moodle Plugin | Archive Worker | Compatible |
|---------------|----------------|------------|
| 1.0.0         | 1.0.0          | Yes        |
| 1.2.3         | 1.0.0          | Yes        |
| 1.0.0         | 1.1.2          | Yes        |
| 2.1.4         | 2.0.1          | Yes        |
|               |                |            |
| 2.0.0         | 1.0.0          | No         |
| 1.0.0         | 2.0.0          | No         |
| 2.4.2         | 1.4.2          | No         |


### Development / Testing Versions

Special development versions, used for testing, can be created on demand. Such
development versions are marked by a `+dev-[TIMESTAMP]` suffix, e.g.,
`2.4.2+dev-202201011337`.


# Configuration

Configuration parameters are located inside `config.py` and can be overwritten
using the following environment variables:

- `QUIZ_ARCHIVER_SERVER_HOST`: Host to bind to (default=`'0.0.0.0'`)
- `QUIZ_ARCHIVER_SERVER_PORT`: Port to bind to (default=`8080`)
- `QUIZ_ARCHIVER_LOG_LEVEL`: Logging level. One of `'CRITICAL'`, `'FATAL'`, `'ERROR'`, `'WARN'`, `'WARNING'`, `'INFO'`, `'DEBUG'` (default=`'INFO'`)
- `QUIZ_ARCHIVER_QUEUE_SIZE`: Maximum number of jobs to enqueue (default=`8`)
- `QUIZ_ARCHIVER_HISTORY_SIZE`: Maximum number of jobs to remember in job history (default=`128`)
- `QUIZ_ARCHIVER_STATUS_REPORTING_INTERVAL_SEC`: Number of seconds to wait between job progress updates (default=`15`)
- `QUIZ_ARCHIVER_REQUEST_TIMEOUT_SEC`: Maximum number of seconds a single job is allowed to run before it is terminated (default=`3600`)
- `QUIZ_ARCHIVER_BACKUP_STATUS_RETRY_SEC`: Number of seconds to wait between backup status queries (default=`30`)
- `QUIZ_ARCHIVER_DOWNLOAD_MAX_FILESIZE_BYTES`: Maximum number of bytes a generic Moodle file is allowed to have for downloading (default=`(1024 * 10e6)`)
- `QUIZ_ARCHIVER_BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES`: Maximum number of bytes Moodle backups are allowed to have (default=`(512 * 10e6)`)
- `QUIZ_ARCHIVER_QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES`: Maximum number of bytes a question attachment is allowed to have for downloading (default=`(128 * 10e6)`)
- `QUIZ_ARCHIVER_REPORT_BASE_VIEWPORT_WIDTH`: Width of the viewport on attempt rendering in px (default=`1240`)
- `QUIZ_ARCHIVER_REPORT_PAGE_MARGIN`: Margin (top, bottom, left, right) of the report PDF pages including unit (mm, cm, in, px) (default=`'5mm'`)
- `QUIZ_ARCHIVER_WAIT_FOR_READY_SIGNAL`: Whether to wait for the ready signal from the report page JS before generating the export (default=`True`)
- `QUIZ_ARCHIVER_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC`: Number of seconds to wait for the ready signal from the report page JS before generating the export (default=`30`)
- `QUIZ_ARCHIVER_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT`: Whether to continue with the export if the ready signal was not received in time (default=`False`)
- `QUIZ_ARCHIVER_WAIT_FOR_NAVIGATION_TIMEOUT_SEC`: Number of seconds to wait for the report page to load before aborting the job (default=`30`)
- `QUIZ_ARCHIVER_PREVENT_REDIRECT_TO_LOGIN`: Whether to supress all redirects to Moodle login pages (`/login/*.php`) after page load. This can occur, if dynamic ajax requests fail due to permission errors (default=`True`)
- `QUIZ_ARCHIVER_DEMO_MODE`: Whether the app is running in demo mode. In demo mode, a watermark will be added to all generated PDFs, only a limited number of attempts will be exported per archive job, and only placeholder Moodle backups are included (default=`False`)


# Development

Development dependencies are not installed by default. To install them, run:

```text
poetry install --with dev
```

## Running Unit Tests

Unit tests are handled by `pytest`. To run all test suites execute:

```text
poetry run pytest
```

If you want to see the console output of the tests, as well as logger calls, you
need to specify `-s` (for test output) and `--log-cli-level=DEBUG` (for app
logging). Example:

```text
poetry run pytest -s --log-cli-level=DEBUG
```

## Running Coverage Checks

Code coverage is evaluated using the `coverage` Python package. To run coverage
checks run the following commands:

```text
poetry run coverage run -m pytest
poetry run coverage html
```

The coverage report is then available in the `htmlcov` directory.


## License

2024 Niels Gandraß <niels@gandrass.de>

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program.  If not, see <https://www.gnu.org/licenses/>.
