"""Modelos validados da extração documental e evidências por campo."""
from datetime import date
from typing import Literal,Any
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

Source=Literal["APOLICE","BOLETO","AMBOS","NAO_IDENTIFICADO"]
class Evidence(BaseModel):
    """Valor observado, origem documental e confiança estimada."""
    model_config=ConfigDict(extra="forbid")
    valor:Any=None
    fonte:Source="NAO_IDENTIFICADO"
    confianca:float=Field(default=0,ge=0,le=1)

class PolicyLot(BaseModel):
    """Lote extraído da apólice e eventual prêmio individual explicitamente associado."""
    model_config=ConfigDict(extra="forbid")
    numero:Evidence
    valor_premio:Evidence=Field(default_factory=Evidence)

class PolicyData(BaseModel):
    model_config=ConfigDict(extra="forbid")
    empresa:str|None=None
    empresa_normalizada:Literal["THI","PHAS"]|None=None
    tipo_empresa:Literal["THI","PHAS"]|None=None
    cnpj:str|None=None
    orgao:str|None=None
    orgao_normalizado:str|None=None
    numero_concorrencia_original:str|None=None
    numero_concorrencia_normalizado:str|None=None
    processo_sei:str|None=None
    lote:str|None=None
    lote_associado:str|None=None
    lotes_associados:list[str]=Field(default_factory=list)
    lotes:list[PolicyLot]=Field(default_factory=list)
    par_coerente:bool|None=None
    objeto:str|None=None
    vigencia_data_inicial:date|None=None
    vigencia_data_final:date|None=None
    valor_premio:float|None=Field(default=None,ge=0)
    numero_registro_susep:str|None=None
    linha_digitavel_boleto:str|None=None
    nome_pasta:str|None=None
    nome_apolice:str|None=None
    nome_boleto:str|None=None
    confianca_geral:float=Field(default=0,ge=0,le=1)
    evidencias:dict[str,Evidence]=Field(default_factory=dict)
    campos_com_duvida:list[str]=Field(default_factory=list)
    observacoes:str|None=None
    @field_validator("lote",mode="before")
    @classmethod
    def normalize_lot(cls,value):
        if value is None:return None
        cleaned=" ".join(str(value).split())
        return cleaned or None
    @field_validator("vigencia_data_inicial","vigencia_data_final",mode="before")
    @classmethod
    def parse_date(cls,value):
        if value in (None,""):return None
        if isinstance(value,date):return value
        return date.fromisoformat(str(value))
    @model_validator(mode="after")
    def validate_term_and_company(self):
        if self.vigencia_data_inicial and self.vigencia_data_final and self.vigencia_data_final<self.vigencia_data_inicial:raise ValueError("A data final da vigência antecede a data inicial")
        if self.empresa_normalizada and self.tipo_empresa and self.empresa_normalizada!=self.tipo_empresa:raise ValueError("empresa_normalizada e tipo_empresa são conflitantes")
        if self.empresa_normalizada is None and self.tipo_empresa:self.empresa_normalizada=self.tipo_empresa
        if self.tipo_empresa is None and self.empresa_normalizada:self.tipo_empresa=self.empresa_normalizada
        for field_name,evidence in self.evidencias.items():
            if not hasattr(self,field_name):raise ValueError(f"Evidência associada a campo desconhecido: {field_name}")
            if evidence.valor is None and getattr(self,field_name,None) is not None:raise ValueError(f"Evidência de {field_name} não pode ser null se o campo possui valor")
        return self
    def confidence_for(self,field_name:str)->float:
        evidence=self.evidencias.get(field_name)
        return evidence.confianca if evidence else self.confianca_geral
    @property
    def lote_operacional(self)->str|None:
        """Lote para organização operacional, sem alterar o dado documental extraído."""
        if self.lote_associado is not None:return self.lote_associado
        if len(self.lotes_associados)==1:return self.lotes_associados[0]
        return self.lote
    @property
    def lote_documental(self)->str|None:
        """Identificador de lote efetivamente retornado pela extração documental."""
        return self.lote
    def minimum_data_present(self)->bool:
        return all((self.empresa_normalizada,self.orgao,self.numero_concorrencia_normalizado,self.vigencia_data_inicial,self.vigencia_data_final))
