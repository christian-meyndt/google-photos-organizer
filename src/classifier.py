"""Vision model classification using Ollama (local, free)."""

import base64
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from .config import config


class ClassificationResult(BaseModel):
    category: str
    description: str


CATEGORIES = [
    "family",
    "travel",
    "food",
    "nature",
    "pets",
    "events",
    "selfie",
    "screenshot",
    "document",
    "sport",
    "architecture",
    "art",
    "other",
]

CLASSIFICATION_PROMPT = f"""Analyze this image and provide:
1. A category from this list: {', '.join(CATEGORIES)}
2. A short description (1-2 sentences) of what's in the image.

Respond in exactly this format:
CATEGORY: <category>
DESCRIPTION: <description>

Be concise. Pick the single best category."""


def classify_image(image_path: Path) -> ClassificationResult:
    """Classify an image using a local vision model via Ollama."""
    llm = ChatOllama(
        model=config.ollama_model,
        base_url=config.ollama_base_url,
        temperature=0,
    )

    image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    mime_type = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    message = HumanMessage(
        content=[
            {"type": "text", "text": CLASSIFICATION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
        ]
    )

    response = llm.invoke([message])
    return _parse_response(response.content)


def _parse_response(text: str) -> ClassificationResult:
    """Parse the LLM response into structured output."""
    category = "other"
    description = ""

    for line in text.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("CATEGORY:"):
            raw_cat = line.split(":", 1)[1].strip().lower()
            if raw_cat in CATEGORIES:
                category = raw_cat
        elif line.upper().startswith("DESCRIPTION:"):
            description = line.split(":", 1)[1].strip()

    return ClassificationResult(category=category, description=description)


def generate_folder_summary(descriptions: list[str], folder_name: str) -> str:
    """Generate a summary for a folder based on its contents."""
    llm = ChatOllama(
        model=config.ollama_model.replace("-vision", ""),
        base_url=config.ollama_base_url,
        temperature=0.3,
    )

    items_text = "\n".join(f"- {d}" for d in descriptions[:20])
    prompt = (
        f"This folder '{folder_name}' contains these photos:\n{items_text}\n\n"
        "Write a 1-2 sentence summary of what this folder contains. Be specific and concise."
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()
