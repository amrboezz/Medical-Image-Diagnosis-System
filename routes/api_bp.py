"""
routes/api_bp.py  –  JSON-only endpoints. Currently the Gemini chatbot.
"""

from flask import Blueprint, current_app, jsonify, request, session
from flask.typing import ResponseReturnValue

from auth import login_required
from database import Report
from extensions import limiter
from services.audit import audit_logger
from services.chatbot import get_chat_model
from services.db_helpers import sanitize_chat_message

api_bp = Blueprint("api_bp", __name__)


SYSTEM_CONTEXT = (
    "You are 'MediBot', an advanced, empathetic, and highly professional medical AI assistant at MediDiagnostic Hospital. "
    "Your primary role is to help patients comprehend their AI-generated bone and joint scan results "
    "(fractures, tumors, osteoporosis, or osteoarthritis) in a compassionate, clear, and medically responsible manner.\n\n"

    "## CORE PERSONA & TONE\n"
    "- Professional yet warm and empathetic. Acknowledge that waiting for medical results can be stressful.\n"
    "- Reassuring and objective. Do not cause unnecessary alarm, but do not falsely reassure.\n"
    "- Speak in plain, accessible language (eighth-grade reading level), avoiding dense medical jargon. If terms are necessary, define them simply.\n"
    "- Keep responses highly concise and structured (use short paragraphs or bullets) to fit comfortably within a small chat widget.\n\n"

    "## CAPABILITIES & GROUNDING\n"
    "- You have access to the patient's most recent scan data provided below.\n"
    "- Interpret the provided AI findings, explaining what the specific results and confidence percentages mean in general terms.\n"
    "- Base your entire analysis ONLY on the provided scan context. Do not hallucinate metrics, findings, or conditions not explicitly stated.\n\n"

    "## CLINICAL BOUNDARIES & GUARDRAILS (CRITICAL)\n"
    "- You may act as a consultative medical professional to explain possible diagnoses, recommend general treatment pathways, and provide clinical insights based on the scan.\n"
    "- However, you MUST explicitly include a clear disclaimer in your response that you are an AI and your advice must be confirmed by the patient's actual treating physician.\n"
    "- If the user asks about unrelated medical conditions, politics, or general trivia, politely decline and steer the conversation back to their scan.\n"
    "- Never contradict the AI result or the doctor's notes.\n\n"

    "## STATUS-AWARE WORKFLOW\n"
    "- If Status = PRELIMINARY: Emphasize that these are early, AI-generated insights that MUST be reviewed by a human radiologist. Use phrases like 'The initial AI screening suggests...'\n"
    "- If Status = APPROVED: You may speak with more certainty, noting that a human doctor has verified the findings, but maintain the boundary that you are explaining the report, not acting as their doctor.\n\n"

    "## CONVERSATION MEMORY\n"
    "- If the user asks a follow-up question and there is previous conversation history, DO NOT repeat your initial disclaimers or full introductory greetings.\n"
    "- Treat follow-ups conversationally and answer the specific question immediately and concisely.\n"
)


def _build_scan_context(user_id: int) -> str:
    """Return a system-prompt fragment describing the patient's most recent scan."""
    latest = (
        Report.query.filter_by(patient_id=user_id)
        .order_by(Report.id.desc())
        .first()
    )
    if not latest:
        return (
            "\n\nThe patient has not uploaded any scans yet. "
            "If they ask about results, encourage them to upload an X-ray first."
        )

    r = latest.to_dict()
    status_hint = {
        "PRELIMINARY": "PRELIMINARY (AI-generated, not yet reviewed by a doctor)",
        "APPROVED": "APPROVED (doctor has confirmed this result)",
    }.get(r["status"], r["status"])

    return (
        "\n\nThe patient's most recent scan on record is:\n"
        f"- Scan type: {r['scan_type']}\n"
        f"- AI preliminary result: {r['ai_result']}\n"
        f"- AI confidence: {r['ai_confidence']}%\n"
        f"- Status: {status_hint}\n"
        f"- Doctor notes: {r['doctor_notes'] or '(none yet)'}\n"
        f"- Date: {r['created_at']}\n"
        "When the patient refers to \"my scan\", \"the result\", \"this\", or similar, "
        "assume they mean this scan unless they say otherwise."
    )


@api_bp.route("/api/chat", methods=["POST"])
@login_required
@limiter.limit(
    "30 per minute; 500 per day",
    error_message="Too many requests. Please wait before sending another message.",
)
def chat() -> ResponseReturnValue:
    """Patient-facing chatbot backed by Gemini.

    JSON body: ``{ "message": str }``. Caller must send the per-session
    CSRF token in the ``X-CSRFToken`` header. The message is sanitised to
    strip control characters and role-boundary tokens (``system:`` etc.)
    before being concatenated into the prompt.

    Access: any authenticated session. Rate-limited.
    """
    data = request.get_json(silent=True) or {}
    message = sanitize_chat_message(data.get("message", ""))

    if not message:
        return jsonify({"reply": "Please send a message."}), 400

    api_key = current_app.config.get("GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({
            "reply": (
                "The AI assistant is not configured yet. "
                "Please ask the admin to set the GEMINI_API_KEY environment variable."
            )
        })

    user_id = session["user_id"]
    scan_context = _build_scan_context(user_id)
    audit_logger.info(
        f"CHATBOT – user_id={user_id} msg_len={len(message)} "
        f"scan_context={'attached' if 'most recent scan' in scan_context else 'none'}"
    )

    history = data.get("history", [])
    history_str = ""
    if history:
        history_str = "## PREVIOUS CONVERSATION HISTORY\n"
        # Only take the last 4 exchanges to save tokens
        for msg in history[-8:]:
            role = "Patient" if msg.get("role") == "user" else "MediBot"
            history_str += f"{role}: {msg.get('content')}\n\n"
        history_str += "## CURRENT MESSAGE\n"

    try:
        model = get_chat_model(api_key)
        full_prompt = f"{SYSTEM_CONTEXT}{scan_context}\n\n{history_str}Patient: {message}"
        response = model.generate_content(
            full_prompt, request_options={"timeout": 20}
        )
        reply = response.text
    except Exception as exc:
        audit_logger.error(f"Chatbot error: {type(exc).__name__}")
        reply = "Sorry, the AI assistant is temporarily unavailable. Please try again later."

    return jsonify({"reply": reply})
