"""
services/chatbot.py  –  Lazy-init wrapper around the Gemini SDK.

The configured model is cached after the first call to avoid per-request
`genai.configure` + `GenerativeModel(...)` overhead.
"""

_chat_model = None
_configured_with_key = None


def get_chat_model(api_key: str):
    """Return a cached `GenerativeModel`. Reconfigures only if the key changes."""
    global _chat_model, _configured_with_key

    if _chat_model is not None and _configured_with_key == api_key:
        return _chat_model

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    _chat_model = genai.GenerativeModel("gemini-2.5-flash")
    _configured_with_key = api_key
    return _chat_model
