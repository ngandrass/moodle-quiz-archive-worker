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

from abc import abstractmethod
from typing import Dict, Tuple, List
from uuid import UUID

from archiveworker.api.worker.archive_job_descriptor import ArchiveJobDescriptor
from archiveworker.api.moodle.base import MoodleAPIBase


class MoodleQuizAPIBase(MoodleAPIBase):
    """
    Intermediate adapter base for Moodle plugins that archive quiz attempts
    """

    @abstractmethod
    def get_attempts_metadata(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor
    ) -> List[Dict[str, str]]:
        """
        Fetches metadata for all quiz attempts that should be archived

        Metadata is fetched in batches of 100 attempts to avoid hitting the
        maximum URL length of the Moodle webservice API

        :param jobid: UUID of the job this request is associated with
        :param jobdescriptor: Descriptor of the archiving job this request belongs to
        :return: list of dicts containing metadata for each quiz attempt

        :raises ConnectionError: if the request to the Moodle webservice API failed
        :raises RuntimeError: if the Moodle webservice API reported an error
        :raises ValueError: if the response from the Moodle webservice API was
        incomplete or contained invalid data
        """
        pass

    @abstractmethod
    def get_attempt_data(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            attemptid: int,
    ) -> Tuple[str, str, str, List[Dict[str, str]]]:
        """
        Requests the attempt data (HTML DOM, attachment metadata) for a quiz
        attempt from the Moodle webservice API

        :param jobid: UUID of the job this request is associated with
        :param jobdescriptor: Descriptor of the archiving job this request belongs to
        :param attemptid: ID of the attempt to fetch data for

        :raises ConnectionError: if the request to the Moodle webservice API
        failed or the response could not be parsed
        :raises RuntimeError: if the Moodle webservice API reported an error
        :raises ValueError: if the response from the Moodle webservice API was incomplete

        :return: Tuple[str, str, str, List] consisting of the folder name, attempt name,
                 the HTML DOM report and a List of attachments for the requested attemptid
        """
        pass
