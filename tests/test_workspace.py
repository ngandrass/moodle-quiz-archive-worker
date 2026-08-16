import logging
from pathlib import Path

from archiveworker.workspace import ArchivingArtifact, AttemptArtifact, SubmissionArtifact, BackupArtifact, Workspace

class TestWorkspace:
    """Tests for the Workspace class artifact container."""

    def test_artifact_files_stored_inside_workspace(self) -> None:
        """Any artifact should be placed under the workspace artifact directory."""

        with Workspace() as workspace:
            artifact = workspace.file("filename.ext")

            assert artifact.path.parent == workspace._artifacts_base_path

    def test_temporaray_directory_inside_workspace(self) -> None:
        """Temporary directories should be nested under the workspace temporary path."""
        with Workspace() as workspace:
            with workspace.tmp_dir() as tmp_dir:
                assert Path(tmp_dir).parent == workspace._tmp_base_path
                assert Path(tmp_dir).exists()

    def test_workspace_registers_artifacts(self) -> None:
        """Any created artifact should be tracked by the workspace."""

        with Workspace() as workspace:
            artifact = workspace.file("notes.txt")
            _attempt = workspace.attempt(42, "my attempt", "attempt-dir")
            pdf_report = _attempt.pdf_report("report.pdf")
            html_report = _attempt.html_report("report.html")
            attachment = _attempt.attachment(123, "attachment.ext")

            assert set(workspace.get_artifacts()) - set([attachment, html_report, pdf_report, artifact]) == set()

    def test_artifact_file_name_collision_avoidance(self) -> None:
        """Any artifact name should be combined with a random string to avoid name collisions."""

        filename = "filename.ext"
        with Workspace() as workspace:
            artifact = workspace.file(filename)

            assert artifact.path.name != filename
            assert filename in artifact.path.name

    def test_attempt_artifact_subtypes_reference_parent(self) -> None:
        """Any AttemptArtifact sub type should reference its parent attempt."""

        with Workspace() as workspace:
            attempt = workspace.attempt(42, "your attempt", "attempt-mir")

            pdf_report = attempt.pdf_report("report.pdf")
            html_report = attempt.html_report("report.html")
            attachment = attempt.attachment(1,"attachment.ext")

            assert pdf_report.attempt is attempt
            assert html_report.attempt is attempt
            assert attachment.attempt is attempt

    def test_create_archiving_artifact(self) -> None:
        """
        Creating an generic artifact should retain supplied filename.
        """

        filename = "filename.ext"

        with Workspace() as workspace:
            artifact = workspace.file(filename)

            assert isinstance(artifact, ArchivingArtifact)
            assert artifact.name == filename
            assert artifact in workspace.get_artifacts()

    def test_create_attempt(self) -> None:
        """
        Creating an attempt should retain supplied id, name and path values.
        """

        attempt_id = 42
        file_name = "he-she-it's attempt"
        dir_name = "attempt-ihr"

        with Workspace() as workspace:
            attempt = workspace.attempt(attempt_id, file_name, dir_name)

            assert isinstance(attempt, AttemptArtifact)
            assert attempt.id == attempt_id
            assert attempt.name == file_name
            assert attempt.dir == dir_name
            assert len(workspace.get_artifacts()) == 0

    def test_create_attempt_pdf_report_artifact(self) -> None:
        """
        Created PDF report artifacts should be tracked by the workspace.
        """
        with Workspace() as workspace:
            _attempt = workspace.attempt(42, "our attempt", "attempt-wir")
            report = _attempt.pdf_report("report.pdf")

            assert isinstance(report, AttemptArtifact.PdfReport)
            assert report in workspace.get_artifacts()

    def test_create_attempt_html_report_artifact(self) -> None:
        """
        Created HTML report artifacts should be tracked by the workspace.
        """
        with Workspace() as workspace:
            _attempt = workspace.attempt(42, "their attempt", "attempt-mir")
            report = _attempt.html_report("report.html")

            assert isinstance(report, AttemptArtifact.HtmlReport)
            assert report in workspace.get_artifacts()

    def test_create_artifact_attachment(self) -> None:
        """
        Created attachment artifacts should be tracked by the workspace and
        retain supplied slot value .
        """



        with Workspace() as workspace:
            _attempt = workspace.attempt(42, "only my attempt", "attempt-gier")
            attachment = _attempt.attachment(1, "answer.txt")

            assert attachment.slot == 1
            assert isinstance(attachment, AttemptArtifact.Attachment)
            assert attachment in workspace.get_artifacts()

    def test_artifacts_are_filterable(self) -> None:
        """
        Artifacts should be retrievable, filtered according to their type if
        requested.
        """

        with Workspace() as workspace:
            file1 = workspace.file("file1.ext")
            file2 = workspace.file("file2.ext")

            backup1 = workspace.backup("backup1.mbz")
            backup2 = workspace.backup("backup2.mbz")

            _attempt = workspace.attempt(42, "my precious attempt", "attempt-gollum")

            pdf_report = _attempt.pdf_report("report.pdf")
            html_report = _attempt.html_report("report.html")

            attachment1 = _attempt.attachment(123, "attachment1.ext")
            attachment2 = _attempt.attachment(987, "attachment2.ext")

            assert set(workspace.get_artifacts(ArchivingArtifact)) - set([attachment2, attachment1, html_report, pdf_report, backup2, backup1, file2, file1]) == set()
            assert set(workspace.get_artifacts(BackupArtifact)) - set([backup2, backup1]) == set()
            assert set(workspace.get_artifacts(AttemptArtifact.PdfReport)) - set([pdf_report]) == set()
            assert set(workspace.get_artifacts(AttemptArtifact.HtmlReport)) - set([html_report]) == set()
            assert set(workspace.get_artifacts(AttemptArtifact.Attachment)) - set([attachment2, attachment1]) == set()

    def test_duplicate_attempt_directory_uses_id_suffix(self, caplog) -> None:
        """
        A duplicate attempt directory name should trigger a warning and receive
        its id as a suffix.
        """

        attempt_dir_name = "attempt-same-dir"

        with Workspace() as workspace:
            workspace.attempt(1, "First", attempt_dir_name)

            with caplog.at_level(logging.WARNING):
                duplicate_attempt = workspace.attempt(12, "Second", attempt_dir_name)

            expected_attempt_dir_name = f"{attempt_dir_name}_{duplicate_attempt.id}"
            assert duplicate_attempt.dir == expected_attempt_dir_name
            assert attempt_dir_name in caplog.text
            assert "already exists" in caplog.text
            assert expected_attempt_dir_name in caplog.text

    def test_submission_artifact_subtypes_reference_parent(self) -> None:
        """Any SubmissionArtifact sub type should reference its parent submission."""

        with Workspace() as workspace:
            submission = workspace.submission(42, "your submission", "submission-mir")

            pdf_report = submission.pdf_report("report.pdf")
            html_report = submission.html_report("report.html")
            attachment = submission.attachment("submission", "answer.txt")

            assert pdf_report.submission is submission
            assert html_report.submission is submission
            assert attachment.submission is submission

    def test_create_submission(self) -> None:
        """
        Creating a submission should retain supplied id, name and path values.
        """

        submission_id = 42
        file_name = "he-she-it's submission"
        dir_name = "submission-ihr"

        with Workspace() as workspace:
            submission = workspace.submission(submission_id, file_name, dir_name)

            assert isinstance(submission, SubmissionArtifact)
            assert submission.id == submission_id
            assert submission.name == file_name
            assert submission.dir == dir_name
            assert len(workspace.get_artifacts()) == 0

    def test_create_submission_pdf_report_artifact(self) -> None:
        """
        Created submission PDF report artifacts should be tracked by the workspace.
        """
        with Workspace() as workspace:
            _submission = workspace.submission(42, "our submission", "submission-wir")
            report = _submission.pdf_report("report.pdf")

            assert isinstance(report, SubmissionArtifact.PdfReport)
            assert report in workspace.get_artifacts()

    def test_create_submission_html_report_artifact(self) -> None:
        """
        Created submission HTML report artifacts should be tracked by the workspace.
        """
        with Workspace() as workspace:
            _submission = workspace.submission(42, "their submission", "submission-mir")
            report = _submission.html_report("report.html")

            assert isinstance(report, SubmissionArtifact.HtmlReport)
            assert report in workspace.get_artifacts()

    def test_create_submission_artifact_attachment(self) -> None:
        """
        Created submission attachment artifacts should be tracked by the
        workspace and retain the supplied type value.
        """

        with Workspace() as workspace:
            _submission = workspace.submission(42, "only my submission", "submission-gier")
            attachment = _submission.attachment("feedback", "answer.txt")

            assert attachment.type == "feedback"
            assert isinstance(attachment, SubmissionArtifact.Attachment)
            assert attachment in workspace.get_artifacts()

    def test_submission_artifacts_are_filterable(self) -> None:
        """
        Submission artifacts should be retrievable, filtered according to
        their type if requested.
        """

        with Workspace() as workspace:
            _submission = workspace.submission(42, "my precious submission", "submission-gollum")

            pdf_report = _submission.pdf_report("report.pdf")
            html_report = _submission.html_report("report.html")

            attachment1 = _submission.attachment("submission", "attachment1.ext")
            attachment2 = _submission.attachment("feedback", "attachment2.ext")

            assert set(workspace.get_artifacts(SubmissionArtifact.PdfReport)) - set([pdf_report]) == set()
            assert set(workspace.get_artifacts(SubmissionArtifact.HtmlReport)) - set([html_report]) == set()
            assert set(workspace.get_artifacts(SubmissionArtifact.Attachment)) - set([attachment2, attachment1]) == set()

    def test_duplicate_submission_directory_uses_id_suffix(self, caplog) -> None:
        """
        A duplicate submission directory name should trigger a warning and
        receive its id as a suffix.
        """

        submission_dir_name = "submission-same-dir"

        with Workspace() as workspace:
            workspace.submission(1, "First", submission_dir_name)

            with caplog.at_level(logging.WARNING):
                duplicate_submission = workspace.submission(12, "Second", submission_dir_name)

            expected_submission_dir_name = f"{submission_dir_name}_{duplicate_submission.id}"
            assert duplicate_submission.dir == expected_submission_dir_name
            assert submission_dir_name in caplog.text
            assert "already exists" in caplog.text
            assert expected_submission_dir_name in caplog.text
