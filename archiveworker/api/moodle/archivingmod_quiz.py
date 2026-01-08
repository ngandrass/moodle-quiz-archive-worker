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

import json
from json import JSONDecodeError
from typing import Dict, Tuple, List
from uuid import UUID

from archiveworker.type import JobStatus, MoodleBackupStatus
from archiveworker.api.worker import ArchiveJobDescriptor

from . import MoodleAPIBase


class ArchivingmodQuizMoodleAPI(MoodleAPIBase):
    """
    Adapter for the archivingmod_quiz plugin Moodle web service API
    """

    MOODLE_WSFUNCTION_ARCHIVE = 'archivingmod_quiz_generate_attempt_report'
    """Name of the Moodle webservice function to call to trigger an quiz attempt export"""

    MOODLE_WSFUNCTION_PROESS_UPLOAD = 'archivingmod_quiz_process_uploaded_artifact'
    """Name of the Moodle webservice function to call after an artifact was uploaded successfully"""

    MOODLE_WSFUNCTION_UPDATE_JOB_STATUS = 'archivingmod_quiz_update_task_status'
    """Name of the Moodle webservice function to call to update the status of a job / task"""

    MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA = 'archivingmod_quiz_get_attempts_metadata'
    """Name of the Moodle webservice function to call to retrieve metadata about quiz attempts"""

    def _get_check_connection_wsfunction_name(self) -> str:
        """
        Returns the name of a webservice function that can be called to check if
        the basic connection to the Moodle API is working. In the easiest case
        this is something like 'update_job_status'.

        :return: Name of the webservice function to call in check_connection()
        """
        return self.MOODLE_WSFUNCTION_UPDATE_JOB_STATUS

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
        :param jobdescriptor: Job descriptor object containing job metadata
        :param status: New status to set
        :param statusextras: Additional status information to include
        :return: True if the status was updated successfully, False otherwise
        """
        try:
            # Prepare statusextras
            conditional_params = {}
            if statusextras:
                if 'progress' in statusextras:
                    conditional_params['progress'] = statusextras['progress']

            # Translate job status to activity archiving task status
            taskstatus = {
                JobStatus.UNINITIALIZED: 20,
                JobStatus.AWAITING_PROCESSING: 40,
                JobStatus.RUNNING: 100,
                JobStatus.WAITING_FOR_BACKUP: 200,
                JobStatus.FINALIZING: 200,
                JobStatus.FINISHED: 220,
                JobStatus.FAILED: 250,
                JobStatus.TIMEOUT: 251,
            }.get(status, 255)

            self.logger.debug("STATUS: %s -> %s", status, taskstatus)

            # Call wsfunction to update job status
            r = self.session.get(
                url=self.ws_rest_url,
                timeout=self.REQUEST_TIMEOUTS,
                params=self._generate_wsfunc_request_params(
                    wsfunction=self.MOODLE_WSFUNCTION_UPDATE_JOB_STATUS,
                    uuid=str(jobid),
                    taskid=str(jobdescriptor.taskid),
                    status=taskstatus,
                    **conditional_params
                )
            )
            self.logger.debug(r.text)
            data = r.json()

            if data['status'] == 'OK':
                return True
            else:
                self.logger.warning(f'Moodle API rejected to update job status to new value: {status}')
        except Exception:
            self.logger.warning('Failed to update job status via Moodle API. Connection error.')

        return False

    def get_backup_status(
            self,
            jobid: UUID,
            jobdescriptor: ArchiveJobDescriptor,
            backupid: str
    ) -> MoodleBackupStatus:
        raise NotImplementedError('Archivingmod Quiz API does not support handling Moodle backups')

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
        # Slice attemptids into batches
        attemptids = jobdescriptor.tasks['quiz_attempts']['attemptids']
        batchsize = 100
        batches = [attemptids[i:i + batchsize] for i in range(0, len(attemptids), batchsize)]

        # Fetch metadata for each batch
        metadata = []
        params = self._generate_wsfunc_request_params(
            wsfunction=self.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA,
            uuid=str(jobid),
            taskid=str(jobdescriptor.taskid),
        )

        for batch in batches:
            try:
                params['attemptids[]'] = batch
                r = self.session.get(
                    url=self.ws_rest_url,
                    timeout=self.REQUEST_TIMEOUTS,
                    params=params
                )
                data = r.json()
            except Exception:
                self.logger.debug(f'Call to Moodle webservice function {self.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} at "{self.ws_rest_url}')
                raise ConnectionError(f'Call to Moodle webservice function {self.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} at "{self.ws_rest_url}" failed')

            # Check if Moodle wsfunction returned an error
            if 'errorcode' in data and 'debuginfo' in data:
                raise RuntimeError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} returned error "{data["errorcode"]}". Message: {data["debuginfo"]}')

            # Check if response is as expected
            for attr in ['attempts', 'cmid', 'courseid', 'quizid']:
                if attr not in data:
                    raise ValueError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_GET_ATTEMPTS_METADATA} returned an incomplete response')

            # Data seems valid
            metadata.extend(data['attempts'])
            self.logger.debug(f"Fetched metadata for {len(metadata)} of {len(attemptids)} quiz attempts")

        return metadata

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
        try:
            r = self.session.get(
                url=self.ws_rest_url,
                timeout=self.REQUEST_TIMEOUTS,
                params=self._generate_wsfunc_request_params(
                    wsfunction=self.MOODLE_WSFUNCTION_ARCHIVE,
                    uuid=str(jobid),
                    taskid=str(jobdescriptor.taskid),
                    attemptid=attemptid,
                    foldernamepattern=jobdescriptor.tasks['quiz_attempts']['foldername_pattern'],
                    filenamepattern=jobdescriptor.tasks['quiz_attempts']['filename_pattern'],
                    attachments=1 if jobdescriptor.tasks['quiz_attempts']['fetch_attachments'] else 0,
                    **{f'sections[{key}]': value for key, value in jobdescriptor.tasks['quiz_attempts']['sections'].items()}
                )
            )

            # Moodle 4.3 seems to return an additional "</body></html>" at the end of the response which causes the JSON parser to fail
            response = r.text.lstrip('<html><body>').rstrip('</body></html>')
            data = json.loads(response)
        except JSONDecodeError as e:
            self.logger.debug(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} response: {r.text}')
            raise ValueError(f'Call to Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} at "{self.ws_rest_url}" returned invalid JSON')
        except Exception as e:
            self.logger.debug(f'Call to Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} caused {type(e).__name__}: {str(e)}')
            raise ConnectionError(f'Call to Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} at "{self.ws_rest_url}" failed')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in data:
            if 'debuginfo' in data:
                raise RuntimeError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}". Message: {data["debuginfo"]}')
            if 'message' in data:
                raise RuntimeError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}". Message: {data["message"]}')
            raise RuntimeError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned error "{data["errorcode"]}".')

        # Check if response is as expected
        for attr in ['attemptid', 'foldername', 'filename', 'report', 'attachments']:
            if attr not in data:
                self.logger.debug(f'Missing attribute: {attr}')
                raise ValueError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned an incomplete response')

        if not (
                data['attemptid'] == attemptid and
                isinstance(data['foldername'], str) and
                isinstance(data['filename'], str) and
                isinstance(data['report'], str) and
                isinstance(data['attachments'], list)
        ):
            raise ValueError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned an invalid response')

        # Validate received folder and file names
        if any(char in data['foldername'] for char in self.FOLDERNAME_FORBIDDEN_CHARACTERS):
            raise ValueError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned an invalid foldername')

        if data['foldername'].startswith('/') or data['foldername'].endswith('/'):
            raise ValueError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned a forbidden foldername')

        if any(char in data['filename'] for char in self.FILENAME_FORBIDDEN_CHARACTERS):
            raise ValueError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_ARCHIVE} returned an invalid filename')

        # Looks fine - Data seems valid :)
        return data['foldername'], data['filename'], data['report'], data['attachments']


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
        # Call wsfunction to process artifact
        try:
            r = self.session.get(
                url=self.ws_rest_url,
                timeout=self.REQUEST_TIMEOUTS_EXTENDED,
                params=self._generate_wsfunc_request_params(
                    wsfunction=self.MOODLE_WSFUNCTION_PROESS_UPLOAD,
                    uuid=str(jobid),
                    taskid=str(jobdescriptor.taskid),
                    artifact_component=component,
                    artifact_contextid=contextid,
                    artifact_userid=userid,
                    artifact_filearea=filearea,
                    artifact_filename=filename,
                    artifact_filepath=filepath,
                    artifact_itemid=itemid,
                    artifact_sha256sum=sha256sum,
                )
            )
            response = r.json()
        except Exception:
            ConnectionError(f'Failed to call upload processing hook "{self.MOODLE_WSFUNCTION_PROESS_UPLOAD}" at "{self.ws_rest_url}"')

        # Check if Moodle wsfunction returned an error
        if 'errorcode' in response and 'debuginfo' in response:
            raise RuntimeError(f'Moodle webservice function {self.MOODLE_WSFUNCTION_PROESS_UPLOAD} returned error "{response["errorcode"]}". Message: {response["debuginfo"]}')

        # Check that everything went smoothly on the Moodle side (not that we could change anything here...)
        if response['status'] != 'OK':
            raise RuntimeError(f'Moodle webservice failed to process uploaded artifact with status: {response["status"]}')

        return True
