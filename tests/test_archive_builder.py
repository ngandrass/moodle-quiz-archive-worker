import os
import hashlib
import logging
import zipfile
import tempfile

import pytest

from archiveworker.archive_builder import ArchiveOrganizer, FlatArchiveOrganizer, HierarchicalArchiveOrganizer, ArchiveBuilder
from archiveworker.workspace import Workspace, ArchivingArtifact


class TestArchiveOrganizer:
    """Tests for the abstract archive organizer contract."""

    def test_archive_organizer_is_abstract(self) -> None:
        """The base organizer should not be instantiable directly."""

        with pytest.raises(TypeError):
            ArchiveOrganizer()


class TestHierarchicalArchiveOrganizer:
    """Tests for the hierarchical archive organizer."""

    def test_place_pdf_reports_in_attempt_folder(self) -> None:
        """PDF report artifacts should be grouped by their attempt directory."""

        with Workspace() as workspace:
            attempt = workspace.attempt(7, "Attempt 7", "attempt-7")
            artifact = attempt.pdf_report("report.pdf")

            path, name = HierarchicalArchiveOrganizer().organize(artifact)

            assert path == "attempts/attempt-7"
            assert name == "report.pdf"

    def test_place_attachments_in_slot_folder(self) -> None:
        """Attachments should be organized under the attempt folder and slot subfolder."""

        with Workspace() as workspace:
            attempt = workspace.attempt(9, "Attachment attempt", "attempt-9")
            artifact = attempt.attachment(3, "answer.txt")

            path, name = HierarchicalArchiveOrganizer().organize(artifact)

            assert path == "attempts/attempt-9/attachments/3"
            assert name == "answer.txt"

    def test_place_backups_in_backups_folder(self) -> None:
        """Backup artifacts should be placed in the backups folder."""

        with Workspace() as workspace:
            artifact = workspace.backup("backup.mbz")

            path, name = HierarchicalArchiveOrganizer().organize(artifact)

            assert path == "backups"
            assert name == "backup.mbz"

    def test_place_generic_artifacts_at_root(self) -> None:
        """Generic artifacts should remain at the archive root."""

        with Workspace() as workspace:
            artifact = workspace.file("notes.txt")

            path, name = HierarchicalArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "notes.txt"


class TestFlatArchiveOrganizer:
    """Tests for the flat archive organizer."""

    def test_prefixes_report_names(self) -> None:
        """Report artifacts should be prefixed with attempt to avoid collisions."""

        with Workspace() as workspace:
            attempt = workspace.attempt(11, "Attempt 11", "attempt-11")
            artifact = attempt.pdf_report("report.pdf")

            path, name = FlatArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "attempt_11.report.pdf"

    def test_prefixes_attachment_names(self) -> None:
        """Attachment artifacts should carry an attachment-specific prefix."""

        with Workspace() as workspace:
            attempt = workspace.attempt(12, "Attempt 12", "attempt-12")
            artifact = attempt.attachment(2, "answer.png")

            path, name = FlatArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "attempt_12.Attempt 12.attachment.2.answer.png"

    def test_prefixes_backup_names(self) -> None:
        """Backup artifacts should be prefixed to avoid collisions."""

        with Workspace() as workspace:
            artifact = workspace.backup("backup.mbz")

            path, name = FlatArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "backup.backup.mbz"

    def test_keeps_generic_artifacts_flat(self) -> None:
        """Generic artifacts should be stored directly as their original filename."""

        with Workspace() as workspace:
            artifact = workspace.file("notes.txt")

            path, name = FlatArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "notes.txt"

    def test_place_submission_reports_in_submission_folder(self) -> None:
        """Submission report artifacts should be grouped by their submission directory."""

        with Workspace() as workspace:
            submission = workspace.submission(7, "Submission 7", "submission-7")
            artifact = submission.pdf_report("report.pdf")

            path, name = HierarchicalArchiveOrganizer().organize(artifact)

            assert path == "submissions/submission-7"
            assert name == "report.pdf"

    def test_place_submission_attachments_in_type_folder(self) -> None:
        """Submission attachments should be organized under the submission folder and type subfolder."""

        with Workspace() as workspace:
            submission = workspace.submission(9, "Attachment submission", "submission-9")
            artifact = submission.attachment("feedback", "comment.txt")

            path, name = HierarchicalArchiveOrganizer().organize(artifact)

            assert path == "submissions/submission-9/feedback"
            assert name == "comment.txt"

    def test_prefixes_submission_report_names(self) -> None:
        """Submission report artifacts should be prefixed with submission id to avoid collisions."""

        with Workspace() as workspace:
            submission = workspace.submission(11, "Submission 11", "submission-11")
            artifact = submission.pdf_report("report.pdf")

            path, name = FlatArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "submission_11.report.pdf"

    def test_prefixes_submission_attachment_names(self) -> None:
        """Submission attachment artifacts should carry an attachment-specific prefix."""

        with Workspace() as workspace:
            submission = workspace.submission(12, "Submission 12", "submission-12")
            artifact = submission.attachment("submission", "answer.png")

            path, name = FlatArchiveOrganizer().organize(artifact)

            assert path == ""
            assert name == "submission_12.Submission 12.submission.answer.png"


