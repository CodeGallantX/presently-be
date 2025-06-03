from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api import AuthViewSet, AttendanceViewSet, CurrentClassView, ValidateAttendanceView

router = DefaultRouter()
router.register(r'attendance', AttendanceViewSet, basename='attendance')

urlpatterns = [
    path('auth/', AuthViewSet.as_view({
        'post': 'student_login'
    }), name='student-login'),
    path('auth/lecturer/', AuthViewSet.as_view({
        'post': 'lecturer_login'
    }), name='lecturer-login'),
    path('current-class/', CurrentClassView.as_view(), name='current-class'),
    path('validate-attendance/', ValidateAttendanceView.as_view(), name='validate-attendance'),
    path('', include(router.urls)),
]