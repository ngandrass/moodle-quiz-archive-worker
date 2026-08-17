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

from typing import Dict, List, Tuple
from uuid import UUID

from archiveworker.api.worker import ArchiveJobDescriptor, ArchivingmodAssignArchiveRequest
from . import reference_assign_full

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
        "submissionids": [201, 202],
        "paper_format": "A4",
        "archive_filename": "assign-archive-collision",
        "archive_flatten": False,
        "archive_filehashes": True,
        "keep_html_files": False,
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
        "foldername_pattern": "collision",
        "filename_pattern": "collision",
        "attachments": {
            "assignment": False,
            "submission": False,
            "feedback": False,
            "annotation": False,
        },
    },
}


class MoodleAPIMock(reference_assign_full.MoodleAPIMock):

    def get_submission_data(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            submissionid: int,
    ) -> Tuple[str, str, str, List[Dict[str, str]]]:
        if submissionid in [201, 202]:
            return 'collision', 'collision', reference_assign_full.SUBMISSION_REPORT_HTML, []

        return super().get_submission_data(jobid, jobdescriptor, submissionid)

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
