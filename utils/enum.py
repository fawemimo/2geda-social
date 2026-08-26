from enum import Enum

# Defines the purpose of an OTP code.


class OTPPurpose(Enum):
    REGISTRATION = "registration"
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"
    PHONE_VERIFY = "phone_verify"
    EMAIL_VERIFY = "email_verify"
    DEVICE_TRUST = "device_trust"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class OTPChannel(Enum):
    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TOTP = "totp"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ConnectionStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class DevicePlatform(Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
    DESKTOP = "desktop"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class FollowStatus(Enum):
    PENDING = "pending"  # awaiting approval on private accounts
    ACCEPTED = "accepted"
    BLOCKED = "blocked"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class KYCStatus(Enum):
    NOT_SUBMITTED = "not_submitted"
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class KYCDocumentType(Enum):
    PASSPORT = "passport"
    NATIONAL_ID = "national_id"
    DRIVERS_LICENSE = "drivers_license"
    RESIDENCE_PERMIT = "residence_permit"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PostVisibility(Enum):
    PUBLIC = "public"
    FOLLOWERS = "followers"
    PRIVATE = "private"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationType(Enum):
    FOLLOW = "follow"
    FOLLOW_REQUEST = "follow_request"
    LIKE_POST = "like_post"
    LIKE_COMMENT = "like_comment"
    COMMENT = "comment"
    REPLY = "reply"
    RESHARE = "reshare"
    MENTION = "mention"
    KYC_APPROVED = "kyc_approved"
    KYC_REJECTED = "kyc_rejected"
    REFERRAL_JOINED = "referral_joined"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class MediaType(Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    GIF = "gif"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class MediaVisibility(Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    FRIENDS = "friends"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    FLAGGED = "flagged"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class CallType(Enum):
    AUDIO = "audio"
    VIDEO = "video"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ConversationType(Enum):
    DIRECT = "direct"  # exactly 2 participants
    GROUP = "group"  # 2+ participants, has name/avatar

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class MemberRole(Enum):
    MEMBER = "member"
    ADMIN = "admin"  # can add/remove members, change group settings
    OWNER = "owner"  # original creator, can delete group

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    LOCATION = "location"
    STICKER = "sticker"
    SYSTEM = "system"  # e.g. "Smith added Eze"
    REPLY = "reply"  # reply-in-thread (has reply_to FK)

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]

    # Delivery state (tracks socket delivery, not app-level read)


class DeliveryStatus(Enum):
    SENT = "sent"  # stored in DB
    DELIVERED = "delivered"  # socket ack received
    READ = "read"  # recipient opened conversation

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PointRewardingMaps(Enum):
    LOGIN = 2
    SIGNUP = 5
    POST = 3
    COMMENT = 2
    CHAT = 1
    STICK = 4
    LIKES = 1
    TIME = 2
    COMMERCE = 2
    LIVESTREAM = 2
    TICKET = 2
    STEREO = 2
    REFFERAL = 2

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationCategory(Enum):
    SOCIAL = "social"  # likes, reshares, comments
    FOLLOWING = "following"  # new follower, follow accepted
    MENTION = "mention"  # @username mentions
    CHAT = "chat"  # new message, group add
    SYSTEM = "system"  # account updates, KYC, security
    TICKETS = "tickets"  # ticket purchases, disputes
    MARKETING = "marketing"  # platform announcements (opt-in)

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationType(Enum):
    #  Social
    POST_LIKED = "post_liked"  # "Someone liked your post"
    POST_COMMENTED = "post_commented"  # "Someone commented on your post")
    POST_RESHARED = "post_reshared"  # "Someone reshared your post")
    COMMENT_LIKED = "comment_liked"  # "Someone liked your comment")
    COMMENT_REPLIED = "comment_replied"  # "Someone replied to your comment")
    DISPLAY_CREATED = "display_created"  # "Someone created a new display")

    #  Following
    NEW_FOLLOWER = "new_follower"  # "Someone followed you")
    FOLLOW_REQUEST = "follow_request"  # "Someone requested to follow you")
    FOLLOW_ACCEPTED = "follow_accepted"  # "Your follow request was accepted")

    #  Mention
    MENTION_POST = "mention_post"  # "You were mentioned in a post")
    MENTION_COMMENT = "mention_comment"  # "You were mentioned in a comment")

    #  Chat ─
    NEW_MESSAGE = "new_message"  # "New message")
    GROUP_ADDED = "group_added"  # "Added to a group chat")
    GROUP_REMOVED = "group_removed"  # "Removed from a group chat")
    JOIN_REQUEST = "join_request"  # "Wants to join a group")
    JOIN_APPROVED = "join_approved"  # "Join request approved")
    JOIN_REJECTED = "join_rejected"  # "Join request rejected")

    #  System ─
    KYC_APPROVED = "kyc_approved"  # "KYC verification approved")
    KYC_REJECTED = "kyc_rejected"  # "KYC verification rejected")
    KYC_EXPIRING = "kyc_expiring"  # "KYC verification expiring soon")
    NEW_DEVICE_LOGIN = "new_device_login"  # "New device login detected")
    PASSWORD_CHANGED = "password_changed"  # "Your password was changed")
    ACCOUNT_SUSPENDED = "account_suspended"  # "Account suspended")
    REFERRAL_JOINED = "referral_joined"  # "Someone joined using your referral")

    #  Tickets
    TICKET_PURCHASE = "ticket_purchase"  # "Someone purchased tickets")
    TICKET_CANCELLED = "ticket_cancelled"  # "Ticket cancelled")
    DISPUTE_OPENED = "dispute_opened"  # "Dispute opened on your event")
    DISPUTE_RESOLVED = "dispute_resolved"  # "Dispute resolved")

    #  Marketing
    ANNOUNCEMENT = "announcement"  # "Platform announcement")
    PROMOTION = "promotion"  # "Promotional offer")

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"  # always delivered even if category muted
    URGENT = "urgent"  # security alerts — bypass all mutes

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationAttachmentType(Enum):
    IMAGE = "image"
    THUMBNAIL = "thumbnail"
    GIF = "gif"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class NotificationMuteType(Enum):
    ACTOR = "actor"  # ("Mute notifications from a specific user")
    SOURCE = "source"  # ("Mute notifications about a specific object (post/group)")
    CATEGORY = "category"  # ("Mute an entire category (duplicate of preference but with expiry)"
     
    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]
    

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


# ──────────────────────────────────────────────
# Tickets / Events
# ──────────────────────────────────────────────


class EventStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class EventVisibility(Enum):
    PUBLIC = "public"
    PRIVATE_LINK = "private_link"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class TicketFeeBearer(Enum):
    BUYER = "buyer"
    SELLER = "seller"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PriceTag(Enum):
    GENERAL = "general"
    VIP = "vip"
    REGULAR = "regular"
    GOLD = "gold"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PricingMode(Enum):
    FLAT = "flat"
    CATEGORIZED = "categorized"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class SellerStatus(Enum):
    NOT_SUBMITTED = "not_submitted"
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class TicketStatus(Enum):
    RESERVED = "reserved"
    SOLD = "sold"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class DisputeReason(Enum):
    TICKET_NOT_DELIVERED = "ticket_not_delivered"
    EVENT_CANCELLED = "event_cancelled"
    WRONG_DESCRIPTION = "wrong_description"
    REFUND_REQUEST = "refund_request"
    OTHER = "other"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class DisputeStatus(Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_BUYER = "resolved_buyer"
    RESOLVED_SELLER = "resolved_seller"
    CLOSED = "closed"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PaymentStatus(Enum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class TransactionType(Enum):
    PURCHASE = "purchase"
    REFUND = "refund"
    FEE = "fee"
    PAYOUT = "payout"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


# ── Advertisements ───────────────────────────────────────────────────────────


class AdStatus(Enum):
    """Lifecycle of an advertisement.

    DRAFT -> PENDING_REVIEW -> APPROVED -> RUNNING -> COMPLETED
    Celery moves APPROVED -> RUNNING at starts_at and RUNNING -> COMPLETED at
    ends_at; every other transition is a human action.
    """

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdMode(Enum):
    """Where in the app an advert surfaces."""

    FLASH = "flash"                      # brief full-bleed flash between screens
    ON_STARTUP = "on_startup"            # splash / cold-start interstitial
    ON_FEED_LIST = "on_feed_list"        # native card inside the feed
    ON_COMMENT_SHOW = "on_comment_show"  # while a comment sheet is open
    ON_DISPLAY_VIEW = "on_display_view"  # between stories/displays
    ON_CHAT_LIST = "on_chat_list"        # banner above the conversation list
    ON_SEARCH_RESULT = "on_search_result"
    ON_PROFILE_VIEW = "on_profile_view"
    ON_POLL_RESULT = "on_poll_result"
    ON_TICKET_CHECKOUT = "on_ticket_checkout"
    ON_EXIT = "on_exit"                  # exit-intent / app backgrounding

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdScreenPosition(Enum):
    """Where on the mobile screen the creative is anchored."""

    TOP = "top"
    HEADER = "header"
    INLINE = "inline"
    MIDDLE = "middle"
    BOTTOM = "bottom"
    FOOTER = "footer"
    FULL_SCREEN = "full_screen"
    FLOATING = "floating"
    SIDEBAR = "sidebar"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdObjective(Enum):
    BRAND_AWARENESS = "brand_awareness"
    REACH = "reach"
    TRAFFIC = "traffic"
    ENGAGEMENT = "engagement"
    APP_INSTALLS = "app_installs"
    LEAD_GENERATION = "lead_generation"
    CONVERSIONS = "conversions"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdCallToAction(Enum):
    NONE = "none"
    LEARN_MORE = "learn_more"
    SHOP_NOW = "shop_now"
    SIGN_UP = "sign_up"
    DOWNLOAD = "download"
    BOOK_NOW = "book_now"
    CONTACT_US = "contact_us"
    GET_OFFER = "get_offer"
    WATCH_MORE = "watch_more"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdPricingModel(Enum):
    CPM = "cpm"    # cost per 1,000 impressions
    CPC = "cpc"    # cost per click
    CPA = "cpa"    # cost per action
    FLAT = "flat"  # flat fee for the flight

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdEventType(Enum):
    IMPRESSION = "impression"
    VIEWABLE_IMPRESSION = "viewable_impression"
    CLICK = "click"
    SKIP = "skip"
    CLOSE = "close"
    CONVERSION = "conversion"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class AdAudienceGender(Enum):
    ALL = "all"
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"

    @classmethod
    def choices(cls):
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]
