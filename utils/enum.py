from enum import Enum

# Defines the purpose of an OTP code.

class OTPPurpose(Enum):
    REGISTRATION    = "registration"
    LOGIN           = "login"
    PASSWORD_RESET  = "password_reset"
    PHONE_VERIFY    = "phone_verify"
    EMAIL_VERIFY    = "email_verify"
    DEVICE_TRUST    = "device_trust"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class OTPChannel(Enum):
    SMS   = "sms"
    EMAIL = "email"
    TOTP  = "totp"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]

class ConnectionStatus(Enum):
    PENDING   = "pending"
    ACCEPTED  = "accepted"
    REJECTED   = "rejected"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]

class DevicePlatform(Enum):
    IOS     = "ios"
    ANDROID = "android"
    WEB     = "web"
    DESKTOP = "desktop"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]

class FollowStatus(Enum):
    PENDING  = "pending"  # awaiting approval on private accounts
    ACCEPTED = "accepted"
    BLOCKED  = "blocked"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class KYCStatus(Enum):
    NOT_SUBMITTED = "not_submitted"
    PENDING       = "pending"
    UNDER_REVIEW  = "under_review"
    APPROVED      = "approved"
    REJECTED      = "rejected"
    EXPIRED       = "expired"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class KYCDocumentType(Enum):
    PASSPORT        = "passport"
    NATIONAL_ID     = "national_id"
    DRIVERS_LICENSE = "drivers_license"
    RESIDENCE_PERMIT = "residence_permit"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PostVisibility(Enum):
    PUBLIC    = "public"
    FOLLOWERS = "followers"
    PRIVATE   = "private"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationType(Enum):
    FOLLOW          = "follow"
    FOLLOW_REQUEST  = "follow_request"
    LIKE_POST       = "like_post"
    LIKE_COMMENT    = "like_comment"
    COMMENT         = "comment"
    REPLY           = "reply"
    RESHARE         = "reshare"
    MENTION         = "mention"
    KYC_APPROVED    = "kyc_approved"
    KYC_REJECTED    = "kyc_rejected"
    REFERRAL_JOINED = "referral_joined"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]



class MediaType(Enum):
    IMAGE    = "image"
    VIDEO    = "video"
    AUDIO    = "audio"
    DOCUMENT = "document"
    GIF      = "gif"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]

class MediaVisibility(Enum):
    PUBLIC   = "public"
    PRIVATE  = "private"
    FRIENDS  = "friends"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ProcessingStatus(Enum):
    PENDING     = "pending"
    PROCESSING  = "processing"
    READY       = "ready"
    FAILED      = "failed"
    FLAGGED     = "flagged"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]



class ConversationType(Enum):
    DIRECT = "direct"  # exactly 2 participants
    GROUP  = "group"     # 2+ participants, has name/avatar

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]



class MemberRole(Enum):
    MEMBER = "member"
    ADMIN  = "admin"   # can add/remove members, change group settings
    OWNER  = "owner"   # original creator, can delete group

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]



class MessageType(Enum):
    TEXT        = "text"
    IMAGE       = "image"
    VIDEO       = "video"
    AUDIO       = "audio"
    FILE        = "file"
    LOCATION    = "location"
    STICKER     = "sticker"
    SYSTEM      = "system"    # e.g. "Smith added Eze"
    REPLY       = "reply"   # reply-in-thread (has reply_to FK)

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]



    # Delivery state (tracks socket delivery, not app-level read)
class DeliveryStatus(Enum):
    SENT      = "sent"    # stored in DB
    DELIVERED = "delivered"    # socket ack received
    READ      = "read"         # recipient opened conversation

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PointRewardingMaps(Enum):
    LOGIN= 2
    SIGNUP= 5
    POST= 3
    COMMENT= 2
    CHAT= 1
    STICK= 4
    LIKES= 1
    TIME= 2
    COMMERCE= 2
    LIVESTREAM= 2
    TICKET= 2
    STEREO= 2
    REFFERAL= 2

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]

