from django.urls import path

from search import views

app_name = "search"

urlpatterns = [
    path("", views.SearchView.as_view(), name="search-list"),
    path("types/", views.SearchTypeListView.as_view(), name="search-types"),
]
