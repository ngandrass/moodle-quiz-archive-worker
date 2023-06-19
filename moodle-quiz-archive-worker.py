#!/usr/bin/env python3
import asyncio
import io
import uuid
from http import HTTPStatus
from collections import deque

from flask import Flask, make_response, jsonify
from PIL import Image
from playwright.async_api import async_playwright, ViewportSize

from config import Config
from quiz_archive_job import QuizArchiveJob
from custom_types import WorkerStatus


app = Flask(__name__)
job_queue = deque()
job_history = deque(maxlen=Config.HISTORY_SIZE)
active_job = None


def execute_job(job_data):
    pass


def is_queue_full():
    return len(job_queue) == Config.QUEUE_SIZE


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
    if len(job_queue) == 0:
        status = WorkerStatus.IDLE
    elif len(job_queue) < Config.QUEUE_SIZE:
        status = WorkerStatus.ACTIVE
    elif is_queue_full():
        status = WorkerStatus.BUSY
    else:
        status = WorkerStatus.UNKNOWN

    return jsonify({
        'status': status,
        'queue_len': len(job_queue)
    }), HTTPStatus.OK


@app.get('/status/<string:jobid>')
def handle_status_jobid(jobid):
    try:
        job = job_queue[job_queue.index(jobid)]
    except ValueError:
        try:
            job = job_history[job_history.index(jobid)]
        except ValueError:
            return error_response(f"Job with requested jobid '{jobid}' was not found", HTTPStatus.NOT_FOUND)

    return jsonify(job.to_json()), HTTPStatus.OK


@app.post('/archive')
def handle_archive_request():
    # Check arguments

    # Check queue capacity
    if is_queue_full():
        return error_response('Maximum number of queued jobs exceeded.', HTTPStatus.TOO_MANY_REQUESTS)

    # Probe moodle API (wstoken validity)

    # Enqueue request
    jobid = uuid.uuid1()
    job_queue.append(QuizArchiveJob(jobid))

    # Return job-ID
    return jsonify({'jobid': jobid}), HTTPStatus.OK


async def foo():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport=ViewportSize(width=1920, height=1080))
        await page.goto("file:///tmp/out.html")
        print(await page.title())
        screenshot = await page.screenshot(
            full_page=True,
            caret="hide",
            type="png"
        )
        await browser.close()

        img = Image.open(io.BytesIO(screenshot))
        img.convert(mode='RGB', palette=Image.ADAPTIVE).save(
            fp="out.pdf",
            format='PDF',
            dpi=(300, 300),
            quality=96
        )


def main():
    app.run(debug=True)
    # asyncio.run(foo())


if __name__ == "__main__":
    main()
