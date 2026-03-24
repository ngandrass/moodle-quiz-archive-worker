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

from enum import StrEnum


class WorkerStatus(StrEnum):
    """
    Status values that the quiz archive worker can report
    """

    IDLE = 'IDLE'
    """No jobs are beeing processed and queue is empty"""

    ACTIVE = 'ACTIVE'
    """All present jobs are beeing worked on and queue is empty"""

    BUSY = 'BUSY'
    """Parallelism limit is reached and at least one job is queued"""

    UNAVAILABLE = 'UNAVAILABLE'
    """Parallelism limit is reached and queue is full"""

    UNKNOWN = 'UNKNOWN'
    """Status is unknown"""
