(function () {
    function bindStudentSearch(searchId, selectId) {
        var search = document.getElementById(searchId);
        var select = document.getElementById(selectId);
        if (!search || !select) { return; }

        function normalize(value) {
            return value.toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        }

        search.addEventListener('input', function () {
            var query = normalize(search.value.trim());
            var selected = select.options[select.selectedIndex];
            if (selected && selected.value && !normalize(selected.text).includes(query)) {
                select.value = '';
            }
            Array.prototype.forEach.call(select.options, function (option) {
                option.hidden = !!option.value && !normalize(option.text).includes(query);
            });
        });
    }

    bindStudentSearch('student-search-enrollment', 'id_inscription-student');
    bindStudentSearch('student-search-payment', 'id_student');

    // Deux onglets pour un seul formulaire : c'est l'onglet actif qui pose le
    // motif (frais d'inscription ou mensualité), plus de menu à choisir.
    var motif = document.getElementById('id_motif');
    var monthlyFields = document.getElementById('payment-monthly-fields');
    var tabs = document.querySelectorAll('[data-payment-tab]');
    if (motif && tabs.length) {
        var month = document.getElementById('id_period_month');
        var year = document.getElementById('id_period_year');
        function activatePaymentTab(kind) {
            var monthly = kind === 'monthly';
            motif.value = monthly ? 'MONTHLY' : 'ENROLLMENT';
            if (monthlyFields) { monthlyFields.hidden = !monthly; }
            if (month) { month.required = monthly; }
            if (year) { year.required = monthly; }
            Array.prototype.forEach.call(tabs, function (tab) {
                var active = tab.getAttribute('data-payment-tab') === kind;
                tab.setAttribute('aria-selected', active ? 'true' : 'false');
                if (active) {
                    tab.classList.remove('ua-btn-ghost');
                    tab.classList.add('ua-btn-primary');
                } else {
                    tab.classList.remove('ua-btn-primary');
                    tab.classList.add('ua-btn-ghost');
                }
            });
        }
        Array.prototype.forEach.call(tabs, function (tab) {
            tab.addEventListener('click', function () {
                activatePaymentTab(tab.getAttribute('data-payment-tab'));
            });
        });
        activatePaymentTab(motif.value === 'MONTHLY' ? 'monthly' : 'enrollment');
    }

    var student = document.getElementById('id_inscription-student');
    var details = document.getElementById('new-student-fields');
    if (!student || !details) { return; }
    function syncStudentFields() {
        var creating = !student.value;
        details.hidden = !creating;
        details.querySelectorAll('input').forEach(function (input) {
            input.required = creating && ['first_name', 'last_name', 'email'].indexOf(input.name.split('-').pop()) !== -1;
        });
    }
    student.addEventListener('change', syncStudentFields);
    syncStudentFields();

    var course = document.getElementById('id_inscription-course');
    var session = document.getElementById('id_inscription-session');
    if (course && session) {
        function syncSessions() {
            session.disabled = !course.value;
            Array.prototype.forEach.call(session.options, function (option) {
                if (!option.value) { return; }
                option.hidden = option.getAttribute('data-course-id') !== course.value;
                if (option.selected && option.hidden) { session.value = ''; }
            });
        }
        course.addEventListener('change', syncSessions);
        syncSessions();
    }

    var motif = document.getElementById('id_inscription-first_payment_motif');
    var month = document.getElementById('id_inscription-first_payment_month');
    var year = document.getElementById('id_inscription-first_payment_year');
    function syncPeriodFields() {
        var monthly = motif && motif.value === 'MONTHLY';
        if (month) { month.required = !!monthly; }
        if (year) { year.required = !!monthly; }
    }
    if (motif) {
        motif.addEventListener('change', syncPeriodFields);
        syncPeriodFields();
    }
})();
