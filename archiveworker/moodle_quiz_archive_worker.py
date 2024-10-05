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
import queue
import threading
import uuid
from http import HTTPStatus
from collections import deque

import waitress
from flask import Flask, make_response, request, jsonify

from config import Config
from .moodle_api import MoodleAPI
from .quiz_archive_job import QuizArchiveJob
from .custom_types import WorkerStatus, JobArchiveRequest, JobStatus, WorkerThreadInterrupter

app = Flask(__name__)
job_queue = queue.Queue(maxsize=Config.QUEUE_SIZE)
job_history = deque(maxlen=Config.HISTORY_SIZE)


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


def queue_processing_loop():
    app.logger.info("Spawned queue worker thread")

    while getattr(threading.current_thread(), "do_run", True):
        # Start job execution
        job = job_queue.get()
        if isinstance(job, WorkerThreadInterrupter):
            app.logger.info("Received interrupt signal. Terminating queue worker thread")
            return

        t = InterruptableThread(target=job.execute)
        t.start()
        t.join(Config.REQUEST_TIMEOUT_SEC)

        # Determine if job finished or timeout was reached
        if t.is_alive():
            t.stop()
            app.logger.warning(f'Job {job.get_id()} exceeded runtime limit of {Config.REQUEST_TIMEOUT_SEC} seconds. Request termination ...')
            t.join()
            app.logger.info(f'Job {job.get_id()} terminated gracefully')

    app.logger.info("Terminating queue worker thread")


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
    if job_queue.empty():
        status = WorkerStatus.IDLE
    elif job_queue.qsize() < Config.QUEUE_SIZE:
        status = WorkerStatus.ACTIVE
    elif job_queue.full():
        status = WorkerStatus.BUSY
    else:
        status = WorkerStatus.UNKNOWN

    return jsonify({
        'status': status,
        'queue_len': job_queue.qsize()
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


@app.post('/archive')
def handle_archive_request():
    app.logger.debug(f"Received new archive request: {request.data}")

    job = None
    try:
        # Check arguments
        if not request.is_json:
            return error_response('Request must be JSON.', HTTPStatus.BAD_REQUEST)
        job_request = JobArchiveRequest.from_json(request.get_json())

        # Check queue capacity early
        if job_queue.full():
            return error_response('Maximum number of queued jobs exceeded.', HTTPStatus.TOO_MANY_REQUESTS)

        # Probe moodle API (wstoken validity)
        moodle_api = MoodleAPI(job_request.moodle_ws_url, job_request.moodle_upload_url, job_request.wstoken)
        if not moodle_api.check_connection():
            return error_response(f'Could not establish a connection to Moodle webservice API at "{job_request.moodle_ws_url}" using the provided wstoken.', HTTPStatus.BAD_REQUEST)

        # Enqueue request
        job = QuizArchiveJob(uuid.uuid1(), job_request)
        job_queue.put_nowait(job)  # Actual queue capacity limit is enforced here!
        job_history.append(job)
        job.set_status(JobStatus.AWAITING_PROCESSING, notify_moodle=False)
        app.logger.info(f"Enqueued job {job.get_id()} from {request.remote_addr}")
    except TypeError as e:
        app.logger.debug(f'JSON is technically incomplete or missing a required parameter. TypeError: {str(e)}')
        return error_response('JSON is technically incomplete or missing a required parameter.', HTTPStatus.BAD_REQUEST)
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
    except Exception:
        app.logger.debug(f'Invalid request.')
        return error_response(f'Invalid request.', HTTPStatus.BAD_REQUEST)
    finally:
        if not job:
            app.logger.warning(f'Failed to process request to {request.url} from {request.remote_addr}')

    # Return job-ID
    return jsonify({'jobid': job.get_id(), 'status': job.get_status()}), HTTPStatus.OK


def start_processing_thread() -> None:
    """
    Starts the queue processing thread.
    :return: None
    """
    queue_processing_thread = InterruptableThread(target=queue_processing_loop, daemon=True, name='queue_processing_thread')
    queue_processing_thread.start()


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

    start_processing_thread()
    waitress.serve(app, host=Config.SERVER_HOST, port=Config.SERVER_PORT)
