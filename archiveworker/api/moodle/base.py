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

import logging
from typing import Dict

from archiveworker.requests_factory import RequestsFactory
from config import Config


class MoodleAPIBase:
    """
    Adapter for the Moodle Web Service API
    """

    MOODLE_UPLOAD_FILE_FIELDS = ['component', 'contextid', 'userid', 'filearea', 'filename', 'filepath', 'itemid']
    """Keys that are present in the response for each file, received after uploading a file to Moodle"""

    REQUEST_TIMEOUTS = (10, 60)
    """Tuple of connection and read timeouts for default requests to the Moodle API in seconds"""

    REQUEST_TIMEOUTS_EXTENDED = (10, 1800)
    """Tuple of connection and read timeouts for long-running requests to the Moodle API in seconds"""

    FOLDERNAME_FORBIDDEN_CHARACTERS = ["\\", ".", ":", ";", "*", "?", "!", "\"", "<", ">", "|", "\0"]
    """List of characters that are forbidden inside an attempt folder name"""

    FILENAME_FORBIDDEN_CHARACTERS = FOLDERNAME_FORBIDDEN_CHARACTERS + ["/"]
    """List of characters that are forbidden inside a file name"""

    def __init__(self, ws_rest_url: str, ws_upload_url: str, wstoken: str):
        """
        Initialize the Moodle API adapter

        :param ws_rest_url: Full URL to the REST endpoint of the Moodle Web Service API
        :param ws_upload_url: Full URL to the upload endpoint of the Moodle Web Service API
        :param wstoken: Web Service token to authenticate with at the Moodle API
        """
        self.logger = logging.getLogger(f"{__name__}")

        self.ws_rest_url = ws_rest_url
        self.ws_upload_url = ws_upload_url
        self.wstoken = wstoken
        self.restformat = 'json'
        self._validate_properties()

        self.session = RequestsFactory.create_session()

    def _validate_properties(self) -> None:
        """
        Validate the set properties of the adapter

        :return: None
        """
        if not self.ws_rest_url:
            raise ValueError('Webservice REST base URL is required')

        if not self.ws_rest_url.startswith('http') or not self.ws_rest_url.endswith('/webservice/rest/server.php'):
            raise ValueError('Webservice REST base URL is invalid')

        if not self.ws_upload_url:
            raise ValueError("Webservice upload URL is required")

        if not self.ws_upload_url.startswith('http') or not self.ws_upload_url.endswith('/webservice/upload.php'):
            raise ValueError("Webservice upload URL is invalid")

        if not self.wstoken:
            raise ValueError("wstoken is required")

    def _generate_wsfunc_request_params(self, **kwargs) -> Dict[str, str]:
        """
        Generate the base request parameters for a Moodle webservice function API request

        :param kwargs: Additional parameters to include in the request
        :return: Dictionary with the request parameters
        """
        return {
            'wstoken': self.wstoken,
            'moodlewsrestformat': self.restformat,
            **kwargs
        }

    def _generate_file_request_params(self, **kwargs) -> Dict[str, str]:
        """
        Generates the base request parameters for a Moodle webservice file API request

        :param kwargs: Additional parameters to include in the request
        :return:  Dictionary with the request parameters
        """
        return {
            'token': self.wstoken,
            **kwargs
        }

    def check_connection(self) -> bool:
        """
        Check if the connection to the Moodle API is working

        :return: True if the connection is working
        :raises ConnectionError: If the connection could not be established
        """
        try:
            r = self.session.get(
                url=self.ws_rest_url,
                timeout=self.REQUEST_TIMEOUTS,
                params=self._generate_wsfunc_request_params(wsfunction=Config.MOODLE_WSFUNCTION_UPDATE_JOB_STATUS)
            )

            data = r.json()
        except Exception as e:
            self.logger.warning(f'Moodle API connection check failed with exception: {str(e)}')
            return False

        if data['errorcode'] == 'invalidparameter':
            # Moodle returns error 'invalidparameter' if the webservice is invoked
            # with a working wstoken but without valid parameters for the wsfunction
            return True
        else:
            self.logger.warning(f'Moodle API connection check failed with Moodle error: {data["errorcode"]}')
            return False
