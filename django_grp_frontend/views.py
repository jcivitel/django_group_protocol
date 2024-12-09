from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template import loader


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

    return HttpResponse(template.render(template_opts, request))


@login_required
def profile(request):
    template = loader.get_template("profile.html")
    template_opts = dict()

    return HttpResponse(template.render(template_opts, request))


@login_required
def resident(request, id=None):
    if id is None:
        template = loader.get_template("list_residents.html")
        template_opts = dict()
    else:
        template = loader.get_template("resident.html")
        template_opts = dict()

    return HttpResponse(template.render(template_opts, request))


@login_required
def add_resident(request):
    template = loader.get_template("add_resident.html")
    template_opts = dict()

    return HttpResponse(template.render(template_opts, request))


@login_required
def protocol(request, id=None):
    if id is None:
        template = loader.get_template("list_protocols.html")
        template_opts = dict()
    else:
        template = loader.get_template("protocol.html")
        template_opts = dict()

    return HttpResponse(template.render(template_opts, request))


@login_required
def add_protocol(request):
    template = loader.get_template("add_protocol.html")
    template_opts = dict()

    return HttpResponse(template.render(template_opts, request))
