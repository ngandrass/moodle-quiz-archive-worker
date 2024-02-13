# Moodle Quiz Archive Worker
# Copyright (C) 2023 Niels Gandraß <niels@gandrass.de>
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

import asyncio
import csv
import glob
import hashlib
import json
import logging
import os
import tarfile
import threading
from json import JSONDecodeError
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Tuple
from uuid import UUID

import requests
from playwright.async_api import async_playwright, ViewportSize, BrowserContext, Route

from config import Config
from custom_types import JobStatus, JobArchiveRequest, ReportSignal


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
        self.archived_attempts = {}
        self.logger = logging.getLogger(f"{__name__}::<{self.id}>")

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

    def set_status(self, status: JobStatus, notify_moodle: bool = False) -> None:
        """
        Updates the status of this job. If notify_moodle is True, the status update
        is passed to the Moodle API as well.

        :param status: New job status
        :param notify_moodle: Call job status update function via Moodle API if True
        :return: None
        """
        self.status = status

        if notify_moodle:
            try:
                r = requests.get(url=self.request.moodle_ws_url, params={
                    'wstoken': self.request.wstoken,
                    'moodlewsrestformat': 'json',
                    'wsfunction': Config.MOODLE_WSFUNCTION_UPDATE_JOB_STATUS,
                    'jobid': str(self.id),
                    'status': str(self.status)
                })
                data = r.json()

                if data['status'] != 'OK':
                    self.logger.warning(f'Moodle API rejected to update job status to new value: {self.status}')
            except Exception:
                self.logger.warning('Failed to update job status via Moodle API. Connection error.')

    def execute(self):
        """
        Executes this job

        :return: None
        """
        self.logger.info(f"Processing job {self.id}")
        self.set_status(JobStatus.RUNNING, notify_moodle=True)

        try:
            with TemporaryDirectory() as tempdir:
                self.workdir = tempdir
                self.logger.debug(f"Using temporary working directory: {self.workdir}")

                # Process task: Archive quiz attempts
                if self.request.tasks['archive_quiz_attempts']:
                    asyncio.run(self._render_quiz_attempts(
                        attemptids=self.request.tasks['archive_quiz_attempts']['attemptids'],
                        paper_format=self.request.tasks['archive_quiz_attempts']['paper_format'])
                    )

                    if self.request.tasks['archive_quiz_attempts']['fetch_metadata']:
                        self._process_quiz_attempts_metadata()

                # Process task: Archive Moodle backups
                if self.request.tasks['archive_moodle_backups']:
                    asyncio.run(self._process_moodle_backups())

                # Hash every file
                self.logger.info("Calculating file hashes ...")
                archive_files = glob.glob(f'{self.workdir}/**/*', recursive=True)
                for archive_file in archive_files:
                    if os.path.isfile(archive_file):
                        with open(archive_file, 'rb') as f:
                            if threading.current_thread().stop_requested():
                                raise InterruptedError('Thread stop requested')

                            sha256_hash = hashlib.sha256()
                            for byte_block in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(byte_block)
                            with open(f'{f.name}.sha256', 'w+') as hashfile:
                                hashfile.write(sha256_hash.hexdigest())

                # Create final archive
                self.logger.info("Generating final archive ...")
                with TemporaryDirectory() as tardir:
                    # Add files
                    archive_file = f'{tardir}/{self.request.archive_filename}.tar.gz'
                    with tarfile.open(archive_file, 'w:gz') as tar:
                        tar.add(self.workdir, arcname="")

                    # Calculate checksum
                    with open(archive_file, 'rb') as f:
                        if threading.current_thread().stop_requested():
                            raise InterruptedError('Thread stop requested')

                        archive_sha256sum = hashlib.sha256()
                        for byte_block in iter(lambda: f.read(4096), b""):
                            archive_sha256sum.update(byte_block)

                    # Push final file to Moodle
                    self._push_artifact_to_moodle(archive_file, archive_sha256sum.hexdigest())

        except InterruptedError:
            self.logger.warning(f'Job termination requested. Terminated gracefully.')
            self.set_status(JobStatus.TIMEOUT, notify_moodle=True)
            return
        except Exception as e:
            self.logger.error(f"Job failed with error: {str(e)}")
            self.set_status(JobStatus.FAILED, notify_moodle=True)
            return

        self.set_status(JobStatus.FINISHED, notify_moodle=False)  # Do not notify Moodle as it marks this job as completed on its own after the file was processed
        self.logger.info(f"Finished job {self.id}")

    async def _render_quiz_attempts(self, attemptids: List[int], paper_format: str):
        """
        Renders all quiz attempts to HTML and PDF files

        :param attemptids: List of attemptids
        :param paper_format: Paper format to use for the PDF (e.g. 'A4')
        :return: None
        """
        os.makedirs(f'{self.workdir}/attempts', exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=['--disable-web-security'])  # Pass --disable-web-security to ignore CORS errors
            context = await browser.new_context(viewport=ViewportSize(
                width=int(Config.REPORT_BASE_VIEWPORT_WIDTH),
                height=int(Config.REPORT_BASE_VIEWPORT_WIDTH / (16/9)))
            )
            self.logger.debug("Spawned new playwright Browser and BrowserContext")

            for attemptid in attemptids:
                if threading.current_thread().stop_requested():
                    raise InterruptedError('Thread stop requested')
                else:
                    await self._render_quiz_attempt(context, attemptid, paper_format)

            await browser.close()
            self.logger.debug("Destroyed playwright Browser and BrowserContext")

    async def _render_quiz_attempt(self, bctx: BrowserContext, attemptid: int, paper_format: str):
        """
        Renders a complete quiz attempt to a PDF file

        :param attemptid: ID of the quiz attempt to render
        :param paper_format: Paper format to use for the PDF (e.g. 'A4')
        """
        # Retrieve attempt data
        attempt_name, attempt_html, attempt_attachments = self._get_attempt_data_from_moodle(attemptid)

        # Prepare attempt dir
        attempt_dir = f"{self.workdir}/attempts/{attempt_name}"
        os.makedirs(attempt_dir, exist_ok=True)

        # Save HTML DOM, if desired
        if self.request.tasks['archive_quiz_attempts']['keep_html_files']:
            with open(f"{attempt_dir}/{attempt_name}.html", "w+") as f:
                f.write(attempt_html)
            self.logger.debug(f"Saved HTML DOM of quiz attempt {attemptid} to {attempt_dir}/{attempt_name}.html")
        else:
            self.logger.debug(f"Skipping HTML DOM saving of quiz attempt {attemptid}")

        # Prepare new page
        page = await bctx.new_page()
        if Config.LOG_LEVEL == logging.DEBUG:
            page.on('console', lambda msg: self.logger.debug(f'Playwright console message: {msg.text}'))
            page.on('pageerror', lambda err: self.logger.debug(f'Playwright page error: {err}'))

        # Create mock responder to serve attempt HTML
        # This is done to avoid CORS errors when loading the attempt HTML and to
        # prevent errors when dynamically loading JavaScript modules via
        # requireJS. Using the base URL of the corresponding Moodle LMS seems to
        # work absolutely fine for now.
        async def mock_responder(route: Route):
            await route.fulfill(body=attempt_html, content_type='text/html')

        await page.route(f"{self.request.moodle_base_url}/mock/attempt", mock_responder)
        await page.goto(f"{self.request.moodle_base_url}/mock/attempt")

        # Wait for the page to report that is fully rendered, if enabled
        if Config.REPORT_WAIT_FOR_READY_SIGNAL:
            try:
                await self._wait_for_page_ready_signal(page)
            except Exception:
                if Config.REPORT_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT:
                    self.logger.warning(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds. Continuing ...')
                else:
                    self.logger.error(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds. Aborting ...')
                    raise RuntimeError()
        else:
            self.logger.debug('Not waiting for ready signal. Export immediately ...')

        # Save attempt page as PDF
        await page.pdf(
            path=f"{attempt_dir}/{attempt_name}.pdf",
            format=paper_format,
            print_background=True,
            display_header_footer=False,
            margin={
                'top': Config.REPORT_PAGE_MARGIN,
                'right': Config.REPORT_PAGE_MARGIN,
                'bottom': Config.REPORT_PAGE_MARGIN,
                'left': Config.REPORT_PAGE_MARGIN,
            }
        )

        # Cleanup and logging
        await page.close()
        self.logger.info(f"Generated \"{attempt_name}\"")

        # Save attempt attachments
        if attempt_attachments:
            self.logger.debug(f"Saving {len(attempt_attachments)} attachments ...")
            for attachment in attempt_attachments:
                target_dir = f"{attempt_dir}/attachments/{attachment['slot']}"

                downloaded_bytes = self._download_moodle_file(
                    download_url=attachment['downloadurl'],
                    path=Path(target_dir),
                    filename=attachment['filename'],
                    sha1sum_expected=attachment['contenthash'],
                    maxsize_bytes=Config.QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES
                )

                self.logger.info(f'Downloaded {downloaded_bytes} bytes of quiz slot {attachment["slot"]} attachment {attachment["filename"]} to {target_dir}')

        # Keep track of processes attempts
        self.archived_attempts[attemptid] = attempt_name

    async def _wait_for_page_ready_signal(self, page):
        """
        Waits for the page to report that it is ready for export

        :param page: Page object
        :return: None
        """
        async with page.expect_console_message(lambda msg: msg.text == ReportSignal.READY_FOR_EXPORT.value, timeout=Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC * 1000) as cmsg_handler:
            self.logger.debug('Injecting JS to wait for page rendering ...')
            await page.evaluate('''
                setTimeout(function() {
                    const SIGNAL_PAGE_READY_FOR_EXPORT = "x-quiz-archiver-page-ready-for-export";
                    const SIGNAL_MATHJAX_FOUND = "x-quiz-archiver-mathjax-found";
                    const SIGNAL_MATHJAX_NOT_FOUND = "x-quiz-archiver-mathjax-not-found";
                    const SIGNAL_MATHJAX_NO_FORMULAS_ON_PAGE = "x-quiz-archiver-mathjax-no-formulas-on-page";

                    if (typeof window.MathJax !== 'undefined') {
                        console.log(SIGNAL_MATHJAX_FOUND);

                        if (document.getElementsByClassName('filter_mathjaxloader_equation').length == 0) {
                            console.log(SIGNAL_MATHJAX_NO_FORMULAS_ON_PAGE);
                            console.log(SIGNAL_PAGE_READY_FOR_EXPORT);
                            return;
                        }

                        window.MathJax.Hub.Queue(function () {
                            console.log(SIGNAL_PAGE_READY_FOR_EXPORT);
                        });
                        window.MathJax.Hub.processSectionDelay = 0;
                    } else {
                        console.log(SIGNAL_MATHJAX_NOT_FOUND);
                        console.log(SIGNAL_PAGE_READY_FOR_EXPORT);
                    }
                }, 1000);
            ''')
            self.logger.debug(f'Waiting for ready signal: {ReportSignal.READY_FOR_EXPORT}')

            cmsg = await cmsg_handler.value
            self.logger.debug(f'Received signal: {cmsg}')

    def _get_attempt_data_from_moodle(self, attemptid: int) -> Tuple[str, str, List]:
        """
        Requests the attempt data (HTML DOM, attachment metadata) for a quiz
        attempt from the Moodle webservice API

        :param attemptid: ID of the attempt to request
        :raises ConnectionError if the request to the Moodle webservice API
        failed or the response could not be parsed
        :raises RuntimeError if the Moodle webservice API reported an error
        :raises ValueError if the response from the Moodle webservice API was incomplete
        :return: Tuple[str, str, List] consisting of the attempt name, the HTML DOM
                 report and a List of attachments for the requested attemptid
        """
        try:
            r = requests.get(url=self.request.moodle_ws_url, params={
                'wstoken': self.request.wstoken,
                'moodlewsrestformat': 'json',
                'wsfunction': Config.MOODLE_WSFUNCTION_ARCHIVE,
                'courseid': self.request.courseid,
                'cmid': self.request.cmid,
                'quizid': self.request.quizid,
                'attemptid': attemptid,
                'filenamepattern': self.request.tasks["archive_quiz_attempts"]["filename_pattern"],
                'attachments': self.request.tasks["archive_quiz_attempts"]["sections"]["attachments"],
                **{f'sections[{key}]': value for key, value in self.request.tasks["archive_quiz_attempts"]["sections"].items()}
            })
            # Moodle 4.3 seems to return an additional "</body></html>" at the end of the response which causes the JSON parser to fail
            response = r.text.lstrip('<html><body>').rstrip('</body></html>')
            data = json.loads(response)
        except JSONDecodeError as e:
            self.logger.debug(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} response: {r.text}')
            raise ValueError(f'Call to Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} at "{self.request.moodle_ws_url}" returned invalid JSON')
        except Exception as e:
            self.logger.debug(f'Call to Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} caused {type(e).__name__}: {str(e)}')
            raise ConnectionError(f'Call to Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} at "{self.request.moodle_ws_url}" failed')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in data:
            if 'debuginfo' in data:
                raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}". Message: {data["debuginfo"]}')
            if 'message' in data:
                raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}". Message: {data["message"]}')
            raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}".')

        # Check if response is as expected
        for attr in ['attemptid', 'cmid', 'courseid', 'quizid', 'filename', 'report', 'attachments']:
            if attr not in data:
                raise ValueError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned an incomplete response')

        if not (
            data['attemptid'] == attemptid and
            data['courseid'] == self.request.courseid and
            data['cmid'] == self.request.cmid and
            data['quizid'] == self.request.quizid and
            isinstance(data['filename'], str) and
            isinstance(data['report'], str) and
            isinstance(data['attachments'], list)
        ):
            raise ValueError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_ARCHIVE} returned an invalid response')

        # Looks fine - Data seems valid :)
        return data['filename'], data['report'], data['attachments']

    def _process_quiz_attempts_metadata(self):
        """
        Fetches metadata for all quiz attempts that should be archived and writes it to a CSV file

        :return: None
        """
        # Fetch metadata for all quiz attempts that should be archived
        metadata = asyncio.run(self._fetch_quiz_attempt_metadata())
        self.logger.debug(f"Quiz attempt metadata: {metadata}")

        # Add path to each entry for metadata processing
        for entry in metadata:
            entry['path'] = f"/attempts/{self.archived_attempts[entry['attemptid']]}"

        # Write metadata to CSV file
        with open(f'{self.workdir}/attempts_metadata.csv', 'w+') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=metadata[0].keys(),
                delimiter=',',
                quotechar='"',
                quoting=csv.QUOTE_NONNUMERIC
            )
            writer.writeheader()
            writer.writerows(metadata)

        self.logger.info(f"Wrote metadata for {len(metadata)} quiz attempts to CSV file")

    async def _fetch_quiz_attempt_metadata(self):
        """
        Fetches metadata for all quiz attempts that should be archived

        :return: list of dicts containing metadata for each quiz attempt
        """
        try:
            r = requests.get(url=self.request.moodle_ws_url, params={
                'wstoken': self.request.wstoken,
                'moodlewsrestformat': 'json',
                'wsfunction': Config.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA,
                'courseid': self.request.courseid,
                'cmid': self.request.cmid,
                'quizid': self.request.quizid,
                'attemptids[]': self.request.tasks["archive_quiz_attempts"]["attemptids"]
            })
            data = r.json()
        except Exception:
            raise ConnectionError(f'Call to Moodle webservice function {Config.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} at "{self.request.moodle_ws_url}" failed')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in data and 'debuginfo' in data:
            raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} returned error "{data["errorcode"]}". Message: {data["debuginfo"]}')

        # Check if response is as expected
        for attr in ['attempts', 'cmid', 'courseid', 'quizid']:
            if attr not in data:
                raise ValueError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} returned an incomplete response')

        if not (
            data['courseid'] == self.request.courseid and
            data['cmid'] == self.request.cmid and
            data['quizid'] == self.request.quizid
        ):
            raise ValueError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} returned an invalid response')

        return data['attempts']

    async def _process_moodle_backups(self):
        try:
            async with asyncio.TaskGroup() as tg:
                for backup in self.request.tasks['archive_moodle_backups']:
                    tg.create_task(self._process_moodle_backup(backup['backupid'], backup['filename'], backup['file_download_url']))
        except ExceptionGroup as eg:
            # Just take the first exception for now as any exception in any task will interrupt the whole job :)
            for e in eg.exceptions:
                raise e

    async def _process_moodle_backup(self, backupid: str, filename: str, download_url: str):
        self.logger.debug(f'Processing Moodle backup with id {backupid}')

        # Wait for backup to finish
        while True:
            try:
                self.logger.debug(f'Requesting status for backup {backupid}')
                r = requests.get(url=self.request.moodle_ws_url, params={
                    'wstoken': self.request.wstoken,
                    'moodlewsrestformat': 'json',
                    'wsfunction': Config.MOODLE_WSFUNCTION_GET_BACKUP,
                    'jobid': self.get_id(),
                    'backupid': backupid
                })
                response = r.json()
            except Exception:
                raise ConnectionError(f'Failed to get status of backup {backupid}')

            if 'errorcode' in response and 'debuginfo' in response:
                raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_GET_BACKUP} returned error "{response["errorcode"]}". Message: {response["debuginfo"]}')

            if response['status'] == 'SUCCESS':
                self.logger.debug(f'Backup {backupid} finished successfully.')
                break

            if response['status'] != 'E_BACKUP_PENDING':
                raise RuntimeError(f'Retrieving status of backup "{backupid}" failed with {response["status"]}. Aborting.')

            if threading.current_thread().stop_requested():
                raise InterruptedError('Thread stop requested')

            self.logger.info(f'Backup {backupid} not finished yet. Waiting {Config.BACKUP_STATUS_RETRY_SEC} seconds before retrying ...')
            await asyncio.sleep(Config.BACKUP_STATUS_RETRY_SEC)

        # Check backup filesize
        try:
            self.logger.debug(f'Requesting status for backup {backupid}')
            h = requests.head(url=download_url, params={'token': self.request.wstoken}, allow_redirects=True)
            self.logger.debug(f'Backup file HEAD request headers: {h.headers}')
            content_type = h.headers.get('Content-Type', None)
            content_length = h.headers.get('Content-Length', None)

            if content_type != 'application/vnd.moodle.backup':
                # Try to get JSON content if debug logging is enabled to allow debugging
                if Config.LOG_LEVEL == logging.DEBUG:
                    if content_type.startswith('application/json'):
                        r = requests.get(url=download_url, params={'token': self.request.wstoken}, allow_redirects=True)
                        self.logger.debug(f'Backup file GET response: {r.text}')

                # Normal error handling
                raise RuntimeError(f'Backup Content-Type invalid. Expected "application/vnd.moodle.backup" but got "{content_type}"')

            if not content_length:
                raise RuntimeError(f'Backup filesize could not be determined')
            elif int(content_length) > Config.BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES:
                raise RuntimeError(f'Backup filesize of {content_length} bytes exceeds maximum allowed filesize {Config.BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES} bytes')
            else:
                self.logger.debug(f'Backup {backupid} filesize')
        except RuntimeError as e:
            raise e
        except Exception as e:
            raise ConnectionError(f'Failed to retrieve HEAD for backup {backupid} at: {download_url}. {str(e)}')

        # Download backup
        downloaded_bytes = self._download_moodle_file(
            download_url,
            Path(f'{self.workdir}/backups'),
            filename,
            maxsize_bytes=Config.BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES,
        )

        self.logger.info(f'Downloaded {downloaded_bytes} bytes of backup {backupid} to {self.workdir}/{filename}')

    def _download_moodle_file(
            self,
            download_url: str,
            path: Path,
            filename: str,
            sha1sum_expected: str = None,
            maxsize_bytes: int = Config.DOWNLOAD_MAX_FILESIZE_BYTES
    ) -> int:
        """
        Downloads a file from Moodle and saves it to the specified path. Downloads
        are performed in chunks.

        :param download_url: The URL to download the file from
        :param path: The path to store the downloaded file into
        :param filename: The name of the file to store
        :param sha1sum_expected: SHA1 sum of the file contents to check against, ignored if None
        :param maxsize_bytes: Maximum number of bytes before the download is forcefully aborted
        :return: Number of bytes downloaded
        """
        try:
            os.makedirs(path, exist_ok=True)
            with open(path.joinpath(filename), 'wb+') as f:
                r = requests.get(url=download_url, params={
                    'token': self.request.wstoken,
                    'forcedownload': 1
                }, stream=True)

                chunksize = int(32 * 10e6)  # 32 MB
                downloaded_bytes = 0
                for chunk in r.iter_content(chunksize):
                    if downloaded_bytes > maxsize_bytes:
                        raise RuntimeError(f'Downloaded Moodle file was larger than expected and exceeded the maximum file size limit of {maxsize_bytes} bytes')
                    downloaded_bytes = downloaded_bytes + f.write(chunk)
        except RuntimeError as e:
            raise e
        except IOError:
            raise RuntimeError(f'Encountered internal IOError while writing a downloading Moodle file from {download_url} to {filename}')
        except Exception:
            ConnectionError(f'Failed to download Moodle file from: {download_url}')

        # Check if we downloaded a Moodle error message
        if downloaded_bytes < 10240:  # 10 KiB
            with open(path.joinpath(filename), 'r') as f:
                try:
                    data = json.load(f)
                    if 'errorcode' in data and 'debuginfo' in data:
                        self.logger.debug(f'Downloaded JSON response: {data}')
                        raise RuntimeError(f'Moodle file download failed with "{data["errorcode"]}"')
                except (JSONDecodeError, UnicodeDecodeError):
                    pass

        # Check SHA1 sum
        if sha1sum_expected:
            with open(path.joinpath(filename), 'rb') as f:
                sha1sum = hashlib.sha1()
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha1sum.update(byte_block)

            if sha1sum.hexdigest() != sha1sum_expected:
                raise RuntimeError(f'Moodle file download failed. Expected SHA1 sum "{sha1sum_expected}" but got "{sha1sum.hexdigest()}"')

        self.logger.info(f'Downloaded {downloaded_bytes} bytes to {self.workdir}/{filename}')
        return downloaded_bytes

    def _push_artifact_to_moodle(self, artifact_filename: str, artifact_sha256sum: str):
        with open(artifact_filename, "rb") as f:
            try:
                file_stats = os.stat(artifact_filename)
                filesize = file_stats.st_size
                self.logger.info(f'Uploading artifact "{artifact_filename}" (size: {filesize} bytes) (sha256sum: {artifact_sha256sum}) to "{self.request.moodle_upload_url}"')

                r = requests.post(self.request.moodle_upload_url, files={'file_1': f}, data={
                    'token': self.request.wstoken,
                    'filepath': '/',
                    'itemid': 0
                })
                response = r.json()
            except Exception as e:
                raise ConnectionError(f'Failed to upload artifact to "{self.request.moodle_upload_url}". Exception: {str(e)}. Response: {r.text}')

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
                'artifact_sha256sum': artifact_sha256sum,
                **dict((f'artifact_{key}', upload_metadata[key]) for key in self.MOODLE_UPLOAD_FILE_FIELDS)
            })
            response = r.json()
        except Exception:
            ConnectionError(f'Failed to call upload processing hook "{Config.MOODLE_WSFUNCTION_PROESS_UPLOAD}" at "{self.request.moodle_ws_url}"')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in response and 'debuginfo' in response:
            raise RuntimeError(f'Moodle webservice function {Config.MOODLE_WSFUNCTION_PROESS_UPLOAD} returned error "{response["errorcode"]}". Message: {response["debuginfo"]}')

        # Check that everything went smoothly on the Moodle side (not that we could change anything here...)
        if response['status'] != 'OK':
            raise RuntimeError(f'Moodle webservice failed to process uploaded artifact with status: {response["status"]}')

        self.logger.info('Processed uploaded artifact successfully.')
