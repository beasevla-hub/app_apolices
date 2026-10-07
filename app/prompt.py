"""Prompts profissionais e schemas JSON para extração multimodal."""

EVIDENCE = {"type":"object","additionalProperties":False,"properties":{
    "valor":{"type":["string","number","null"]},
    "fonte":{"type":"string","enum":["APOLICE","BOLETO","AMBOS","NAO_IDENTIFICADO"]},
    "confianca":{"type":"number","minimum":0,"maximum":1}},"required":["valor","fonte","confianca"]}

FIELD_NAMES=["empresa","empresa_normalizada","orgao","numero_concorrencia_original","numero_concorrencia_normalizado","processo_sei","objeto","vigencia_data_inicial","vigencia_data_final","valor_premio","numero_registro_susep","linha_digitavel_boleto"]
POLICY_SCHEMA={"type":"object","additionalProperties":False,"properties":{
    **{name:EVIDENCE for name in FIELD_NAMES},
    "orgao_normalizado":{"type":["string","null"]},
    "tipo_empresa":{"type":["string","null"],"enum":["THI","PHAS",None]},
    "nome_pasta":{"type":["string","null"]},"nome_apolice":{"type":["string","null"]},"nome_boleto":{"type":["string","null"]},
    "confianca_geral":{"type":"number","minimum":0,"maximum":1},
    "campos_com_duvida":{"type":"array","items":{"type":"string"}},"observacoes":{"type":["string","null"]}},
    "required":FIELD_NAMES+["orgao_normalizado","tipo_empresa","nome_pasta","nome_apolice","nome_boleto","confianca_geral","campos_com_duvida","observacoes"]}
ROLE_SCHEMA={"type":"object","additionalProperties":False,"properties":{"roles":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"file":{"type":"string"},"role":{"type":"string","enum":["APOLICE","BOLETO","OUTRO"]}},"required":["file","role"]}}},"required":["roles"]}

SYSTEM_PROMPT="""Você é um sistema de extração documental especializado em apólices de seguro relacionadas a contratos públicos e licitações brasileiras. Receberá (1) um PDF contendo as primeiras páginas da apólice e (2) o PDF completo do boleto. Extraia informações literalmente presentes, sem conhecimento externo e sem usar nomes de arquivos como prova.

NUNCA invente informações, complete números parcialmente visíveis, faça OCR imaginário, deduza processo SEI, SUSEP, linha digitável, datas ou valores, nem transforme algo incerto em certo. Se ausente/ilegível/inseguro, valor=null, fonte=NAO_IDENTIFICADO, confiança baixa e inclua o campo em campos_com_duvida. A confiança por campo deve refletir legibilidade e evidência, não mera plausibilidade. Indique fonte APOLICE, BOLETO, AMBOS ou NAO_IDENTIFICADO. Se os documentos conflitam, use a fonte prioritária abaixo, mas registre o conflito em campos_com_duvida e observacoes.

PRIORIDADE DOCUMENTAL: dados do seguro, empresa, órgão, concorrência, SEI, objeto, vigência e SUSEP: APOLICE. Linha digitável e dados de cobrança: BOLETO. Valor de prêmio: priorize apólice e registre divergência com boleto. Não infira empresa por contexto externo. empresa_normalizada deve ser THI ou PHAS somente se sustentada pelos documentos; caso contrário null. Retorne o nome jurídico observado em empresa e a classificação em empresa_normalizada. Datas ISO YYYY-MM-DD; prêmio como número decimal JSON, nunca texto monetário. Linha digitável deve ser transcrição exata e literal: não valide/corrija matematicamente nem complete dígitos; se qualquer trecho essencial estiver ilegível, null e dúvida.

Para concorrência/licitação/edital, identifique semanticamente o número no documento e preserve forma original; numero_concorrencia_normalizado deve substituir separadores por hífens sem inventar/alterar números. órgão normalizado deve ser uma forma curta fiel ao nome. nome_pasta/nome_apolice/nome_boleto são sugestões apenas: o sistema Python gerará os nomes finais. confianca_geral deve resumir a qualidade global; cada campo crítico inclui valor, fonte e confiança.
"""
def role_prompt(names:list[str])->str:
    return "Classifique pelo conteúdo cada PDF anexado como APOLICE, BOLETO ou OUTRO. Não confie só no nome. Os nomes exatos dos arquivos anexados são: "+"; ".join(names)+". Devolva esses nomes sem alterações e não atribua papel a arquivo ausente. Deve haver exatamente uma apólice e um boleto para continuar."
def policy_prompt(company_names:list[str]|None=None)->str:
    references=""
    if company_names:references="\nNomes jurídicos de referência configurados pelo usuário: "+"; ".join(company_names)+". Use apenas para reconhecer a denominação impressa nos documentos, nunca como prova independente nem para inferir empresa ausente."
    return SYSTEM_PROMPT+references+"\nRetorne exclusivamente JSON compatível com o schema estrito. Cada campo em FIELD_NAMES deve ser objeto {valor, fonte, confianca}; mantenha o valor no tipo adequado ao schema. Para empresa_normalizada, use THI ou PHAS. Para as datas, string ISO no valor. Liste dúvidas pelo nome exato do campo."
