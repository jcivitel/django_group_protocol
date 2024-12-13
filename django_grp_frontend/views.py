from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template import loader

from django_grp_backend.models import (
    Resident,
    Protocol,
    Group,
    ProtocolItem,
    ProtocolPresence,
)

from django.utils.timezone import now
from datetime import datetime

from django_grp_frontend.forms import ResidentForm, ProfileForm, GroupForm, ProtocolForm


def login_view(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"WELCOME {user}❤️")
            return redirect("dashboard")
        else:
            messages.error(request, "Invalid username or password")
    return render(request, "login.html")


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out 🫡")
    return redirect("login")


@login_required
def dashboard(request):
    template = loader.get_template("dashboard.html")
    template_opts = dict()

    today = now().date()

    template_opts["residents"] = Resident.objects.filter(moved_out_since__isnull=True)
    template_opts["protocols"] = Protocol.objects.filter(
        protocol_date__year=today.year, protocol_date__month=today.month
    )

    return HttpResponse(template.render(template_opts, request))


@login_required
def profile(request):
    template = loader.get_template("profile.html")
    template_opts = dict()
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated")
            return redirect("profile")
    template_opts["form"] = ProfileForm(instance=request.user)

    return HttpResponse(template.render(template_opts, request))


@login_required
def resident(request, id=None):
    if id is None:
        template = loader.get_template("list_residents.html")
        template_opts = dict()
        template_opts["residents"] = Resident.objects.all()
    else:
        template = loader.get_template("resident.html")
        template_opts = dict()
        if request.method == "POST":
            form = ResidentForm(request.POST, instance=Resident.objects.get(id=id))
            if form.is_valid():
                form.save()
                messages.success(request, "Resident has been updated")
                return redirect("resident")

        template_opts["form"] = ResidentForm(instance=Resident.objects.get(id=id))
        template_opts["action"] = "Update"

    return HttpResponse(template.render(template_opts, request))


@login_required
def add_resident(request):
    template = loader.get_template("resident.html")
    template_opts = dict()
    if request.method == "POST":
        form = ResidentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Resident has been added")
            return redirect("resident")

    template_opts["form"] = ResidentForm()
    template_opts["action"] = "Add"

    return HttpResponse(template.render(template_opts, request))


@login_required
def protocol(request, id=None):
    if id is None:
        template = loader.get_template("list_protocols.html")
        template_opts = dict()
        template_opts["protocols"] = Protocol.objects.all()
    else:
        template = loader.get_template("protocol.html")
        template_opts = dict()
        template_opts["protocol"] = Protocol.objects.get(id=id)
        template_opts["protocol_items"] = ProtocolItem.objects.filter(protocol=id)
        template_opts["presence_list"] = ProtocolPresence.objects.filter(protocol=id)

    return HttpResponse(template.render(template_opts, request))


@login_required
def add_protocol(request):
    template = loader.get_template("add_protocol.html")
    template_opts = dict()
    if request.method == "POST":
        form = ProtocolForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Protocol has been added")
            return redirect("protocol")
        messages.error(request, "Invalid form")

    template_opts["form"] = ProtocolForm()

    return HttpResponse(template.render(template_opts, request))


@login_required
def group(request, id=None):
    if id is None:
        template = loader.get_template("list_groups.html")
        template_opts = dict()
        template_opts["groups"] = Group.objects.all()
    else:
        template = loader.get_template("group.html")
        template_opts = dict()
        if request.method == "POST":
            form = GroupForm(request.POST, instance=Group.objects.get(id=id))
            if form.is_valid():
                form.save()
                messages.success(request, "Group has been updated")
                return redirect("group")

        template_opts["form"] = GroupForm(instance=Group.objects.get(id=id))
        template_opts["group_residents"] = Resident.objects.filter(group__id=id)
        template_opts["group_members"] = Group.objects.get(id=id).group_members.all()
        template_opts["action"] = "Update"

    return HttpResponse(template.render(template_opts, request))


@login_required
def add_group(request):
    template = loader.get_template("group.html")
    template_opts = dict()
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Group has been added")
            return redirect("group")

    template_opts["form"] = GroupForm()
    template_opts["action"] = "Add"

    return HttpResponse(template.render(template_opts, request))
