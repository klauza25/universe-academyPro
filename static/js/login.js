(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-password-toggle]').forEach(function (button) {
            const input = document.getElementById(button.getAttribute('aria-controls'));
            if (!input) { return; }

            button.addEventListener('click', function () {
                const visible = input.type === 'password';
                input.type = visible ? 'text' : 'password';
                button.textContent = visible
                    ? button.dataset.hideLabel
                    : button.dataset.showLabel;
                button.setAttribute('aria-pressed', visible ? 'true' : 'false');
            });
        });
    });
})();
