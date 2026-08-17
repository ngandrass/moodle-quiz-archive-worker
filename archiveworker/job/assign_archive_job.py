# Moodle Archiving Worker
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
from archiveworker.workspace import SubmissionArtifact
from archiveworker.interruptable_thread import raise_error_if_stop_requested
from archiveworker.job.archive_job import ArchiveJob


class AssignArchiveJob(ArchiveJob):
    """
    Process logic for Moodle assignment archiving jobs
    """

    def _apply_demo_mode_limits(self) -> None:
        """
        Limits the number of assignment submissions to be processed in demo mode

        :return: None
        """
        if self.descr.tasks['assign_submissions']:
            self.logger.info("Demo mode: Only processing the first 10 assignment submissions!")
            if len(self.descr.tasks['assign_submissions']['submissionids']) > 10:
                self.descr.tasks['assign_submissions']['submissionids'] = self.descr.tasks['assign_submissions']['submissionids'][:10]

    async def _process_activity_tasks(self) -> None:
        """
        Processes all assignment-submission related tasks of this job

        :return: None
        """
        if self.descr.tasks['assign_submissions']:
            await self._process_assign_submissions()

            if self.descr.tasks['assign_submissions']['fetch_metadata']:
                await self._process_assign_submissions_metadata()

    async def _process_assign_submissions(self) -> None:
        """
        Processes all assignment submissions of this job (rendering, attachments,
        post-processing) and reports progress to Moodle

        :return: None
        """
        task = self.descr.tasks['assign_submissions']

        async with async_playwright() as p:
            browser, context = await report_renderer.launch_browser_and_context(p)
            self.logger.debug("Spawned new playwright Browser and BrowserContext")

            for submissionid in task['submissionids']:
                raise_error_if_stop_requested()

                # Process a single submission
                await self._process_assign_submission(
                    context,
                    submissionid,
                    task['paper_format'],
                    task['keep_html_files'],
                    task['image_optimize'],
                    task['attachments']
                )

                # Report status
                if time() >= self.last_moodle_status_update + Config.STATUS_REPORTING_INTERVAL_SEC:
                    self.set_status(
                        JobStatus.RUNNING,
                        statusextras={'progress': round((self.archived_items_count / len(task['submissionids'])) * 100)},
                        notify_moodle=True
                    )
                else:
                    self.logger.debug("Skipping status update because reporting interval has not been reached yet")

            await browser.close()
            self.logger.debug("Destroyed playwright Browser and BrowserContext")

    async def _process_assign_submission(
            self,
            bctx: BrowserContext,
            submissionid: int,
            paper_format: PaperFormat,
            keep_html_files: bool,
            image_optimize: Union[Dict, bool],
            attachment_types: Dict
    ) -> None:
        """
        Processes a single assignment submission: renders it to HTML/PDF, downloads
        its attachments, and applies the configured PDF post-processing
        (image optimization, PDF/A conversion)

        :param bctx: Playwright BrowserContext to render the submission with
        :param submissionid: ID of the assignment submission to process
        :param paper_format: Paper format to use for the PDF (e.g. 'A4')
        :param keep_html_files: Whether to keep the rendered HTML DOM as a separate file
        :param image_optimize: Image optimization settings to apply to the PDF, or False to skip
        :param attachment_types: Per-type attachment selection to respect when saving attachments
        :return: None
        """
        # Retrieve submission data and setup workspace
        folder_name, submission_name, submission_html, submission_attachments = self.moodle_api.get_submission_data(
            self.get_id(),
            self.descr,
            submissionid
        )
        submission_artifact = self.workspace.submission(submissionid, submission_name, folder_name)

        # Save HTML DOM, if desired
        if keep_html_files:
            html_report = submission_artifact.html_report(f"{submission_name}.html")
            with open(html_report.path, "w+") as f:
                f.write(submission_html)
            self.logger.debug(f"Saved HTML DOM of assignment submission {submissionid} to {html_report.path}")
        else:
            self.logger.debug(f"Skipping HTML DOM saving of assignment submission {submissionid}")

        # Render submission page as PDF
        pdf_report = submission_artifact.pdf_report(f"{submission_name}.pdf")
        await report_renderer.render_html_to_pdf(
            bctx=bctx,
            base_url=self.moodle_api.base_url,
            html=submission_html,
            paper_format=paper_format,
            output_path=pdf_report.path,
            logger=self.logger
        )
        self.logger.info(f"Generated \"{submission_name}\"")

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

        # Save submission attachments
        self._save_submission_attachments(submission_artifact, submission_attachments, attachment_types)

        self.archived_items_count += 1

    def _save_submission_attachments(
            self,
            submission_artifact: SubmissionArtifact,
            attachments: List[Dict],
            attachment_types: Dict
    ) -> None:
        """
        Downloads and saves all given attachments of an assignment submission,
        respecting the per-type attachment selection

        :param submission_artifact: Workspace artifact of the assignment submission the attachments belong to
        :param attachments: Attachments to download, as returned by the Moodle API
        :param attachment_types: Per-type attachment selection to respect when saving attachments
        :return: None
        """
        if not attachments:
            self.logger.debug('No attachments to save')
            return

        self.logger.debug(f"Saving {len(attachments)} attachments ...")
        for attachment in attachments:
            if not attachment_types.get(attachment['type'], True):
                self.logger.debug(f'Skipping {attachment["type"]} attachment {attachment["filename"]} (disabled by job descriptor)')
                continue

            attachment_artifact = submission_artifact.attachment(
                attachment['type'],
                attachment['filename']
            )

            downloaded_bytes = self.moodle_api.download_moodle_file(
                download_url=attachment['downloadurl'],
                target_file=attachment_artifact.path,
                sha1sum_expected=attachment['contenthash'],
                maxsize_bytes=Config.QUESTION_ATTACHMENT_DOWNLOAD_MAX_FILESIZE_BYTES
            )

            self.logger.info(f'Downloaded {downloaded_bytes} bytes of {attachment["type"]} attachment {attachment["filename"]} to {attachment_artifact.path}')

    async def _process_assign_submissions_metadata(self) -> None:
        """
        Fetches metadata for all assignment submissions that should be archived and writes it to a CSV file

        :return: None
        """
        # Fetch metadata for all assignment submissions that should be archived
        metadata = self.moodle_api.get_submissions_metadata(
            self.get_id(),
            self.descr
        )

        # Add path to each entry for metadata processing
        submission_artifacts = {
            artifact.submission.id: artifact
            for artifact in self.workspace.get_artifacts(type_filter=SubmissionArtifact.PdfReport)
        }
        for entry in metadata:
            submission_id = int(entry['submissionid'])
            if submission_id not in submission_artifacts.keys():
                raise RuntimeError("Submission artifact is missing from workspace to populate assignment submissions metadata")
            (file_path, file_name) = self._archive_organizer.organize(submission_artifacts[submission_id])
            entry['path'] = f'{file_path}/{file_name}'.lstrip('/')

        # Write metadata to CSV file
        submissions_metadata_artifact = self.workspace.file('submissions_metadata.csv')
        with open(submissions_metadata_artifact.path, 'w+') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=metadata[0].keys(),
                delimiter=',',
                quotechar='"',
                quoting=csv.QUOTE_NONNUMERIC
            )
            writer.writeheader()
            writer.writerows(metadata)

        self.logger.info(f"Wrote metadata for {len(metadata)} assignment submissions to CSV file")
