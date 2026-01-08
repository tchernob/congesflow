/**
 * CongesFlow - Main JavaScript Application
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize components
    initNotifications();
    initMobileMenu();
    initDropdowns();
    initModals();
    initDateInputs();
    initToasts();
});

/**
 * Notifications System
 */
function initNotifications() {
    const dropdown = document.getElementById('notificationsDropdown');
    const btn = document.getElementById('notificationsBtn');
    const countBadge = document.getElementById('notificationsCount');
    const list = document.getElementById('notificationsList');
    const markAllBtn = document.getElementById('markAllRead');

    if (!dropdown || !btn) return;

    // Toggle dropdown
    btn.addEventListener('click', function(e) {
        e.stopPropagation();
        dropdown.classList.toggle('open');
        if (dropdown.classList.contains('open')) {
            loadNotifications();
        }
    });

    // Close on outside click
    document.addEventListener('click', function(e) {
        if (!dropdown.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });

    // Mark all as read
    if (markAllBtn) {
        markAllBtn.addEventListener('click', function() {
            fetch('/api/notifications/read-all', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        countBadge.style.display = 'none';
                        loadNotifications();
                    }
                });
        });
    }

    // Initial load
    loadNotificationsCount();
    setInterval(loadNotificationsCount, 60000); // Check every minute
}

function loadNotificationsCount() {
    const countBadge = document.getElementById('notificationsCount');
    if (!countBadge) return;

    fetch('/api/notifications')
        .then(response => response.json())
        .then(data => {
            if (data.unread_count > 0) {
                countBadge.textContent = data.unread_count;
                countBadge.style.display = 'flex';
            } else {
                countBadge.style.display = 'none';
            }
        })
        .catch(err => console.error('Error loading notifications:', err));
}

function loadNotifications() {
    const list = document.getElementById('notificationsList');
    if (!list) return;

    fetch('/api/notifications')
        .then(response => response.json())
        .then(data => {
            // Clear existing content safely
            list.textContent = '';

            if (data.notifications.length === 0) {
                const emptyState = document.createElement('div');
                emptyState.className = 'empty-state p-6';
                const emptyText = document.createElement('p');
                emptyText.className = 'text-muted text-sm';
                emptyText.textContent = 'Aucune notification';
                emptyState.appendChild(emptyText);
                list.appendChild(emptyState);
                return;
            }

            data.notifications.forEach(notif => {
                const item = document.createElement('div');
                item.className = 'notification-item' + (notif.is_read ? '' : ' unread');
                item.dataset.id = notif.id;
                item.addEventListener('click', () => handleNotificationClick(notif.id, notif.link || ''));

                const title = document.createElement('div');
                title.className = 'notification-title';
                title.textContent = notif.title;

                const message = document.createElement('div');
                message.className = 'notification-message';
                message.textContent = notif.message;

                const time = document.createElement('div');
                time.className = 'notification-time';
                time.textContent = formatTimeAgo(notif.created_at);

                item.appendChild(title);
                item.appendChild(message);
                item.appendChild(time);
                list.appendChild(item);
            });
        })
        .catch(err => {
            list.textContent = '';
            const emptyState = document.createElement('div');
            emptyState.className = 'empty-state p-6';
            const emptyText = document.createElement('p');
            emptyText.className = 'text-muted text-sm';
            emptyText.textContent = 'Erreur de chargement';
            emptyState.appendChild(emptyText);
            list.appendChild(emptyState);
        });
}

function handleNotificationClick(id, link) {
    fetch('/api/notifications/' + id + '/read', { method: 'POST' })
        .then(() => {
            loadNotificationsCount();
            if (link) {
                window.location.href = link;
            }
        });
}

/**
 * Mobile Menu
 */
function initMobileMenu() {
    const toggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');

    if (!toggle || !sidebar) return;

    // Show toggle on mobile
    if (window.innerWidth <= 768) {
        toggle.style.display = 'flex';
    }

    window.addEventListener('resize', function() {
        if (window.innerWidth <= 768) {
            toggle.style.display = 'flex';
        } else {
            toggle.style.display = 'none';
            sidebar.classList.remove('open');
        }
    });

    toggle.addEventListener('click', function() {
        sidebar.classList.toggle('open');
    });

    // Close on outside click
    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 768 &&
            sidebar.classList.contains('open') &&
            !sidebar.contains(e.target) &&
            !toggle.contains(e.target)) {
            sidebar.classList.remove('open');
        }
    });
}

