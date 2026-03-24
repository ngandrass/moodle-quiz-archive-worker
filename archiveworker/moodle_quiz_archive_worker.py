# Moodle Quiz Archive Worker
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

import logging
import os
import sys
import queue
import re
import threading
import subprocess
import shutil
import uuid
import copy
from collections import deque
from http import HTTPStatus

import waitress
from flask import Flask, make_response, request, jsonify

from archiveworker.api.worker import QuizArchiverArchiveRequest, ArchiveRequest
from archiveworker.api.worker.archivingmod_quiz import ArchivingmodQuizArchiveRequest
from archiveworker.quiz_archive_job import QuizArchiveJob
from archiveworker.type import WorkerStatus, JobStatus, WorkerThreadInterrupter
from config import Config

class InterruptableThread(threading.Thread):
    """
    Custom Thread that allows to be interrupted by a stop event
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stop_event = threading.Event()

    def run(self):
        super().run()

    def stop(self):
        self._stop_event.set()

    def stop_requested(self):
        return self._stop_event.is_set()

app = Flask(__name__)
"""Moodle Quiz Archive Worker REST API"""

worker_threads:list[InterruptableThread] = list()
"""List collecting all references of started worker threads"""

current_jobs:dict[str,QuizArchiveJob] = dict()
"""Mapping of worker thread name to their current job"""

current_jobs_mutex = threading.Lock()
"""Mutex for `current_jobs`'s thread savety"""

job_queue:queue.Queue[QuizArchiveJob|WorkerThreadInterrupter] = queue.Queue(maxsize=Config.QUEUE_SIZE)
"""Queue collecting all pending jobs"""

job_history:deque[QuizArchiveJob] = deque(maxlen=Config.HISTORY_SIZE)
"""List of past submitted jobs up to a maximum history size"""


def queue_processing_loop():
    thread_name = threading.current_thread().name
    app.logger.info(f"Spawned queue worker thread '{thread_name}'")

    while getattr(threading.current_thread(), "do_run", True):
        # Start job execution
        job = job_queue.get()
        if isinstance(job, WorkerThreadInterrupter):
            app.logger.info("Received interrupt signal. Terminating queue worker thread")
            return

        # Reference current job
        with current_jobs_mutex:
            current_jobs[thread_name] = job

        t = InterruptableThread(target=job.execute)
        t.start()
        t.join(Config.REQUEST_TIMEOUT_SEC)

        # Determine if job finished or timeout was reached
        if t.is_alive():
            t.stop()
            app.logger.warning(f'Job {job.get_id()} exceeded runtime limit of {Config.REQUEST_TIMEOUT_SEC} seconds. Request termination ...')
            t.join()
            app.logger.info(f'Job {job.get_id()} terminated gracefully')

        # Remove reference for current job
        with current_jobs_mutex:
            current_jobs[thread_name] = None

    app.logger.info(f"Queue worker thread '{thread_name}' terminated")


def error_response(error_msg: str, status_code):
    return make_response(jsonify({'error': error_msg}), status_code)


@app.get('/')
def handle_index():
    return {
        'app': Config.APP_NAME,
        'version': Config.VERSION
    }


@app.get('/status')
def handle_status():
    current_jobs_copy = None
    if current_jobs_mutex.acquire(blocking = True, timeout = 10):
        current_jobs_copy = copy.deepcopy(current_jobs)
        current_jobs_mutex.release()
    else:
        response = error_response("503 Service Unavailable (could not aquire current jobs lock)", HTTPStatus.SERVICE_UNAVAILABLE)
        response.headers["Retry-After"] = 10
        return response

    jobs_processing = []
    for _, job in current_jobs_copy.items():
        if job is not None:
            jobs_processing.append(job.id)
    occupancy = len(jobs_processing)

    if occupancy == 0:
        status = WorkerStatus.IDLE
    elif occupancy < Config.PARALLEL_JOBS:
        status = WorkerStatus.ACTIVE
    elif occupancy == Config.PARALLEL_JOBS:
        status = WorkerStatus.BUSY
    else:
        status = WorkerStatus.UNKNOWN

    return jsonify({
        'status': status,
        'jobs_processing': jobs_processing,
        'jobs_max': Config.PARALLEL_JOBS,
        'queue_len': job_queue.qsize(),
        'queue_max': Config.QUEUE_SIZE
    }), HTTPStatus.OK


