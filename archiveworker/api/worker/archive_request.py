# Moodle Quiz Archive Worker
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

from abc import ABCMeta, abstractmethod

from archiveworker.api.worker import ArchiveJobDescriptor


class ArchiveRequest(metaclass=ABCMeta):
    """
    Abstract base class for all incoming archive requests.
    """

    API_VERSION = 0

    @staticmethod
    @abstractmethod
    def from_raw_request_data(json: dict) -> ArchiveJobDescriptor:
        """
        Creates an ArchiveJobDescriptor object from a deserialized JSON request object

        :param json: Request data (deserialized POSTed JSON data)
        :return: Internal archive request object
        """
        pass
