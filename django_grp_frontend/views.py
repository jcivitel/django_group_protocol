from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template import loader
from django.utils.timezone import now
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator

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

    template_opts["residents"] = Resident.objects.active().for_user(request.user).order_by("group")
    template_opts["protocols"] = Protocol.objects.current_month().for_user(request.user)

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


# ============ CLASS-BASED VIEWS ============

class UserAccessMixin:
    """Mixin to filter querysets based on user permissions."""
    
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.for_user(self.request.user)


class ResidentListView(UserAccessMixin, ListView):
    model = Resident
    template_name = "list_residents.html"
    context_object_name = "residents"
    
    def get_queryset(self):
        return Resident.objects.for_user(self.request.user)


class ResidentCreateView(CreateView):
    model = Resident
    form_class = ResidentForm
    template_name = "resident.html"
    success_url = reverse_lazy("resident_list")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "Add"
        return context
    
    def form_valid(self, form):
        messages.success(self.request, "Resident has been added")
        return super().form_valid(form)


class ResidentUpdateView(UpdateView):
    model = Resident
    form_class = ResidentForm
    template_name = "resident.html"
    success_url = reverse_lazy("resident_list")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "Update"
        return context
    
    def form_valid(self, form):
        messages.success(self.request, "Resident has been updated")
        return super().form_valid(form)


class ProtocolListView(UserAccessMixin, ListView):
    model = Protocol
    template_name = "list_protocols.html"
    context_object_name = "protocols"
    
    def get_queryset(self):
        return Protocol.objects.for_user(self.request.user)


class ProtocolCreateView(CreateView):
    model = Protocol
    form_class = ProtocolForm
    template_name = "add_protocol.html"
    success_url = reverse_lazy("protocol_list")
    
    def form_valid(self, form):
        messages.success(self.request, "Protocol has been added")
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, "Invalid form")
        return super().form_invalid(form)


class ProtocolDetailView(DetailView):
    model = Protocol
    template_name = "protocol.html"
    context_object_name = "protocol"
    pk_url_kwarg = "id"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["protocol_items"] = ProtocolItem.objects.filter(protocol=self.object)
        context["presence_list"] = ProtocolPresence.objects.filter(protocol=self.object)
        return context


class GroupListView(UserAccessMixin, ListView):
    model = Group
    template_name = "list_groups.html"
    context_object_name = "groups"
    
    def get_queryset(self):
        return Group.objects.for_user(self.request.user)


class GroupCreateView(CreateView):
    model = Group
    form_class = GroupForm
    template_name = "group.html"
    success_url = reverse_lazy("group_list")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "Add"
        return context
    
    def form_valid(self, form):
        messages.success(self.request, "Group has been added")
        return super().form_valid(form)


class GroupUpdateView(UpdateView):
    model = Group
    form_class = GroupForm
    template_name = "group.html"
    success_url = reverse_lazy("group_list")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "Update"
        context["group_residents"] = Resident.objects.filter(group=self.object)
        return context
    
    def form_valid(self, form):
        messages.success(self.request, "Group has been updated")
        return super().form_valid(form)


# ============ BACKWARD COMPATIBILITY VIEWS ============
# Keep old function-based views for now to avoid breaking changes

@login_required
def resident(request, id=None):
    if id is None:
        template = loader.get_template("list_residents.html")
        template_opts = dict()
        template_opts["residents"] = Resident.objects.for_user(request.user)
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
        template_opts["protocols"] = Protocol.objects.for_user(request.user)
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
        template_opts["groups"] = Group.objects.for_user(request.user)
    else:
        template = loader.get_template("group.html")
        template_opts = dict()
        if request.method == "POST":
            form = GroupForm(
                request.POST, request.FILES, instance=Group.objects.get(id=id)
            )
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
