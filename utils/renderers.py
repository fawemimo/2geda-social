from __future__ import annotations

from rest_framework.renderers import JSONRenderer

from utils.encoders import LocalTimezoneJSONEncoder


class LocalTimezoneJSONRenderer(JSONRenderer):
    encoder_class = LocalTimezoneJSONEncoder

