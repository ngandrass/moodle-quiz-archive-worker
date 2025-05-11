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

import requests

from archiveworker.requests_factory import RequestsFactory
from config import Config


class TestRequestsFactory:
    """
    Tests for the RequestsFactory class
    """

    def test_create_session(self) -> None:
        """
        Test the create_session method
        """
        factory = RequestsFactory()
        session = factory.create_session()

        assert session is not None
        assert isinstance(session, requests.Session)

    def test_create_session_without_proxies(self) -> None:
        """
        Test the create_session method without proxies
        """
        Config.PROXY_SERVER_URL = None
        Config.PROXY_USERNAME = None
        Config.PROXY_PASSWORD = None

        factory = RequestsFactory()
        session = factory.create_session()

        assert session.proxies is None

    def test_create_session_with_proxies_noauth(self) -> None:
        """
        Test the create_session method with proxies and no auth
        """
        Config.PROXY_SERVER_URL = "http://proxy.example.com"
        Config.PROXY_USERNAME = None
        Config.PROXY_PASSWORD = None

        factory = RequestsFactory()
        session = factory.create_session()

        assert session.proxies['all'] == "http://proxy.example.com"

    def test_create_session_with_proxies_auth(self) -> None:
        """
        Test the create_session method with proxies and auth
        """
        Config.PROXY_SERVER_URL = "http://proxy.example.com"
        Config.PROXY_USERNAME = "user"
        Config.PROXY_PASSWORD = "pass"

        factory = RequestsFactory()
        session = factory.create_session()

        assert session.proxies['all'] == "http://user:pass@proxy.example.com"
