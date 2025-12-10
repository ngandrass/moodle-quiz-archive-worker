# Moodle Quiz Archive Worker
# Copyright (C) 2025 Niels Gandraß <niels@gandrass.de>
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
from typing import List, Dict, Tuple
from uuid import UUID

from archiveworker.api.worker import ArchiveJobDescriptor, QuizArchiverArchiveRequest
from . import reference_quiz_full

ARCHIVE_API_REQUEST = {
    "api_version": QuizArchiverArchiveRequest.API_VERSION,
    "moodle_base_url": "http://localhost",
    "moodle_ws_url": "http://localhost/webservice/rest/server.php",
    "moodle_upload_url": "http://localhost/webservice/upload.php",
    "wstoken": "5ebe2294ecd0e0f08eab7690d2a6ee69",
    "courseid": 9,
    "cmid": 23,
    "quizid": 12,
    "task_archive_quiz_attempts": {
        "attemptids": [24, 25],
        "fetch_metadata": True,
        "sections": {
            "header": "1",
            "quiz_feedback": "1",
            "question": "1",
            "question_feedback": "1",
            "general_feedback": "1",
            "rightanswer": "1",
            "history": "1",
            "attachments": "1"
        },
        "paper_format": "A4",
        "keep_html_files": False,
        "foldername_pattern": "foo",
        "filename_pattern": "attempt",
        "image_optimize": False,
    },
    "task_moodle_backups": False,
    "archive_filename": "archive"
}


class MoodleAPIMock(reference_quiz_full.MoodleAPIMock):

    def get_attempt_data(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            attemptid: int,
    ) -> Tuple[str, str, str, List[Dict[str, str]]]:
        if attemptid in [23, 24, 25]:
            with open(f'{self.RESOURCE_BASE}/attempts/{attemptid}.html', 'r') as f:
                return f'foo', f'attempt', f.read(), []

        return super().get_attempt_data(jobid, jobdescriptor, attemptid)
