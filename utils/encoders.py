from __future__ import annotations

import logging
from datetime import datetime

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


logger = logging.getLogger(__name__)


class LocalTimezoneJSONEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            if timezone.is_aware(obj):
                obj = timezone.localtime(obj)
            return obj.isoformat()
        return super().default(obj)

