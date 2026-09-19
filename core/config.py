# core/config.py
import os
from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm
import warnings
import logging

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.CRITICAL)

load_dotenv()

MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
llm = LiteLlm(model=MODEL_NAME)