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
import hashlib
import logging
from abc import ABCMeta, abstractmethod
from pathlib import Path
from time import time
from typing import Dict
from uuid import UUID

from config import Config
from archiveworker.type import JobStatus, MoodleBackupStatus
from archiveworker.api.worker import ArchiveJobDescriptor
from archiveworker.requests_factory import RequestsFactory
from archiveworker.workspace import Workspace
from archiveworker.archive_builder import ArchiveBuilder, HierarchicalArchiveOrganizer, FlatArchiveOrganizer
from archiveworker.interruptable_thread import raise_error_if_stop_requested


class ArchiveJob(metaclass=ABCMeta):
    """
    Abstract base class for a single archive job that is processed by the
    archive worker. Handles the generic job lifecycle (status bookkeeping,
    workspace setup, final archive assembly, upload to Moodle) that is shared
    by all activity types. Concrete subclasses implement the activity-specific
    data fetching and rendering (e.g. for quiz attempts or assignment
    submissions).
    """

    def __init__(self, jobid: UUID, descriptor: ArchiveJobDescriptor) -> None:
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED
        self.descr = descriptor
        self.moodle_api = descriptor.moodle_api
        self.statusextras = None
        self.last_moodle_status_update = None
        self.workspace: Workspace = None
        self._archive_organizer = (
            FlatArchiveOrganizer()
            if descriptor.archive_flatten
            else HierarchicalArchiveOrganizer()
        )
        self.archived_items_count = 0
        self.logger = logging.getLogger(f"{__name__}::<{self.id}>")

        # Limit amount of activity-specific work to be done in demo mode
        if Config.DEMO_MODE:
            self._apply_demo_mode_limits()

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
            with Workspace() as workspace:
                self.workspace = workspace
                self.logger.debug(f"Using temporary workspace directory: {self.workspace.name}")

                # Process activity-specific tasks (e.g. quiz attempts, assignment submissions)
                asyncio.run(self._process_activity_tasks())

                # Process task: Archive Moodle backups
                if self.descr.tasks['moodle_backups']:
                    asyncio.run(self._process_moodle_backups())

                # Transition to state: FINALIZING
                self.set_status(JobStatus.FINALIZING, notify_moodle=True)

                # Create final archive
                self.logger.info("Generating final archive ...")
                with self.workspace.tmp_dir() as zipdir:
                    zipdir = Path(zipdir)

                    archive_file_path = Path(zipdir, f'{self.descr.archive_filename}.zip')

                    ArchiveBuilder(
                        self._archive_organizer,
                        self.descr.archive_filehashes,
                        Config.ZIP_COMPRESSION_ALGO
                    ).write(self.workspace, archive_file_path)

                    # Calculate checksum
                    with open(archive_file_path, 'rb') as f:
                        archive_sha256sum = hashlib.sha256()
                        for byte_block in iter(lambda: f.read(4096), b""):
                            raise_error_if_stop_requested()
                            archive_sha256sum.update(byte_block)

                    # Push final file to Moodle
                    self._push_artifact_to_moodle(
                        archive_file_path,
                        archive_sha256sum.hexdigest()
                    )
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

        backup_artifact = self.workspace.backup(filename)

        # Handle demo mode
        if Config.DEMO_MODE:
            self.logger.info(f'Demo mode: Skipping download of backup {backupid}. Replacing with placeholder ...')

            with open(backup_artifact.path, 'w+') as f:
                f.write('!!!DEMO MODE!!!\r\nThis is a placeholder file for a Moodle backup.\r\n\r\nPlease disable demo mode to download the actual backups.')

            return

        # Wait for backup to finish
        while True:
            status = self.moodle_api.get_backup_status(self.id, self.descr, backupid)

            raise_error_if_stop_requested()

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
            target_file=backup_artifact.path,
            maxsize_bytes=Config.BACKUP_DOWNLOAD_MAX_FILESIZE_BYTES,
        )

        self.logger.info(f'Downloaded {downloaded_bytes} bytes of backup {backupid} to {backup_artifact.path}')

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

    @abstractmethod
    async def _process_activity_tasks(self) -> None:
        """
        Processes all activity-specific tasks of this job (e.g. rendering quiz
        attempts or assignment submissions to PDF). Called exactly once from
        execute(), before Moodle backups are processed.

        :return: None
        """
        pass

    @abstractmethod
    def _apply_demo_mode_limits(self) -> None:
        """
        Limits the amount of activity-specific work to be done when demo mode
        is enabled (e.g. by truncating the list of items to be processed).
        Called from __init__ when Config.DEMO_MODE is enabled.

        :return: None
        """
        pass
