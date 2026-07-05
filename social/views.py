from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.views import APIView

from accounts.services.exceptions import ConflictError, NotFoundError, ServiceError, ValidationError
from social.cache import (
    bump_post_list_version,
    delete_post_cache,
    get_cached,
    make_post_detail_cache_key,
    make_post_list_cache_key,
    make_post_trending_cache_key,
    set_cached,
    CACHE_POST_DETAIL_TTL,
    CACHE_POST_LIST_TTL,
    CACHE_POST_TRENDING_TTL,
)
from social.models import Comment, Like, Post, Reshare
from social.serializers import (
    CommentCreateSerializer,
    CommentSerializer,
    CommentUpdateSerializer,
    FollowResponseSerializer,
    PostCreateSerializer,
    PostListSerializer,
    PostUpdateSerializer,
    ReshareCreateSerializer,
    ReshareSerializer,
)
from social.services import CommentService, FollowService, LikeService, PostService, ReshareService
from utils.enum import PostVisibility
from utils.pagination import StandardPagination
from utils.responses import APIResponse
from utils.throttles import DeviceScopedRateThrottle


class PostViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    throttle_scope = "post_create"
    throttle_classes = [DeviceScopedRateThrottle]
    pagination_class = StandardPagination
    pagination_message = "Posts fetched successfully."

    def get_queryset(self):
        return Post.objects.filter(is_deleted=False).select_related(
            "author", "reshare_of",
        ).prefetch_related("attachments__media").order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return PostCreateSerializer
        if self.action in ("update", "partial_update"):
            return PostUpdateSerializer
        return PostListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = PostService.create(author=request.user, validated_data=serializer.validated_data)
        return APIResponse.success(
            message="Post created successfully.",
            data=PostListSerializer(post, context={"request": request}).data,
            status_code=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        user_id = str(getattr(request.user, "pk", "anon") or "anon")
        page = int(request.query_params.get(self.paginator.page_query_param, 1))
        page_size = int(
            request.query_params.get(self.paginator.page_size_query_param, self.paginator.page_size)
        )
        cache_key = make_post_list_cache_key(
            page, page_size, user_id, dict(request.query_params.items())
        )
        cached = get_cached(cache_key)
        if cached is not None:
            return APIResponse.success(data=cached)
        
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            set_cached(cache_key, response.data, ttl=CACHE_POST_LIST_TTL)
            return response
        serializer = self.get_serializer(queryset, many=True)
        response = APIResponse.success(data=serializer.data)
        set_cached(cache_key, response.data, ttl=CACHE_POST_LIST_TTL)
        return response

    def retrieve(self, request, *args, **kwargs):
        cache_key = make_post_detail_cache_key(str(kwargs["pk"]))
        cached = get_cached(cache_key)
        if cached is not None:
            if request.user.is_authenticated:
                cached["data"]["is_liked"] = Like.objects.filter(
                    user=request.user,
                    content_type=ContentType.objects.get_for_model(Post),
                    object_id=kwargs["pk"],
                ).exists()
            else:
                cached["data"]["is_liked"] = False
            return APIResponse.success(data=cached)
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        response = APIResponse.success(data=serializer.data)
        set_cached(cache_key, response.data, ttl=CACHE_POST_DETAIL_TTL)
        return response

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only edit your own posts.", status_code=403)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        post = PostService.update(instance=instance, validated_data=serializer.validated_data)
        delete_post_cache(str(instance.pk))
        bump_post_list_version()
        return APIResponse.success(
            message="Post updated successfully.",
            data=PostListSerializer(post, context={"request": request}).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only delete your own posts.", status_code=403)
        PostService.delete(instance=instance)
        delete_post_cache(str(instance.pk))
        bump_post_list_version()
        return APIResponse.success(message="Post deleted successfully.", status_code=200)

    @action(detail=True, methods=["post"])
    def like(self, request, pk=None):
        post = self.get_object()
        post_ct = ContentType.objects.get_for_model(Post)
        try:
            result = LikeService.toggle(
                user=request.user,
                content_type_id=post_ct.id,
                object_id=str(post.id),
            )
        except ServiceError as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        delete_post_cache(str(post.pk))
        bump_post_list_version()
        return APIResponse.success(
            message="Like toggled successfully.",
            data=result,
        )

    @action(detail=False, methods=["get"])
    def trending(self, request):
        user_id = str(getattr(request.user, "pk", "anon") or "anon")
        cache_key = make_post_trending_cache_key(user_id)
        cached = get_cached(cache_key)
        if cached is not None:
            return APIResponse.success(data=cached)
        queryset = self.get_queryset().filter(visibility=PostVisibility.PUBLIC.value)[:10]
        serializer = self.get_serializer(queryset, many=True)
        response = APIResponse.success(data=serializer.data)
        set_cached(cache_key, response.data, ttl=CACHE_POST_TRENDING_TTL)
        return response
    

class CommentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        post_id = self.kwargs.get("post_id")
        qs = Comment.objects.filter(is_deleted=False).select_related("author", "post")
        if post_id:
            qs = qs.filter(post_id=post_id)
        if self.action == "list":
            qs = qs.filter(parent__isnull=True)
        return qs.order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return CommentCreateSerializer
        if self.action in ("update", "partial_update"):
            return CommentUpdateSerializer
        return CommentSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            comment = CommentService.create(
                author=request.user,
                post_id=str(self.kwargs["post_id"]),
                validated_data=serializer.validated_data,
            )
        except ServiceError as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        return APIResponse.success(
            message="Comment created successfully.",
            data=CommentSerializer(comment, context={"request": request}).data,
            status_code=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return APIResponse.success(data=serializer.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only edit your own comments.", status_code=403)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        comment = CommentService.update(instance=instance, body=serializer.validated_data["body"])
        return APIResponse.success(
            message="Comment updated successfully.",
            data=CommentSerializer(comment, context={"request": request}).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only delete your own comments.", status_code=403)
        CommentService.delete(instance=instance)
        return APIResponse.success(message="Comment deleted successfully.")

    @action(detail=True, methods=["post"])
    def like(self, request, post_id=None, pk=None):
        comment = self.get_object()
        comment_ct = ContentType.objects.get_for_model(Comment)
        try:
            result = LikeService.toggle(
                user=request.user,
                content_type_id=comment_ct.id,
                object_id=str(comment.id),
            )
        except ServiceError as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        return APIResponse.success(message="Like toggled successfully.", data=result)


class ReplyViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = CommentSerializer

    def get_queryset(self):
        return Comment.objects.filter(
            parent_id=self.kwargs["comment_id"],
            post_id=self.kwargs["post_id"],
            is_deleted=False,
        ).select_related("author").order_by("created_at")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)


class ReshareViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Reshare.objects.filter(
            original_post__is_deleted=False,
        ).select_related("user", "original_post", "reshare_post").order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return ReshareCreateSerializer
        return ReshareSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reshare = ReshareService.create(user=request.user, validated_data=serializer.validated_data)
        except ServiceError as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        return APIResponse.success(
            message="Post reshared successfully.",
            data=ReshareSerializer(reshare, context={"request": request}).data,
            status_code=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return APIResponse.success(data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != request.user:
            return APIResponse.error(message="You can only delete your own reshares.", status_code=403)
        ReshareService.delete(instance=instance)
        return APIResponse.success(message="Reshare deleted successfully.")


class UserPostViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    serializer_class = PostListSerializer

    def get_queryset(self):
        user_id = self.kwargs.get("user_id")
        qs = Post.objects.filter(
            author_id=user_id, is_deleted=False
        ).select_related(
            "author", "reshare_of",
        ).prefetch_related("attachments__media").order_by("-created_at")

        media_type = self.request.query_params.get("media_type")
        if media_type:
            qs = qs.filter(attachments__media__media_type=media_type)

        return qs.distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return APIResponse.success(data=serializer.data)


class FollowUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        try:
            follow = FollowService.follow(follower=request.user, following_id=user_id)
        except (ValidationError, NotFoundError, ConflictError) as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        return APIResponse.success(
            message="Followed successfully.",
            data=FollowResponseSerializer(follow).data,
            status_code=status.HTTP_201_CREATED,
        )


class UnfollowUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        try:
            FollowService.unfollow(follower=request.user, following_id=user_id)
        except (ValidationError, NotFoundError) as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        return APIResponse.success(message="Unfollowed successfully.")
