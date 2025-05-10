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

from archiveworker.api.moodle import QuizArchiverMoodleAPI
from archiveworker.type import PaperFormat

from . import ArchiveJobDescriptor


class QuizArchiverArchiveRequest:
    """
    Deserialized JSON request for creating an archive job via the quiz_archiver
    Moodle plugin
    """

    API_VERSION = 7

    @staticmethod
    def from_raw_request_data(json: dict) -> ArchiveJobDescriptor:
        """
        Creates a new internal archive request object from a JSON dictionary

        :param json: Request data (deserialized POSTed JSON data)
        :return: Internal archive request object
        """
        # Catch API version missmatch
        if 'api_version' not in json:
            raise ValueError('API version missing in request payload')
        if not isinstance(json['api_version'], int):
            raise ValueError('API version must be an integer')
        if json['api_version'] != QuizArchiverArchiveRequest.API_VERSION:
            raise ValueError(f'API version mismatch. Expected: {QuizArchiverArchiveRequest.API_VERSION}, Got: {json["api_version"]}. Please update your quiz-archive-worker!')

        # Prepare base
        req = ArchiveJobDescriptor(
            moodle_api=QuizArchiverMoodleAPI(
                json['moodle_base_url'],
                json['moodle_ws_url'],
                json['moodle_upload_url'],
                json['wstoken']
            ),
            taskid=None,
            courseid=json['courseid'],
            cmid=json['cmid'],
            quizid=json['quizid'],
            archive_filename=json['archive_filename']
        )

        # Add archive quiz attempts task
        if json['task_archive_quiz_attempts']:
            if json['task_archive_quiz_attempts']['image_optimize']:
                image_optimize_data = {
                    'width': json['task_archive_quiz_attempts']['image_optimize']['width'],
                    'height': json['task_archive_quiz_attempts']['image_optimize']['height'],
                    'quality': json['task_archive_quiz_attempts']['image_optimize']['quality'],
                }
            else:
                image_optimize_data = False

            req.add_task_quiz_attempts(
                attemptids=json['task_archive_quiz_attempts']['attemptids'],
                sections=json['task_archive_quiz_attempts']['sections'],
                fetch_metadata=json['task_archive_quiz_attempts']['fetch_metadata'],
                fetch_attachments=True if json['task_archive_quiz_attempts']['sections']['attachments'] == '1' else False,
                paper_format=PaperFormat[json['task_archive_quiz_attempts']['paper_format']],
                keep_html_files=json['task_archive_quiz_attempts']['keep_html_files'],
                foldername_pattern=json['task_archive_quiz_attempts']['foldername_pattern'],
                filename_pattern=json['task_archive_quiz_attempts']['filename_pattern'],
                image_optimize=True if image_optimize_data else False,
                image_optimize_width=image_optimize_data['width'] if image_optimize_data else None,
                image_optimize_height=image_optimize_data['height'] if image_optimize_data else None,
                image_optimize_quality=image_optimize_data['quality'] if image_optimize_data else None
            )

        # Add archive moodle backups tasks
        if json['task_moodle_backups']:
            for backup in json['task_moodle_backups']:
                req.add_task_moodle_backup(
                    backupid=backup['backupid'],
                    filename=backup['filename'],
                    file_download_url=backup['file_download_url']
                )

        return req
