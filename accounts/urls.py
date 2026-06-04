from django.urls import path

from accounts import views


app_name = "accounts"

urlpatterns = [
    # registration & OTP
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/verify-otp/", views.VerifyRegistrationOTPView.as_view(), name="verify-otp"),
    path("auth/resend-otp/", views.ResendOTPView.as_view(), name="resend-otp"),

    # login / logout
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/logout-everywhere/", views.LogoutEverywhereView.as_view(), name="logout-everywhere"),

    # tokens
    path("auth/token/refresh/", views.TokenRefreshView.as_view(), name="token-refresh"),

    # password
    path("auth/password/reset/", views.PasswordResetRequestView.as_view(), name="password-reset"),
    path("auth/password/reset/confirm/", views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("auth/password/change/", views.PasswordChangeView.as_view(), name="password-change"),

    # profile
    path("me/", views.MeView.as_view(), name="me"),
    path("me/profile/", views.ProfileView.as_view(), name="profile"),
    path("me/profile/avatar/", views.ProfileAvatarUpdateView.as_view(), name="profile-avatar"),
    path("me/profile/cover/", views.ProfileCoverUpdateView.as_view(), name="profile-cover"),
    path("me/profile/display-photo/", views.ProfileDisplayPhotoUpdateView.as_view(), name="profile-display-photo"),

    # devices
    path("me/devices/", views.DeviceListCreateView.as_view(), name="devices"),
    path("me/devices/<uuid:device_id>/", views.DeviceDetailView.as_view(), name="device-detail"),
    path("me/devices/<uuid:device_id>/push-token/", views.DevicePushTokenView.as_view(), name="device-push-token"),
    path("me/devices/<uuid:device_id>/trust/", views.DeviceTrustView.as_view(), name="device-trust"),

    # users
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<uuid:user_id>/", views.UserDetailView.as_view(), name="user-detail"),

    # connect
    path("location/update/", views.UserLocationUpdateView.as_view(), name="location-update"),
    path("connect/discover/", views.ConnectDiscoveryView.as_view(), name="connect-discover"),
    path("connect/request/<uuid:user_id>/", views.ConnectRequestView.as_view(), name="connect-request"),
    path("connect/respond/<uuid:connection_id>/", views.ConnectRespondView.as_view(), name="connect-respond"),
]

