from accounts.services.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServiceError,
    ValidationError,
)


class PollExpiredError(ServiceError):
    default_message = "This poll has expired."
    code = "poll_expired"
    status_code = 400


class VoteAlreadyCastError(ConflictError):
    default_message = "You have already voted on this poll."
    code = "vote_already_cast"


class DuplicateVoteError(ConflictError):
    default_message = "You have already voted for this option."
    code = "duplicate_vote"
