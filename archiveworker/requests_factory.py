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

import re
from typing import Dict

import requests

from config import Config


class RequestsFactory:
    """
    Factory to provide requests sessions
    """

    @classmethod
    def create_session(cls) -> requests.Session:
        """
        Prepares a new requests session with all global config fully set up

        :return: Prepared requests session
        """
        s = requests.Session()
        s.proxies = cls._generate_proxy_settings()
        s.verify = not Config.SKIP_HTTPS_CERT_VALIDATION

        return s

    @classmethod
    def _generate_proxy_settings(cls) -> Dict[str, str] | None:
        """
        Generates a dictionary with proxy settings for the requests library

        :return: Dictionary with proxy settings or None if no proxy is configured
        """
        if Config.PROXY_SERVER_URL:
            if Config.PROXY_USERNAME and Config.PROXY_PASSWORD:
                match = re.search(r"(.+)://(.+)", Config.PROXY_SERVER_URL)
                return {
                    "all": f"{match.group(1)}://{Config.PROXY_USERNAME}:{Config.PROXY_PASSWORD}@{match.group(2)}",
                }
            else:
                return {
                    "all": Config.PROXY_SERVER_URL,
                }
        else:
            return None
