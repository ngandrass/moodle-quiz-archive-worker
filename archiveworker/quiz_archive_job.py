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

import asyncio
import csv
import glob
import hashlib
import logging
import os
import re
import threading
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from typing import Dict
from uuid import UUID

from PIL.Image import Resampling
from playwright.async_api import async_playwright, ViewportSize, BrowserContext, Route
from pypdf import PdfWriter

from config import Config
from archiveworker.type import JobStatus, ReportSignal, MoodleBackupStatus, PaperFormat
from archiveworker.api.worker import ArchiveJobDescriptor
from archiveworker.requests_factory import RequestsFactory

DEMOMODE_JAVASCRIPT = open(os.path.join(os.path.dirname(__file__), '../res/demomode.js')).read()
READYSIGNAL_JAVASCRIPT = open(os.path.join(os.path.dirname(__file__), '../res/readysignal.js')).read()

SRGB_ICC_COLOR_PROFILE_PATH = Path(os.path.join(Path(os.path.dirname(__file__)).parent, "res", "sRGB_v4_ICC_preference_displayclass.icc"))

class QuizArchiveJob:
    """
    A single archive job that is processed by the quiz archive worker
    """

    def __init__(self, jobid: UUID, descriptor: ArchiveJobDescriptor) -> None:
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED
        self.descr = descriptor
        self.moodle_api = descriptor.moodle_api
        self.statusextras = None
        self.last_moodle_status_update = None
        self.workdir = None
        self.archived_attempts = {}
        self.logger = logging.getLogger(f"{__name__}::<{self.id}>")

        # Limit number of attempts in demo mode
        if Config.DEMO_MODE:
            if self.descr.tasks['quiz_attempts']:
                self.logger.info("Demo mode: Only processing the first 10 quiz attempts!")
                if len(self.descr.tasks['quiz_attempts']['attemptids']) > 10:
                    self.descr.tasks['quiz_attempts']['attemptids'] = self.descr.tasks['quiz_attempts']['attemptids'][:10]

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

    def get_statusextras(self) -> Dict:
        """
        Returns additional status information

        :return: Additional status information
        """
        return self.statusextras

    def set_status(self, status: JobStatus, statusextras: Dict = None, notify_moodle: bool = False) -> None:
        """
        Updates the status of this job. If notify_moodle is True, the status update
        is passed to the Moodle API as well.

        :param status: New job status
        :param statusextras: Additional status information
        :param notify_moodle: Call job status update function via Moodle API if True
        :return: None
        """
        self.status = status
        self.statusextras = statusextras

        if notify_moodle:
            self.moodle_api.update_job_status(self.id, self.descr, self.status, self.statusextras)
            self.last_moodle_status_update = time()

    def execute(self) -> None:
        """
        Executes this job

        :return: None
        """
        self.logger.info(f"Processing job {self.id}")
        self.set_status(JobStatus.RUNNING, statusextras={'progress': 0}, notify_moodle=True)

        try:
            with TemporaryDirectory() as tempdir:
                self.workdir = tempdir
                self.logger.debug(f"Using temporary working directory: {self.workdir}")

                # Process task: Archive quiz attempts
                if self.descr.tasks['quiz_attempts']:
                    asyncio.run(self._process_quiz_attempts())

                    if self.descr.tasks['quiz_attempts']['fetch_metadata']:
                        asyncio.run(self._process_quiz_attempts_metadata())

                # Process task: Archive Moodle backups
                if self.descr.tasks['moodle_backups']:
                    asyncio.run(self._process_moodle_backups())

                # Transition to state: FINALIZING
                self.set_status(JobStatus.FINALIZING, notify_moodle=True)

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
                with TemporaryDirectory() as zipdir:
                    # Add files
                    archive_file = f'{zipdir}/{self.descr.archive_filename}.zip'
                    with zipfile.ZipFile(archive_file, 'w', Config.ZIP_COMPRESSION_ALGO) as archive:
                        for root, _, files in os.walk(self.workdir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, self.workdir)
                                archive.write(file_path, arcname=arcname)

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

    async def _process_quiz_attempts(self) -> None:
        """
        Renders all quiz attempts to HTML and PDF files

        :return: None
        """
        task = self.descr.tasks['quiz_attempts']
        os.makedirs(f'{self.workdir}/attempts', exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=['--disable-web-security'],  # Pass --disable-web-security to ignore CORS errors
                proxy={
                    'server': Config.PROXY_SERVER_URL,
                    'username': Config.PROXY_USERNAME,
                    'password': Config.PROXY_PASSWORD,
                    'bypass': Config.PROXY_BYPASS_DOMAINS,
                } if Config.PROXY_SERVER_URL else None,
            )
            context = await browser.new_context(
                viewport=ViewportSize(
                    width=int(Config.REPORT_BASE_VIEWPORT_WIDTH),
                    height=int(Config.REPORT_BASE_VIEWPORT_WIDTH / (16/9))
                ),
                ignore_https_errors=Config.SKIP_HTTPS_CERT_VALIDATION
            )
            context.set_default_navigation_timeout(Config.REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC * 1000)
            self.logger.debug("Spawned new playwright Browser and BrowserContext")

            for attemptid in task['attemptids']:
                if threading.current_thread().stop_requested():
                    raise InterruptedError('Thread stop requested')
                else:
                    # Process attempt
                    quiz_attempt_pdf_path = await self._render_quiz_attempt(
                        context,
                        attemptid,
                        task['paper_format']
                    )
                    if task['image_optimize']:
                        await self._compress_pdf(
                            file=quiz_attempt_pdf_path,
                            pdf_compression_level=6,
                            image_maxwidth=task['image_optimize']['width'],
                            image_maxheight=task['image_optimize']['height'],
                            image_quality=task['image_optimize']['quality']
                        )
                    if Config.PDFA_CONVERSION:
                        await self._convert_pdf_to_pdfa(
                            input_pdf_file=quiz_attempt_pdf_path,
                        )

                    # Report status
                    if time() >= self.last_moodle_status_update + Config.STATUS_REPORTING_INTERVAL_SEC:
                        self.set_status(
                            JobStatus.RUNNING,
                            statusextras={'progress': round((len(self.archived_attempts) / len(task['attemptids'])) * 100)},
                            notify_moodle=True
                        )
                    else:
                        self.logger.debug("Skipping status update because reporting interval has not been reached yet")

            await browser.close()
            self.logger.debug("Destroyed playwright Browser and BrowserContext")

    async def _render_quiz_attempt(self, bctx: BrowserContext, attemptid: int, paper_format: PaperFormat) -> Path:
        """
        Renders a complete quiz attempt to a PDF file

        :param attemptid: ID of the quiz attempt to render
        :param paper_format: Paper format to use for the PDF (e.g. 'A4')
        :return: Path of rendered PDF file
        """
        # Retrieve attempt data
        folder_name, attempt_name, attempt_html, attempt_attachments = self.moodle_api.get_attempt_data(
            self.get_id(),
            self.descr,
            attemptid
        )

        # Prepare attempt dir
        attempts_dir = f"{self.workdir}/attempts"
        os.makedirs(attempts_dir, exist_ok=True)

        attempt_dir = f"{attempts_dir}/{folder_name}"
        if os.path.isdir(attempt_dir):
            # Prepend unique attemptid to folder name if it already exists
            self.logger.warning(f"Attempt directory '{folder_name}' already exists. Using '{folder_name}_{attemptid}' instead.")
            folder_name = f"{folder_name}_{attemptid}"
            attempt_dir = f"{attempts_dir}/{folder_name}"

        os.makedirs(attempt_dir, exist_ok=False)

        # Save HTML DOM, if desired
        if self.descr.tasks['quiz_attempts']['keep_html_files']:
            with open(f"{attempt_dir}/{attempt_name}.html", "w+") as f:
                f.write(attempt_html)
            self.logger.debug(f"Saved HTML DOM of quiz attempt {attemptid} to {attempt_dir}/{attempt_name}.html")
        else:
            self.logger.debug(f"Skipping HTML DOM saving of quiz attempt {attemptid}")

        # Prepare new page
        await bctx.clear_cookies()
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

        # Aborts navigations to login page
        async def login_redirection_interceptor(route: Route):
            self.logger.warning(f'Prevented belated redirection to: {route.request.url}')
            await route.abort('blockedbyclient')

        # Removes javascript code that redirects to the login page
        # This can happen if ajax requests fail with permission errors due to missing sessions.
        # We alter the javascript code because we cannot prevent the redirection event once it is fired. Intercepting
        # the request after it fired may lead to situations where the HTML DOM of the attempt page is already
        # destructed, leading to empty pages and thus to blank PDF files.
        async def javascript_redirection_patcher(route: Route):
            try:
                # Perform request
                response = await route.fetch(timeout=Config.REQUEST_TIMEOUT_SEC if not Config.UNIT_TESTS_RUNNING else 0.1)

                # Remove code that redirects to the login page
                body_original = await response.text()
                body_patched = re.sub(
                    r'window\.location\s*=\s*URL\.relativeUrl\(\"/login/index.php\"\)',
                    'console.warn("Prevented redirect to /login/index.php")',
                    body_original
                )

                if body_patched != body_original:
                    self.logger.debug(f'Disabled javascript login page redirection code in {route.request.url}')

                # Return the patched response
                await route.fulfill(response=response, body=body_patched)
            except Exception as e:
                if Config.UNIT_TESTS_RUNNING:
                    self.logger.info(f'Failed to fetch and patch javascript resource {route.request.url}: {e}')
                    await route.abort()
                else:
                    self.logger.error(f'Failed to fetch and patch javascript resource {route.request.url}: {e}')
                    raise RuntimeError(f'Failed to fetch and patch javascript resource {route.request.url}: {e}')

        try:
            # Flush and re-register custom route handlers as required
            await bctx.unroute_all()
            await bctx.route(f"{self.moodle_api.base_url}/mock/attempt", mock_responder)
            if Config.PREVENT_REDIRECT_TO_LOGIN:
                await bctx.route('**/login/*.php', login_redirection_interceptor)
                await bctx.route('**/*.js', javascript_redirection_patcher)

            # Load attempt HTML
            await page.goto(f"{self.moodle_api.base_url}/mock/attempt")
        except Exception:
            self.logger.error(f'Page did not load after {Config.REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC} seconds. Aborting ...')
            raise

        # If in demo mode, inject watermark JS
        if Config.DEMO_MODE:
            await page.evaluate(DEMOMODE_JAVASCRIPT)

        # Wait for the page to report that is fully rendered, if enabled
        if Config.REPORT_WAIT_FOR_READY_SIGNAL:
            try:
                await self._wait_for_page_ready_signal(page)
            except Exception:
                if Config.REPORT_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT:
                    self.logger.warning(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds. Continuing ...')
                else:
                    self.logger.error(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds. Aborting ...')
                    raise RuntimeError(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds.')
        else:
            self.logger.debug('Not waiting for ready signal. Export immediately ...')

        # Save attempt page as PDF
        pdf_render_path = Path(f"{attempt_dir}/{attempt_name}.pdf")
        await page.pdf(
            path=pdf_render_path,
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
        self.archived_attempts[attemptid] = f"{attempt_dir}/{attempt_name}"

        return pdf_render_path

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
            await page.evaluate(READYSIGNAL_JAVASCRIPT)
            self.logger.debug(f'Waiting for ready signal: {ReportSignal.READY_FOR_EXPORT}')

            cmsg = await cmsg_handler.value
            self.logger.debug(f'Received signal: {cmsg}')

    async def _compress_pdf(
            self,
            file: Path,
            pdf_compression_level: int,
            image_maxwidth: int,
            image_maxheight: int,
            image_quality: int
    ) -> None:
        """
        Compresses a PDF file by resizing/compressing images and compressing content streams.
        Replaces the given file.

        :param file: Path to the PDF file to compress
        :param pdf_compression_level: Compression level for content streams (0-9)
        :param image_maxwidth: Maximum width of images in pixels
        :param image_maxheight: Maximum height of images in pixels
        :param image_quality: JPEG2000 compression quality (0-100)
        :return: None
        """

        # Dev notes:
        # (1) Page content stream compression did not much in our tests, but it's basically free, so we keep it without
        # making it configurable to the user for now.
        # (2) Re-writing the whole file after compression, as suggested by pypdf, does change nothing for us, since it
        # is already re-written during the image processing step.
        # (3) By far the greatest size reduction is achieved scaling down huge images, if people upload high-res images.

        old_filesize = os.path.getsize(file)
        self.logger.debug(f"Compressing PDF file: {file} (size: {old_filesize} bytes)")
        writer = PdfWriter(clone_from=file)

        img_idx = 0
        for page in writer.pages:
            for img in page.images:
                img_idx += 1

                # Do not touch images with transparency data (mode=RGBA).
                # See: https://github.com/python-pillow/Pillow/issues/8074
                if img.image.has_transparency_data:
                    self.logger.debug(f"  -> Skipping image {img_idx} on page {page.page_number} because it contains transparency data")
                    continue

                # Scale down large images
                if img.image.width > image_maxwidth or img.image.height > image_maxheight:
                    self.logger.debug(f"  -> Resizing image {img_idx} on page {page.page_number} from {img.image.width}x{img.image.height} px to fit into {image_maxwidth}x{image_maxheight} px")
                    img.image.thumbnail(size=(image_maxwidth, image_maxheight), resample=Resampling.LANCZOS)

                # Compress images
                self.logger.debug(f"  -> Replacing image {img_idx} on page {page.page_number} with quality {image_quality}")
                img.replace(
                    img.image,
                    quality=image_quality,
                    optimize=True,
                    progressive=False
                )

            self.logger.debug(f" -> Compressing PDF content streams on page {page.page_number} with level {pdf_compression_level}")
            page.compress_content_streams(level=pdf_compression_level)

        with open(file, "wb") as f:
            writer.write(f)
            new_filesize = os.path.getsize(file)
            size_percent = round((new_filesize / old_filesize) * 100, 2)
            self.logger.debug(f"  -> Saved compressed PDF as: {file} (size: {os.path.getsize(file)} bytes, {size_percent}% of original)")

    async def _convert_pdf_to_pdfa(self, input_pdf_file: Path) -> None:
        """
        Converts given PDF file to the PDF/A-3b format by invoking a ghostscript subprocess.
        Replaces the given file.

        :param input_pdf_file: Path to the PDF file to convert to PDF/A

        :return: None

        :raises RuntimeError: If the conversion process failes with status code != 0
        :raises TimeoutError: If the conversion process takes longer then allowed
        """

        def __generate_ghostscript_command_arguments(
                working_dir: Path,
                input_postscript_file: Path,
                input_pdf_file: Path,
                output_pdf_file: Path
        ) -> list[str]:
            """
            Generates a list of ghostscript command arguments for PDF/A conversion.

            :param working_dir: Path to the conversion working directory
            :input_postscript_file:  Path of the conversion postscript file
            :input_pdf_file: Path to the input PDF that should be converted
            :output_pdf_file: Path to store the converted output PDF to

            :return: List of command arguments as strings
            """

            return [
                # Allow required file reads and writes
                f'--permit-file-read="{working_dir.absolute()}"',
                f'--permit-file-read="{input_postscript_file.absolute()}"',
                f'--permit-file-read="{SRGB_ICC_COLOR_PROFILE_PATH.absolute()}"',
                f'--permit-file-write="{working_dir.absolute()}"',

                # Output to file instead of rendering
                '-sDEVICE=pdfwrite',

                # Configure PDF/A color conversion
                 '-sColorConversionStrategy=RGB',
                 '-dProcessColorModel=/DeviceRGB',
                f'-sOutputICCProfile="{SRGB_ICC_COLOR_PROFILE_PATH.absolute()}"',
                f'-sDefaultRGBProfile="{SRGB_ICC_COLOR_PROFILE_PATH.absolute()}"',

                # Set output file and PDF/A version
                '-dCompatibilityLevel=1.7',
                '-dPDFA=3',
                '-dPDFACompatibilityPolicy=1',

                # Configure compression and embedding
                '-dEmbedAllFonts=true',
                '-dSubsetFonts=true',
                '-dCompressFonts=true',
                '-dNOSUBSTFONTS=false',

                # Prevent halting on user input
                '-dNOPAUSE',
                '-dBATCH',
                '-dNOOUTERSAVE',

                # File I/O
                f'-sOutputFile="{output_pdf_file.absolute()}"',
                f'"{input_postscript_file.absolute()}"',
                f'"{input_pdf_file.absolute()}"'
            ]

        def __generate_postscript_file(
                working_dir: Path,
                color_profile_path: Path,
                title:str|None=None,
        ) -> Path:
            """
            Generates postscript file contents required for PDF/A conversion and writes them to disk.
            (Based on https://github.com/ArtifexSoftware/ghostpdl/blob/19820f3ae748450f5943fdd679d97b3ecd6d12c5/lib/PDFA_def.ps)

            :param working_dir: Path to the conversion working directory
            :color_profile_path:  Path of the icc color profile
            :title: Title metadata of the converted PDF file (optional)

            :return: Path to the generated postscript file within the working directory
            """

            pdf_metadata = {
                'MoodleQuizArchiveWorkerVersion': Config.VERSION,
            }
            if title is not None and title != "":
                pdf_metadata["Title"] = title

            file_content = "\n\r".join([
                '%!PS',

                # PDF file metadata
                f'[ {"\n\r  ".join(["/"+k+" ("+v+")" for k,v in pdf_metadata.items()])}',
                 '  /DOCINFO pdfmark',
                 '',

                # Configure icc profile
                 '[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark',
                 '[{icc_PDFA} << /N 3 >> /PUT pdfmark', # NOTE: N is always 3 because of sRGB profile
                f'[{{icc_PDFA}} ({color_profile_path.absolute()}) (r) file /PUT pdfmark',
                 '',

                # Configure output intent
                '[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark',
                '[{OutputIntent_PDFA} <<',
                '  /Type /OutputIntent',
                '  /S /GTS_PDFA1',
                '  /DestOutputProfile {icc_PDFA}',
                '  /OutputConditionIdentifier (sRGB)',
                '>> /PUT pdfmark',
                '[{Catalog} <</OutputIntents [ {OutputIntent_PDFA} ]>> /PUT pdfmark',
                ''
                # EOF
            ])

            file_path = Path(os.path.join(working_dir, "PDFA_def.ps"))

            with open(file=file_path, mode="w") as f:
                f.write(file_content)
                f.flush()
                f.close()

            return file_path

        self.logger.debug(f"Converting '{input_pdf_file.absolute()}' to PDF/A")

        with TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self.logger.debug(f"Using temporary directory for PDF/A conversion: '{tmpdir.absolute()}'.")

            # NOTE: Ghostscript can not convert the PDF file in place, therefore
            #       we write to a designated output file and replace the input
            #       file with it when the subprocess finished successfully.
            output_pdf_file = Path(os.path.join(tmpdir, "output.pdf"))

            postscript_file = __generate_postscript_file(
                working_dir=tmpdir,
                color_profile_path=SRGB_ICC_COLOR_PROFILE_PATH
            )

            command = "gs " + " ".join(
                __generate_ghostscript_command_arguments(
                    working_dir=tmpdir,
                    input_postscript_file=postscript_file,
                    input_pdf_file=input_pdf_file,
                    output_pdf_file=output_pdf_file
                )
            )

            self.logger.debug(f'Creating ghostscript subprocess as `{command}`.')
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    Config.PDFA_CONVERSION_TIMEOUT_SEC,
                )
                self.logger.debug(f"ghostscript subprocess stdout was: `{stdout.decode().strip()}`")
                self.logger.debug(f"ghostscript subprocess stderr was: `{stderr.decode().strip()}`")

                if proc.returncode != 0:
                    raise RuntimeError("ghostscript subprocess failed with status code != 0")

                os.replace(output_pdf_file.absolute(), input_pdf_file.absolute())
            except TimeoutError as te:
                self.logger.error("PDF/A conversion timed out")
                raise te
            except Exception as e:
                self.logger.error(f"PDF/A conversion failed: '{e}'")
                raise e

    async def _process_quiz_attempts_metadata(self) -> None:
        """
        Fetches metadata for all quiz attempts that should be archived and writes it to a CSV file

        :return: None
        """
        # Fetch metadata for all quiz attempts that should be archived
        metadata = self.moodle_api.get_attempts_metadata(
            self.get_id(),
            self.descr
        )

        # Add path to each entry for metadata processing
        for entry in metadata:
            entry['path'] = os.path.relpath(self.archived_attempts[int(entry['attemptid'])], self.workdir)

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
                for backup in self.descr.tasks['moodle_backups']:
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

        # Handle demo mode
        if Config.DEMO_MODE:
            self.logger.info(f'Demo mode: Skipping download of backup {backupid}. Replacing with placeholder ...')
            os.makedirs(f'{self.workdir}/backups', exist_ok=True)
            with open(f'{self.workdir}/backups/{filename}', 'w+') as f:
                f.write('!!!DEMO MODE!!!\r\nThis is a placeholder file for a Moodle backup.\r\n\r\nPlease disable demo mode to download the actual backups.')

            return

        # Wait for backup to finish
        while True:
            status = self.moodle_api.get_backup_status(self.id, self.descr, backupid)

            if threading.current_thread().stop_requested():
                raise InterruptedError('Thread stop requested')

            if status == MoodleBackupStatus.SUCCESS:
                break

            # Notify user about waiting
            self.logger.info(f'Backup {backupid} not finished yet. Waiting {Config.BACKUP_STATUS_RETRY_SEC} seconds before retrying ...')
            if self.get_status() != JobStatus.WAITING_FOR_BACKUP:
                self.set_status(JobStatus.WAITING_FOR_BACKUP, notify_moodle=True)

            # Wait for next backup status check
            await asyncio.sleep(Config.BACKUP_STATUS_RETRY_SEC)

        # Check backup filesize
        content_type, content_length = self.moodle_api.get_remote_file_metadata(download_url)

        if content_type != 'application/vnd.moodle.backup':
            # Try to get JSON content if debug logging is enabled to allow debugging
            if Config.LOG_LEVEL == logging.DEBUG:
                if content_type.startswith('application/json'):
                    # This request is kept here instead of the MoodleAPI wrapper because it is
                    # solely used for debugging purposes
                    session = RequestsFactory.create_session()
                    r = session.get(
                        url=download_url,
                        params={'token': self.moodle_api.wstoken},
                        allow_redirects=True
                    )
                    self.logger.debug(f'Backup file GET response: {r.text}')

            # Normal error handling
            raise RuntimeError(f'Backup Content-Type invalid. Expected "application/vnd.moodle.backup" but got "{content_type}"')

        if not content_length:
            self.logger.warning("Backup filesize could not be determined because 'Content-Length' HTTP header is missing. Trying to download anyways ...")
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
            jobdescriptor=self.descr,
            sha256sum=artifact_sha256sum,
            **upload_medata
        )
        self.logger.info('Processed uploaded artifact successfully.')

