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

import pytest

from archiveworker.moodle_quiz_archive_worker import detect_proxy_settings

from config import Config


class TestProxyDetection:
    """
    Tests for proxy server detection
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """
        Prepare config structure for every test
        :return: None
        """
        # Reset all config values
        Config.PROXY_SERVER_URL = "invalid"
        Config.PROXY_SERVER_USERNAME = "invalid"
        Config.PROXY_SERVER_PASSWORD = "invalid"
        Config.PROXY_BYPASS_DOMAINS = "invald"

    def test_no_envvars(self):
        """
        Tests the case where no proxy environment variables are set
        :return: None
        """
        detect_proxy_settings({})

        assert Config.PROXY_SERVER_URL is None
        assert Config.PROXY_USERNAME is None
        assert Config.PROXY_PASSWORD is None
        assert Config.PROXY_BYPASS_DOMAINS is None

    @pytest.mark.parametrize("envvar, value", [
        # Full URL
        ("HTTP_PROXY", "http://myproxy.com:3128"),
        ("http_proxy", "http://myproxy.com:3128"),
        ("HTTPS_PROXY", "http://myproxy.com:3128"),
        ("https_proxy", "http://myproxy.com:3128"),
        ("ALL_PROXY", "http://myproxy.com:3128"),
        ("all_proxy", "http://myproxy.com:3128"),
        # URL without port
        ("HTTP_PROXY", "http://myproxy.com"),
        ("http_proxy", "http://myproxy.com"),
        ("HTTPS_PROXY", "http://myproxy.com"),
        ("https_proxy", "http://myproxy.com"),
        ("ALL_PROXY", "http://myproxy.com"),
        ("all_proxy", "http://myproxy.com"),
        # URL with path
        ("HTTP_PROXY", "http://myproxy.com:3128/foo/bar"),
        ("http_proxy", "http://myproxy.com:3128/foo/bar"),
        ("HTTPS_PROXY", "http://myproxy.com:3128/foo/bar"),
        ("https_proxy", "http://myproxy.com:3128/foo/bar"),
        ("ALL_PROXY", "http://myproxy.com:3128/foo/bar"),
        ("all_proxy", "http://myproxy.com:3128/foo/bar"),
        # URL with IPv4 address
        ("HTTP_PROXY", "http://10.0.0.1:3128"),
        ("http_proxy", "http://10.0.0.1:3128"),
        ("HTTPS_PROXY", "http://10.0.0.1:3128"),
        ("https_proxy", "http://10.0.0.1:3128"),
        ("ALL_PROXY", "http://10.0.0.1:3128"),
        ("all_proxy", "http://10.0.0.1:3128"),

    ])
    def test_proxy_without_auth(self, envvar, value):
        """
        Tests detection of proxy servers from various environment variables without authentication
        :param envvar: Name of the environment variable to set
        :param value: Value to set the environment variable to
        :return: None
        """
        detect_proxy_settings({
            envvar: value
        })

        assert Config.PROXY_SERVER_URL == value
        assert Config.PROXY_USERNAME is None
        assert Config.PROXY_PASSWORD is None
        assert Config.PROXY_BYPASS_DOMAINS is None


    @pytest.mark.parametrize("envvar, rawvalue, proxyurl, username, password", [
        ("HTTP_PROXY", "http://foo:bar@myproxy.com:3128", "http://myproxy.com:3128", "foo", "bar"),
        ("HTTPS_PROXY", "http://foo:bar@myproxy.com:3128", "http://myproxy.com:3128", "foo", "bar"),
        ("HTTP_PROXY", "https://lorem:ipsum@127.0.0.1:8080", "https://127.0.0.1:8080", "lorem", "ipsum"),
        ("ALL_PROXY", "https://lorem:ipsum@127.0.0.1:8080", "https://127.0.0.1:8080", "lorem", "ipsum"),
        ("HTTP_PROXY", "http://user:password@localservice", "http://localservice", "user", "password"),
        ("http_proxy", "http://user:password@localservice", "http://localservice", "user", "password"),
    ])
    def test_proxy_with_auth(self, envvar, rawvalue, proxyurl, username, password):
        """
        Tests detection of proxy servers with authentication set
        :param envvar: Name of the environment variable to set
        :param rawvalue: Value to set the environment variable to
        :param proxyurl: Expected proxy URL
        :param username: Expected username
        :param password: Expected password
        :return: None
        """
        detect_proxy_settings({
            envvar: rawvalue
        })

        assert Config.PROXY_SERVER_URL == proxyurl
        assert Config.PROXY_USERNAME == username
        assert Config.PROXY_PASSWORD == password
        assert Config.PROXY_BYPASS_DOMAINS is None

    @pytest.mark.parametrize("envvars, proxyurl", [
        ({'HTTP_PROXY': 'http://myproxy.com:3128', 'ALL_PROXY': 'http://myproxy.com:8080'}, 'http://myproxy.com:3128'),
        ({'HTTPS_PROXY': 'http://myproxy.com:3128', 'ALL_PROXY': 'http://myproxy.com:8080'}, 'http://myproxy.com:3128'),
        ({'ALL_PROXY': 'http://myproxy.com:8080'}, 'http://myproxy.com:8080'),
    ])
    def test_multiple_envvars(self, envvars, proxyurl):
        """
        Tests that the more specific envirnoment variables take precedence

        :param envvars: Dictionary of environment variables to set
        :param proxyurl: Expected proxy URL
        :return: None
        """
        detect_proxy_settings(envvars)

        assert Config.PROXY_SERVER_URL == proxyurl
        assert Config.PROXY_USERNAME is None
        assert Config.PROXY_PASSWORD is None
        assert Config.PROXY_BYPASS_DOMAINS is None

    @pytest.mark.parametrize("proxyurl, valid", [
        ("http://myproxy.com:3128", True),
        ("https://myproxy.com:3128", True),
        ("socks://myproxy.com:3128", True),
        ("socks5://myproxy.com:3128", True),
        ("ftp://myproxy.com:3128", False),
        ("ssh://myproxy.com:3128", False),
        ("foo://myproxy.com:3128", False),
    ])
    def test_proxy_procotols(self, proxyurl, valid):
        """
        Tests the detection of invalid proxy protocols
        :param proxyurl: Proxy URL to test
        :param valid: Whether the value is considered valid
        :return: None
        """
        detect_proxy_settings({ "HTTP_PROXY": proxyurl })

        if valid:
            assert Config.PROXY_SERVER_URL == proxyurl
        else:
            assert Config.PROXY_SERVER_URL is None

    @pytest.mark.parametrize("proxyurl, valid", [
        ("http://myproxy.com:3128", True),
        ("http://myproxy.com", True),
        ("http://myproxy.com:3128/foo/bar", True),
        ("http://127.0.0.1:3128/foo/bar", True),
        ("http://127.0.0.1", True),
        ("://localhost/", False),
        ("localhost", False),
        ("127.0.0.1:3128", False),
        ("foo:bar@myproxy.com:3127", False),
    ])
    def test_proxy_url_validation(self, proxyurl, valid):
        """
        Tests the validation of proxy URLs
        :param proxyurl: Proxy URL to test
        :param valid: Whether the value is considered valid
        :return: None
        """
        detect_proxy_settings({ "HTTP_PROXY": proxyurl })

        if valid:
            assert Config.PROXY_SERVER_URL == proxyurl
        else:
            assert Config.PROXY_SERVER_URL is None

    def test_noproxy_urls(self):
        """
        Tests if the NO_PROXY environment variable is respected
        :return: None
        """
        # No bypass URLs are set
        detect_proxy_settings({ "HTTP_PROXY": "http://myproxy.com:3128" })

        assert Config.PROXY_SERVER_URL == "http://myproxy.com:3128"
        assert Config.PROXY_BYPASS_DOMAINS is None

        # Bypass URLs are set
        detect_proxy_settings({ "HTTP_PROXY": "http://myproxy.com:3128", "NO_PROXY": "localhost, whatever.local" })

        assert Config.PROXY_SERVER_URL == "http://myproxy.com:3128"
        assert Config.PROXY_BYPASS_DOMAINS == "localhost, whatever.local"
