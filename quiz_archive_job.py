from uuid import UUID

from custom_types import JobStatus


class QuizArchiveJob:
    """
    A single archive job that is processed by the quiz archive worker
    """

    def __init__(self, jobid):
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == UUID(other)
        else:
            return False

    def to_json(self) -> object:
        return {
            'id': self.id,
            'status': self.status
        }

    def get_id(self) -> UUID:
        return self.id

    def get_status(self) -> JobStatus:
        return self.status