@app.get('/status/<string:jobid>')
def handle_status_jobid(jobid):
    try:
        job = job_history[job_history.index(jobid)]
    except ValueError:
        return error_response(f"Job with requested jobid '{jobid}' was not found", HTTPStatus.NOT_FOUND)

    return jsonify(job.to_json()), HTTPStatus.OK


@app.get('/version')
def handle_version():
    return jsonify({'version': Config.VERSION}), HTTPStatus.OK


@app.post('/archive')  # Legacy endpoint for backwards compatibility
@app.post('/archive/quiz_archiver')
def handle_archive_request_quiz_archiver():
    """
    Handles the archive request for the quiz archiver API
    :return:
    """
    return _handle_archive_request(QuizArchiverArchiveRequest)


@app.post('/archive/archivingmod_quiz')
def handle_archive_request_archivingmod_quiz():
    """
    Handles the archive request for the archivingmod_quiz API
    :return:
    """
    return _handle_archive_request(ArchivingmodQuizArchiveRequest)


def _handle_archive_request(apicls: type[ArchiveRequest]):
    """
    Generic handler for archive requests

    :param apicls: Worker API class to use for deserializing the request
    :return: Response object
    """
    app.logger.debug(f"Received new {apicls.__name__}: {request.data}")

    job = None
    try:
        # Check arguments
        if not request.is_json:
            return error_response('Request payload must be JSON.', HTTPStatus.BAD_REQUEST)
        job_descriptor = apicls.from_raw_request_data(request.get_json())

        # Check queue capacity early
        if job_queue.full():
            return error_response('Maximum number of queued jobs exceeded.', HTTPStatus.TOO_MANY_REQUESTS)

        # Probe moodle API (wstoken validity)
        if not job_descriptor.moodle_api.check_connection():
            return error_response(f'Could not establish a connection to Moodle webservice API at "{job_descriptor.moodle_api.ws_rest_url}" using the provided wstoken.', HTTPStatus.BAD_REQUEST)

        # Enqueue request
        job = QuizArchiveJob(uuid.uuid1(), job_descriptor)
        job_queue.put_nowait(job)  # Actual queue capacity limit is enforced here!
        job_history.append(job)
        job.set_status(JobStatus.AWAITING_PROCESSING, notify_moodle=False)
        app.logger.info(f"Enqueued job {job.get_id()} from {request.remote_addr}")
    except TypeError as e:
        app.logger.debug(f'JSON is technically incomplete or missing a required parameter. TypeError: {str(e)}')
        return error_response('JSON is technically incomplete or missing a required parameter.', HTTPStatus.BAD_REQUEST)
    except KeyError as e:
        app.logger.debug(f'JSON is missing a required parameter: {str(e)}')
        return error_response('JSON is missing a required parameter.', HTTPStatus.BAD_REQUEST)
    except ValueError as e:
        app.logger.debug(f'JSON data is invalid: {str(e)}')
        return error_response(f'JSON data is invalid: {str(e)}', HTTPStatus.BAD_REQUEST)
    except ConnectionError as e:
        app.logger.debug(f'Connection to Moodle webservice failed. Cannot process request. Aborting: {str(e)}')
        return error_response('Connection to Moodle webservice failed. Cannot process request. Aborting.', HTTPStatus.BAD_REQUEST)
    except queue.Full:
        job = None
        app.logger.debug(f'Maximum number of queued jobs exceeded.')
        return error_response('Maximum number of queued jobs exceeded.', HTTPStatus.TOO_MANY_REQUESTS)
    except Exception as e:
        app.logger.debug(f'Invalid request. {str(e)}')
        return error_response(f'Invalid request.', HTTPStatus.BAD_REQUEST)
    finally:
        if not job:
            app.logger.warning(f'Failed to process request to {request.url} from {request.remote_addr}')

    # Return job-ID
    return jsonify({'jobid': job.get_id(), 'status': job.get_status()}), HTTPStatus.OK


