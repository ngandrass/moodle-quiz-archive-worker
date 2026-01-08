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

import hashlib
import json
import logging
import os
from abc import ABCMeta, abstractmethod
from json import JSONDecodeError
from pathlib import Path
from typing import Dict, Tuple, List
from uuid import UUID

from archiveworker.api.worker.archive_job_descriptor import ArchiveJobDescriptor
from archiveworker.requests_factory import RequestsFactory
from archiveworker.type import JobStatus, MoodleBackupStatus
from config import Config


class MoodleAPIBase(metaclass=ABCMeta):
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

    def __init__(self, base_url: str, ws_rest_url: str, ws_upload_url: str, wstoken: str):
        """
        Initialize the Moodle API adapter

        :param base_url: Base URL of the Moodle instance
        :param ws_rest_url: Full URL to the REST endpoint of the Moodle Web Service API
        :param ws_upload_url: Full URL to the upload endpoint of the Moodle Web Service API
        :param wstoken: Web Service token to authenticate with at the Moodle API
        """
        self.logger = logging.getLogger(f"{__name__}")

        self.base_url = base_url
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
        if not self.base_url:
            raise ValueError('Base URL is required')

        if not self.base_url.startswith('http') or self.base_url.endswith('.php'):
            raise ValueError('Base URL is invalid')

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
                params=self._generate_wsfunc_request_params(wsfunction=self._get_check_connection_wsfunction_name())
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

    def get_remote_file_metadata(self, download_url: str) -> Tuple[str, int]:
        """
        Fetches metadata (HEAD) for a file that should be downloaded

        :param download_url: URL of the file to fetch metadata for
        :return: Tuple of content type and content length of the file
        :raises ConnectionError: if the request to the given download_url failed
        """
        try:
            self.logger.debug(f'Requesting HEAD for file {download_url}')
            h = self.session.head(
                url=download_url,
                timeout=self.REQUEST_TIMEOUTS,
                params=self._generate_file_request_params(),
                allow_redirects=True
            )
            self.logger.debug(f'Download file HEAD request headers: {h.headers}')
        except Exception as e:
            raise ConnectionError(f'Failed to retrieve HEAD for remote file at: {download_url}. {str(e)}')

        content_type = h.headers.get('Content-Type', None)
        content_length = h.headers.get('Content-Length', None)

        return content_type, content_length

    def download_moodle_file(
            self,
            download_url: str,
            target_path: Path,
            target_filename: str,
            sha1sum_expected: str = None,
            maxsize_bytes: int = Config.DOWNLOAD_MAX_FILESIZE_BYTES
    ) -> int:
        """
        Downloads a file from Moodle and saves it to the specified path. Downloads
        are performed in chunks.

        :param download_url: The URL to download the file from
        :param target_path: The path to store the downloaded file into
        :param target_filename: The name of the file to store
        :param sha1sum_expected: SHA1 sum of the file contents to check against, ignored if None
        :param maxsize_bytes: Maximum number of bytes before the download is forcefully aborted

        :return: Number of bytes downloaded

        :raises RuntimeError: If the file download failed or the downloaded file
        was larger than the specified maximum size, an I/O error occurred, or
        the downloaded file did not match the given SHA1 sum
        :raises ConnectionError: if the download failed for any other reason
        """
        target_file = target_path.joinpath(target_filename)

        try:
            os.makedirs(target_path, exist_ok=True)
            with open(target_file, 'wb+') as f:
                r = self.session.get(
                    url=download_url,
                    stream=True,
                    timeout=self.REQUEST_TIMEOUTS_EXTENDED,
                    params=self._generate_file_request_params(forcedownload=1)
                )

                chunksize = int(32 * 10e6)  # 32 MB
                downloaded_bytes = 0
                for chunk in r.iter_content(chunksize):
                    if downloaded_bytes > maxsize_bytes:
                        raise RuntimeError(f'Downloaded Moodle file was larger than expected and exceeded the maximum file size limit of {maxsize_bytes} bytes')
                    downloaded_bytes = downloaded_bytes + f.write(chunk)
        except RuntimeError as e:
            raise e
        except IOError:
            raise RuntimeError(f'Encountered internal IOError while writing a downloading Moodle file from {download_url} to {target_filename}')
        except Exception:
            ConnectionError(f'Failed to download Moodle file from: {download_url}')

        # Check if we downloaded a Moodle error message
        if downloaded_bytes < 10240:  # 10 KiB
            with open(target_file, 'r') as f:
                try:
                    data = json.load(f)
                    if 'errorcode' in data and 'debuginfo' in data:
                        self.logger.debug(f'Downloaded JSON response: {data}')
                        raise RuntimeError(f'Moodle file download failed with "{data["errorcode"]}"')
                except (JSONDecodeError, UnicodeDecodeError):
                    pass

        # Check SHA1 sum
        if sha1sum_expected:
            with open(target_file, 'rb') as f:
                sha1sum = hashlib.sha1()
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha1sum.update(byte_block)

            if sha1sum.hexdigest() != sha1sum_expected:
                raise RuntimeError(f'Moodle file download failed. Expected SHA1 sum "{sha1sum_expected}" but got "{sha1sum.hexdigest()}"')

        self.logger.info(f'Downloaded {downloaded_bytes} bytes to {target_file}')
        return downloaded_bytes

    def upload_file(self, file: Path) -> Dict[str, str]:
        """
        Uploads a file to the Moodle API. Uploaded files will be stored in a
        temporary file area. The precise location can be found in the returned
        metadata.

        :param file: Path to the file to upload
        :return: Dictionary with metadata about the uploaded file, according
        to self.MOODLE_UPLOAD_FILE_FIELDS
        :raises ConnectionError: if the upload failed due to network issues
        :raises RuntimeError: if the Moodle webservice API reported an error
        :raises ValueError: if the metadata response from the Moodle webservice
        API was incomplete or invalid
        """

        with open(file, "rb") as f:
            try:
                file_stats = os.stat(file)
                filesize = file_stats.st_size
                self.logger.info(f'Uploading file "{file}" (size: {filesize} bytes) to "{self.ws_upload_url}"')

                r = self.session.post(
                    url=self.ws_upload_url,
                    timeout=self.REQUEST_TIMEOUTS_EXTENDED,
                    files={'file_1': f},
                    data=self._generate_file_request_params(filepath='/', itemid=0)
                )
                response = r.json()
            except Exception as e:
                raise ConnectionError(f'Failed to upload file to "{self.ws_upload_url}". Exception: {str(e)}. Response: {r.text}')

        # Check if upload failed
        if 'errorcode' in response and 'debuginfo' in response:
            self.logger.debug(f'Upload response: {response}')
            raise RuntimeError(f'Moodle webservice upload returned error "{response["errorcode"]}". Message: {response["debuginfo"]}')

        # Validate response
        upload_metadata = response[0]
        for key in self.MOODLE_UPLOAD_FILE_FIELDS:
            if key not in upload_metadata:
                self.logger.debug(f'Upload response: {response}')
                raise ValueError(f'Moodle webservice upload returned an invalid response')

        # Return metadata
        return {key: upload_metadata[key] for key in self.MOODLE_UPLOAD_FILE_FIELDS}

    @abstractmethod
    def _get_check_connection_wsfunction_name(self) -> str:
        """
        Returns the name of a webservice function that can be called to check if
        the basic connection to the Moodle API is working. In the easiest case
        this is something like 'update_job_status'.

        :return: Name of the webservice function to call in check_connection()
        """
        pass

    @abstractmethod
    def update_job_status(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            status: JobStatus,
            statusextras: Dict = None
    ) -> bool:
        """
        Update the status of a job via the Moodle API

        :param jobid: UUID of the job to update
        :param jobdescriptor: Descriptor of the archiving job this request belongs to
        :param status: New status to set
        :param statusextras: Additional status information to include
        :return: True if the status was updated successfully, False otherwise
        """
        pass

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

    @abstractmethod
    def process_uploaded_artifact(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            component: str,
            contextid: int,
            userid: int,
            filearea: str,
            filename: str,
            filepath: str,
            itemid: int,
            sha256sum: str
    ) -> bool:
        """
        Calls the Moodle webservice function to process an uploaded artifact

        :param jobid: UUID of the job the artifact is associated with
        :param jobdescriptor: Descriptor of the archiving job this request belongs to
        :param component: Moodle File API component
        :param contextid: Moodle File API contextid
        :param userid: Moodle File API userid
        :param filearea: Moodle File API filearea
        :param filename: Moodle File API filename
        :param filepath: Moodle File API filepath
        :param itemid: Moodle File API itemid
        :param sha256sum: SHA256 checksum of the artifact file

        :return: True on success

        :raises ConnectionError: if the request to the Moodle webservice API failed
        :raises RuntimeError: if the Moodle webservice API reported an error
        """
        pass

    @abstractmethod
    def get_backup_status(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            backupid: str
    ) -> MoodleBackupStatus:
        """
        Retrieves the status of the given backup from the Moodle API

        :param jobid: UUID of the job the backupid is associated with
        :param jobdescriptor: Descriptor of the archiving job this request belongs to
        :param backupid: ID of the backup to get the status for
        :return: BackupStatus enum value
        :raises ConnectionError: if the request to the Moodle webservice API failed
        :raises RuntimeError: if the Moodle webservice API reported an error or
        the response contained an unhandled status value
        """
        pass
