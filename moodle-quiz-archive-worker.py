#!/usr/bin/env python3
import queue
import threading
import time
import uuid
from http import HTTPStatus
from collections import deque

import requests
from flask import Flask, make_response, request, jsonify

from config import Config
from quiz_archive_job import QuizArchiveJob
from custom_types import WorkerStatus, JobArchiveRequest, JobStatus

app = Flask(__name__)
job_queue = queue.Queue(maxsize=Config.QUEUE_SIZE)
job_history = deque(maxlen=Config.HISTORY_SIZE)


class FlaskThread(threading.Thread):
    """
    Custom Thread that runs with Flask context
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self):
        time.sleep(3)  # Delay thread execution to make sure app_context is ready
        with app.app_context():
            super().run()


def queue_processing_loop():
    app.logger.info("Spwaned queue worker thread")

    while getattr(threading.current_thread(), "do_run", True):
        job = job_queue.get()
        job.execute()

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
    except Exception:
        raise ConnectionError()

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


@app.post('/archive')
def handle_archive_request():
    app.logger.debug(f"Received new archive request: {request.data}")

    job = None
    try:
        # Check arguments
        if not request.is_json:
            return error_response('Request must be JSON.', HTTPStatus.BAD_REQUEST)
        job_request = JobArchiveRequest(**request.get_json())

        # Check queue capacity early
        if job_queue.full():
            return error_response('Maximum number of queued jobs exceeded.', HTTPStatus.TOO_MANY_REQUESTS)

        # Probe moodle API (wstoken validity)
        if not probe_moodle_webservice_api(job_request.moodle_ws_url, job_request.wstoken):
            return error_response(f'Could not establish a connection to Moodle webservice API at "{job_request.moodle_ws_url}" using the prodived wstoken.', HTTPStatus.BAD_REQUEST)

        # Enqueue request
        job = QuizArchiveJob(uuid.uuid1(), job_request)
        job_queue.put_nowait(job)  # Actual queue capacity limit is enforced here!
        job_history.append(job)
        job.set_status(JobStatus.AWAITING_PROCESSING)
        app.logger.info(f"Enqueued job {job.get_id()} from {request.remote_addr}")
    except TypeError:
        return error_response('JSON is technically incomplete or missing a required parameter.', HTTPStatus.BAD_REQUEST)
    except ValueError as e:
        return error_response(f'JSON data is invalid: {str(e)}', HTTPStatus.BAD_REQUEST)
    except ConnectionError:
        return error_response('Connection to Moodle webservice failed. Cannot process request. Aborting.', HTTPStatus.BAD_REQUEST)
    except queue.Full:
        job = None
        return error_response('Maximum number of queued jobs exceeded.', HTTPStatus.TOO_MANY_REQUESTS)
    except:
        return error_response(f'Invalid request.', HTTPStatus.BAD_REQUEST)
    finally:
        if not job:
            app.logger.warning(f'Failed to process request to {request.url} from {request.remote_addr}')

    # Return job-ID
    return jsonify({'jobid': job.get_id(), 'status': job.get_status()}), HTTPStatus.OK


def main():
    app.logger.setLevel(Config.LOG_LEVEL)
    queue_processing_thread = FlaskThread(target=queue_processing_loop, daemon=True, name='queue_processing_thread')
    queue_processing_thread.start()
    app.run(debug=True)


if __name__ == "__main__":
    main()
