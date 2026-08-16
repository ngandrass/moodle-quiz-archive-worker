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

import hashlib
import logging
import os
import zipfile
from pathlib import Path
from abc import ABCMeta, abstractmethod

from archiveworker.workspace import Workspace, ArchivingArtifact, AttemptArtifact, SubmissionArtifact, BackupArtifact
from archiveworker.interruptable_thread import raise_error_if_stop_requested

class ArchiveOrganizer(metaclass=ABCMeta):
    """
    Abstract base class for organizing artifacts within an archive. Subclasses
    must implement the organize method to determine the archive path and file
    name for a given artifact.
    """

    @abstractmethod
    def organize(self, artifact: ArchivingArtifact) -> tuple[str, str]:
        """
        Organizes artifact by providing file path and name.

        :param artifact: Artifact to be organized.
        :return: tuple with (file_path, file_name)
        """
        pass


class HierarchicalArchiveOrganizer(ArchiveOrganizer):
    """
    Organizes artifacts in a hierarchical structure based on their type and
    context.
    """

    def organize(self, artifact: ArchivingArtifact) -> tuple[str, str]:

        if not isinstance(artifact, ArchivingArtifact):
            raise RuntimeError(
                f'Expected (sub-)class of type "{ArchivingArtifact.__name__}" but got "{type(artifact).__name__}"'
            )
        elif (
            isinstance(artifact, AttemptArtifact.PdfReport) or
            isinstance(artifact, AttemptArtifact.HtmlReport)
        ):
            attempt = artifact.attempt
            return (
                f"attempts/{attempt.dir}",
                artifact.name
            )
        elif isinstance(artifact, AttemptArtifact.Attachment):
            attempt = artifact.attempt
            return (
                f"attempts/{attempt.dir}/attachments/{artifact.slot}",
                artifact.name
            )
        elif (
                isinstance(artifact, SubmissionArtifact.PdfReport) or
                isinstance(artifact, SubmissionArtifact.HtmlReport)
        ):
            submission = artifact.submission
            return (
                f"submissions/{submission.dir}",
                artifact.name
            )
        elif isinstance(artifact, SubmissionArtifact.Attachment):
            submission = artifact.submission
            return (
                f"submissions/{submission.dir}/{artifact.type}",
                artifact.name
            )
        elif isinstance(artifact, BackupArtifact):
            return (
                "backups",
                artifact.name
            )
        elif type(artifact) == ArchivingArtifact:
            return ("", artifact.name)
        else:
            raise NotImplementedError(
                f'Missing organization mapping for class {type(artifact).__name__}'
            )


class FlatArchiveOrganizer(ArchiveOrganizer):
    """
    Organizes all artifacts in a flat structure, prefixing file names to
    identify conflicts different artifact types.
    """

    def organize(self, artifact: ArchivingArtifact) -> tuple[str, str]:

        if not isinstance(artifact, ArchivingArtifact):
            raise RuntimeError(
                f'Expected (sub-)class of type "{ArchivingArtifact.__name__}" but got "{type(artifact).__name__}"'
            )
        elif (
            isinstance(artifact, AttemptArtifact.PdfReport) or
            isinstance(artifact, AttemptArtifact.HtmlReport)
        ):
            attempt = artifact.attempt
            return (
                "",
                f"attempt_{attempt.id}.{artifact.name}"
            )
        elif isinstance(artifact, AttemptArtifact.Attachment):
            attempt = artifact.attempt
            return (
                "",
                f"attempt_{attempt.id}.{attempt.name}.attachment.{artifact.slot}.{artifact.name}"
            )
        elif (
                isinstance(artifact, SubmissionArtifact.PdfReport) or
                isinstance(artifact, SubmissionArtifact.HtmlReport)
        ):
            submission = artifact.submission
            return (
                "",
                f"submission_{submission.id}.{artifact.name}"
            )
        elif isinstance(artifact, SubmissionArtifact.Attachment):
            submission = artifact.submission
            return (
                "",
                f"submission_{submission.id}.{submission.name}.{artifact.type}.{artifact.name}"
            )
        elif isinstance(artifact, BackupArtifact):
            return (
                "",
                f"backup.{artifact.name}"
            )
        elif type(artifact) == ArchivingArtifact:
            return ("", artifact.name)
        else:
            raise NotImplementedError(
                f'Missing organization mapping for class {type(artifact).__name__}'
            )


class ArchiveBuilder:
    """
    Builds an archive from workspace artifacts using a specified organizer
    and compression algorithm.
    """
    def __init__(
        self,
        organizer: ArchiveOrganizer,
        calculate_file_hashes: bool,
        compression_algorithm: int,
    ):
        """
        Initializes the ArchiveBuilder.

        :param organizer: The ArchiveOrganizer to use for organizing artifacts
        :param calculate_file_hashes: Whether to include SHA256 hashes for files
        :param compression_algorithm: Compression algorithm for the archive (e.g., zipfile.ZIP_DEFLATED)
        """
        self._organizer = organizer
        self._include_file_hashes = calculate_file_hashes
        self._compression_algorithm = compression_algorithm

    def write(self, workspace: Workspace, archive_file_path: Path):
        """
        Writes all artifacts from the workspace into a zip archive at the
        specified path.

        :param workspace: The Workspace containing artifacts to archive
        :param archive_file_path: The path to the output archive file
        :raises ValueError: If writing to archive failes
        :raises RuntimeError: If file too archive is to large
        :raises InterruptedError: If the thread was requested to stop
        """

        file_count: dict[str, int] = {}

        with zipfile.ZipFile(
            archive_file_path,
            'w',
            self._compression_algorithm
        ) as archive:

            for artifact in workspace.get_artifacts():
                (path, name) = self._organizer.organize(artifact)
                zip_file_name = f'{path}/{name}'.lstrip('/')

                # Ensure unique file paths
                if zip_file_name in file_count:
                    file_count[zip_file_name] += 1
                    file_path, file_ext = os.path.splitext(zip_file_name)
                    zip_file_name_override = f'{file_path}({file_count[zip_file_name]}){file_ext}'
                    logging.warning(
                        f'File path "{zip_file_name}" was already used by another artifact. Check your attempt folder and report naming! Will use "{zip_file_name_override}" instead. Can not update metadata file!'
                    )
                    zip_file_name = zip_file_name_override
                else:
                    file_count[zip_file_name] = 0

                archive.write(artifact.path, arcname=zip_file_name)

                if self._include_file_hashes:
                    with open(artifact.path, 'rb') as f:
                        sha256_hash = hashlib.sha256()
                        for byte_block in iter(lambda: f.read(4096), b""):
                            raise_error_if_stop_requested()

                            sha256_hash.update(byte_block)
                        archive.writestr(f'{zip_file_name}.sha256', sha256_hash.hexdigest())
