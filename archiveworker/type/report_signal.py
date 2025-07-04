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

from enum import StrEnum


class ReportSignal(StrEnum):
    """
    Signals that can be emitted by the report page JS
    """
    READY_FOR_EXPORT = "x-quiz-archiver-page-ready-for-export"
    MATHJAX_FOUND = "x-quiz-archiver-mathjax-found"
    MATHJAX_NOT_FOUND = "x-quiz-archiver-mathjax-not-found"
