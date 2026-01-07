from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated

from django.core.mail import send_mail
from django.conf import settings
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.utils.html import escape

from .models import UserProfile
import requests

# ------------------ SIGNUP ------------------
class SignupView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response({"error": "All fields are required"}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({"error": "Username already exists"}, status=400)

        user = User.objects.create_user(username=username, password=password, is_active=False)

        # Generate activation link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        activation_link = f"{settings.PUBLIC_BASE_URL}/activate/{uid}/{token}/"

        subject = "Welcome to Zipeline Tracker! Your account has been activated successfully"
        plain_message = (
            f"Hi,\n\nWelcome to Zipeline Tracker!\nYour account has been activated successfully. You can now login to your account.\n\nThank you!"
        )
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Welcome to Zipeline Tracker!</h2>
            <p>Hi,<br>
            Thank you for signing up. Your account has been activated successfully. You can now login to your account.</p>
            <p>
            <a href="https://qla.zipeline.com/login" style="
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                display: inline-block;
                border-radius: 6px;
                font-weight: bold;">
                Login to your account
            </a>
            </p>
            <p>If the button does not work, copy and paste this link into your browser:</p>
            <p>https://qla.zipeline.com/login</p>
            <br>
            <p>Cheers,<br>Zipeline Team</p>
        </body>
        </html>
        """

        send_mail(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,
            [username],
            html_message=html_message,
        )

        return Response({"message": "Check your email to activate account"}, status=201)


# ------------------ ACTIVATE ACCOUNT ------------------
class ActivateAccountView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def get(self, request, uid, token):
        try:
            uid = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({"error": "Invalid link"}, status=400)

        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.save()

            return Response({"message": "Account activated successfully"})
        return Response({"error": "Activation link is invalid"}, status=400)


# ------------------ LOGIN (JWT) ------------------
class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        return token


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer


# ------------------ FORGOT PASSWORD ------------------
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        email = request.data.get("username")
        if not email:
            return Response({"error": "Email is required"}, status=400)

        try:
            user = User.objects.get(username=email)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Generate reset link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        reset_link = f"{settings.PUBLIC_BASE_URL}/reset-password/{uid}/{token}/"

        subject = "Reset Your Password"
        plain_message = (
            f"Hi,\n\nYou requested to reset your password. Please use the link below:\n{reset_link}\n\n"
            "If you didn't request this, please ignore this email.\n\nThanks!"
        )
        html_message = f"""
        <html>
          <body style="font-family: Arial, sans-serif;">
            <h2>Password Reset Request</h2>
            <p>Hi,</p>
            <p>You requested to reset your password. Please click the button below to proceed:</p>
            <p>
              <a href="{escape(reset_link)}" style="
                background-color: #f44336;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                display: inline-block;
                border-radius: 6px;
                font-weight: bold;">
                Reset Password
              </a>
            </p>
            <p>If the button doesn't work, copy and paste this link into your browser:</p>
            <p>{escape(reset_link)}</p>
            <br>
            <p>If you did not request a password reset, please ignore this email.</p>
            <p>Thanks,<br>YourSite Team</p>
          </body>
        </html>
        """

        send_mail(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,
            [email],
            html_message=html_message,
        )

        return Response({"message": "Password reset link sent"}, status=200)


# ------------------ RESET PASSWORD ------------------
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request, uid, token):
        password = request.data.get("password")
        if not password:
            return Response({"error": "Password is required"}, status=400)

        try:
            uid = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({"error": "Invalid link"}, status=400)

        if default_token_generator.check_token(user, token):
            user.set_password(password)
            user.save()
            return Response({"message": "Password reset successful"})
        return Response({"error": "Invalid token"}, status=400)

class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        # For JWT, logout is typically handled client-side by deleting the token.
        # Optionally, you can blacklist the refresh token if using SimpleJWT with blacklist app.
        refresh_token = request.data.get("refresh_token")
        if not refresh_token:
            return Response({"error": "Refresh token required"}, status=400)

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Logout successful"}, status=200)
        except TokenError:
            return Response({"error": "Invalid or expired token"}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

class GetUserInfoView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def get(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_info = {
            "username": user_obj.username,
            "email": user_obj.email,
            "first_name": user_obj.first_name,
            "last_name": user_obj.last_name,
            "is_active": user_obj.is_active,
        }
        return Response({"user": user_info}, status=200)

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def put(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)
        
        user_profile.company_name = request.data.get('company_name')
        user_profile.company_domains = request.data.get('company_domains', [])
        user_profile.save()
        return Response({"message": "User profile updated successfully"}, status=200)
    
    def get(self, request):
        user = request.user
        user_obj = User.objects.get(id=user.id)
        user_profile = UserProfile.objects.get(user=user_obj)


        return Response({"company_name": user_profile.company_name, "company_domain": user_profile.company_domains, "pixel_id": user_profile.pixel_id, "username": user_obj.username}, status=200)
    

class ListProfilePixel(APIView):
    def get(self, request):
        url = "https://api.snitcher.com/radar/operator/v1/tracking-scripts"
        headers = {"Authorization": "Bearer 511|E2434QIIwDUYauvxr0NsD37QWg01sfgU1vXuJo24849fb401"}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            return Response(
                {"error": f"Snitcher API call failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(response.json(), status=status.HTTP_200_OK)



