from django.urls import path

from displays import views

app_name = "displays"

display_list = views.DisplayViewSet.as_view({"get": "list", "post": "create"})
display_detail = views.DisplayViewSet.as_view({"get": "retrieve", "delete": "destroy"})
display_like = views.DisplayViewSet.as_view({"post": "like"})
display_viewers = views.DisplayViewSet.as_view({"get": "viewers"})
display_my = views.DisplayViewSet.as_view({"get": "my"})
display_feed = views.DisplayViewSet.as_view({"get": "feed"})

comment_list = views.DisplayCommentViewSet.as_view({"get": "list", "post": "create"})
comment_detail = views.DisplayCommentViewSet.as_view({"delete": "destroy"})

urlpatterns = [
    path("", display_list, name="display-list"),
    path("my/", display_my, name="display-my"),
    path("feed/", display_feed, name="display-feed"),
    path("<uuid:pk>/", display_detail, name="display-detail"),
    path("<uuid:pk>/like/", display_like, name="display-like"),
    path("<uuid:pk>/viewers/", display_viewers, name="display-viewers"),
    path("<uuid:display_id>/comments/", comment_list, name="display-comments"),
    path("<uuid:display_id>/comments/<uuid:pk>/", comment_detail, name="display-comment-detail"),
]
