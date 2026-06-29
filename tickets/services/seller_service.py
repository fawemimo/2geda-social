from django.db import transaction
from django.utils import timezone

from accounts.models import User
from tickets.models import SellerProfile
from tickets.services.exceptions import SellerNotApproved, SellerSuspended
from utils.enum import SellerStatus
from utils.generators import _generate_referral_code


class SellerService:

    @staticmethod
    def apply(user: User, business_name: str, **kwargs) -> SellerProfile:
        profile, created = SellerProfile.objects.get_or_create(
            user=user,
            defaults={
                "business_name": business_name,
                "business_email": kwargs.get("business_email", ""),
                "business_phone": kwargs.get("business_phone", ""),
                "business_address": kwargs.get("business_address", ""),
                "status": SellerStatus.PENDING.value,
                "submitted_at": timezone.now(),
            },
        )
        if not created:
            profile.business_name = business_name
            profile.business_email = kwargs.get("business_email", profile.business_email)
            profile.business_phone = kwargs.get("business_phone", profile.business_phone)
            profile.business_address = kwargs.get("business_address", profile.business_address)
            profile.status = SellerStatus.PENDING.value
            profile.submitted_at = timezone.now()
            profile.front_image_id = kwargs.get("front_image_id")
            profile.back_image_id = kwargs.get("back_image_id")
            profile.selfie_image_id = kwargs.get("selfie_image_id")
            profile.save()
        return profile

    @staticmethod
    def approve(profile: SellerProfile, reviewer: User) -> SellerProfile:
        profile.approve(reviewer)
        return profile

    @staticmethod
    def reject(profile: SellerProfile, reviewer: User, reason: str) -> SellerProfile:
        profile.reject(reviewer, reason)
        return profile

    @staticmethod
    def suspend(profile: SellerProfile) -> SellerProfile:
        profile.suspend()
        return profile

    @staticmethod
    def get_for_user(user: User) -> SellerProfile | None:
        return SellerProfile.objects.filter(user=user, is_deleted=False).first()

    @staticmethod
    def require_approved(profile: SellerProfile | None) -> SellerProfile:
        if not profile:
            raise SellerNotApproved()
        if profile.status == SellerStatus.SUSPENDED.value:
            raise SellerSuspended()
        if profile.status != SellerStatus.APPROVED.value:
            raise SellerNotApproved()
        return profile