/**
 * Generic Dropdowns
 */
function initDropdowns() {
    document.querySelectorAll('[data-dropdown]').forEach(trigger => {
        const targetId = trigger.dataset.dropdown;
        const target = document.getElementById(targetId);
        if (!target) return;

        trigger.addEventListener('click', function(e) {
            e.stopPropagation();
            target.classList.toggle('open');
        });

        document.addEventListener('click', function(e) {
            if (!target.contains(e.target) && !trigger.contains(e.target)) {
                target.classList.remove('open');
            }
        });
    });
}

/**
 * Modal System
 */
function initModals() {
    // Open modal triggers
    document.querySelectorAll('[data-modal]').forEach(trigger => {
        trigger.addEventListener('click', function() {
            const modalId = this.dataset.modal;
            openModal(modalId);
        });
    });

    // Close buttons
    document.querySelectorAll('[data-modal-close]').forEach(btn => {
        btn.addEventListener('click', function() {
            const modal = this.closest('.modal-overlay');
            if (modal) closeModal(modal.id);
        });
    });

    // Close on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal(this.id);
            }
        });
    });

    // Close on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay.active').forEach(modal => {
                closeModal(modal.id);
            });
        }
    });
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
    }
}

/**
 * Date Inputs Enhancement
 */
function initDateInputs() {
    // Auto-calculate days when dates change
    const startDate = document.getElementById('start_date');
    const endDate = document.getElementById('end_date');
    const startHalfDay = document.querySelector('input[name="start_half_day"]');
    const endHalfDay = document.querySelector('input[name="end_half_day"]');
    const daysDisplay = document.getElementById('days_count');

    if (startDate && endDate && daysDisplay) {
        function updateDays() {
            if (startDate.value && endDate.value) {
                const start = new Date(startDate.value);
                const end = new Date(endDate.value);

                if (end >= start) {
                    let days = calculateBusinessDays(start, end);

                    // Prendre en compte les demi-journées
                    if (startHalfDay && startHalfDay.checked) {
                        days -= 0.5;
                    }
                    if (endHalfDay && endHalfDay.checked) {
                        days -= 0.5;
                    }

                    days = Math.max(0, days);

                    if (days === 0.5) {
                        daysDisplay.textContent = '0.5 jour';
                    } else if (days % 1 !== 0) {
                        daysDisplay.textContent = days + ' jours';
                    } else {
                        daysDisplay.textContent = days + ' jour' + (days > 1 ? 's' : '');
                    }
                } else {
                    daysDisplay.textContent = 'Dates invalides';
                }
            } else {
                daysDisplay.textContent = '-- jours';
            }
        }

        startDate.addEventListener('change', updateDays);
        endDate.addEventListener('change', updateDays);

        // Écouter aussi les changements sur les demi-journées
        if (startHalfDay) {
            startHalfDay.addEventListener('change', updateDays);
        }
        if (endHalfDay) {
            endHalfDay.addEventListener('change', updateDays);
        }

        // Synchroniser la date de fin minimum avec la date de début
        startDate.addEventListener('change', function() {
            if (startDate.value) {
                endDate.min = startDate.value;
                // Si la date de fin est avant la date de début, la corriger
                if (endDate.value && endDate.value < startDate.value) {
                    endDate.value = startDate.value;
                }
            }
            updateDays();
        });
    }

    // Check for conflicts when dates change
    const conflictChecker = document.getElementById('conflict_checker');
    if (startDate && endDate && conflictChecker) {
        function checkConflicts() {
            if (startDate.value && endDate.value) {
                fetch('/api/check-conflicts?start_date=' + startDate.value + '&end_date=' + endDate.value)
                    .then(response => response.json())
                    .then(data => {
                        // Clear existing content safely
                        conflictChecker.textContent = '';

                        if (data.has_conflicts) {
                            const alert = document.createElement('div');
                            alert.className = 'alert alert-warning';

                            const content = document.createElement('div');
                            content.className = 'alert-content';

                            const strong = document.createElement('strong');
                            strong.textContent = 'Conflits potentiels:';
                            content.appendChild(strong);

                            const ul = document.createElement('ul');
                            ul.className = 'mt-2';

                            data.conflicts.forEach(c => {
                                const li = document.createElement('li');
                                li.textContent = c.employee_name + ': ' + c.start_date + ' - ' + c.end_date;
                                ul.appendChild(li);
                            });

                            content.appendChild(ul);
                            alert.appendChild(content);
                            conflictChecker.appendChild(alert);
                        }
                    });
            }
        }

        startDate.addEventListener('change', checkConflicts);
        endDate.addEventListener('change', checkConflicts);
    }
}

