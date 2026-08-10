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

import threading


class InterruptableThread(threading.Thread):
    """
    Custom Thread that allows to be interrupted by a stop event
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stop_event = threading.Event()

    def run(self):
        super().run()

    def stop(self):
        self._stop_event.set()

    def stop_requested(self):
        return self._stop_event.is_set()


def raise_error_if_stop_requested():
    """
    Checks if the current thread is interruptable and raises an error if it is
    requested to stop.

    :return: None
    :raises InterruptedError: If the thread was requested to stop
    """
    thread = threading.current_thread()
    if isinstance(thread, InterruptableThread) and thread.stop_requested():
        raise InterruptedError('Thread stop requested')
