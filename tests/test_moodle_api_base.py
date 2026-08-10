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

"""
This modile implements the test suite for the MoodleAPIBase class, testing only its concrete (non-abstract) methods.
"""

import math
import pytest
from pathlib import Path
from typing import List
from unittest.mock import Mock, MagicMock, patch

@pytest.fixture
def mock_session():
    """Mock requests.Session object"""
    return MagicMock()

@pytest.fixture
def max_upload_bytes():
    """
    This fixture provides a mock maximum byte upload size value for this test
    suite to use when testing behaviour about conforming to or exceeding this
    hard limit. The value is arbitrarily chosen, but intentionally small
    compared to the default 512 MiB value of default moodle configurations.
    """
    return 1024*1024*5 # 5 MiB

@pytest.fixture(autouse=False)
def moodle_base_api(mock_session, max_upload_bytes):
    """
    Fixture providing a MoodleAPIBase instance with mocked session.
    """

    # Lazy import to avoid circular import issues
    from archiveworker.api.moodle import MoodleAPIBase

    # Overwrite abstract methods to enable instanciating for test
    def should_not_be_tested(*args, **kwargs):
        raise NotImplementedError("This abstract method should not be tested")
    original_abstract_methods =  MoodleAPIBase.__abstractmethods__
    original_methods = {
        name: getattr(MoodleAPIBase, name)
        for name in original_abstract_methods
    }
    for name in MoodleAPIBase.__abstractmethods__:
        setattr(MoodleAPIBase, name, should_not_be_tested)
    MoodleAPIBase.__abstractmethods__ = set()

    # Create fixture with modified abstract methods and yield to the test
    with patch('archiveworker.requests_factory.RequestsFactory.create_session', return_value=mock_session):
        api = MoodleAPIBase(
            base_url='http://example.invalid/moodle',
            ws_rest_url='http://example.invalid/moodle/webservice/rest/server.php',
            ws_upload_url='http://example.invalid/moodle/webservice/upload.php',
            wstoken='shepardlemon',
            max_upload_bytes=max_upload_bytes
        )
    yield api

    # Restore original abstract methods
    for name, method in original_methods.items():
        setattr(MoodleAPIBase, name, method)
    MoodleAPIBase.__abstractmethods__ = original_abstract_methods


@pytest.fixture
def small_test_file(tmp_path, max_upload_bytes):
    """
    Fixture providing a test file small enougth to be uploaded in one go.
    """
    file_path = tmp_path / "small_test_file.bin"
    file_path.write_bytes(b'x' * max_upload_bytes)
    return file_path

@pytest.fixture
def small_file_moodle_upload_response(small_test_file):
    """
    Fixture providing a valid Moodle file upload response structure.
    """
    return [{
        'component': 'user',
        'contextid': 1,
        'userid': 2,
        'filearea': 'draft',
        'filename': small_test_file.name,
        'filepath': '/',
        'itemid': 123
    }]

@pytest.fixture
def large_test_file(tmp_path, max_upload_bytes):
    """
    Fixture providing a test file to large to be uploaded in one go.
    """
    file_path = tmp_path / "large_test_file.bin"
    file_path.write_bytes(b'y' * (max_upload_bytes + 1))
    return file_path

@pytest.fixture
def large_file_moodle_upload_responses():
    """
    Fixture providing valid Moodle file upload response structures for each expected chunk.
    """
    component = 'user'
    contextid = 1234
    userid = 2
    filearea = 'draft'
    filepath = '/'
    itemid = 9876

    return [
        [{
        'component': component,
        'contextid': contextid,
        'userid': userid,
        'filearea': filearea,
        'filename': 'c000000.bin',
        'filepath': filepath,
        'itemid': itemid
        }],
        [{
        'component': component,
        'contextid': contextid,
        'userid': userid,
        'filearea': filearea,
        'filename': 'c000001.bin',
        'filepath': filepath,
        'itemid': itemid
        }],
    ]

@pytest.fixture
def empty_test_file(tmp_path):
    """
    Fixture providing an empty test file.
    """
    file_path = tmp_path / "empty_file.bin"
    file_path.write_bytes(b'')
    return file_path


