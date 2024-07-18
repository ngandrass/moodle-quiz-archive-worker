# Moodle Quiz Archive Worker
# Copyright (C) 2024 Niels Gandraß <niels@gandrass.de>
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
import os
import shutil
from pathlib import Path
from typing import Tuple, List, Dict

from archiveworker.custom_types import JobArchiveRequest
from config import Config
from tests.conftest import MoodleAPIMockBase

ARCHIVE_API_REQUEST = {
    "api_version": JobArchiveRequest.API_VERSION,
    "moodle_base_url": "http://localhost",
    "moodle_ws_url": "http://localhost/webservice/rest/server.php",
    "moodle_upload_url": "http://localhost/webservice/upload.php",
    "wstoken": "5ebe2294ecd0e0f08eab7690d2a6ee69",
    "courseid": 9,
    "cmid": 23,
    "quizid": 12,
    "task_archive_quiz_attempts": {
        "attemptids": [24, 25, 23],
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
        "keep_html_files": True,
        "filename_pattern": "attempt-${attemptid}-${username}_${date}-${time}",
        "image_optimize": False,
    },
    "task_moodle_backups": [
        {
            "backupid": "d68a3dedfdc9a93dab4b8c93dfd6dda9",
            "userid": 47,
            "context": 66,
            "component": "backup",
            "filearea": "activity",
            "filepath": "/",
            "filename": "quiz_archiver-activity-backup-23.mbz",
            "itemid": None,
            "pathnamehash": "118304132d9af1fcdd201bab191744a6043a8525",
            "file_download_url": "http://localhost/webservice/pluginfile.php/66/backup/activity/quiz_archiver-activity-backup-23.mbz"
        },
        {
            "backupid": "2562986e38f83cd9857e1b4494cfecad",
            "userid": 47,
            "context": 64,
            "component": "backup",
            "filearea": "course",
            "filepath": "/",
            "filename": "quiz_archiver-course-backup-9.mbz",
            "itemid": None,
            "pathnamehash": "722b7fbc463a355b9622b976b2d0c1a602b6da85",
            "file_download_url":"http://localhost/webservice/pluginfile.php/64/backup/course/quiz_archiver-course-backup-9.mbz"
        }
    ],
    "archive_filename": "quiz-archive-QA-REF-9-Reference Quiz (standard question types)-12"
}


class MoodleAPIMock(MoodleAPIMockBase):

    RESOURCE_BASE = 'tests/resources/reference_quiz_full'

    def get_attempt_data(
            self,
            courseid: int,
            cmid: int,
            quizid: int,
            attemptid: int,
            sections: dict,
            filenamepattern: str,
            attachments: bool
    ) -> Tuple[str, str, List[Dict[str, str]]]:
        if attemptid in [23, 24, 25]:
            with open(f'{self.RESOURCE_BASE}/attempts/{attemptid}.html', 'r') as f:
                return f'attempt-{attemptid}', f.read(), []

        super().get_attempt_data(courseid, cmid, quizid, attemptid, sections, filenamepattern, attachments)

    def get_attempts_metadata(
            self,
            courseid: int,
            cmid: int,
            quizid: int,
            attemptids: List[int]
    ) -> List[Dict[str, str]]:
        metadata = []
        with open(f'{self.RESOURCE_BASE}/attempts_metadata.csv', 'r') as f:
            for row in csv.DictReader(f, skipinitialspace=True):
                if int(row['attemptid']) in attemptids:
                    metadata.append({key: value for key, value in row.items()})

        return metadata

    def download_moodle_file(
            self,
            download_url: str,
            target_path: Path,
            target_filename: str,
            sha1sum_expected: str = None,
            maxsize_bytes: int = Config.DOWNLOAD_MAX_FILESIZE_BYTES
    ) -> int:
        # Lookup file
        target_file = os.path.join(target_path, target_filename)
        source_file = None
        if download_url == ARCHIVE_API_REQUEST['task_moodle_backups'][0]['file_download_url']:
            source_file = f'{self.RESOURCE_BASE}/backups/{ARCHIVE_API_REQUEST['task_moodle_backups'][0]["filename"]}'
        if download_url == ARCHIVE_API_REQUEST['task_moodle_backups'][1]['file_download_url']:
            source_file = f'{self.RESOURCE_BASE}/backups/{ARCHIVE_API_REQUEST['task_moodle_backups'][1]["filename"]}'

        # Handle unexpected download URLs
        if not source_file:
            raise RuntimeError(f'Unexpected download URL: {download_url}')

        # "Download" file to target location
        os.makedirs(target_path, exist_ok=True)
        shutil.copy2(source_file, target_file)
        return os.path.getsize(target_file)
