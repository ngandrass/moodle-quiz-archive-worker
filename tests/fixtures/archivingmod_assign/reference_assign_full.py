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
from pathlib import Path
from typing import Dict, List, Tuple
from unittest.mock import patch
from uuid import UUID

from config import Config
from archiveworker.api.worker import ArchiveJobDescriptor, ArchivingmodAssignArchiveRequest
from tests.conftest import MoodleAPIMockBase

ARCHIVE_API_REQUEST = {
    "api_version": ArchivingmodAssignArchiveRequest.API_VERSION,
    "taskid": 1,
    "moodle_api": {
        "wstoken": "5ebe2294ecd0e0f08eab7690d2a6ee69",
        "base_url": "http://localhost",
        "webservice_url": "http://localhost/webservice/rest/server.php",
        "upload_url": "http://localhost/webservice/upload.php",
        "max_upload_bytes": 536870912,  # 512 MiB
    },
    "job": {
        "submissionids": [101, 102],
        "paper_format": "A4",
        "archive_filename": "assign-archive-CM-1-Example Assignment",
        "archive_flatten": False,
        "archive_filehashes": True,
        "keep_html_files": True,
        "image_optimize": False,
        "report_sections": {
            "header": True,
            "instructions": True,
            "submission": True,
            "submissionstatus": True,
            "submissioncomments": True,
            "feedback": True,
            "feedbackcomments": True,
            "grade": True,
            "gradedetails": True,
        },
        "fetch_metadata": True,
        "foldername_pattern": "submission_${submissionid}",
        "filename_pattern": "submission_${submissionid}",
        "attachments": {
            "assignment": True,
            "submission": True,
            "feedback": True,
            "annotation": True,
        },
    },
}

SUBMISSION_REPORT_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Assignment Submission Report</title></head>
<body>
<h1>Assignment Submission</h1>
<p>This is a reference submission report used for testing the archive worker.</p>
</body>
</html>
"""

# Attachments returned for submission 101, one per attachment_type value
SUBMISSION_101_ATTACHMENTS = [
    {
        "type": "assignment",
        "filename": "instructions.pdf",
        "filesize": 1024,
        "mimetype": "application/pdf",
        "contenthash": "a" * 40,
        "downloadurl": "http://localhost/pluginfile/assignment/instructions.pdf",
    },
    {
        "type": "submission",
        "filename": "essay.docx",
        "filesize": 2048,
        "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "contenthash": "b" * 40,
        "downloadurl": "http://localhost/pluginfile/submission/essay.docx",
    },
    {
        "type": "feedback",
        "filename": "feedback.pdf",
        "filesize": 512,
        "mimetype": "application/pdf",
        "contenthash": "c" * 40,
        "downloadurl": "http://localhost/pluginfile/feedback/feedback.pdf",
    },
    {
        "type": "annotation",
        "filename": "essay_annotated.pdf",
        "filesize": 2560,
        "mimetype": "application/pdf",
        "contenthash": "d" * 40,
        "downloadurl": "http://localhost/pluginfile/annotation/essay_annotated.pdf",
    },
]


class MoodleAPIMock(MoodleAPIMockBase):

    CLS_ROOT = 'archiveworker.api.moodle.ArchivingmodAssignMoodleAPI'

    def __init__(self):
        super().__init__()
        self.patchers['get_submission_data'] = patch(
            self.CLS_ROOT + '.get_submission_data',
            new=self.get_submission_data
        )
        self.patchers['get_submissions_metadata'] = patch(
            self.CLS_ROOT + '.get_submissions_metadata',
            new=self.get_submissions_metadata
        )
        self.patchers['download_moodle_file'] = patch(
            self.CLS_ROOT + '.download_moodle_file',
            new=self.download_moodle_file
        )

    def get_submission_data(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            submissionid: int,
    ) -> Tuple[str, str, str, List[Dict[str, str]]]:
        if submissionid == 101:
            return f'submission-{submissionid}', f'submission-{submissionid}', SUBMISSION_REPORT_HTML, SUBMISSION_101_ATTACHMENTS
        if submissionid in ARCHIVE_API_REQUEST['job']['submissionids']:
            return f'submission-{submissionid}', f'submission-{submissionid}', SUBMISSION_REPORT_HTML, []

        raise RuntimeError(f'Unexpected submissionid: {submissionid}')

    def download_moodle_file(
            self,
            download_url: str,
            target_file: Path,
            sha1sum_expected: str = None,
            maxsize_bytes: int = Config.DOWNLOAD_MAX_FILESIZE_BYTES
    ) -> int:
        for attachment in SUBMISSION_101_ATTACHMENTS:
            if attachment['downloadurl'] == download_url:
                os.makedirs(target_file.parent, exist_ok=True)
                content = f"Fake content for {attachment['filename']} ({attachment['type']})".encode() * 10
                with open(target_file, 'wb') as f:
                    f.write(content)
                return len(content)

        raise RuntimeError(f'Unexpected download URL: {download_url}')

    def get_submissions_metadata(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
    ) -> List[Dict[str, str]]:
        return [
            {
                "submissionid": submissionid,
                "userid": 1000 + submissionid,
                "username": f"user{submissionid}",
                "firstname": "Test",
                "lastname": f"User {submissionid}",
                "idnumber": f"ID{submissionid}",
                "attemptnumber": 0,
                "status": "submitted",
                "timecreated": 1700000000,
                "timemodified": 1700000100,
                "timestarted": 1700000000,
            }
            for submissionid in ARCHIVE_API_REQUEST['job']['submissionids']
        ]
