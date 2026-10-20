"""Bounded JSON transport shared by user-confirmed assistant workflows."""
import json
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from deskcare.ai.cloud_task_assistant import _RejectRedirects
from deskcare.ai.optional_local_llm import _json_content
from deskcare.services.reminder_advice import AdviceError


def request_model_json(provider, endpoint, body, *, credentials=None, request_fn=None):
    headers = {"Content-Type": "application/json"}
    try:
        if provider == "cloud":
            key = credentials.load() if credentials else None
            if not key:
                raise AdviceError("尚未保存服务密钥，请在 AI 服务中配置。")
            headers["Authorization"] = f"Bearer {key}"
        opener = request_fn or (build_opener(ProxyHandler({}), _RejectRedirects()).open
                                if provider == "local" else build_opener(_RejectRedirects()).open)
        response = opener(Request(endpoint, data=body, headers=headers, method="POST"), timeout=15)
        try:
            raw = response.read(65537)
        finally:
            response.close()
        if len(raw) > 65536:
            raise AdviceError("AI 回复过长，没有执行任何操作。")
        envelope = json.loads(raw)
        if provider == "local":
            content = envelope["message"]["content"]
        else:
            choice = envelope["choices"][0]
            if choice.get("finish_reason") == "length":
                raise AdviceError("AI 回复不完整，没有执行任何操作。")
            content = choice["message"]["content"]
        return _json_content(content)
    except AdviceError:
        raise
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise AdviceError(f"AI 服务返回 HTTP {code}，请核对地址、模型及密钥；没有执行操作。") from None
    except Exception:
        raise AdviceError("AI 暂时不可用、请求超时或回复无效；原有设置和任务不变。") from None
