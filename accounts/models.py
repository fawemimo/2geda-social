"""
Covers:
  - Custom User (email-first, phone-first onboarding)
  - OTP validation
  - Registered devices  (push tokens, device fingerprints)
  - User locations
  - Referral codes
  - User device
  - 

Design principles applied:
  - SOLID: each model owns exactly one domain concept
  - PostgreSQL: GIN indexes on search vectors, BRIN on time columns
  - Scalability: device & location tables are append-only with TTL semantics
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import BrinIndex, GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from utils.enum import DevicePlatform, FollowStatus, KYCDocumentType, KYCStatus, OTPChannel, OTPPurpose, ConnectionStatus
from utils.generators import _generate_referral_code
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin



class UserManager(BaseUserManager):

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        return self._create_user(email, password, **extra_fields)

    def active(self):
        return self.get_queryset().filter(is_active=True, is_deleted=False)



class User(UUIDPrimaryKeyMixin, TimestampMixin, PermissionsMixin, AbstractBaseUser):
    """
    Central identity record.

    - Email is the login credential.
    - Phone number is optional at registration; required for OTP later.
    - `referral_code` is unique per user; auto-generated on creation.
    - `referred_by` FK is set at registration if the user arrived via a link.
    - `search_vector` is maintained via a PostgreSQL trigger.
    """

    # ---- Core identity ----
    email = models.EmailField(_("email address"), unique=True, db_index=True,blank=True, null=True)
    phone_number = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=_("E.164 format: +2348012345678"),
    )
    username = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        help_text=_("Public handle. Alphanumeric + underscores, 3-40 chars."),
    )

    # ---- Status flags ----
    is_active = models.BooleanField(default=False)   # activated after OTP
    is_staff = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # ---- Email / phone verification ----
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)

    # ---- Referral ----
    referral_code = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        default=_generate_referral_code,
    )
    referred_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referrals",
        db_index=True,
    )

    # ---- Full-text search ----
    # Populated by a DB trigger: UPDATE user SET search_vector = to_tsvector(...)
    search_vector = SearchVectorField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        verbose_name = _("user")
        verbose_name_plural = _("users")
        indexes = [
            GinIndex(fields=["search_vector"], name="user_search_gin_idx"),
            models.Index(fields=["referral_code"], name="user_referral_idx"),
            models.Index(fields=["referred_by"], name="user_referred_by_idx"),
            models.Index(fields=["created_at"], name="user_created_at_idx"),
            # Partial index: active, non-deleted users only (most queries)
            models.Index(
                fields=["email"],
                condition=models.Q(is_active=True, is_deleted=False),
                name="user_active_email_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.email}>>"

    def soft_delete(self):
        self.is_deleted = True
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "is_active", "deleted_at"])


class OTP(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One-time password record.

    Security notes:
      - Store only the **hashed** code (use Django's make_password / check_password).
      - `expires_at` is checked at validation time; expired rows are purged by a cron job.
      - `attempt_count` guards against brute-force on the 6-digit space.
      - A single `is_used` flag prevents replay.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="otps",
        db_index=True,
    )
    # Store hashed OTP — NEVER plaintext
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=20, choices=OTPPurpose.choices, db_index=True)
    channel = models.CharField(max_length=10, choices=OTPChannel.choices, default=OTPChannel.EMAIL.value)

    # Delivery target (could differ from user's primary phone/email)
    delivery_address = models.CharField(
        max_length=255,
        help_text=_("Phone number or email the OTP was sent to."),
    )

    expires_at = models.DateTimeField(db_index=True)
    is_used = models.BooleanField(default=False, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)

    # Rate-limiting helpers
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "accounts_otp"
        verbose_name = _("OTP")
        indexes = [
            models.Index(fields=["user", "purpose", "is_used"], name="otp_user_purpose_idx"),
            models.Index(fields=["expires_at"], name="otp_expires_at_idx"),
            # Partial index: only unexpired, unused rows are ever queried
            models.Index(
                fields=["user", "purpose"],
                condition=models.Q(is_used=False),
                name="otp_active_idx",
            ),
        ]

    def is_valid(self) -> bool:
        return not self.is_used and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"OTP({self.purpose}) \u2192 {self.user_id}"


class UserDevice(BaseModel):
    """
    Registered device record.

    Users see this list in their security settings and can revoke any entry.
    Revoked devices lose their push token and cannot receive silent notifications.

    `device_fingerprint` is a stable client-generated hash (e.g. from screen
    resolution + GPU + fonts) — NOT a UUID we generate.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="devices",
        db_index=True,
    )
    # Human-readable name shown in the UI ("iPhone 15 Pro", "Chrome on Mac")
    name = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=10, choices=DevicePlatform.choices)
    os_version = models.CharField(max_length=30, blank=True)
    app_version = models.CharField(max_length=20, blank=True)

    # Stable fingerprint generated client-side
    device_fingerprint = models.CharField(max_length=256, db_index=True)

    # Push notification token (FCM / APNs)
    push_token = models.TextField(blank=True)
    push_token_updated_at = models.DateTimeField(null=True, blank=True)

    # Trust state
    is_trusted = models.BooleanField(default=False, db_index=True)
    trusted_at = models.DateTimeField(null=True, blank=True)

    # Last activity
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    

    class Meta:
        db_table = "accounts_user_device"
        verbose_name = _("user device")
        unique_together = [("user", "device_fingerprint")]
        indexes = [
            models.Index(fields=["user", "is_deleted"], name="device_user_active_idx"),
            BrinIndex(fields=["last_seen_at"], name="device_last_seen_brin_idx"),
        ]

    def revoke(self):
        """Soft-delete = logout from this device."""
        self.push_token = ""
        self.is_trusted = False
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["push_token", "is_trusted", "is_deleted", "deleted_at"])

    def __str__(self) -> str:
        return f"{self.name or self.platform} ({self.user_id})"



