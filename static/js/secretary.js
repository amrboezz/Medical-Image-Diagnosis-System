// --- File Upload UI Logic ---
function showFileName() {
    const fileInput = document.getElementById('real-file-input');
    const promptDiv = document.getElementById('upload-prompt');
    const infoDiv = document.getElementById('file-info');
    const nameDisplay = document.getElementById('filename-display');
    const dropZone = document.getElementById('drop-zone');

    if (fileInput.files.length > 0) {
        nameDisplay.innerText = fileInput.files[0].name;
        promptDiv.classList.add('hidden');
        infoDiv.classList.remove('hidden');
        infoDiv.classList.add('flex');
        dropZone.classList.remove('border-slate-300', 'border-dashed');
        dropZone.classList.add('border-green-500', 'border-solid', 'bg-green-50');
    }
}

// --- Debounced filter for Recent Registrations (left side) ---
document.addEventListener('DOMContentLoaded', () => {
    const recentInput = document.getElementById('search-input');
    const recentItems = Array.from(document.getElementsByClassName('patient-item'));
    if (recentInput && window.UI) {
        window.UI.debouncedFilter(recentInput, recentItems, item => {
            const nameEl = item.getElementsByClassName('patient-name')[0];
            return nameEl ? nameEl.innerText : '';
        }, { delay: 100 });
    }

    // --- Debounced filter for the patient dropdown (right side) ---
    const dropdownInput = document.getElementById('patient-search-input');
    const dropdownOptions = Array.from(document.getElementsByClassName('patient-option'));
    if (dropdownInput && window.UI) {
        window.UI.debouncedFilter(dropdownInput, dropdownOptions, opt => opt.innerText, { delay: 80 });
    }
});

// --- Custom Searchable Dropdown Logic (Right Side) ---
function showPatientDropdown() {
    document.getElementById('patient-dropdown').classList.remove('hidden');
}

function selectPatient(id, displayText) {
    document.getElementById('selected-patient-id').value = id;
    document.getElementById('patient-search-input').value = displayText;
    document.getElementById('patient-dropdown').classList.add('hidden');
}

// Close dropdown if clicked outside
document.addEventListener('click', function (event) {
    const searchInput = document.getElementById('patient-search-input');
    const dropdown = document.getElementById('patient-dropdown');
    if (!searchInput.contains(event.target) && !dropdown.contains(event.target)) {
        dropdown.classList.add('hidden');
    }
});
