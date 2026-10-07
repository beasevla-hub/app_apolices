"""Modelos e validação dos dados estruturados retornados pela IA."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class PolicyData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    empresa: str | None = None
    tipo_empresa: Literal["THI", "PHAS"] | None = None
    orgao: str | None = None
    orgao_normalizado: str | None = None
    numero_concorrencia_original: str | None = None
    numero_concorrencia_normalizado: str | None = None
    processo_sei: str | None = None
    objeto: str | None = None
    vigencia_data_inicial: date | None = None
    vigencia_data_final: date | None = None
    valor_premio: float | None = Field(default=None, ge=0)
    numero_registro_susep: str | None = None
    linha_digitavel_boleto: str | None = None
    nome_pasta: str | None = None
    nome_apolice: str | None = None
    nome_boleto: str | None = None
    confianca_geral: float = Field(ge=0, le=1)
    campos_com_duvida: list[str] = Field(default_factory=list)
    observacoes: str | None = None

    @field_validator("vigencia_data_inicial", "vigencia_data_final", mode="before")
    @classmethod
    def parse_date(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    @model_validator(mode="after")
    def validate_term(self):
        if self.vigencia_data_inicial and self.vigencia_data_final and self.vigencia_data_final < self.vigencia_data_inicial:
            raise ValueError("A data final da vigência antecede a data inicial")
        return self

    def minimum_data_present(self) -> bool:
        return all((self.tipo_empresa, self.orgao, self.numero_concorrencia_normalizado, self.vigencia_data_inicial, self.vigencia_data_final))
