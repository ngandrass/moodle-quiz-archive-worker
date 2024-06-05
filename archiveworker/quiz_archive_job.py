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

import asyncio
import csv
import glob
import hashlib
import logging
import os
import tarfile
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List
from uuid import UUID

import requests
from playwright.async_api import async_playwright, ViewportSize, BrowserContext, Route

from config import Config
from .custom_types import JobStatus, JobArchiveRequest, ReportSignal, BackupStatus
from .moodle_api import MoodleAPI


class QuizArchiveJob:
    """
    A single archive job that is processed by the quiz archive worker
    """

    def __init__(self, jobid: UUID, job_request: JobArchiveRequest):
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED
        self.request = job_request
        self.workdir = None
        self.archived_attempts = {}
        self.logger = logging.getLogger(f"{__name__}::<{self.id}>")
        self.moodle_api = MoodleAPI(
            ws_rest_url=self.request.moodle_ws_url,
            ws_upload_url=self.request.moodle_upload_url,
            wstoken=self.request.wstoken
        )

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == UUID(other)
        else:
            return False

    def to_json(self) -> dict:
        """
        Returns a JSON serializable representation of this job

        :return: JSON serializable representation of this job
        """
        return {
            'id': self.id,
            'status': self.status
        }

    def get_id(self) -> UUID:
        """
        Returns the UUID of this job

        :return: UUID of this job
        """
        return self.id

    def get_status(self) -> JobStatus:
        """
        Returns the current status of this job

        :return: Current job status
        """
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
            self.moodle_api.update_job_status(jobid=self.id, status=self.status)

    def execute(self) -> None:
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
                    asyncio.run(self._process_quiz_attempts(
                        attemptids=self.request.tasks['archive_quiz_attempts']['attemptids'],
                        paper_format=self.request.tasks['archive_quiz_attempts']['paper_format'])
                    )

                    if self.request.tasks['archive_quiz_attempts']['fetch_metadata']:
                        asyncio.run(self._process_quiz_attempts_metadata())

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
                    with tarfile.open(archive_file, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
                        # ^-- Historic USTAR format is used to ensure compatibility with Moodle's file API
                        tar.add(self.workdir, arcname='')

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
            self.logger.error(f"Job failed with error: {type(e).__name__}: {str(e)}")
            self.set_status(JobStatus.FAILED, notify_moodle=True)
            return

        self.set_status(JobStatus.FINISHED, notify_moodle=False)  # Do not notify Moodle as it marks this job as completed on its own after the file was processed
        self.logger.info(f"Finished job {self.id}")

    async def _process_quiz_attempts(self, attemptids: List[int], paper_format: str) -> None:
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
            context.set_default_navigation_timeout(Config.REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC * 1000)
            self.logger.debug("Spawned new playwright Browser and BrowserContext")

            for attemptid in attemptids:
                if threading.current_thread().stop_requested():
                    raise InterruptedError('Thread stop requested')
                else:
                    await self._render_quiz_attempt(context, attemptid, paper_format)

            await browser.close()
            self.logger.debug("Destroyed playwright Browser and BrowserContext")

    async def _render_quiz_attempt(self, bctx: BrowserContext, attemptid: int, paper_format: str) -> None:
        """
        Renders a complete quiz attempt to a PDF file

        :param attemptid: ID of the quiz attempt to render
        :param paper_format: Paper format to use for the PDF (e.g. 'A4')
        :return: None
        """
        # Retrieve attempt data
        attempt_name, attempt_html, attempt_attachments = self.moodle_api.get_attempt_data(
            self.request.courseid,
            self.request.cmid,
            self.request.quizid,
            attemptid,
            self.request.tasks['archive_quiz_attempts']['sections'],
            self.request.tasks['archive_quiz_attempts']['filename_pattern'],
            self.request.tasks['archive_quiz_attempts']['sections']['attachments']
        )

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
            page.on('pageerror', lambda msg: self.logger.debug(f'Playwright page error: {msg}'))
            page.on('crash', lambda msg: self.logger.debug(f'Playwright page crash: {msg}'))
            page.on('requestfailed', lambda req: self.logger.debug(f'Playwright request failed: {req.url}'))
            page.on('domcontentloaded', lambda _: self.logger.debug('Playwright DOM content loaded'))
            # page.on('requestfinished', lambda req: self.logger.debug(f'Playwright request finished: {req.url}'))

        # Create mock responder to serve attempt HTML
        # This is done to avoid CORS errors when loading the attempt HTML and to
        # prevent errors when dynamically loading JavaScript modules via
        # requireJS. Using the base URL of the corresponding Moodle LMS seems to
        # work absolutely fine for now.
        async def mock_responder(route: Route):
            await route.fulfill(body=attempt_html, content_type='text/html')

        try:
            await page.route(f"{self.request.moodle_base_url}/mock/attempt", mock_responder)
            await page.goto(f"{self.request.moodle_base_url}/mock/attempt")
        except Exception:
            self.logger.error(f'Page did not load after {Config.REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC} seconds. Aborting ...')
            raise

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

                downloaded_bytes = self.moodle_api.download_moodle_file(
                    download_url=attachment['downloadurl'],
                    target_path=Path(target_dir),
                    target_filename=attachment['filename'],
                    sha1sum_expected=attachment['contenthash'],
                    maxsize_bytes=Config.QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES
                )

                self.logger.info(f'Downloaded {downloaded_bytes} bytes of quiz slot {attachment["slot"]} attachment {attachment["filename"]} to {target_dir}')

        # Keep track of processes attempts
        self.archived_attempts[attemptid] = attempt_name

    async def _wait_for_page_ready_signal(self, page) -> None:
        """
        Waits for the page to report that it is ready for export

        :param page: Page object
        :return: None
        """
        async with page.expect_console_message(
                lambda msg: msg.text == ReportSignal.READY_FOR_EXPORT.value,
                timeout=Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC * 1000
        ) as cmsg_handler:
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

    async def _process_quiz_attempts_metadata(self) -> None:
        """
        Fetches metadata for all quiz attempts that should be archived and writes it to a CSV file

        :return: None
        """
        # Fetch metadata for all quiz attempts that should be archived
        metadata = self.moodle_api.get_attempts_metadata(
            self.request.courseid,
            self.request.cmid,
            self.request.quizid,
            self.request.tasks['archive_quiz_attempts']['attemptids']
        )

        # Add path to each entry for metadata processing
        for entry in metadata:
            entry['path'] = f"/attempts/{self.archived_attempts[int(entry['attemptid'])]}"

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

    async def _process_moodle_backups(self) -> None:
        """
        Waits for completion of all Moodle backups and downloads them after successful completion

        :return: None
        """
        try:
            async with asyncio.TaskGroup() as tg:
                for backup in self.request.tasks['archive_moodle_backups']:
                    tg.create_task(self._process_moodle_backup(backup['backupid'], backup['filename'], backup['file_download_url']))
        except ExceptionGroup as eg:
            # Just take the first exception for now as any exception in any task will interrupt the whole job :)
            for e in eg.exceptions:
                raise e

    async def _process_moodle_backup(self, backupid: str, filename: str, download_url: str) -> None:
        """
        Waits for a single Moodle backup to finish and downloads it after successful completion

        :param backupid: Moodle ID of the backup
        :param filename: Filename to save the backup as
        :param download_url: Moodle URL to download the backup from
        :return: None
        :raises InterruptedError: If the thread was requested to stop
        :raises RuntimeError: If the backup download failed
        """
        self.logger.debug(f'Processing Moodle backup with id {backupid}')

        # Wait for backup to finish
        while True:
            status = self.moodle_api.get_backup_status(self.id, backupid)

            if threading.current_thread().stop_requested():
                raise InterruptedError('Thread stop requested')

            if status == BackupStatus.SUCCESS:
                break

            self.logger.info(f'Backup {backupid} not finished yet. Waiting {Config.BACKUP_STATUS_RETRY_SEC} seconds before retrying ...')
            await asyncio.sleep(Config.BACKUP_STATUS_RETRY_SEC)

        # Check backup filesize
        content_type, content_length = self.moodle_api.get_remote_file_metadata(download_url)

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

        # Download backup
        downloaded_bytes = self.moodle_api.download_moodle_file(
            download_url=download_url,
            target_path=Path(f'{self.workdir}/backups'),
            target_filename=filename,
            maxsize_bytes=Config.BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES,
        )

        self.logger.info(f'Downloaded {downloaded_bytes} bytes of backup {backupid} to {self.workdir}/{filename}')

    def _push_artifact_to_moodle(self, artifact_file: Path, artifact_sha256sum: str) -> None:
        """
        Pushes the given artifact file to Moodle and requests its processing

        :param artifact_file: Path to the artifact file to upload
        :param artifact_sha256sum: SHA256 checksum of the artifact file
        :return: None
        :raises ConnectionError: If the connection to the Moodle API failed
        :raises RuntimeError: If the Moodle webservice API reported an error
        :raises ValueError: If the response from the Moodle API after file
        upload was invalid and the artifact could therefore not be processed
        """
        upload_medata = self.moodle_api.upload_file(Path(artifact_file))
        self.moodle_api.process_uploaded_artifact(
            jobid=self.id,
            sha256sum=artifact_sha256sum,
            **upload_medata
        )
        self.logger.info('Processed uploaded artifact successfully.')