function calculateBusinessDays(start, end) {
    let count = 0;
    const current = new Date(start);

    while (current <= end) {
        const dayOfWeek = current.getDay();
        if (dayOfWeek !== 0 && dayOfWeek !== 6) {
            count++;
        }
        current.setDate(current.getDate() + 1);
    }

    return count;
}

/**
 * Toast Auto-dismiss
 */
function initToasts() {
    document.querySelectorAll('.toast').forEach(toast => {
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s forwards';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    });
}

/**
 * Utility Functions
 */
function formatTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'À l\'instant';
    if (seconds < 3600) return Math.floor(seconds / 60) + ' min';
    if (seconds < 86400) return Math.floor(seconds / 3600) + ' h';
    if (seconds < 604800) return Math.floor(seconds / 86400) + ' j';

    return date.toLocaleDateString('fr-FR');
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('fr-FR', {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
    });
}

/**
 * Form Validation
 */
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return true;

    let isValid = true;

    // Clear previous errors
    form.querySelectorAll('.form-error').forEach(el => el.remove());
    form.querySelectorAll('.form-input, .form-select, .form-textarea').forEach(el => {
        el.classList.remove('error');
    });

    // Check required fields
    form.querySelectorAll('[required]').forEach(field => {
        if (!field.value.trim()) {
            isValid = false;
            field.classList.add('error');
            const error = document.createElement('div');
            error.className = 'form-error';
            error.textContent = 'Ce champ est requis';
            field.parentNode.appendChild(error);
        }
    });

    // Check email format
    form.querySelectorAll('input[type="email"]').forEach(field => {
        if (field.value && !isValidEmail(field.value)) {
            isValid = false;
            field.classList.add('error');
            const error = document.createElement('div');
            error.className = 'form-error';
            error.textContent = 'Email invalide';
            field.parentNode.appendChild(error);
        }
    });

    return isValid;
}

function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

/**
 * Confirmation Dialog
 */
function confirmAction(message, callback) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay active';

    const modalContent = document.createElement('div');
    modalContent.className = 'modal';
    modalContent.style.maxWidth = '400px';

    const modalHeader = document.createElement('div');
    modalHeader.className = 'modal-header';
    const modalTitle = document.createElement('h3');
    modalTitle.className = 'modal-title';
    modalTitle.textContent = 'Confirmation';
    modalHeader.appendChild(modalTitle);

    const modalBody = document.createElement('div');
    modalBody.className = 'modal-body';
    const messagePara = document.createElement('p');
    messagePara.textContent = message;
    modalBody.appendChild(messagePara);

    const modalFooter = document.createElement('div');
    modalFooter.className = 'modal-footer';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Annuler';

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-danger';
    confirmBtn.textContent = 'Confirmer';

    modalFooter.appendChild(cancelBtn);
    modalFooter.appendChild(confirmBtn);

    modalContent.appendChild(modalHeader);
    modalContent.appendChild(modalBody);
    modalContent.appendChild(modalFooter);
    modal.appendChild(modalContent);

    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';

    cancelBtn.addEventListener('click', () => {
        modal.remove();
        document.body.style.overflow = '';
    });

    confirmBtn.addEventListener('click', () => {
        modal.remove();
        document.body.style.overflow = '';
        if (callback) callback();
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
            document.body.style.overflow = '';
        }
    });
}

/**
 * Calendar Initialization (if using FullCalendar)
 */
function initCalendar(elementId, options) {
    options = options || {};
    const calendarEl = document.getElementById(elementId);
    if (!calendarEl || typeof FullCalendar === 'undefined') return null;

    const defaultOptions = {
        locale: 'fr',
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,listWeek'
        },
        events: '/api/calendar/events',
        eventClick: function(info) {
            // Handle event click
        },
        eventDidMount: function(info) {
            // Add tooltips or extra styling
        }
    };

    const mergedOptions = Object.assign({}, defaultOptions, options);

    const calendar = new FullCalendar.Calendar(calendarEl, mergedOptions);

    calendar.render();
    return calendar;
}

/**
 * Export functionality
 */
window.CongesFlow = {
    openModal: openModal,
    closeModal: closeModal,
    confirmAction: confirmAction,
    validateForm: validateForm,
    initCalendar: initCalendar,
    formatDate: formatDate,
    formatTimeAgo: formatTimeAgo
};