class UserLocation(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Append-only location snapshot.

    - Never mutate; always insert a new row.
    - The most recent row per user is the canonical location.
    - Older rows are archived / purged after a retention window.
    - PostGIS point field can be added later without schema upheaval:
        position = PointField(geography=True, null=True)

    For now we store lat/lon as Decimal for portability.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="locations",
        db_index=True,
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    location_data = models.JSONField(blank=True, null=True)  # e.g. geocoding results

    class Meta:
        db_table = "accounts_user_location"
        verbose_name = _("user location")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="location_user_latest_idx"),
            BrinIndex(fields=["created_at"], name="location_created_brin_idx")
        ]

    def __str__(self) -> str:
        return f"({self.latitude}, {self.longitude}) @ {self.created_at:%Y-%m-%d %H:%M}"


class Referral(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tracks a completed referral conversion.
    A row is created when a referred_user completes registration.
    Useful for rewarding referrers (credits, badges, etc.).
    """
    referrer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="successful_referrals",
        db_index=True,
    )
    referred_user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="referral_record",
    )
    reward_granted = models.BooleanField(default=False)
    reward_granted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_referral"
        indexes = [
            models.Index(fields=["referrer", "reward_granted"], name="referral_reward_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.referrer} \u2192 {self.referred_user}"



class PointsRewarding(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Generic reward record associable with any source action
    (referral, KYC approval, daily login, etc.) via GenericForeignKey.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="point_rewards",
        db_index=True,
    )
    points = models.PositiveIntegerField()
    reason = models.CharField(max_length=120, blank=True)

    source_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    source_object_id = models.UUIDField(db_index=True)
    source = GenericForeignKey("source_content_type", "source_object_id")

    is_claimed = models.BooleanField(default=False, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_point_reward"
        indexes = [
            models.Index(fields=["user", "is_claimed"], name="reward_user_claimed_idx"),
            models.Index(
                fields=["source_content_type", "source_object_id"],
                name="reward_source_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} +{self.points}pts ({self.reason or 'reward'})"


class UserProfile(BaseModel):
    """
    Public-facing profile data, separate from auth concerns.
 
    `search_vector` covers display_name + bio + username (maintained via trigger).
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        primary_key=False,
    )
 
    # ---- Display info ----
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    website = models.URLField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
 
    # ---- Media (FK to media.Media, set via string ref to avoid circular import) ----
    avatar = models.ForeignKey(
        "medias.Media",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile_avatars",
    )
    cover_photo = models.ForeignKey(
        "medias.Media",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile_covers",
    )
 
    # ---- Privacy ----
    is_private = models.BooleanField(
        default=False,
        help_text=_("If True, follower requests must be approved."),
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("Set by KYC approval."),
    )
 
    # ---- Counters (denormalised for fast reads — updated by signals/tasks) ----
    followers_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    posts_count = models.PositiveIntegerField(default=0)
 
    # ---- Full-text search ----
    search_vector = SearchVectorField(null=True, blank=True)
 
    class Meta:
        db_table = "profiles_user_profile"
        verbose_name = _("user profile")
        indexes = [
            GinIndex(fields=["search_vector"], name="profile_search_gin_idx"),
            models.Index(fields=["is_verified"], name="profile_verified_idx"),
            models.Index(fields=["is_private"], name="profile_private_idx"),
        ]
 
    def __str__(self) -> str:
        return f"Profile({self.user.username})"
 

