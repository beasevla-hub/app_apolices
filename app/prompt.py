"""Prompts e schemas usados em inferência multimodal."""
import json

POLICY_SCHEMA = {
 "type":"object", "additionalProperties":False,
 "properties": {
  "empresa":{"type":["string","null"]},"tipo_empresa":{"type":["string","null"],"enum":["THI","PHAS",None]},
  "orgao":{"type":["string","null"]},"orgao_normalizado":{"type":["string","null"]},
  "numero_concorrencia_original":{"type":["string","null"]},"numero_concorrencia_normalizado":{"type":["string","null"]},
  "processo_sei":{"type":["string","null"]},"objeto":{"type":["string","null"]},
  "vigencia_data_inicial":{"type":["string","null"]},"vigencia_data_final":{"type":["string","null"]},
  "valor_premio":{"type":["number","null"]},"numero_registro_susep":{"type":["string","null"]},
  "linha_digitavel_boleto":{"type":["string","null"]},"nome_pasta":{"type":["string","null"]},
  "nome_apolice":{"type":["string","null"]},"nome_boleto":{"type":["string","null"]},
  "confianca_geral":{"type":"number","minimum":0,"maximum":1},"campos_com_duvida":{"type":"array","items":{"type":"string"}},"observacoes":{"type":["string","null"]}
 }, "required":["empresa","tipo_empresa","orgao","orgao_normalizado","numero_concorrencia_original","numero_concorrencia_normalizado","processo_sei","objeto","vigencia_data_inicial","vigencia_data_final","valor_premio","numero_registro_susep","linha_digitavel_boleto","nome_pasta","nome_apolice","nome_boleto","confianca_geral","campos_com_duvida","observacoes"]
}

ROLE_SCHEMA={"type":"object","additionalProperties":False,"properties":{"roles":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"file":{"type":"string"},"role":{"type":"string","enum":["APOLICE","BOLETO","OUTRO"]}},"required":["file","role"]}}},"required":["roles"]}

SYSTEM_PROMPT = """Você analisa documentos brasileiros de apólices de seguro relacionadas a contratos/licitações. Use exclusivamente o conteúdo visível nos documentos; nunca invente nem complete informação parcialmente visível. Ausência ou dúvida deve ser null e apontada em campos_com_duvida/observacoes. Para dados da apólice priorize a apólice; para cobrança e linha digitável priorize o boleto. Identifique THI/PHAS apenas quando o documento der suporte. Normalizar número para uso em nome de pasta substituindo separadores por hífens. Datas ISO YYYY-MM-DD. Gere também nomes sugeridos. Não deduza processo SEI, SUSEP, datas, valor ou linha digitável."""

def role_prompt(names: list[str]) -> str:
    return "Classifique cada PDF anexado como APOLICE, BOLETO ou OUTRO. Examine o conteúdo, não confie somente no nome. Devolva o nome exato de cada arquivo. Nomes de empresas de referência: " + "; ".join(names)

def policy_prompt() -> str:
    return SYSTEM_PROMPT + "\nExtraia todos os campos solicitados no schema. Você receberá as primeiras páginas da apólice e o PDF completo do boleto. Para campo ausente use null; confianca_geral é número entre 0 e 1; campos_com_duvida é lista."
