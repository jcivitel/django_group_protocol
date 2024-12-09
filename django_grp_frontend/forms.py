from django import forms
from django_grp_backend.models import Resident


class ResidentForm(forms.ModelForm):
    class Meta:
        model = Resident
        fields = ['first_name', 'last_name', 'picture', 'moved_in_since', 'moved_out_since', 'group']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'picture': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'moved_in_since': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'moved_out_since': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'group': forms.Select(attrs={'class': 'form-control'}),
        }
