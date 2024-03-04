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

import requests
import waitress
from flask import Flask, make_response, request, jsonify

from config import Config
from .quiz_archive_job import QuizArchiveJob
from .custom_types import WorkerStatus, JobArchiveRequest, JobStatus

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


def probe_moodle_webservice_api(moodlw_ws_url: str, wstoken: str) -> bool:
    """
    Probes the Moodle webservice API for availability, hereby assuring that the
    given wstoken works

    :param moodlw_ws_url: Base-URL of the Moodle webservice to probe
    :param wstoken: Webservice token to use for authentication
    :return: bool true on success
    """
    try:
        r = requests.get(url=moodlw_ws_url, params={
            'wstoken': wstoken,
            'moodlewsrestformat': 'json',
            'wsfunction': Config.MOODLE_WSFUNCTION_ARCHIVE
        })

        data = r.json()
    except Exception as e:
        raise ConnectionError(f'probe_moodle_webservice_api failed {str(e)}')

    if data['errorcode'] == 'invalidparameter':
        # Moodle returns error 'invalidparameter' if the webservice is invoked
        # with a working wstoken but without valid parameters for the wsfunction
        return True
    else:
        return False


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
        if not probe_moodle_webservice_api(job_request.moodle_ws_url, job_request.wstoken):
            return error_response(f'Could not establish a connection to Moodle webservice API at "{job_request.moodle_ws_url}" using the provided wstoken.', HTTPStatus.BAD_REQUEST)

        # Enqueue request
        job = QuizArchiveJob(uuid.uuid1(), job_request)
        job_queue.put_nowait(job)  # Actual queue capacity limit is enforced here!
        job_history.append(job)
        job.set_status(JobStatus.AWAITING_PROCESSING)
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


def run():
    """
    Runs the application
    :return:
    """
    logging.basicConfig(encoding='utf-8', format='[%(asctime)s] | %(levelname)-8s | %(name)s | %(message)s', level=Config.LOG_LEVEL)
    app.logger.info(f'Running {Config.APP_NAME} version {Config.VERSION} on log level {logging.getLevelName(Config.LOG_LEVEL)}')

    queue_processing_thread = InterruptableThread(target=queue_processing_loop, daemon=True, name='queue_processing_thread')
    queue_processing_thread.start()

    waitress.serve(app, host=Config.SERVER_HOST, port=Config.SERVER_PORT)
