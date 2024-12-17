from django import forms
from django.contrib.auth.models import User

from django_grp_backend.models import Resident, Group, Protocol


class ResidentForm(forms.ModelForm):
    class Meta:
        model = Resident
        fields = [
            "first_name",
            "last_name",
            "picture",
            "moved_in_since",
            "moved_out_since",
            "group",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "First Name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Last Name"}
            ),
            "picture": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "moved_in_since": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"
            ),
            "moved_out_since": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"
            ),
            "group": forms.Select(attrs={"class": "form-select"}),
        }


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Username"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Username"}
            ),
            "email": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Username"}
            ),
        }


class GroupForm(forms.ModelForm):
    group_members = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "form-check-input", "role": "switch"}
        ),
        required=False,
    )

    class Meta:
        model = Group
        fields = ["name", "address", "postalcode", "city", "group_members"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Name"}
            ),
            "address": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Address"}
            ),
            "postalcode": forms.NumberInput(
                attrs={"class": "form-control", "placeholder": "Postal Code"}
            ),
            "city": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "City"}
            ),
        }


class ProtocolForm(forms.ModelForm):
    class Meta:
        model = Protocol
        fields = [
            "protocol_date",
            "group",
        ]
        widgets = {
            "protocol_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "group": forms.Select(attrs={"class": "form-select"}),
        }
