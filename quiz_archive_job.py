from uuid import UUID

from custom_types import JobStatus, JobArchiveRequest


class QuizArchiveJob:
    """
    A single archive job that is processed by the quiz archive worker
    """

    def __init__(self, jobid: UUID, job_request: JobArchiveRequest):
        self.id = jobid
        self.status = JobStatus.UNINITIALIZED
        self.request = job_request

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

    def set_status(self, status: JobStatus) -> None:
        self.status = status
