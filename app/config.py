"""Configuração centralizada do aplicativo."""
from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    email_host: str = os.getenv("EMAIL_HOST", "email-ssl.com.br")
    email_port: int = int(os.getenv("EMAIL_PORT", "993"))
    email_use_ssl: bool = os.getenv("EMAIL_USE_SSL", "true").lower() in {"1", "true", "yes"}
    email_user: str = os.getenv("EMAIL_USER", "")
    email_password: str = os.getenv("EMAIL_PASSWORD", "")
    email_folder: str = os.getenv("EMAIL_FOLDER", "INBOX")
    allowed_sender_domains: tuple[str, ...] = tuple(x.strip().lower() for x in os.getenv("ALLOWED_SENDER_DOMAINS", "@finlandiaseguros.com.br").split(",") if x.strip())
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_timeout: int = int(os.getenv("OPENROUTER_TIMEOUT", "120"))
    root_dir: Path = Path(os.getenv("PASTA_RAIZ", "./documentos"))
    robot_control: Path = Path(os.getenv("CONTROLE_ROBO", "controle_robo.xlsx"))
    policies_excel: Path = Path(os.getenv("CONTROLE_APOLICES", "controle_apolices.xlsx"))
    thi_names: str = os.getenv("THI_NAMES", "THI ENGENHARIA E ARQUITETURA LTDA")
    phas_names: str = os.getenv("PHAS_NAMES", "PHAS ENGENHARIA, CONSTRUÇÕES E SERVIÇOS LTDA-ME")
    dry_run: bool = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_emails_per_run: int = int(os.getenv("MAX_EMAILS_PER_RUN", "100"))
    robot_max_attempts: int = int(os.getenv("ROBOT_MAX_ATTEMPTS", "5"))
    keep_success_temp: bool = os.getenv("KEEP_SUCCESS_TEMP", "false").lower() in {"1", "true", "yes"}

settings = Settings()