def start_processing_threads(n:int=1) -> None:
    """
    Starts n queue processing threads.

    :param n: Number of worker threads to be started. If n < 1 it will be set to 1.

    :return: None
    """

    if n < 1:
        app.logger.warning("Can not start less then 1 worker thread! Starting at least one.")
        n=1

    for i in range(n):
        queue_processing_thread = InterruptableThread(
            target=queue_processing_loop,
            daemon=True,
            name=f'queue_processing_thread_{i}'
        )
        worker_threads.append(queue_processing_thread)
        queue_processing_thread.start()


def stop_processing_threads() -> None:
    """
    Stops all currently running worker threads. Blocks until all threads are stopped.

    :return: None
    """

    for t in worker_threads:
        app.logger.info(f"Signaling thread '{t.name}' to stop ...")
        t.stop()
        job_queue.put_nowait(WorkerThreadInterrupter())

    while len(worker_threads) > 0:
        t = worker_threads[0]
        app.logger.info(f"Waiting for thread '{t.name}' ...")
        t.join()
        app.logger.info(f"Thread '{t.name}' stopped")
        worker_threads.remove(t)


def detect_proxy_settings(envvars) -> None:
    """
    Performs proxy server auto-detection based on environment variables.
    Results are automatically populated into Config object.

    :param envvars: Environment variables from os.environ
    :return: None
    """
    # Prepare config values
    Config.PROXY_SERVER_URL = None
    Config.PROXY_USERNAME = None
    Config.PROXY_PASSWORD = None
    Config.PROXY_BYPASS_DOMAINS = None

    # Try to detect HTTP proxy
    for varname in [
        'QUIZ_ARCHIVER_PROXY_SERVER_URL',
        'http_proxy',
        'HTTP_PROXY',
        'https_proxy',
        'HTTPS_PROXY',
        'all_proxy',
        'ALL_PROXY'
    ]:
        if varname in envvars:
            proxy_url_raw = envvars[varname]

            match = re.search(r"^(?P<protocol>.+?)://((?P<username>.+?):(?P<password>.+?)@)?(?P<address>.+)$", proxy_url_raw)
            if not match:
                app.logger.warning(f'Found proxy server info in ${varname}, but could not parse it as a proxy server URL "{proxy_url_raw}". Skipping ...')
                continue
            else:
                # Validate protocol
                if match.group('protocol') not in ['http', 'https', 'socks', 'socks5']:
                    app.logger.warning(f'Found proxy server info in ${varname}, but protocol "{match.group("protocol")}" is not supported. Skipping ...')
                    continue

                # Set config values for proxy server
                Config.PROXY_SERVER_URL = f"{match.group('protocol')}://{match.group('address')}"
                Config.PROXY_USERNAME = match.group('username')
                Config.PROXY_PASSWORD = match.group('password')

                # Logging
                app.logger.info(
                    f'Detected proxy server in ${varname}, using: {Config.PROXY_SERVER_URL}' +
                    (' (with authentication)' if Config.PROXY_USERNAME else '')
                )
                break

    # Try to detect bypass domains
    for varname in ['no_proxy', 'NO_PROXY']:
        if varname in envvars:
            Config.PROXY_BYPASS_DOMAINS = envvars[varname]
            app.logger.info(f'Detected proxy bypass domains in ${varname}: {Config.PROXY_BYPASS_DOMAINS}')
            app.logger.debug(f'Proxy bypass domains: {Config.PROXY_BYPASS_DOMAINS}')
            break

    # Log if no proxy was detected
    if Config.PROXY_SERVER_URL is None:
        app.logger.debug('No proxy server detected')


