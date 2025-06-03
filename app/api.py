from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
from .models import User, Department, Course, LectureHall, Timetable, Attendance
from .serializers import (
    UserSerializer, DepartmentSerializer, CourseSerializer, 
    LectureHallSerializer, TimetableSerializer, AttendanceSerializer,
    AttendanceStatsSerializer
)
import geopy.distance
from datetime import datetime, timedelta
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from django.http import HttpResponse
import csv
import openpyxl
from reportlab.pdfgen import canvas
from io import BytesIO
from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.exceptions import ObjectDoesNotExist

class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]
    
    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'matric_number': {'type': 'string', 'example': '20/1234'},
                    'password': {'type': 'string', 'example': 'securepassword123'},
                    'latitude': {'type': 'number', 'format': 'float', 'example': 6.5244},
                    'longitude': {'type': 'number', 'format': 'float', 'example': 3.3792},
                },
                'required': ['matric_number', 'password', 'latitude', 'longitude']
            }
        },
        responses={
            200: OpenApiResponse(
                description='Login successful',
                response=UserSerializer,
                examples=[
                    OpenApiExample(
                        name='Successful Login',
                        value={
                            'message': 'Login successful',
                            'user': {
                                'id': 1,
                                'matric_number': '20/1234',
                                'full_name': 'John Doe',
                                'department': 'Computer Science',
                                'level': 200
                            },
                            'current_class': {
                                'course': {
                                    'code': 'CSC201',
                                    'title': 'Data Structures'
                                },
                                'lecture_hall': {
                                    'name': 'LT1',
                                    'building': 'Science Block'
                                },
                                'time': '08:00-10:00'
                            },
                            'tokens': {
                                'refresh': 'xxx.yyy.zzz',
                                'access': 'aaa.bbb.ccc'
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description='Invalid credentials',
                examples=[
                    OpenApiExample(
                        name='Invalid Credentials',
                        value={'error': 'Invalid credentials'}
                    )
                ]
            ),
            403: OpenApiResponse(
                description='Location not allowed',
                examples=[
                    OpenApiExample(
                        name='Outside Lecture Hall',
                        value={
                            'error': 'You must be in the lecture hall to mark attendance',
                            'distance': 250.5,
                            'allowed_radius': 100
                        }
                    )
                ]
            )
        },
        methods=['POST'],
        description='Student login with location verification'
    )
    @action(detail=False, methods=['post'])
    def student_login(self, request):
        matric = request.data.get('matric_number')
        password = request.data.get('password')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        
        user = authenticate(request, username=matric, password=password)
        
        if user is None or user.user_type != User.UserType.STUDENT:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
        current_time = timezone.now().time()
        today = timezone.now().weekday()
        
        current_timetable = Timetable.objects.filter(
            day_of_week=today,
            start_time__lte=current_time,
            end_time__gte=current_time,
            course__department=user.department,
            active=True
        ).first()
        
        if not current_timetable:
            return Response({'error': 'No active class at this time'}, status=status.HTTP_403_FORBIDDEN)
        
        lecture_hall = current_timetable.lecture_hall
        hall_coords = (lecture_hall.latitude, lecture_hall.longitude)
        student_coords = (float(latitude), float(longitude))
        
        distance = geopy.distance.distance(hall_coords, student_coords).m
        
        if distance > lecture_hall.radius:
            return Response({
                'error': 'You must be in the lecture hall to mark attendance',
                'distance': distance,
                'allowed_radius': lecture_hall.radius
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Update user's last login location
        user.last_login_location = {
            'latitude': latitude,
            'longitude': longitude,
            'timestamp': timezone.now().isoformat()
        }
        user.save()
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        login(request, user)
        return Response({
            'message': 'Login successful',
            'user': UserSerializer(user).data,
            'current_class': TimetableSerializer(current_timetable).data,
            'tokens': {
                'refresh': str(refresh),
                'access': access_token
            }
        })
    
    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'email': {'type': 'string', 'example': 'lecturer@uni.edu'},
                    'password': {'type': 'string', 'example': 'securepassword123'},
                },
                'required': ['email', 'password']
            }
        },
        responses={
            200: OpenApiResponse(
                description='Login successful',
                response=UserSerializer
            ),
            401: OpenApiResponse(
                description='Invalid credentials'
            )
        },
        methods=['POST'],
        description='Lecturer login'
    )
    @action(detail=False, methods=['post'])
    def lecturer_login(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        
        user = authenticate(request, username=email, password=password)
        
        if user is None or user.user_type != User.UserType.LECTURER:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        login(request, user)
        return Response({
            'message': 'Login successful',
            'user': UserSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': access_token
            }
        })

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.user_type == User.UserType.STUDENT:
            return Attendance.objects.filter(student=user)
        elif user.user_type == User.UserType.LECTURER:
            return Attendance.objects.filter(course__in=user.courses.all())
        return Attendance.objects.none()
    
    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'latitude': {'type': 'number', 'format': 'float', 'example': 6.5244},
                    'longitude': {'type': 'number', 'format': 'float', 'example': 3.3792},
                },
                'required': ['latitude', 'longitude']
            }
        },
        responses={
            201: OpenApiResponse(
                description='Attendance marked successfully',
                response=AttendanceSerializer
            ),
            400: OpenApiResponse(
                description='Attendance already marked'
            ),
            403: OpenApiResponse(
                description='Not allowed'
            )
        },
        methods=['POST'],
        description='Mark attendance for current class'
    )
    @action(detail=False, methods=['post'])
    def mark_attendance(self, request):
        user = request.user
        if user.user_type != User.UserType.STUDENT:
            return Response({'error': 'Only students can mark attendance'}, status=status.HTTP_403_FORBIDDEN)
        
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        
        current_time = timezone.now().time()
        today = timezone.now().weekday()
        
        current_timetable = Timetable.objects.filter(
            day_of_week=today,
            start_time__lte=current_time,
            end_time__gte=current_time,
            course__department=user.department,
            active=True
        ).first()
        
        if not current_timetable:
            return Response({'error': 'No active class at this time'}, status=status.HTTP_403_FORBIDDEN)
        
        existing_attendance = Attendance.objects.filter(
            student=user,
            timetable=current_timetable
        ).exists()
        
        if existing_attendance:
            return Response({'error': 'Attendance already marked for this class'}, status=status.HTTP_400_BAD_REQUEST)
        
        lecture_hall = current_timetable.lecture_hall
        hall_coords = (lecture_hall.latitude, lecture_hall.longitude)
        student_coords = (float(latitude), float(longitude))
        
        distance = geopy.distance.distance(hall_coords, student_coords).m
        
        if distance > lecture_hall.radius:
            return Response({
                'error': 'You must be in the lecture hall to mark attendance',
                'distance': distance,
                'allowed_radius': lecture_hall.radius
            }, status=status.HTTP_403_FORBIDDEN)
        
        attendance = Attendance.objects.create(
            student=user,
            course=current_timetable.course,
            timetable=current_timetable,
            latitude=latitude,
            longitude=longitude
        )
        
        return Response({
            'message': 'Attendance marked successfully',
            'attendance': AttendanceSerializer(attendance).data
        }, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='course_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Filter by course ID',
                required=False
            )
        ],
        responses={
            200: OpenApiResponse(
                description='List of attendance records',
                response=AttendanceSerializer(many=True)
            )
        },
        methods=['GET'],
        description='Get attendance records for the current user'
    )
    @action(detail=False, methods=['get'])
    def my_attendance(self, request):
        user = request.user
        if user.user_type != User.UserType.STUDENT:
            return Response({'error': 'Only students can view their attendance'}, status=status.HTTP_403_FORBIDDEN)
        
        course_id = request.query_params.get('course_id')
        queryset = Attendance.objects.filter(student=user)
        
        if course_id:
            queryset = queryset.filter(course_id=course_id)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='course_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Course ID to get statistics for',
                required=True
            )
        ],
        responses={
            200: OpenApiResponse(
                description='Attendance statistics',
                response=AttendanceStatsSerializer(many=True)
            )
        },
        methods=['GET'],
        description='Get attendance statistics for a course'
    )
    @action(detail=False, methods=['get'])
    def course_stats(self, request):
        user = request.user
        course_id = request.query_params.get('course_id')
        
        if not course_id:
            return Response({'error': 'course_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({'error': 'Course not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if user.user_type == User.UserType.STUDENT:
            total_classes = Timetable.objects.filter(course=course).count()
            attended_classes = Attendance.objects.filter(
                student=user, 
                course=course,
                status=Attendance.Status.PRESENT
            ).count()
            percentage = (attended_classes / total_classes * 100) if total_classes > 0 else 0
            
            return Response({
                'total_classes': total_classes,
                'attended_classes': attended_classes,
                'percentage': percentage,
                'quartile': Attendance._meta.get_field('quartile').value_from_object(Attendance(
                    student=user,
                    course=course,
                    timetable=None
                )),
                'feedback': Attendance._meta.get_field('feedback_message').value_from_object(Attendance(
                    student=user,
                    course=course,
                    timetable=None
                ))
            })
        
        elif user.user_type == User.UserType.LECTURER:
            if course not in user.courses.all():
                return Response({'error': 'You are not teaching this course'}, status=status.HTTP_403_FORBIDDEN)
            
            students = User.objects.filter(
                user_type=User.UserType.STUDENT,
                department=course.department,
                level=course.level
            ).annotate(
                attended_classes=Count(
                    'attendance',
                    filter=Q(attendance__course=course, attendance__status=Attendance.Status.PRESENT)
                )
            )
            
            total_classes = Timetable.objects.filter(course=course).count()
            
            result = []
            for student in students:
                percentage = (student.attended_classes / total_classes * 100) if total_classes > 0 else 0
                
                result.append({
                    'student_id': student.id,
                    'matric_number': student.matric_number,
                    'full_name': student.get_full_name(),
                    'attended_classes': student.attended_classes,
                    'percentage': percentage,
                    'quartile': Attendance._meta.get_field('quartile').value_from_object(Attendance(
                        student=student,
                        course=course,
                        timetable=None
                    )),
                    'feedback': Attendance._meta.get_field('feedback_message').value_from_object(Attendance(
                        student=student,
                        course=course,
                        timetable=None
                    ))
                })
            
            return Response(result)
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='course_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Course ID to export',
                required=True
            ),
            OpenApiParameter(
                name='format',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Export format (csv, xlsx, pdf)',
                default='csv',
                enum=['csv', 'xlsx', 'pdf']
            )
        ],
        responses={
            200: OpenApiResponse(
                description='File download',
                response=OpenApiTypes.BINARY
            )
        },
        methods=['GET'],
        description='Export attendance data in various formats'
    )
    @action(detail=False, methods=['get'])
    def export_attendance(self, request):
        course_id = request.query_params.get('course_id')
        format = request.query_params.get('format', 'csv')
        
        if not course_id:
            return Response({'error': 'course_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({'error': 'Course not found'}, status=status.HTTP_404_NOT_FOUND)
        
        user = request.user
        if user.user_type == User.UserType.STUDENT:
            queryset = Attendance.objects.filter(student=user, course=course)
        elif user.user_type == User.UserType.LECTURER:
            if course not in user.courses.all():
                return Response({'error': 'You are not teaching this course'}, status=status.HTTP_403_FORBIDDEN)
            queryset = Attendance.objects.filter(course=course)
        else:
            queryset = Attendance.objects.filter(course=course)
        
        if format == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="attendance_{course.code}.csv"'
            
            writer = csv.writer(response)
            writer.writerow(['S/N', 'Matric Number', 'Full Name', 'Timestamp', 'Status'])
            
            for idx, attendance in enumerate(queryset, start=1):
                writer.writerow([
                    idx,
                    attendance.student.matric_number,
                    attendance.student.get_full_name(),
                    attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    attendance.get_status_display()
                ])
            
            return response
        
        elif format == 'xlsx':
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="attendance_{course.code}.xlsx"'
            
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Attendance"
            
            ws.append(['S/N', 'Matric Number', 'Full Name', 'Timestamp', 'Status'])
            
            for idx, attendance in enumerate(queryset, start=1):
                ws.append([
                    idx,
                    attendance.student.matric_number,
                    attendance.student.get_full_name(),
                    attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    attendance.get_status_display()
                ])
            
            wb.save(response)
            return response
        
        elif format == 'pdf':
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="attendance_{course.code}.pdf"'
            
            buffer = BytesIO()
            p = canvas.Canvas(buffer)
            
            p.drawString(100, 800, f"Attendance Report for {course.code} - {course.title}")
            p.drawString(100, 780, "Generated on: " + timezone.now().strftime('%Y-%m-%d %H:%M:%S'))
            
            y = 750
            p.drawString(100, y, "S/N")
            p.drawString(150, y, "Matric Number")
            p.drawString(300, y, "Full Name")
            p.drawString(450, y, "Timestamp")
            p.drawString(550, y, "Status")
            
            for idx, attendance in enumerate(queryset, start=1):
                y -= 20
                p.drawString(100, y, str(idx))
                p.drawString(150, y, attendance.student.matric_number)
                p.drawString(300, y, attendance.student.get_full_name())
                p.drawString(450, y, attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S'))
                p.drawString(550, y, attendance.get_status_display())
            
            p.showPage()
            p.save()
            
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)
            
            return response
        
        else:
            return Response({'error': 'Invalid format'}, status=status.HTTP_400_BAD_REQUEST)

class CurrentClassView(APIView):
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        responses={
            200: OpenApiResponse(
                description='Current active class',
                response=TimetableSerializer
            ),
            404: OpenApiResponse(
                description='No active class found'
            )
        },
        methods=['GET'],
        description='Get current active class for student'
    )
    def get(self, request):
        user = request.user
        if user.user_type != User.UserType.STUDENT:
            return Response({'error': 'Only students can check current class'}, status=status.HTTP_403_FORBIDDEN)
        
        current_time = timezone.now().time()
        today = timezone.now().weekday()
        
        current_timetable = Timetable.objects.filter(
            day_of_week=today,
            start_time__lte=current_time,
            end_time__gte=current_time,
            course__department=user.department,
            active=True
        ).first()
        
        if not current_timetable:
            return Response({'error': 'No active class at this time'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = TimetableSerializer(current_timetable)
        return Response(serializer.data)

class ValidateAttendanceView(APIView):
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        responses={
            200: OpenApiResponse(
                description='Attendance validation result',
                examples=[
                    OpenApiExample(
                        name='Validation Result',
                        value={
                            'message': 'Attendance validated',
                            'voided_count': 0,
                            'total_classes': 2
                        }
                    )
                ]
            )
        },
        methods=['POST'],
        description='Validate attendance records (run as periodic task)'
    )
    def post(self, request):
        # This should be run as a periodic task (e.g., every hour)
        current_time = timezone.now().time()
        today = timezone.now().weekday()
        
        # Get all timetables that just ended (within last 1 hour)
        one_hour_ago = (datetime.now() - timedelta(hours=1)).time()
        recent_classes = Timetable.objects.filter(
            day_of_week=today,
            end_time__gte=one_hour_ago,
            end_time__lte=current_time,
            active=True
        )
        
        voided_count = 0
        
        for timetable in recent_classes:
            total_students = User.objects.filter(
                user_type=User.UserType.STUDENT,
                department=timetable.course.department,
                level=timetable.course.level
            ).count()
            
            marked_attendance = Attendance.objects.filter(timetable=timetable).count()
            
            if marked_attendance / total_students < 0.1:  # Less than 10%
                # Void all attendance for this timetable
                voided = Attendance.objects.filter(timetable=timetable).update(status=Attendance.Status.VOIDED)
                voided_count += voided
                
        return Response({
            'message': 'Attendance validated',
            'voided_count': voided_count,
            'total_classes': recent_classes.count()
        })