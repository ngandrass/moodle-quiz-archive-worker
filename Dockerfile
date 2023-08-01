# Moodle Quiz Archive Worker
# Copyright (C) 2023 Niels Gandraß <niels@gandrass.de>
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

FROM python:3.11

ENV USER_NAME archiveworker
ENV USER_HOME /app

RUN set -e && \
    mkdir ${USER_HOME}
WORKDIR ${USER_HOME}

# Install chromium dependencies
RUN set -e && \
    apt-get update && \
    apt-get install -y $(apt-cache depends chromium | grep Depends | grep --invert-match "Depends: <" | sed "s/.*Depends:\ //" | tr '\n' ' ') && \
    rm -rf /var/lib/apt/lists/*

# Install poetry and app requirements
COPY . ${USER_HOME}
RUN set -e && \
    pip3 install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-root --only main && \
    chmod +x "${USER_HOME}/moodle-quiz-archive-worker.py"

# Create app user
RUN set -ex && \
    groupadd --system --gid 1000 "${USER_NAME}" && \
    useradd --system -g "${USER_NAME}" --uid 1000 --no-create-home --home-dir "${USER_HOME}" "${USER_NAME}" && \
    chown -R "${USER_NAME}" "${USER_HOME}"
USER ${USER_NAME}

# Initialize playwright (download browsers). THIS MUST BE PERFORMED AS THE APP USER!
RUN set -ex && \
    playwright install chromium

# Run definition
EXPOSE 8080
CMD ["/bin/sh", "-c", "/app/moodle-quiz-archive-worker.py"]
