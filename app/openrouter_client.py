"""Cliente OpenRouter com anexos PDF, retries limitados e mensagens seguras."""
import base64, json, time
from pathlib import Path
import httpx
from .prompt import POLICY_SCHEMA, ROLE_SCHEMA, role_prompt, policy_prompt

class OpenRouterError(RuntimeError): pass

class OpenRouterClient:
    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 120, company_names: list[str] | None = None):
        if not api_key: raise ValueError("OPENROUTER_API_KEY não configurada")
        self.api_key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout
        self.company_names=company_names or []

    def _request(self, prompt: str, files: list[Path], schema: dict) -> dict:
        content=[{"type":"text","text":prompt}]
        for path in files:
            encoded=base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type":"file","file":{"filename":path.name,"file_data":"data:application/pdf;base64,"+encoded}})
        body={"model":self.model,"temperature":0,"messages":[{"role":"user","content":content}],"response_format":{"type":"json_schema","json_schema":{"name":"result","strict":True,"schema":schema}}}
        last=None
        for attempt in range(3):
            try:
                response=httpx.post(self.base_url+"/chat/completions",headers={"Authorization":"Bearer "+self.api_key,"Content-Type":"application/json","HTTP-Referer":"https://github.com/beasevla-hub/app_apolices","X-Title":"Robo local de apolices THI PHAS"},json=body,timeout=self.timeout)
                if response.status_code in (400,401,402): raise OpenRouterError(f"OpenRouter HTTP {response.status_code}: {response.text[:500]}")
                if response.status_code==429 or response.status_code>=500:
                    response.raise_for_status()
                response.raise_for_status()
                try: payload=response.json()
                except json.JSONDecodeError as exc: raise OpenRouterError("OpenRouter retornou corpo HTTP inválido") from exc
                choices=payload.get("choices",[]) if isinstance(payload,dict) else []
                text=choices[0].get("message",{}).get("content") if choices else None
                if isinstance(text,list): text="".join(part.get("text","") for part in text)
                if not text: raise OpenRouterError("Resposta vazia do OpenRouter")
                try: return json.loads(text)
                except json.JSONDecodeError as exc: raise OpenRouterError("OpenRouter retornou JSON inválido") from exc
            except (httpx.TimeoutException,httpx.TransportError,httpx.HTTPStatusError,OpenRouterError) as exc:
                last=exc
                if isinstance(exc,OpenRouterError) and ("HTTP 400" in str(exc) or "HTTP 401" in str(exc) or "HTTP 402" in str(exc)): break
                if attempt<2: time.sleep(2**attempt)
        raise OpenRouterError(f"Falha no OpenRouter após tentativas limitadas: {last}") from last

    def classify(self, files: list[Path], names: list[str]) -> dict:
        return self._request(role_prompt(names), files, ROLE_SCHEMA)

    def analyze(self, policy: Path, bill: Path, expected_lot: str | None = None) -> dict:
        return self._request("Anexo 1 = páginas iniciais da APÓLICE; anexo 2 = BOLETO completo do mesmo grupo.\n"+policy_prompt(self.company_names,expected_lot), [policy,bill], POLICY_SCHEMA)
