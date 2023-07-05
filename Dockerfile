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
EXPOSE 5000
CMD ["/bin/sh", "-c", "/app/moodle-quiz-archive-worker.py"]
