from django.urls import path

from social import views

app_name = "social"

post_list = views.PostViewSet.as_view({"get": "list", "post": "create"})
post_detail = views.PostViewSet.as_view({
    "get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy",
})
post_like = views.PostViewSet.as_view({"post": "like"})
post_trending = views.PostViewSet.as_view({"get": "trending"})

comment_list = views.CommentViewSet.as_view({"get": "list", "post": "create"})
comment_detail = views.CommentViewSet.as_view({
    "get": "retrieve", "patch": "partial_update", "delete": "destroy",
})
comment_like = views.CommentViewSet.as_view({"post": "like"})

reply_list = views.ReplyViewSet.as_view({"get": "list"})

reshare_list = views.ReshareViewSet.as_view({"get": "list", "post": "create"})
reshare_detail = views.ReshareViewSet.as_view({"get": "retrieve", "delete": "destroy"})

urlpatterns = [
    path("posts/", post_list, name="post-list"),
    path("posts/trending/", post_trending, name="post-trending"),
    path("posts/<uuid:pk>/", post_detail, name="post-detail"),
    path("posts/<uuid:pk>/like/", post_like, name="post-like"),
    path("posts/<uuid:post_id>/comments/", comment_list, name="post-comments"),
    path("posts/<uuid:post_id>/comments/<uuid:pk>/", comment_detail, name="post-comment-detail"),
    path("posts/<uuid:post_id>/comments/<uuid:pk>/like/", comment_like, name="post-comment-like"),
    path(
        "posts/<uuid:post_id>/comments/<uuid:comment_id>/replies/",
        reply_list,
        name="post-comment-replies",
    ),
    path("reshares/", reshare_list, name="reshare-list"),
    path("reshares/<uuid:pk>/", reshare_detail, name="reshare-detail"),
    path("follow/<uuid:user_id>/", views.FollowUserView.as_view(), name="follow"),
    path("unfollow/<uuid:user_id>/", views.UnfollowUserView.as_view(), name="unfollow"),
]
