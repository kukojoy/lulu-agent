import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    openai_base_url: str
    openai_api_key: str
    openai_model: str

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or ""
if not OPENAI_BASE_URL:
    raise RuntimeError("Missing required environment variable: OPENAI_BASE_URL")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
if not OPENAI_API_KEY:
    raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

OPENAI_MODEL = os.getenv("OPENAI_MODEL") or ""
if not OPENAI_MODEL:
    raise RuntimeError("Missing required environment variable: OPENAI_MODEL")

config = Config(
    openai_api_key=OPENAI_API_KEY,
    openai_base_url=OPENAI_BASE_URL,
    openai_model=OPENAI_MODEL,
)