class TestUploadFile:
    """
    Test suite for class method `upload_file`.
    """

    def test_single_upload_success(
            self,
            moodle_base_api,
            mock_session,
            small_test_file: Path,
            small_file_moodle_upload_response: List
        ):
        """
        Test upload of a file that is small enougth to fit in a single upload.
        """
        # Arrange
        mock_session.post.return_value.json.return_value = small_file_moodle_upload_response

        # Act
        result = moodle_base_api.upload_file(small_test_file)

        # Assert
        expected = small_file_moodle_upload_response[0]
        assert result is not None
        assert len(result.keys()) > 0
        assert result['component'] == expected['component']
        assert result['contextid'] == expected['contextid']
        assert result['userid'] == expected['userid']
        assert result['filearea'] == expected['filearea']
        assert result['filename'] == expected['filename']
        assert result['filepath'] == expected['filepath']
        assert result['itemid'] == expected['itemid']
        assert result['artifactcount'] == 1, f"Expected 1 artifact to process, got {result['artifactcount']}"

        mock_session.post.assert_called_once()

    def test_chunked_upload_success(
            self,
            moodle_base_api,
            mock_session,
            large_test_file: Path,
            large_file_moodle_upload_responses: List
    ):
        """
        Test that files larger than max_upload_bytes are chunked with multiple uploads.
        """
        # Arrange
        chunk0_response = Mock()
        chunk0_response.status_code = 200
        chunk0_response.json.return_value = large_file_moodle_upload_responses[0]
        chunk1_response = Mock()
        chunk1_response.status_code = 200
        chunk1_response.json.return_value = large_file_moodle_upload_responses[1]
        mock_session.post.side_effect = [chunk0_response, chunk1_response]
        expected_chunks = math.ceil(
            large_test_file.stat().st_size / moodle_base_api.max_upload_bytes
        )

        # Act
        result = moodle_base_api.upload_file(large_test_file)

        # Assert
        assert mock_session.post.call_count == expected_chunks
        expected = large_file_moodle_upload_responses[0][0]
        assert result is not None
        assert len(result.keys()) > 0
        assert result['component'] == expected['component']
        assert result['contextid'] == expected['contextid']
        assert result['userid'] == expected['userid']
        assert result['filearea'] == expected['filearea']
        assert result['filename'] == large_test_file.name
        assert result['filepath'] == expected['filepath']
        assert result['itemid'] == expected['itemid']
        assert result['artifactcount'] == expected_chunks, f"Expected {expected_chunks} artifact (chunks), got {result['artifactcount']}"

    def test_nonexistent_file_raises_error(self, moodle_base_api):
        """
        Test that uploading a non-existent file raises FileNotFoundError.
        """
        with pytest.raises(FileNotFoundError):
            moodle_base_api.upload_file(
                Path("./nonexistent/path/to/a/specific/file.bin")
            )

    def test_moodle_upload_error(self, moodle_base_api, mock_session, small_test_file):
        """
        Test that a Moodle API error response (with errorcode and debuginfo) raises RuntimeError.
        """
        # Arrange
        error_response = Mock()
        error_response.status_code = 400
        error_response.json.return_value = {
            'errorcode': 'invalid_request',
            'debuginfo': 'Invalid request parameters'
        }
        mock_session.post.return_value = error_response

        # Act + Assert
        with pytest.raises(RuntimeError) as exc_info:
            moodle_base_api.upload_file(small_test_file)

    def test_moodle_upload_exception(self, moodle_base_api, mock_session, small_test_file):
        """
        Test that a Moodle API error response (with exception and message) raises RuntimeError.
        """
        # Arrange
        error_response = Mock()
        error_response.status_code = 400
        error_response.json.return_value = {
            'exception': 'error',
            'message': 'Class "Exception" has no method "just_fix_it".'
        }
        mock_session.post.return_value = error_response

        # Act + Assert
        with pytest.raises(RuntimeError) as exc_info:
            moodle_base_api.upload_file(small_test_file)

class TestDownloadMoodleFile:
    """
    TODO: implement
    """

class TestCheckConnection:
    """
    TODO: implement
    """

class TestGetRemoteFileMetadata:
    """
    TODO: implement
    """
