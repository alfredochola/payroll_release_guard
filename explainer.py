"""Optional plain-English summary of a held payment, written by the private AI (Ollama) and fact-checked.

The checks already produce exact reasons. The AI only rewords them into one sentence for a manager.
If its sentence changes a number, drops a fact or accuses anyone, it is thrown away and the exact reasons are used.
"""
import re

import requests

OLLAMA = "http://127.0.0.1:11434"
MODEL = "llama3.2:3b"
FORBIDDEN = re.compile(r"\b(fraud\w*|stole|steal\w*|theft|criminal|guilty|illegal|significant\w*|"
                       r"alarming\w*|should|must|recommend\w*)\b", re.I)


def facts_sentence(ben, reasons):
    parts = [r["text"].rstrip(".") for r in reasons if r["check"] != "Context"]
    return f"Payment to {ben} was held because: " + "; ".join(p[0].lower() + p[1:] for p in parts) + "."


def numbers(text):
    """Numbers with the words either side, ignoring codes such as B-12AB34CD."""
    text = re.sub(r"\b[A-Z]{1,2}-[0-9A-F]{6,}\b", "code", text)
    words = re.findall(r"\d[\d,]*(?:\.\d+)?|[a-z]+", text.lower())
    at = lambda i: words[i] if 0 <= i < len(words) else ""
    return {(at(i - 1), w.replace(",", ""), at(i + 1)) for i, w in enumerate(words) if w[0].isdigit()}


def explain(ben, reasons):
    """Returns (sentence, written_by_ai, rejection_reason)."""
    base = facts_sentence(ben, reasons)
    prompt = ("Rewrite this for a bank manager in one clear, plain sentence. Keep every number exactly, with the "
              "same words on each side of it. Do not add facts or opinions, and do not accuse anyone. "
              f"Output only the sentence.\n\nSentence: {base}\nRewritten:")
    try:
        r = requests.post(f"{OLLAMA}/api/generate", json={"model": MODEL, "prompt": prompt, "stream": False,
                                                          "options": {"temperature": 0.1, "num_predict": 120}},
                          timeout=60)
        draft = r.json()["response"].strip().strip('"')
    except (requests.RequestException, ValueError, KeyError):
        return base, False, "the private AI is not running"
    if FORBIDDEN.search(draft):
        return base, False, "it used accusing or opinion words"
    missing = numbers(base) - numbers(draft)
    if missing:
        return base, False, "it changed or dropped a number"
    return draft, True, None


def ready():
    try:
        tags = requests.get(f"{OLLAMA}/api/tags", timeout=2).json()
        return any(m["name"].startswith(MODEL) for m in tags.get("models", []))
    except requests.RequestException:
        return False
