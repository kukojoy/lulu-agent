from enum import StrEnum

class ReviewerType(StrEnum):
    MEMORY = "memory"
    SKILLS = "skills"


class ReviewStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
