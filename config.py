class Config:

    APP_NAME = "moodle-quiz-archive-worker"
    """Name of this app."""

    VERSION = "0.1.0"
    """Version of this app."""

    QUEUE_SIZE = 8
    """Maximum number of requests that are queued before returning an error."""

    HISTORY_SIZE = 128
    """Maximum number of jobs to keep in the history before forgetting about them."""

    REQUEST_TIMEOUT_SEC = 1800
    """Number of seconds before execution of a single request is aborted."""
