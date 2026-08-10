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

import csv
from time import time
from typing import Dict, List, Union

from playwright.async_api import async_playwright, BrowserContext

from config import Config
from archiveworker import report_renderer
from archiveworker.type import JobStatus, PaperFormat
from archiveworker.workspace import AttemptArtifact
from archiveworker.interruptable_thread import raise_error_if_stop_requested
from archiveworker.job.archive_job import ArchiveJob


class QuizArchiveJob(ArchiveJob):
    """
    Concrete ArchiveJob implementation that archives Moodle quiz attempts
    """

    def _apply_demo_mode_limits(self) -> None:
        """
        Limits the number of quiz attempts to be processed in demo mode

        :return: None
        """
        if self.descr.tasks['quiz_attempts']:
            self.logger.info("Demo mode: Only processing the first 10 quiz attempts!")
            if len(self.descr.tasks['quiz_attempts']['attemptids']) > 10:
                self.descr.tasks['quiz_attempts']['attemptids'] = self.descr.tasks['quiz_attempts']['attemptids'][:10]

    async def _process_activity_tasks(self) -> None:
        """
        Processes all quiz activity related tasks of this job

        :return: None
        """
        if self.descr.tasks['quiz_attempts']:
            await self._process_quiz_attempts()

            if self.descr.tasks['quiz_attempts']['fetch_metadata']:
                await self._process_quiz_attempts_metadata()

    async def _process_quiz_attempts(self) -> None:
        """
        Processes all quiz attempts of this job (rendering, attachments,
        post-processing) and reports progress to Moodle

        :return: None
        """
        task = self.descr.tasks['quiz_attempts']

        async with async_playwright() as p:
            browser, context = await report_renderer.launch_browser_and_context(p)
            self.logger.debug("Spawned new playwright Browser and BrowserContext")

            for attemptid in task['attemptids']:
                raise_error_if_stop_requested()

                # Process a single attempt
                await self._process_quiz_attempt(
                    context,
                    attemptid,
                    task['paper_format'],
                    task['keep_html_files'],
                    task['image_optimize']
                )

                # Report status
                if time() >= self.last_moodle_status_update + Config.STATUS_REPORTING_INTERVAL_SEC:
                    self.set_status(
                        JobStatus.RUNNING,
                        statusextras={'progress': round((self.archived_items_count / len(task['attemptids'])) * 100)},
                        notify_moodle=True
                    )
                else:
                    self.logger.debug("Skipping status update because reporting interval has not been reached yet")

            await browser.close()
            self.logger.debug("Destroyed playwright Browser and BrowserContext")

    async def _process_quiz_attempt(
            self,
            bctx: BrowserContext,
            attemptid: int,
            paper_format: PaperFormat,
            keep_html_files: bool,
            image_optimize: Union[Dict, bool]
    ) -> None:
        """
        Processes a single quiz attempt: renders it to HTML/PDF, downloads
        its attachments, and applies the configured PDF post-processing
        (image optimization, PDF/A conversion)

        :param bctx: Playwright BrowserContext to render the attempt with
        :param attemptid: ID of the quiz attempt to process
        :param paper_format: Paper format to use for the PDF (e.g. 'A4')
        :param keep_html_files: Whether to keep the rendered HTML DOM as a separate file
        :param image_optimize: Image optimization settings to apply to the PDF, or False to skip
        :return: None
        """
        # Retrieve attempt data and setup workspace
        folder_name, attempt_name, attempt_html, attempt_attachments = self.moodle_api.get_attempt_data(
            self.get_id(),
            self.descr,
            attemptid
        )
        attempt_artifact = self.workspace.attempt(attemptid, attempt_name, folder_name)

        # Save HTML DOM, if desired
        if keep_html_files:
            html_report = attempt_artifact.html_report(f"{attempt_name}.html")
            with open(html_report.path, "w+") as f:
                f.write(attempt_html)
            self.logger.debug(f"Saved HTML DOM of quiz attempt {attemptid} to {html_report.path}")
        else:
            self.logger.debug(f"Skipping HTML DOM saving of quiz attempt {attemptid}")

        # Render attempt page as PDF
        pdf_report = attempt_artifact.pdf_report(f"{attempt_name}.pdf")
        await report_renderer.render_html_to_pdf(
            bctx=bctx,
            base_url=self.moodle_api.base_url,
            html=attempt_html,
            paper_format=paper_format,
            output_path=pdf_report.path,
            logger=self.logger
        )
        self.logger.info(f"Generated \"{attempt_name}\"")

        # Post-process rendered PDF
        if image_optimize:
            await report_renderer.compress_pdf(
                file=pdf_report.path,
                pdf_compression_level=6,
                image_maxwidth=image_optimize['width'],
                image_maxheight=image_optimize['height'],
                image_quality=image_optimize['quality'],
                logger=self.logger
            )
        if Config.PDFA_CONVERSION:
            await report_renderer.convert_pdf_to_pdfa(
                input_pdf_file=pdf_report.path,
                tmp_dir_factory=self.workspace.tmp_dir,
                logger=self.logger
            )

        # Save attempt attachments
        self._save_attempt_attachments(attempt_artifact, attempt_attachments)

        self.archived_items_count += 1

    def _save_attempt_attachments(self, attempt_artifact: AttemptArtifact, attachments: List[Dict]) -> None:
        """
        Downloads and saves all given attachments of a quiz attempt

        :param attempt_artifact: Workspace artifact of the quiz attempt the attachments belong to
        :param attachments: Attachments to download, as returned by the Moodle API
        :return: None
        """
        if not attachments:
            self.logger.debug('No attachments to save')
            return

        self.logger.debug(f"Saving {len(attachments)} attachments ...")
        for attachment in attachments:
            attachment_artifact = attempt_artifact.attachment(
                attachment['slot'],
                attachment['filename']
            )

            downloaded_bytes = self.moodle_api.download_moodle_file(
                download_url=attachment['downloadurl'],
                target_file=attachment_artifact.path,
                sha1sum_expected=attachment['contenthash'],
                maxsize_bytes=Config.QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES
            )

            self.logger.info(f'Downloaded {downloaded_bytes} bytes of quiz slot {attachment["slot"]} attachment {attachment["filename"]} to {attachment_artifact.path}')

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
        attempt_artifacts = {
            artifact.attempt.id: artifact
            for artifact in self.workspace.get_artifacts(type_filter=AttemptArtifact.PdfReport)
        }
        for entry in metadata:
            attempt_id = int(entry['attemptid'])
            if attempt_id not in attempt_artifacts.keys():
                raise RuntimeError("Attempt artifact is missing from workspace to populate quiz attempts metadata")
            (file_path, file_name) = self._archive_organizer.organize(attempt_artifacts[attempt_id])
            entry['path'] = f'{file_path}/{file_name}'.lstrip('/')

        # Write metadata to CSV file
        attempts_metadata_artifact = self.workspace.file('attempts_metadata.csv')
        with open(attempts_metadata_artifact.path, 'w+') as f:
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
