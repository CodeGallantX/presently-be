from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

class UserManager(BaseUserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username must be set')
        if 'user_type' not in extra_fields:
            raise ValueError('User type must be specified')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('user_type', User.UserType.ADMIN)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(username, email, password, **extra_fields)

class User(AbstractUser):
    class UserType(models.IntegerChoices):
        STUDENT = 1, 'Student'
        LECTURER = 2, 'Lecturer'
        ADMIN = 3, 'Admin'
    
    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'
        OTHER = 'O', 'Other'
    
    objects = UserManager()
    
    user_type = models.PositiveSmallIntegerField(choices=UserType.choices)
    matric_number = models.CharField(max_length=20, unique=True, blank=True, null=True)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True)
    digital_signature = models.TextField(blank=True)
    level = models.IntegerField(
        blank=True, 
        null=True, 
        validators=[MinValueValidator(100), MaxValueValidator(900)]
    )
    courses = models.ManyToManyField('Course', blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True, null=True)
    last_login_location = models.JSONField(blank=True, null=True)
    
    def __str__(self):
        return self.get_full_name() or self.username

class Department(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)
    
    def __str__(self):
        return self.name

class Course(models.Model):
    code = models.CharField(max_length=10)
    title = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    level = models.IntegerField(validators=[MinValueValidator(100), MaxValueValidator(900)])
    
    def __str__(self):
        return f"{self.code} - {self.title}"

class LectureHall(models.Model):
    name = models.CharField(max_length=50)
    building = models.CharField(max_length=50)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius = models.IntegerField(default=100)  # in meters
    
    def __str__(self):
        return f"{self.building} - {self.name}"

class Timetable(models.Model):
    class DayOfWeek(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'
    
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    lecturer = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'user_type': User.UserType.LECTURER})
    day_of_week = models.IntegerField(choices=DayOfWeek.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    lecture_hall = models.ForeignKey(LectureHall, on_delete=models.CASCADE)
    active = models.BooleanField(default=True)
    semester = models.CharField(max_length=50)
    
    class Meta:
        ordering = ['day_of_week', 'start_time']
        unique_together = ('course', 'day_of_week', 'start_time', 'semester')
    
    @property
    def is_active_now(self):
        now = timezone.now()
        current_time = now.time()
        current_day = now.weekday()
        
        return (
            self.day_of_week == current_day and
            self.start_time <= current_time <= self.end_time and
            self.active
        )

class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'P', 'Present'
        ABSENT = 'A', 'Absent'
        VOIDED = 'V', 'Voided'
    
    student = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'user_type': User.UserType.STUDENT})
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.PRESENT)
    
    class Meta:
        unique_together = ('student', 'timetable')
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.student} - {self.course} - {self.timestamp}"
    
    @property
    def attendance_percentage(self):
        total_classes = Timetable.objects.filter(course=self.course, active=True).count()
        attended_classes = Attendance.objects.filter(
            student=self.student, 
            course=self.course,
            status=Attendance.Status.PRESENT
        ).count()
        return (attended_classes / total_classes * 100) if total_classes > 0 else 0
    
    @property
    def quartile(self):
        percentage = self.attendance_percentage
        if percentage == 0:
            return 0
        elif percentage <= 25:
            return 1
        elif percentage <= 50:
            return 2
        elif percentage <= 75:
            return 3
        elif percentage < 100:
            return 4
        else:
            return 5
    
    @property
    def feedback_message(self):
        quartile = self.quartile
        messages = {
            0: "Bro you no dey come class?!! Shuu !! 🤦🏽‍♂️",
            1: "Better dey try come class o!",
            2: "Why you dey miss class na?",
            3: "No miss class oh, make you no fail!",
            4: "Omo, you dey try. Just add small pepper 🫡",
            5: "Responsible pikin, you know wetin you come do for school! 👏"
        }
        return messages.get(quartile, "")