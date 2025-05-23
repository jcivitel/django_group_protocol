from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template import loader
from django.utils.timezone import now

from django_grp_backend.functions import group_required
from django_grp_backend.models import (
    Resident,
    Protocol,
    Group,
    ProtocolItem,
    ProtocolPresence,
)
from django_grp_frontend.forms import (
    ResidentForm,
    ProfileForm,
    GroupForm,
    ProtocolForm,
    UpdateUserForm,
    AddUserForm,
)


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

    template_opts["residents"] = (
        Resident.objects.filter(moved_out_since__isnull=True).order_by("group")
        if request.user.is_staff
        else Resident.objects.filter(moved_out_since__isnull=True)
        .filter(group__group_members=request.user)
        .order_by("group")
    )

    template_opts["protocols"] = (
        Protocol.objects.filter(
            protocol_date__year=today.year, protocol_date__month=today.month
        )
        if request.user.is_staff
        else Protocol.objects.filter(
            protocol_date__year=today.year, protocol_date__month=today.month
        ).filter(group__group_members=request.user)
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
        template_opts["residents"] = (
            Resident.objects.all()
            if request.user.is_staff
            else Resident.objects.filter(group__group_members=request.user)
        )
    else:
        template = loader.get_template("resident.html")
        template_opts = dict()
        if request.method == "POST":
            form = ResidentForm(
                request.POST, request.FILES, instance=Resident.objects.get(id=id)
            )
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
        template_opts["protocols"] = (
            Protocol.objects.all()
            if request.user.is_staff
            else Protocol.objects.filter(group__group_members=request.user)
        )
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
        template_opts["groups"] = (
            Group.objects.all()
            if request.user.is_staff
            else Group.objects.filter(group_members=request.user)
        )
    else:
        template = loader.get_template("group.html")
        template_opts = dict()
        if request.method == "POST":
            form = GroupForm(
                request.POST, request.FILES, instance=Group.objects.get(id=id)
            )
            print(request.FILES)
            if form.is_valid():
                form.save()
                messages.success(request, "Group has been updated")
                return redirect("group")

        template_opts["form"] = GroupForm(instance=Group.objects.get(id=id))
        template_opts["group_residents"] = Resident.objects.filter(group__id=id)
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


@login_required
@group_required("staff")
def staff(request):
    template = loader.get_template("staff.html")
    template_opts = dict()
    template_opts["members"] = User.objects.all()
    return HttpResponse(template.render(template_opts, request))


@login_required
@group_required("staff")
def UpdateUser(request, user_id=None):
    template = loader.get_template("modal_user.html")
    template_opts = dict()
    if user_id is not None:
        template_opts["content_title_main"] = "Update User"
        template_opts["user_id"] = user_id
        if request.method == "POST":
            form = UpdateUserForm(request.POST, instance=User.objects.get(id=user_id))
            if form.is_valid():
                form.save()
                messages.success(request, "User has been updated")
                return redirect("staff")

        template_opts["userform"] = UpdateUserForm(
            instance=User.objects.get(id=user_id)
        )
    else:
        template_opts["content_title_main"] = "Add User"
        if request.method == "POST":
            form = AddUserForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "User has been added")
                return redirect("staff")
        template_opts["userform"] = AddUserForm()

    return HttpResponse(template.render(template_opts, request))
