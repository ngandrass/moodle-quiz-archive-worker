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

import os
import random
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

class ArchivingArtifact:
    """
    Represents a file artifact to be archived, with a unique path and name.
    """
    def __init__(self, workspace: 'Workspace', file_name: str):
        self.name: str = file_name
        self.path: Path = Path(
            workspace._artifacts_base_path,
            f'{random.randint(0,int(10e9-1)):010d}.{file_name}'
        )

class AttemptArtifact():
    """
    Represents an attempt artifact, which may include reports and attachments
    for a quiz attempt.
    """
    class PdfReport(ArchivingArtifact):
        """
        Represents a PDF report artifact for a quiz attempt.
        """
        def __init__(self, workspace, file_name, attempt: 'AttemptArtifact'):
            super().__init__(workspace, file_name)
            self.attempt = attempt

    class HtmlReport(ArchivingArtifact):
        """
        Represents an HTML report artifact for a quiz attempt.
        """
        def __init__(self, workspace, file_name, attempt: 'AttemptArtifact'):
            super().__init__(workspace, file_name)
            self.attempt = attempt

    class Attachment(ArchivingArtifact):
        """
        Represents an attachment artifact for a quiz attempt.
        """
        def __init__(self, workspace: 'Workspace', file_name: str, attempt: 'AttemptArtifact', slot: int):
            """
            Initializes an Attachment artifact.

            :param workspace: The Workspace instance
            :param file_name: The name of the attachment file
            :param attempt: The parent AttemptArtifact
            :param slot: The slot number for the attachment
            """
            super().__init__(workspace, file_name)
            self.attempt = attempt
            self.slot = slot

    def __init__(self, workspace: 'Workspace', id: int, name: str, dir_name: str):
        """
        Initializes an AttemptArtifact instance.

        :param workspace: The corresponding Workspace instance
        :param id: The attempt ID
        :param name: The attempt name
        :param dir_name: The directory name for the attempt
        """
        self._workspace = workspace
        self.id = id
        self.name = name
        self.dir = dir_name

    def pdf_report(self, file_name: str) -> PdfReport:
        """
        Creates and adds a PDF report artifact for this attempt.

        :param file_name: The name of the PDF file
        :return: The created PdfReport artifact
        """
        pdf_report = AttemptArtifact.PdfReport(self._workspace, file_name, self)
        self._workspace.add_artifact(pdf_report)
        return pdf_report

    def html_report(self, file_name: str) -> HtmlReport:
        """
        Creates and adds an HTML report artifact for this attempt.

        :param file_name: The name of the HTML file
        :return: The created HtmlReport artifact
        """
        html_report = AttemptArtifact.HtmlReport(self._workspace, file_name, self)
        self._workspace.add_artifact(html_report)
        return html_report

    def attachment(self, slot: int, file_name: str) -> Attachment:
        """
        Creates and adds an attachment artifact for this attempt.

        :param slot: The slot number for the attachment
        :param file_name: The name of the attachment file
        :return: The created Attachment artifact
        """
        attachment = AttemptArtifact.Attachment(
            self._workspace,
            file_name,
            self,
            slot
        )
        self._workspace.add_artifact(attachment)
        return attachment


class BackupArtifact(ArchivingArtifact):
    """
    Represents a backup artifact to be archived.
    """
    pass


class Workspace(TemporaryDirectory):
    """
    Manages a temporary workspace for collecting and organizing artifacts before
    archiving.
    """
    def __init__(self):
        """
        Initializes the Workspace, creating directories for artifacts and
        temporary files.
        """
        super().__init__(prefix='mqaw_')
        self._artifacts_base_path: Path = Path(self.name, 'artifacts')
        os.makedirs(self._artifacts_base_path, exist_ok=True)

        self._tmp_base_path: Path = Path(self.name, 'tmp')
        os.makedirs(self._tmp_base_path, exist_ok=True)

        self._artifacts: list[ArchivingArtifact] = []
        self._attempt_folders: dict[int, str] = {}


    def __enter__(self):
        """
        Enters the context manager for the workspace.
        :return: Workspace (self)
        """
        return self


    def add_artifact(self, artifact: AttemptArtifact):
        """
        Adds an artifact to the workspace.

        :param artifact: The artifact to add
        """
        self._artifacts.append(artifact)


    def get_artifacts[T: ArchivingArtifact](self, type_filter: type[T] | None = None) -> list[T]:
        """
        Returns all artifacts, optionally filtered by type.

        :param type_filter: Optional type to filter artifacts
        :return: List of artifacts (optionally filtered)
        """
        if type_filter is None:
            return self._artifacts
        else:
            return [artifact for artifact in self._artifacts if isinstance(artifact, type_filter)]


    def attempt(self, id: int, name: str, dir_name: str) -> AttemptArtifact:
        """
        Creates a new AttemptArtifact and ensures unique attempt directories.

        :param id: The attempt ID
        :param name: The attempt name
        :param dir_name: The directory name for the attempt
        :return: The created AttemptArtifact
        """
        # Check if the attempt folders are unique
        if dir_name in self._attempt_folders.values():
            dir_name_override = f'{dir_name}_{id}'
            logging.getLogger().warning(
                f'Attempt directory "{dir_name}" already exists. Using "{dir_name_override}" instead. Check your attempt folder naming!'
            )
            dir_name = dir_name_override
        self._attempt_folders[id] = dir_name

        attempt_artifact = AttemptArtifact(self, id, name, dir_name)
        return attempt_artifact


    def backup(self, file_name: str) -> BackupArtifact:
        """
        Creates and adds a backup artifact to the workspace.

        :param file_name: The name of the backup file
        :return: The created BackupArtifact
        """
        backup_artifact = BackupArtifact(self, file_name)
        self.add_artifact(backup_artifact)
        return backup_artifact


    def file(self, file_name: str) -> ArchivingArtifact:
        """
        Creates and adds a generic file artifact to the workspace.

        :param file_name: The name of the file
        :return: The created ArchivingArtifact
        """
        artifact = ArchivingArtifact(self, file_name)
        self.add_artifact(artifact)
        return artifact


    def tmp_dir(self) -> TemporaryDirectory:
        """
        Creates a new temporary directory within the workspace.

        :return: A TemporaryDirectory instance
        """
        return TemporaryDirectory(dir=self._tmp_base_path)