class TestArchiveOrganizerArtifactCoverage:
    """
    Regression guard: every concrete artifact type the Workspace can produce
    must be handled by both organizers without raising. This is meant to fail
    loudly if a future artifact type is added without a matching organizer
    branch.
    """

    @staticmethod
    def _build_one_of_every_artifact(workspace: Workspace) -> list[ArchivingArtifact]:
        attempt = workspace.attempt(1, "Attempt", "attempt-dir")
        submission = workspace.submission(1, "Submission", "submission-dir")

        return [
            workspace.file("generic.txt"),
            workspace.backup("backup.mbz"),
            attempt.pdf_report("attempt-report.pdf"),
            attempt.html_report("attempt-report.html"),
            attempt.attachment(1, "attempt-attachment.txt"),
            submission.pdf_report("submission-report.pdf"),
            submission.html_report("submission-report.html"),
            submission.attachment("feedback", "submission-attachment.txt"),
        ]

    def test_all_known_artifact_types_are_organizable(self) -> None:
        """Both organizers must handle every concrete artifact type without raising."""

        for organizer in [HierarchicalArchiveOrganizer(), FlatArchiveOrganizer()]:
            with Workspace() as workspace:
                for artifact in self._build_one_of_every_artifact(workspace):
                    path, name = organizer.organize(artifact)
                    assert isinstance(path, str)
                    assert isinstance(name, str)


class TestArchiveBuilder:
    """Tests for the archive builder."""

    def test_builder_writes_artifacts_using_the_selected_organizer(self) -> None:
        """The builder should write entries according to the organizer output."""

        for organizer in [HierarchicalArchiveOrganizer(), FlatArchiveOrganizer()]:

            with tempfile.TemporaryDirectory() as tempdir:

                with Workspace() as workspace:
                    attempt = workspace.attempt(1, "Attempt 1", "attempt-1")
                    report = attempt.pdf_report("report.pdf")
                    report.path.write_text("report data", encoding="utf-8")
                    backup = workspace.backup("backup.mbz")
                    backup.path.write_text("backup data", encoding="utf-8")
                    generic = workspace.file("notes.txt")
                    generic.path.write_text("notes", encoding="utf-8")

                    archive_path = os.path.join(tempdir, "archive.zip")
                    ArchiveBuilder(organizer, False, zipfile.ZIP_DEFLATED).write(workspace, archive_path)

                with zipfile.ZipFile(archive_path, 'r') as archive:
                    expected_names = []
                    for artifact in [report, backup, generic]:
                        path, name = organizer.organize(artifact)
                        expected_names.append(f'{path}/{name}'.lstrip('/'))

                    assert archive.namelist() == expected_names

    def test_inluding_hashes_when_enabled(self) -> None:
        """The builder should add sidecar hash files when requested."""

        with tempfile.TemporaryDirectory() as tempdir:

            file_name = "sample.txt"

            with Workspace() as workspace:
                artifact = workspace.file(file_name)
                artifact.path.write_text("hello world", encoding="utf-8")

                archive_path = os.path.join(tempdir, "archive.zip")
                ArchiveBuilder(FlatArchiveOrganizer(), True, zipfile.ZIP_DEFLATED).write(workspace, archive_path)

            with zipfile.ZipFile(archive_path, 'r') as archive:
                assert (set(archive.namelist()) - set([file_name, file_name + '.sha256'])) == set()

                file_content = archive.read(file_name).decode('utf-8')
                file_hash_content = archive.read(file_name + '.sha256').decode('utf-8')
                expected_hash = hashlib.sha256(file_content.encode()).hexdigest()
                assert file_hash_content == expected_hash

    def test_excluding_hashes_when_disabled(self) -> None:
        """The builder should not add sidecar hash files when disabled."""

        with tempfile.TemporaryDirectory() as tempdir:

            file_name = "sample.txt"

            with Workspace() as workspace:
                artifact = workspace.file(file_name)
                artifact.path.write_text("hello world", encoding="utf-8")

                archive_path = os.path.join(tempdir, "archive.zip")
                ArchiveBuilder(FlatArchiveOrganizer(), False, zipfile.ZIP_DEFLATED).write(workspace, archive_path)

            with zipfile.ZipFile(archive_path, 'r') as archive:
                assert archive.namelist() == [file_name]
                assert file_name + 'sha256' not in archive.namelist()

    def test_builder_renames_duplicate_archive_entries(self, caplog) -> None:
        """Colliding archive entries should be renamed with an incrementing suffix."""

        with tempfile.TemporaryDirectory() as tempdir:

            with Workspace() as workspace:
                first = workspace.file('duplicate.txt')
                first.path.write_text("first", encoding="utf-8")
                second = workspace.file('duplicate.txt')
                second.path.write_text("second", encoding="utf-8")
                third = workspace.file('duplicate.txt')
                third.path.write_text("third", encoding="utf-8")
                other_first = workspace.file('other duplicate.txt')
                other_first.path.write_text("other first", encoding="utf-8")
                other_second = workspace.file('other duplicate.txt')
                other_second.path.write_text("other second", encoding="utf-8")

                archive_path = os.path.join(tempdir, "archive.zip")
                with caplog.at_level(logging.WARNING):
                    ArchiveBuilder(FlatArchiveOrganizer(), False, zipfile.ZIP_DEFLATED).write(workspace, archive_path)

            with zipfile.ZipFile(archive_path, 'r') as archive:
                assert len(archive.namelist()) == 5
                assert 'duplicate.txt' in archive.namelist()
                assert 'duplicate(1).txt' in archive.namelist(), "Duplicates are not discerned"
                assert 'duplicate(2).txt' in archive.namelist(), "Duplicates are not counted properly"
                assert 'other duplicate.txt' in archive.namelist()
                assert 'other duplicate(1).txt' in archive.namelist(), "Different duplicates are not counted separately"
                assert 'already used by another artifact' in caplog.text
