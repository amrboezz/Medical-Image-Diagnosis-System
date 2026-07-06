const reports = window.REPORTS || [];

function loadPatient(index) {
    const data = reports[index];
    document.getElementById('hidden-report-id').value = data.id;

    document.querySelectorAll('.patient-card').forEach(el => {
        el.classList.remove('border-blue-600', 'bg-slate-50');
    });
    const activeCard = document.getElementById(`card-${index}`);
    if(activeCard) {
        activeCard.classList.add('border-blue-600', 'bg-slate-50');
    }

    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('content-state').classList.remove('hidden');
    document.getElementById('ai-panel').classList.remove('hidden');
    document.getElementById('action-panel').classList.remove('opacity-50', 'pointer-events-none');

    // Reset the edit container when switching patients
    document.getElementById('edit-diagnosis-container').classList.add('hidden');
    document.getElementById('final-diagnosis-input').value = "";

    document.getElementById('scan-type-badge').innerText = data.scan_type;
    document.getElementById('ai-result-text').innerText = data.ai_result;
    document.getElementById('confidence-text').innerText = data.ai_confidence + "% Confidence";

    let filename = data.image_path;
    document.getElementById('main-image').src = "/uploads_view/" + filename;

    setTimeout(() => {
        document.getElementById('confidence-bar').style.width = data.ai_confidence + "%";
    }, 100);
}

function enableEditMode() {
    document.getElementById('edit-diagnosis-container').classList.remove('hidden');
    const currentAiText = document.getElementById('ai-result-text').innerText;
    document.getElementById('final-diagnosis-input').value = currentAiText;
    document.getElementById('final-diagnosis-input').focus();
}
