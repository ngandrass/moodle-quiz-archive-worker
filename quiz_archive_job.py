import asyncio
import io
import logging
from uuid import UUID

import requests
from PIL import Image
from playwright.async_api import async_playwright, ViewportSize

from config import Config
from custom_types import JobStatus, JobArchiveRequest


class QuizArchiveJob:
    """
    A single archive job that is processed by the quiz archive worker
    """

    def __init__(self, jobid: UUID, job_request: JobArchiveRequest):
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED
        self.request = job_request

        self.logger = logging.getLogger(f"{__name__}::<{self.id}>")
        logging.basicConfig(
            encoding="utf-8",
            level=Config.LOG_LEVEL,
            format="[%(asctime)s] %(levelname)s in %(name)s: %(message)s"
        )

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == UUID(other)
        else:
            return False

    def to_json(self) -> object:
        return {
            'id': self.id,
            'status': self.status
        }

    def get_id(self) -> UUID:
        return self.id

    def get_status(self) -> JobStatus:
        return self.status

    def set_status(self, status: JobStatus) -> None:
        self.status = status

    def execute(self):
        self.logger.info(f"Processing job {self.id}")
        self.set_status(JobStatus.RUNNING)

        if self.request.tasks['archive_quiz_attempts']:
            for attemptid in self.request.tasks['archive_quiz_attempts']['attemptids']:
                asyncio.run(self._render_quiz_attempt(attemptid))

        self.set_status(JobStatus.FINISHED)
        self.logger.info(f"Finished job {self.id}")

    async def _render_quiz_attempt(self, attemptid: int) -> object: # TODO
        """
        Renders a complete quiz attempt to a PDF file

        :param attemptid: ID of the quiz attempt to render
        :return: TOOD
        """
        report_name = f"quiz_attempt_report_cid{self.request.courseid}_cmid{self.request.cmid}_qid{self.request.quizid}_aid{attemptid}"
        attempt_html = self._get_attempt_html_from_moodle(attemptid)
        with open(f"out/{report_name}.html", "w+") as f:
            f.write(attempt_html)

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=['--disable-web-security'])  # Pass --disable-web-security to ignore CORS errors
            context = await browser.new_context(viewport=ViewportSize(width=1920, height=1080))
            page = await context.new_page()
            await page.set_content(attempt_html)
            screenshot = await page.screenshot(
                full_page=True,
                caret="hide",
                type="png"
            )
            await browser.close()

            img = Image.open(io.BytesIO(screenshot))
            img.convert(mode='RGB', palette=Image.ADAPTIVE).save(
                fp=f"out/{report_name}.pdf",
                format='PDF',
                dpi=(300, 300),
                quality=96
            )

            self.logger.info(f"Generated {report_name}")

    def _get_attempt_html_from_moodle(self, attemptid: int) -> str:
        """
        Requests the HTML DOM for a quiz attempt from the Moodle webservice API

        :param attemptid: ID of the attempt to request
        :raises ConnectionError if the request to the Moodle webservice API
        failed or the response could not be parsed
        :raises RuntimeError if the Moodle webservice API reported an error
        :raises ValueError if the response from the Moodle webservice API was incomplete
        :return: string HTML DOM report for the requested attemptid
        """
        try:
            r = requests.get(url=self.request.moodle_ws_url, params={
                'wstoken': self.request.wstoken,
                'moodlewsrestformat': 'json',
                'wsfunction': Config.MOODLE_WSFUNCTION_ARCHIVE,
                'courseid': self.request.courseid,
                'cmid': self.request.cmid,
                'quizid': self.request.quizid,
                'attemptid': attemptid
            })
            data = r.json()
        except Exception:
            raise ConnectionError(f'Call to Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} at "{self.request.moodle_ws_url}" failed')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in data and 'debuginfo' in data:
            raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}". Message: {data["debuginfo"]}')

        # Check if response is as expected
        for attr in ['attemptid', 'cmid', 'courseid', 'quizid', 'report']:
            if attr not in data:
                raise ValueError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned an incomplete response')

        if not (
            data['attemptid'] == attemptid and
            data['courseid'] == self.request.courseid and
            data['cmid'] == self.request.cmid and
            data['quizid'] == self.request.quizid
        ):
            raise ValueError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned an invalid response')

        # Looks fine - Data seems valid :)
        return data['report']
