from enum import StrEnum


class WorkerStatus(StrEnum):
    """
    Status values that the quiz archive worker can report
    """
    IDLE = 'IDLE'
    ACTIVE = 'ACTIVE'
    BUSY = 'BUSY'
    UNKNOWN = 'UNKNOWN'


class JobStatus(StrEnum):
    """
    Status values a single quiz archive worker job can have
    """
    UNINITIALIZED = 'UNINITIALIZED'
    AWAITING_PROCESSING = 'AWAITING_PROCESSING'
    RUNNING = 'RUNNING'
    FINISHED = 'FINISHED'
    FAILED = 'FAILED'
