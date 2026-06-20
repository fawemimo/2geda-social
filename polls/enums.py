from enum import Enum


class PollType(Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PollStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]
