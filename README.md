# Universal Creative Agent (UCOA)

Universal AI agent for mobile GUI, browser, video, design, and coding workflows.

Production cloud routing uses Gemini as the primary provider with Hugging Face as secondary where configured. The Android APK embeds the local Qwen3 0.6B INT4 LiteRTLM model for offline/local execution.

The backend exposes the FastAPI app through `server/app.py` and the Vercel Python Function entrypoint at `api/index.py`.

## Verification

Run `pytest -q` from the repository root. The Android CI build also validates that the debug APK contains `assets/ucoa_local_model.litertlm`.
