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

import os
from typing import List, Dict

from archiveworker.type.paper_format import PaperFormat


class ArchiveJobDescriptor:
    """
    Internal representation of an archive job request.

    This representation is created from any of the supported worker APIs and is
    used within the worker to process jobs independent of the component that
    created the job.

    :param moodle_api: Instance of the Moodle API to use for this job
    :param archive_filename: Filename of the archive to create
    :param taskid: Task ID of the job (optional)
    :param courseid: Course ID of the job (optional)
    :param cmid: Course module ID of the job (optional)
    :param quizid: Quiz ID of the job (optional)

    :raises ValueError: If any of the parameters are invalid
    """

    def __init__(
        self,
        moodle_api: 'MoodleAPIBase',
        archive_filename: str,
        taskid: int = None,
        courseid: int = None,
        cmid: int = None,
        quizid: int = None
    ):
        # Import locally to prevent circular import issues
        from archiveworker.api.moodle.base import MoodleAPIBase

        # Create instance properties
        self.moodle_api = moodle_api
        self.taskid = int(taskid) if taskid else None
        self.courseid = int(courseid) if courseid else None
        self.cmid = int(cmid) if cmid else None
        self.quizid = int(quizid) if quizid else None
        self.archive_filename = archive_filename
        self.tasks = {
            'quiz_attempts': None,
            'moodle_backups': None
        }

        # Validate arguments
        if not isinstance(self.moodle_api, MoodleAPIBase):
            raise ValueError('moodle_api must be an instance of MoodleAPIBase.')

        if not (
            (
                self.courseid is not None and self.courseid > 0 and
                self.cmid is not None and self.cmid > 0 and
                self.quizid is not None and self.quizid > 0
            ) or (
                self.taskid is not None and self.taskid > 0
            )
        ):
            raise ValueError('Either the 3-tuple courseid, cmid and quizid or taskid must be given to create an archive request.')

        if not isinstance(self.archive_filename, str) or len(self.archive_filename) == 0:
            raise ValueError('Archive filename is invalid.')
        else:
            # Do not allow paths
            if not os.path.basename(self.archive_filename) == self.archive_filename:
                raise ValueError('Archive filename must not contain a path.')

            # Do not allow forbidden characters
            if any(c in self.archive_filename for c in ["\0", "\\", "/", ":", "*", "?", "\"", "<", ">", "|", "."]):
                raise ValueError('Archive filename contains forbidden characters.')

    def add_task_quiz_attempts(
        self,
        attemptids: List[int],
        sections: Dict,
        fetch_metadata: bool,
        fetch_attachments: bool,
        paper_format: PaperFormat,
        keep_html_files: bool,
        foldername_pattern: str,
        filename_pattern: str,
        image_optimize: bool,
        image_optimize_width: int = None,
        image_optimize_height: int = None,
        image_optimize_quality: int = None,
    ):
        # Validate input
        if not isinstance(attemptids, List) or len(attemptids) == 0:
            raise ValueError('Attempt ID list is invalid.')
        if not isinstance(sections, object) or len(sections) == 0:
            raise ValueError('Attempt report sections are invalid.')
        if not isinstance(fetch_metadata, bool):
            raise ValueError('Fetch metadata flag is invalid.')
        if not isinstance(fetch_attachments, bool):
            raise ValueError('Fetch attachments flag is invalid.')
        if not isinstance(paper_format, PaperFormat):
            raise ValueError('Paper format is invalid.')
        if not isinstance(keep_html_files, bool):
            raise ValueError('Keep HTML files flag is invalid.')
        if not isinstance(foldername_pattern, str) or len(foldername_pattern) == 0:
            raise ValueError('Folder name pattern is invalid.')
        if not isinstance(filename_pattern, str) or len(filename_pattern) is None:
            raise ValueError('Filename pattern is invalid.')
        if not isinstance(image_optimize, bool):
            raise ValueError('Image optimization flag is invalid.')

        if image_optimize:
            if not isinstance(image_optimize_width, int) or image_optimize_width < 1:
                raise ValueError('Image optimization width is invalid.')
            if not isinstance(image_optimize_height, int) or image_optimize_height < 1:
                raise ValueError('Image optimization height is invalid.')
            if not isinstance(image_optimize_quality, int) or not 0 <= image_optimize_quality <= 100:
                raise ValueError('Image optimization quality is invalid.')

        # Append the new attempt information
        self.tasks['quiz_attempts'] = {
            'attemptids': attemptids,
            'sections': sections,
            'fetch_metadata': fetch_metadata,
            'fetch_attachments': fetch_attachments,
            'paper_format': paper_format,
            'keep_html_files': keep_html_files,
            'foldername_pattern': foldername_pattern,
            'filename_pattern': filename_pattern,
            'image_optimize': {
                'width': image_optimize_width,
                'height': image_optimize_height,
                'quality': image_optimize_quality
            } if image_optimize else False,
        }

    def add_task_moodle_backup(
        self,
        backupid: str,
        filename: str,
        file_download_url: str
    ) -> None:
        """
        Adds a new Moodle backup retrieval task to this job request.

        :param backupid: Internal ID of the Moodle backup
        :param filename: Filename of the Moodle backup to download
        :param file_download_url: URL to download the Moodle backup from
        :return: None

        :raises ValueError: If any of the parameters is invalid
        """
        # Validate input
        if not isinstance(backupid, str) or len(backupid) == 0:
            raise ValueError('Moodle backup ID is invalid.')

        if not isinstance(filename, str) or len(filename) == 0:
            raise ValueError('Moodle backup filename is invalid.')

        if not isinstance(file_download_url, str) or len(file_download_url) == 0 or not file_download_url.startswith(self.moodle_api.base_url):
            raise ValueError('Moodle backup file download URL is invalid.')

        # Prepare list for first entry
        if not isinstance(self.tasks['moodle_backups'], List):
            self.tasks['moodle_backups'] = []

        # Append the new backup information
        self.tasks['moodle_backups'].append({
            'backupid': backupid,
            'filename': filename,
            'file_download_url': file_download_url
        })
