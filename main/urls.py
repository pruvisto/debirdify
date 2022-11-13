from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('profile', views.profile, name='profile'),
    path('batch', views.batch, name='batch'),
    path('batch/progress', views.batch_progress, name='batch_progress')
]
