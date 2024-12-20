$(document).ready(function () {
    const hiddenModalEl = document.getElementById('modal')
    hiddenModalEl.addEventListener('hidden.bs.modal', event => {
        document.getElementById("modal-content").innerHTML = "";
    })
});
$(document).on('click', "a[data-bs-toggle=modal]", function () {
    var target = $(this).attr("href");
    $.get(target, function (data) {
        $("#modal-content").html(data);
    });
});