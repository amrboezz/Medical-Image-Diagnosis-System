const chatToggle = document.getElementById('chat-toggle');
const chatClose = document.getElementById('chat-close');
const chatWindow = document.getElementById('chat-window');
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');

chatToggle.addEventListener('click', () => {
    chatWindow.classList.toggle('hidden');
    chatWindow.classList.toggle('flex');
});
chatClose.addEventListener('click', () => {
    chatWindow.classList.add('hidden');
    chatWindow.classList.remove('flex');
});

let chatHistory = [];

function formatChatText(text) {
    let safeText = String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Convert bullets (* or - at start of line)
    safeText = safeText.replace(/^[\*\-]\s+(.*)$/gm, '&bull; $1');
    // Convert bold (**text**)
    safeText = safeText.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
    // Convert italic (*text*)
    safeText = safeText.replace(/\*(.*?)\*/g, '<i>$1</i>');
    // Convert newlines
    safeText = safeText.replace(/\n/g, '<br>');
    return safeText;
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    // Add user bubble (sent — blue)
    chatMessages.innerHTML += `
        <div class="bg-blue-600 text-white p-3 rounded-2xl rounded-tr-sm max-w-[85%] self-end text-left mt-2 shadow-sm">
            ${formatChatText(text)}
        </div>`;
    chatInput.value = '';
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({ message: text, history: chatHistory })
        });
        const data = await response.json();

        chatHistory.push({ role: 'user', content: text });
        chatHistory.push({ role: 'assistant', content: data.reply });

        // Add AI reply bubble (received — white)
        setTimeout(() => {
            chatMessages.innerHTML += `
                <div class="bg-white border border-slate-200 text-slate-700 p-3 rounded-2xl rounded-tl-sm max-w-[85%] self-start text-left mt-2 shadow-sm">
                    ${formatChatText(data.reply)}
                </div>`;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 500);
    } catch (error) {
        console.error("Chat error:", error);
    }
}

chatSend.addEventListener('click', sendMessage);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

function showPatientFileName() {
    const fileInput = document.getElementById('patient-file-input');
    const promptDiv = document.getElementById('patient-upload-prompt');
    const infoDiv = document.getElementById('patient-file-info');
    const nameDisplay = document.getElementById('patient-filename-display');
    const dropZone = document.getElementById('patient-drop-zone');

    if (fileInput.files.length > 0) {
        nameDisplay.innerText = fileInput.files[0].name;
        promptDiv.classList.add('hidden');
        infoDiv.classList.remove('hidden');
        infoDiv.classList.add('flex');
        dropZone.classList.remove('border-slate-300', 'border-dashed');
        dropZone.classList.add('border-green-500', 'border-solid', 'bg-green-50');
    }
}
