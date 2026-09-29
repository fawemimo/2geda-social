from __future__ import annotations

from rest_framework import serializers

from accounts.serializers import UserListSerializer
from medias.models import Collection, Media
from search.enums import SearchType
from search.services.search_service import SearchResult
from social.models import Comment
from social.serializers import PostListSerializer, UserSocialSerializer


class SearchUserSerializer(UserListSerializer):
    bio = serializers.CharField(source="profile.bio", read_only=True, default="")

    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + ["bio"]


class SearchPostSerializer(PostListSerializer):
    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields


class SearchCommentSerializer(serializers.ModelSerializer):

    author = UserSocialSerializer(read_only=True)
    is_liked = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Comment
        fields = [
            "id", "post", "author", "parent", "body",
            "likes_count", "replies_count", "is_liked", "created_at",
        ]
        read_only_fields = fields


class SearchMediaSerializer(serializers.ModelSerializer):

    caption = serializers.CharField(read_only=True)
    alt_text = serializers.CharField(read_only=True)
    owner = SearchUserSerializer(read_only=True)

    class Meta:
        model = Media
        fields = [
            "id", "owner", "media_type", "mime_type", "cdn_url",
            "original_filename", "width_px", "height_px", "duration_seconds",
            "blurhash", "processing_status",
            "caption", "alt_text", "visibility", "created_at",
        ]
        read_only_fields = fields


class SearchCollectionSerializer(serializers.ModelSerializer):
    owner = SearchUserSerializer(read_only=True)
    cover = serializers.CharField(source="cover_media.cdn_url", read_only=True, default=None)

    class Meta:
        model = Collection
        fields = [
            "id", "owner", "name", "description", "cover",
            "is_public", "items_count", "created_at", "updated_at",
        ]
        read_only_fields = fields


# type -> serializer, used by the view to render the mixed result list.
RESULT_SERIALIZERS: dict[str, type[serializers.BaseSerializer]] = {
    SearchType.USERS.value: SearchUserSerializer,
    SearchType.POSTS.value: SearchPostSerializer,
    SearchType.COMMENTS.value: SearchCommentSerializer,
    SearchType.MEDIA.value: SearchMediaSerializer,
    SearchType.COLLECTIONS.value: SearchCollectionSerializer,
}


class SearchResultItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=SearchType.choices())
    score = serializers.FloatField(
        help_text=(
            "Relevance score, higher is better. The exact value depends on the "
            "engine that served the request, so only compare scores within a "
            "single response."
        )
    )
    item = serializers.DictField()


class SearchFacetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=SearchType.choices())
    label = serializers.CharField()
    count = serializers.IntegerField()


class SearchAppliedFiltersSerializer(serializers.Serializer):
    types = serializers.ListField(child=serializers.CharField())
    media_type = serializers.CharField(allow_null=True)
    date_from = serializers.CharField(allow_null=True)
    date_to = serializers.CharField(allow_null=True)
    sort = serializers.ChoiceField(choices=["relevance", "recent"])


class SearchResponseSerializer(serializers.Serializer):

    query = serializers.CharField()
    tokens = serializers.ListField(child=serializers.CharField())
    engine = serializers.CharField(
        help_text=(
            "Which implementation served this request: 'postgres_fulltext' for "
            "index-backed full-text search, 'portable_substring' on other "
            "databases or when the query has no indexable terms. Scores are only "
            "comparable within a single response."
        )
    )
    types = SearchFacetSerializer(many=True)
    appliedFilters = SearchAppliedFiltersSerializer()
    data = SearchResultItemSerializer(many=True)
    totalItem = serializers.IntegerField()
    totalPages = serializers.IntegerField()
    currentPage = serializers.IntegerField()
    totalPerPage = serializers.IntegerField()
    nextPage = serializers.IntegerField(allow_null=True)
    previousPage = serializers.IntegerField(allow_null=True)


def serialize_results(result: SearchResult, *, request) -> list[dict]:
    payload = []
    for hit in result.results:
        serializer_class = RESULT_SERIALIZERS[hit.type]
        payload.append(
            {
                "type": hit.type,
                "score": hit.score,
                "item": serializer_class(hit.item, context={"request": request}).data,
            }
        )
    return payload
