import asyncio
import glob
import hashlib
import io
import logging
import tarfile
from datetime import datetime
from tempfile import TemporaryDirectory
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

    MOODLE_UPLOAD_FILE_FIELDS = ['component', 'contextid', 'userid', 'filearea', 'filename', 'filepath', 'itemid']
    """Keys that are present in the response for each file, received after uploading a file to Moodle"""

    def __init__(self, jobid: UUID, job_request: JobArchiveRequest):
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED
        self.request = job_request
        self.workdir = None

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

        try:
            with TemporaryDirectory() as tempdir:
                self.workdir = tempdir
                self.logger.debug(f"Using temporary working directory: {self.workdir}")

                # Process tasks
                if self.request.tasks['archive_quiz_attempts']:
                    for attemptid in self.request.tasks['archive_quiz_attempts']['attemptids']:
                        asyncio.run(self._render_quiz_attempt(attemptid))

                if self.request.tasks['archive_moodle_course_backup']:
                    self.logger.warning('Task archive_moodle_course_backup requested but currently not implemented!')
                    # TODO: Implement

                # Hash every file
                self.logger.info("Calculating file hashes ...")
                archive_files = glob.glob(f'{self.workdir}/**/*', recursive=True)
                for archive_file in archive_files:
                    with open(archive_file, 'rb') as f:
                        sha256_hash = hashlib.sha256()
                        for byte_block in iter(lambda: f.read(4096),b""):
                            sha256_hash.update(byte_block)
                        with open(f'{f.name}.sha256', 'w+') as hashfile:
                            hashfile.write(sha256_hash.hexdigest())

                # Create final archive
                self.logger.info("Generating final archive ...")
                with TemporaryDirectory() as tardir:
                    archive_name = f'quiz_archive_cid{self.request.courseid}_cmid{self.request.cmid}_qid{self.request.quizid}_{datetime.now().strftime("%Y-%m-%d_%H%M%S")}.tar.gz'
                    with tarfile.open(f'{tardir}/{archive_name}', 'w:gz') as tar:
                        tar.add(self.workdir, arcname="")

                    # Push final file to Moodle
                    self._push_artifact_to_moodle(f'{tardir}/{archive_name}')

        except Exception as e:
            self.logger.error(f"Job failed with error: {str(e)}")
            self.set_status(JobStatus.FAILED)
            return

        self.set_status(JobStatus.FINISHED)
        self.logger.info(f"Finished job {self.id}")

    async def _render_quiz_attempt(self, attemptid: int):
        """
        Renders a complete quiz attempt to a PDF file

        :param attemptid: ID of the quiz attempt to render
        """
        report_name = f"quiz_attempt_report_cid{self.request.courseid}_cmid{self.request.cmid}_qid{self.request.quizid}_aid{attemptid}"
        attempt_html = self._get_attempt_html_from_moodle(attemptid)
        with open(f"{self.workdir}/{report_name}.html", "w+") as f:
            f.write(attempt_html)

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=['--disable-web-security'])  # Pass --disable-web-security to ignore CORS errors
            context = await browser.new_context(viewport=ViewportSize(width=int(Config.REPORT_BASE_VIEWPORT_WIDTH), height=int(Config.REPORT_BASE_VIEWPORT_WIDTH / (16/9))))
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
                fp=f"{self.workdir}/{report_name}.pdf",
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

    def _push_artifact_to_moodle(self, artifact_filename: str):
        with open(artifact_filename, "rb") as f:
            try:
                self.logger.info(f'Uploading artifact "{artifact_filename}" to "{self.request.moodle_upload_url}"')
                r = requests.post(self.request.moodle_upload_url, files={'file_1': f}, data={
                    'token': self.request.wstoken,
                    'filepath': '/',
                    'itemid': 0
                })
                response = r.json()
            except Exception:
                raise ConnectionError(f'Failed to upload artifact to "{self.request.moodle_upload_url}"')

        # Check if upload failed
        if 'errorcode' in response and 'debuginfo' in response:
            self.logger.debug(f'Upload response: {response}')
            raise RuntimeError(f'Moodle webservice upload returned error "{response["errorcode"]}". Message: {response["debuginfo"]}')

        # Validate response
        upload_metadata = response[0]
        for key in self.MOODLE_UPLOAD_FILE_FIELDS:
            if key not in upload_metadata:
                self.logger.debug(f'Upload response: {response}')
                raise ValueError(f'Moodle webservice upload returned an invalid response')

        # Call wsfunction to process artifact
        try:
            r = requests.get(url=self.request.moodle_ws_url, params={
                'wstoken': self.request.wstoken,
                'moodlewsrestformat': 'json',
                'wsfunction': Config.MOODLE_WSFUNCTION_PROESS_UPLOAD,
                'jobid': self.get_id(),
                **dict((f'artifact_{key}', upload_metadata[key]) for key in self.MOODLE_UPLOAD_FILE_FIELDS)
            })
            response = r.json()
        except Exception:
            ConnectionError(f'Failed to call upload processing hook "{Config.MOODLE_WSFUNCTION_PROESS_UPLOAD}" at "{self.request.moodle_ws_url}"')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in response and 'debuginfo' in response:
            raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_PROESS_UPLOAD} returned error "{response["errorcode"]}". Message: {response["debuginfo"]}')

        # Check that everything went smoothely on the Moodle side (not that we could change anything here...)
        if response['jobid'] != str(self.get_id()) or response['status'] != 'OK':
            raise RuntimeError(f'Moodle webservice failed to process uploaded artifact with status: {response["status"]}')

        self.logger.info('Processed uploaded artifact successfully.')
