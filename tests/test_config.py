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
import os

import pytest

from config import parse_env_variable


class TestConfig:
    """
    Tests for the Config class
    """

    @pytest.mark.parametrize("envvar, default", [
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_1337", None),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_42", "foo"),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_1337", "bar"),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_42", "baz"),
    ])
    def test_parse_env_variable_unset_default(self, envvar, default) -> None:
        """
        Tests that unset environment variables are parsed to their default value

        :param envvar: Name of the env var
        :param default: Default value to use if env var is unset
        :return: None
        """
        os.environ.pop(envvar, None)

        assert parse_env_variable(envvar, default) == default

    @pytest.mark.parametrize("envvar, value, default", [
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_1337", "foo", None),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_42", "baz", None),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_1337", "bar", "invalid"),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ_42", "baz", "invalid"),
    ])
    def test_parse_env_variable_existing(self, envvar, value, default) -> None:
        """
        Tests that set environment variables are parsed to their value

        :param envvar: Name of the env var
        :param value: Value to set the env var to
        :param default: Default value to use if env var is unset
        :return: None
        """
        os.environ[envvar] = value
        assert parse_env_variable(envvar, default) == value

        os.environ.pop(envvar, None)
        assert parse_env_variable(envvar, default) == default

    @pytest.mark.parametrize("envvar, valtype, value, expected, shouldfail", [
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "True", True, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "true", True, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "1", True, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "tru", False, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "False", False, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "false", False, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "0", False, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "", False, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", bool, "None", False, False),

        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", int, "1337", 1337, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", int, "42", 42, False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", int, "-42", -42, False),

        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", str, "foo", "foo", False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", str, "bar", "bar", False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", str, "baz", "baz", False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", str, "", "", False),

        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", int, "13xxx37", None, True),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", int, "zweiundvierzig", None, True),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", int, "", None, True),
    ])
    def test_parse_env_variable_typecast(self, envvar, valtype, value, expected, shouldfail) -> None:
        """
        Tests that environment variables are typecasted correctly

        :param envvar: Name of the env var
        :param valtype: Type to forcecast the env var to
        :param value: Value to set the env var to
        :param expected: Expected value after typecasting
        :param shouldfail: Whether the test should fail
        :return: None
        """
        os.environ[envvar] = value
        if shouldfail:
            with pytest.raises(ValueError):
                assert parse_env_variable(envvar, None, valtype) == expected
        else:
            assert parse_env_variable(envvar, None, valtype) == expected
            assert type(parse_env_variable(envvar, None, valtype)) == type(expected)

        os.environ.pop(envvar, None)

    @pytest.mark.parametrize("envvar, value, expected", [
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "True", True),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "true", True),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "False", False),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "false", False),

        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "1337", 1337),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "42", 42),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "-42", -42),

        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "foo", "foo"),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "bar", "bar"),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "baz", "baz"),
        ("MOODLE_ARCHIVER_FOO_BAR_BAZ", "", ""),
    ])
    def test_parse_env_variable_auto_typecast(self, envvar, value, expected) -> None:
        """
        Tests that environment variables are typecasted correctly

        :param envvar: Name of the env var
        :param value: Value to set the env var to
        :param expected: Expected value after typecasting
        :return: None
        """
        os.environ[envvar] = value
        assert parse_env_variable(envvar, None) == expected
        assert type(parse_env_variable(envvar, None)) == type(expected)
        os.environ.pop(envvar, None)

    def test_parse_env_variable_auto_typecast_unset(self) -> None:
        """
        Tests that the automatic type detection does not trigger for unset env vars
        :return:
        """
        os.environ.pop("MOODLE_ARCHIVER_FOO_BAR_BAZ", None)
        assert type(parse_env_variable("MOODLE_ARCHIVER_FOO_BAR_BAZ", None)) is type(None)
        assert type(parse_env_variable("MOODLE_ARCHIVER_FOO_BAR_BAZ", None, bool)) is type(None)
        assert type(parse_env_variable("MOODLE_ARCHIVER_FOO_BAR_BAZ", None, int)) is type(None)
        assert type(parse_env_variable("MOODLE_ARCHIVER_FOO_BAR_BAZ", None, str)) is type(None)
