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

from archiveworker.api.moodle.archivingmod_quiz import ArchivingmodQuizMoodleAPI
from archiveworker.type import PaperFormat
from . import ArchiveJobDescriptor, ArchiveRequest


class ArchivingmodQuizArchiveRequest(ArchiveRequest):
    """
    Deserialized JSON request for creating an archive job via the
    archivingmod_quiz Moodle plugin
    """

    API_VERSION = 1

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
        if json['api_version'] != ArchivingmodQuizArchiveRequest.API_VERSION:
            raise ValueError(f'API version mismatch. Expected: {ArchivingmodQuizArchiveRequest.API_VERSION}, Got: {json["api_version"]}. Please update your quiz-archive-worker!')

        # Prepare base
        req = ArchiveJobDescriptor(
            moodle_api=ArchivingmodQuizMoodleAPI(
                json['moodle_api']['base_url'],
                json['moodle_api']['webservice_url'],
                json['moodle_api']['upload_url'],
                json['moodle_api']['wstoken']
            ),
            taskid=json['taskid'],
            archive_filename=json['job']['archive_filename']
        )

        # Add archive quiz attempts task
        if json['job']['image_optimize']:
            image_optimize_data = {
                'width': json['job']['image_optimize']['width'],
                'height': json['job']['image_optimize']['height'],
                'quality': json['job']['image_optimize']['quality'],
            }
        else:
            image_optimize_data = False

        req.add_task_quiz_attempts(
            attemptids=json['job']['attemptids'],
            sections=json['job']['report_sections'],
            fetch_metadata=json['job']['fetch_metadata'],
            fetch_attachments=json['job']['fetch_attachments'],
            paper_format=PaperFormat[json['job']['paper_format']],
            keep_html_files=json['job']['keep_html_files'],
            foldername_pattern=json['job']['foldername_pattern'],
            filename_pattern=json['job']['filename_pattern'],
            image_optimize=True if image_optimize_data else False,
            image_optimize_width=image_optimize_data['width'] if image_optimize_data else None,
            image_optimize_height=image_optimize_data['height'] if image_optimize_data else None,
            image_optimize_quality=image_optimize_data['quality'] if image_optimize_data else None
        )

        return req
