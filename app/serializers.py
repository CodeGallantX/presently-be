from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import User, Department, Course, LectureHall, Timetable, Attendance
import base64
from django.core.files.base import ContentFile

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    digital_signature = serializers.CharField(required=False, allow_blank=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 
            'matric_number', 'department', 'digital_signature', 
            'level', 'user_type', 'gender', 'password'
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'digital_signature': {'write_only': True}
        }
    
    def create(self, validated_data):
        signature_data = validated_data.pop('digital_signature', None)
        password = validated_data.pop('password')
        
        user = User.objects.create(
            **validated_data,
            password=make_password(password)
        )
        
        if signature_data:
            format, imgstr = signature_data.split(';base64,')
            ext = format.split('/')[-1]
            file_name = f"signature_{user.matric_number}.{ext}"
            data = ContentFile(base64.b64decode(imgstr), name=file_name)
            user.digital_signature.save(file_name, data, save=True)
        
        return user

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = '__all__'

class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = '__all__'

class LectureHallSerializer(serializers.ModelSerializer):
    class Meta:
        model = LectureHall
        fields = '__all__'

class TimetableSerializer(serializers.ModelSerializer):
    is_active_now = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Timetable
        fields = '__all__'

class AttendanceSerializer(serializers.ModelSerializer):
    student = UserSerializer(read_only=True)
    course = CourseSerializer(read_only=True)
    timetable = TimetableSerializer(read_only=True)
    attendance_percentage = serializers.FloatField(read_only=True)
    quartile = serializers.IntegerField(read_only=True)
    feedback_message = serializers.CharField(read_only=True)
    
    class Meta:
        model = Attendance
        fields = '__all__'

class AttendanceStatsSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    matric_number = serializers.CharField()
    full_name = serializers.CharField()
    attended_classes = serializers.IntegerField()
    percentage = serializers.FloatField()
    quartile = serializers.IntegerField()
    feedback = serializers.CharField()