# Moodle Quiz Archive Worker
# Copyright (C) 2024 Niels Gandraß <niels@gandrass.de>
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

from .conftest import client

from config import Config


def test_index(client):
    response = client.get('/')

    assert response.status_code == 200
    assert response.json['app'] == Config.APP_NAME
    assert response.json['version'] == Config.VERSION


def test_version(client):
    response = client.get('/version')

    assert response.status_code == 200
    assert response.json['version'] == Config.VERSION


def test_status(client):
    response = client.get('/status')

    assert response.status_code == 200
    assert response.json['status'] == 'IDLE'
    assert response.json['queue_len'] == 0