def check_for_ghostscript() -> None:
    """
    Checks whether Ghostscript binary is available and runable. Raises specific errors and exceptions if not.

    :raises FileNotFoundError: If configured Ghostscript binary path does not exist or is not a file
    :raises subprocess.TimeoutExpired: If minimal Ghostscript execution times out after 10 seconds
    :raises RuntimeError: If minimal Ghostscript execution failes with status code != 0 or produces unexpected output
    :raises Exception: If minimal Ghostscript execution failes otherwise

    :return: None
    """

    if not os.path.exists(Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH):
        raise FileNotFoundError(f'Missing executable, file "{Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH}" not found')

    if not os.path.isfile(Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH):
        raise FileNotFoundError(f'Missing executable, path "{Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH}" is not a file')

    try:
        proc = subprocess.Popen(
            executable=Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH,
            args='--help',
            shell=True,
            text=True,
            bufsize=1024,
            stdout=subprocess.PIPE,
            stderr=None
        )
        stdout, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired as tex:
        raise tex
    except Exception as ex:
        raise Exception(f"Executing `{Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH} --help` failed with Exception: {ex}")
    finally:
        proc.kill()

    if proc.returncode != 0:
        raise RuntimeError(f'Executing `{Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH} --help` exited with status code != 0')

    output_match_regex = 'GPL\\sGhostscript\\s\\d+\\.\\d+\\.\\d+'
    if re.search(output_match_regex, stdout) is None:
        raise RuntimeError(f'Executing `{Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH} --help` produced unexpected output: Expected to find regex `{output_match_regex}` in stdout `{stdout}` but did not')

def run() -> None:
    """
    Runs the application
    :return: None
    """
    logging.basicConfig(encoding='utf-8', format='[%(asctime)s] | %(levelname)-8s | %(name)s | %(message)s', level=Config.LOG_LEVEL)
    app.logger.info(f'Running {Config.APP_NAME} version {Config.VERSION} on log level {logging.getLevelName(Config.LOG_LEVEL)}')

    # Print demo mode notice if enabled
    if Config.DEMO_MODE:
        app.logger.warning('---> ATTENTION: Running in demo mode! This will add a watermark to all generated PDFs, only a limited number of attempts will be exported per archive job, and only placeholder Moodle backups are included. <---')
        app.logger.info('---> To disable demo mode, set the environment variable QUIZ_ARCHIVER_DEMO_MODE to "False". <---')

    # Handle DEBUG specifics
    if Config.LOG_LEVEL == logging.DEBUG:
        # Dump app config
        app.logger.debug(Config.tostring())

        # Reduce noise from 3rd party library loggers
        logging.getLogger("PIL").setLevel('INFO')

    # Produce warning if TLS cert validation is turned off
    if Config.SKIP_HTTPS_CERT_VALIDATION:
        app.logger.warning('TLS / SSL certificate validation is TURNED OFF! This server will accept any given certificate for HTTPS connections without trying to validate it.')
        app.logger.info('To enable certificate validation set QUIZ_ARCHIVER_SKIP_HTTPS_CERT_VALIDATION to "False" or unset the variable.')

    # Handle proxy settings
    if Config.PROXY_SERVER_URL is not None and Config.PROXY_SERVER_URL.lower() == 'false':
        Config.PROXY_SERVER_URL = None
        app.logger.info('Proxy server auto detection was skipped. No proxy will explicitly be used.')
    else:
        detect_proxy_settings(os.environ)

    # Check for and setup external Ghostscript dependency
    if Config.PDFA_CONVERSION:
        if Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH is None:
            Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH = shutil.which("gs") or ""
            app.logger.debug(f'Auto-detected Ghostscript path: {Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH}')
        try:
            check_for_ghostscript()
        except Exception as ex:
            app.logger.error(f'Checking for external dependency "Ghostscript" failed with Error: {ex}')
            app.logger.error('PDF/A conversion requires Ghostscript. Either install Ghostscript or disable PDF/A conversion. See README for more information.')
            sys.exit(1)

    start_processing_threads(Config.PARALLEL_JOBS)

    waitress.serve(app, host=Config.SERVER_HOST, port=Config.SERVER_PORT)