class Follow(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Directed follow graph: follower \u2192 following.
 
    For public accounts, status is immediately ACCEPTED.
    For private accounts, status starts as PENDING until the followee approves.
 
    Blocking is also modelled here (status=BLOCKED) to keep graph queries simple.
 
    Unique constraint on (follower, following) prevents duplicate edges.
    """
    follower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="following_set",   # people this user follows
        db_index=True,
    )
    following = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="followers_set",   # people who follow this user
        db_index=True,
    )
    status = models.CharField(
        max_length=10,
        choices=FollowStatus.choices,
        default=FollowStatus.ACCEPTED.value,
        db_index=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        db_table = "profiles_follow"
        verbose_name = _("follow")
        verbose_name_plural = _("follows")
        unique_together = [("follower", "following")]
        indexes = [
            # "Who follows user X?" — notifications, follower list
            models.Index(fields=["following", "status"], name="follow_following_status_idx"),
            # "Who does user X follow?" — feed fan-out
            models.Index(fields=["follower", "status"], name="follow_follower_status_idx"),
            # Partial: accepted follows only (the hot path)
            models.Index(
                fields=["follower"],
                condition=models.Q(status="accepted"),
                name="follow_accepted_follower_idx",
            ),
            models.Index(
                fields=["following"],
                condition=models.Q(status="accepted"),
                name="follow_accepted_following_idx",
            ),
        ]
 
    def __str__(self) -> str:
        return f"{self.follower.username} \u2192 {self.following.username} [{self.status}]"


class Connection(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Bidirectional connection between two users.
    """
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_connections",
        db_index=True,
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_connections",
        db_index=True,
    )
    status = models.CharField(
        max_length=15,
        choices=ConnectionStatus.choices(),
        default=ConnectionStatus.PENDING.value,
        db_index=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "profiles_connection"
        verbose_name = _("connection")
        verbose_name_plural = _("connections")
        unique_together = [("requester", "recipient")]
        indexes = [
            models.Index(fields=["requester", "status"], name="connection_requester_idx"),
            models.Index(fields=["recipient", "status"], name="connection_recipient_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.requester.username} - {self.recipient.username} [{self.status}]"
    

class KYC(BaseModel):
    """
    KYC verification record per user.
 
    Document images are stored as Media objects (FK).
    The verification workflow:
      1. User submits document images \u2192 status=PENDING
      2. Admin/automated checks \u2192 status=UNDER_REVIEW
      3. Approved \u2192 status=APPROVED + UserProfile.is_verified=True (signal)
         Rejected \u2192 status=REJECTED + rejection_reason populated
 
    Sensitive document fields are intentionally minimal here.
    Full document data should live in an encrypted vault 
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="kyc",
    )
    status = models.CharField(
        max_length=15,
        choices=KYCStatus.choices,
        default=KYCStatus.NOT_SUBMITTED.value,
        db_index=True,
    )
    document_type = models.CharField(
        max_length=20,
        choices=KYCDocumentType.choices,
        blank=True,
    )
 
    # Reference token from third-party KYC provider (Jumio, Smile ID, etc.)
    provider_reference = models.CharField(max_length=255, blank=True, db_index=True)
    provider_name = models.CharField(max_length=60, blank=True)
 
    # Document images (stored as Media objects so they live in the same CDN pipeline)
    front_image = models.ForeignKey(
        "medias.Media",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="kyc_front",
    )
    back_image = models.ForeignKey(
        "medias.Media",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="kyc_back",
    )
    selfie_image = models.ForeignKey(
        "medias.Media",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="kyc_selfie",
    )
 
    # Review metadata
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="kyc_reviews",
    )
    rejection_reason = models.TextField(blank=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the KYC approval expires and re-verification is required."),
    )
 
    class Meta:
        db_table = "profiles_kyc"
        verbose_name = _("KYC")
        indexes = [
            models.Index(fields=["status"], name="kyc_status_idx"),
            models.Index(fields=["submitted_at"], name="kyc_submitted_idx"),
        ]
 
    def approve(self, reviewer: User):
        from django.utils import timezone
        from datetime import timedelta
        self.status = KYCStatus.APPROVED.value
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        self.expires_at = timezone.now() + timedelta(days=365 * 2)  # 2-year validity
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "expires_at"])
        # Signal handler will set profile.is_verified = True
 
    def reject(self, reviewer: User, reason: str):
        from django.utils import timezone
        self.status = KYCStatus.REJECTED.value
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        self.rejection_reason = reason
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])
 
    def __str__(self) -> str:
        return f"KYC({self.user.username}) [{self.status}]"
