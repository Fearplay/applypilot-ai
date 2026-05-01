# ApplyPilot AI

> **Job URL to Tailored Resume & Cover Letter**

ApplyPilot AI is a Python desktop GenAI application that turns a job posting URL, resume, GitHub profile and LinkedIn export into a tailored ATS-friendly resume and cover letter. It uses evidence-based generation, clarifying questions and structured AI outputs to avoid hallucinated experience. The app supports a provider-agnostic AI API architecture and includes a fake/demo provider for local testing without API costs.

A full README with architecture diagram, screenshots, provider setup tables and roadmap will land in a follow-up commit on this branch (`docs:` commit).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
python app.py
```

By default the app runs in **demo mode** with the `FakeAIProvider` - no API key needed, no network, no cost.

## License

MIT for application code. See [`LICENSE`](LICENSE). PySide6/Qt is LGPL-3.0 and is linked dynamically.
