from __future__ import annotations

import os
os.environ["DJANGO_SETTINGS_MODULE"] = "core.test_settings"

import django
django.setup()

from django.core.cache import cache
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from social.models import Post

User = get_user_model()

user = User.objects.create_user(email="dbg@t.com", username="debugger", password="pass", is_active=True)
Post.objects.create(author=user, body="Debug post")

client = APIClient()
client.force_authenticate(user=user)

resp1 = client.get("/api/v2/social/posts/")
print("=== First request (normal) ===")
print(f"status: {resp1.status_code}")
print(f"data type: {type(resp1.data)}")
print(f"data keys: {list(resp1.data.keys()) if hasattr(resp1.data, 'keys') else 'N/A'}")
print(f"data['data'] type: {type(resp1.data.get('data', 'N/A'))}")
print(f"data['data']: {resp1.data.get('data', 'N/A')}")

resp2 = client.get("/api/v2/social/posts/")
print("\n=== Second request (cached) ===")
print(f"status: {resp2.status_code}")
print(f"data type: {type(resp2.data)}")
print(f"data keys: {list(resp2.data.keys()) if hasattr(resp2.data, 'keys') else 'N/A'}")
print(f"data['data'] type: {type(resp2.data.get('data', 'N/A'))}")
print(f"data['data']: {resp2.data.get('data', 'N/A')}")
