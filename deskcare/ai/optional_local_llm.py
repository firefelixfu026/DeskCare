"""Optional localhost Ollama-compatible task candidate parser.

The module never contacts a non-loopback host. Its output remains an editable
ImportResult and is never persisted without the existing user confirmation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from deskcare.domain.types import TaskDraft
from deskcare.importers.loader import parse_selected_file
from deskcare.importers.base import (
    MAX_ESTIMATED_MINUTES,
    MAX_FILE_BYTES,
    MAX_TASKS_PER_IMPORT,
    ImportIssue,
    ImportResult,
    duplicate_issues,
    validate_title,
)


class LocalModelError(RuntimeError):
    """The optional local model could not provide a validated result."""


_LOCAL_OPENER = build_opener(ProxyHandler({}))


def _local_urlopen(request, timeout=None):
    """Open only through a direct connection, ignoring HTTP(S)_PROXY env vars."""

    return _LOCAL_OPENER.open(request, timeout=timeout)


def _loopback_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


def _json_content(value: str) -> object:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LocalModelError("本机模型返回的不是有效 JSON。") from exc


class LocalLLMClient:
    """Small Ollama-compatible client with injectable transport for tests."""

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:11434/api/chat",
        model: str = "llama3.2:3b",
        timeout_seconds: float = 12.0,
        request_fn: Callable[..., object] | None = None,
    ) -> None:
        if not _loopback_url(endpoint):
            raise ValueError("本地 AI 地址只允许 localhost、127.0.0.1 或 ::1。")
        if not isinstance(model, str) or not model.strip() or len(model.strip()) > 120:
            raise ValueError("本地 AI 模型名长度必须为 1-120 个字符。")
        self.endpoint = endpoint
        self.model = model.strip()
        self.timeout_seconds = float(timeout_seconds)
        self._request_fn = request_fn or _local_urlopen

    def parse(self, content: bytes, filename: str) -> ImportResult:
        if len(content) > min(MAX_FILE_BYTES, 100_000):
            raise LocalModelError("所选文本过大，未发送给本机模型；已保留规则解析。")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LocalModelError("所选文本不是有效 UTF-8；已保留规则解析。") from exc
        if not text.strip():
            raise LocalModelError("所选文本为空；已保留规则解析。")
        prompt = (
            "你是 DeskCare 的本地任务候选解析器。只处理用户主动选择的文本。"
            "输出严格 JSON，格式为 {\"tasks\":[{\"title\":string,"
            "\"due_at\":string|null,\"estimated_minutes\":integer|null,\"location\":string|null,\"source_row\":integer|null}]}。"
            "location 只逐字摘录本条活动明确的地点、教室、场馆或线上平台，没有就返回 null，不推测地址。"
            "source_row 为原文行号（从1起，含标题和空行），地点单独放 location，不混入任务标题，将在备注中供用户核对。"
            "按日期标题归属每条任务，区分括号里的 ddl、24:00 和活动起止时间，不遗漏原任务。"
            "同日同一时段的同一事项只输出一次，不同日期或场次分别保留；保留原任务名称，避免重复改写。"
            "已有任务由应用在本机核对，不要声称读过未提供的任务库。"
            "不要补充文本中不存在的日期或钟点；无法确定的时间返回 null。"
            "用户已写预计用时时保留；未写时根据任务给出保守的预计分钟数，作为用户可修改的建议。"
            "不要输出医学、情绪或任务完成判断。"
        )
        parsed = self.request_json(prompt, text)
        return self._to_import_result(parsed, text, filename)

    def request_json(self, system_prompt: str, user_text: str) -> object:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self._request_fn(request, timeout=self.timeout_seconds)
            raw = response.read()
            if hasattr(response, "close"):
                response.close()
            envelope = json.loads(raw.decode("utf-8"))
            model_text = envelope.get("message", {}).get("content") or envelope.get("response")
            if not isinstance(model_text, str):
                raise LocalModelError("本机模型响应缺少 JSON 内容。")
            return _json_content(model_text)
        except LocalModelError:
            raise
        except Exception as exc:
            raise LocalModelError("本机模型当前不可用；已保留规则解析。") from exc

    def list_models(self) -> tuple[str, ...]:
        """Return locally installed Ollama-compatible model names.

        The discovery request contains no DeskCare data and uses the same
        loopback-only, proxy-free transport as inference requests.
        """

        parsed = urlparse(self.endpoint)
        api_prefix, separator, _leaf = parsed.path.rpartition("/api/")
        tags_path = f"{api_prefix}/api/tags" if separator else "/api/tags"
        tags_endpoint = parsed._replace(path=tags_path, query="", fragment="").geturl()
        if not _loopback_url(tags_endpoint):
            raise LocalModelError("本机模型检测被安全策略拒绝。")
        request = Request(tags_endpoint, method="GET")
        try:
            response = self._request_fn(request, timeout=min(self.timeout_seconds, 4.0))
            raw = response.read()
            if hasattr(response, "close"):
                response.close()
            envelope = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise LocalModelError("无法连接本机模型服务；请确认 Ollama 已启动。") from exc
        raw_models = envelope.get("models") if isinstance(envelope, dict) else None
        if not isinstance(raw_models, list):
            raise LocalModelError("本机模型服务返回了无法识别的模型列表。")
        models: list[str] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if isinstance(name, str) and 1 <= len(name.strip()) <= 120:
                cleaned = name.strip()
                if cleaned not in models:
                    models.append(cleaned)
        return tuple(models)

    @staticmethod
    def json_text(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)

    @staticmethod
    def _to_import_result(parsed: object, source_text: str, filename: str) -> ImportResult:
        raw_tasks = parsed.get("tasks") if isinstance(parsed, dict) else parsed
        if not isinstance(raw_tasks, list):
            raise LocalModelError("本机模型输出缺少 tasks 数组；已保留规则解析。")
        drafts: list[TaskDraft] = []
        issues: list[ImportIssue] = []
        for index, item in enumerate(raw_tasks[:MAX_TASKS_PER_IMPORT], start=1):
            if not isinstance(item, dict) or not isinstance(item.get("title"), str):
                issues.append(ImportIssue("ai_invalid_task", "本机模型返回了无法编辑的任务候选。", index))
                continue
            title = " ".join(item["title"].split())
            title_issue = validate_title(title, index)
            if title_issue:
                issues.append(title_issue)
                continue
            uncertainty = ["model_suggestion"]
            due_at = None
            raw_due = item.get("due_at")
            if isinstance(raw_due, str) and raw_due.strip():
                try:
                    candidate_due = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
                except ValueError:
                    candidate_due = None
                # A model may preserve an explicit ISO timestamp, but it may
                # not silently turn "tomorrow" or "下午" into a date.
                explicit_dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", source_text))
                if candidate_due is not None and candidate_due.date().isoformat() in explicit_dates:
                    due_at = candidate_due
                else:
                    uncertainty.append("model_due_needs_confirmation")
            estimate = item.get("estimated_minutes")
            if estimate is not None:
                if isinstance(estimate, bool) or not isinstance(estimate, int) or not 1 <= estimate <= MAX_ESTIMATED_MINUTES:
                    estimate = None
                    uncertainty.append("model_estimate_needs_confirmation")
            from deskcare.importers.task_locations import checked_location, LOCATION_PREFIX
            location = checked_location(item.get("location"), item.get("source_row"), source_text)
            notes = ""
            source_row = index
            if location:
                value, source_row = location
                notes = LOCATION_PREFIX + value
                uncertainty.append("source_location")
            elif item.get("location") not in (None, ""):
                uncertainty.append("model_location_needs_confirmation")
            drafts.append(TaskDraft(title, due_at, estimate, source_row, tuple(uncertainty),
                                    notes=notes, estimate_is_suggestion=estimate is not None))
        from deskcare.importers.task_times import merge_source_times
        drafts = merge_source_times(drafts, source_text, filename) if drafts else drafts
        issues.extend(duplicate_issues(drafts))
        if not drafts:
            raise LocalModelError("本机模型没有返回可编辑候选；已保留规则解析。")
        return ImportResult(filename, tuple(drafts), tuple(issues))


class LocalAIService:
    """Consent gate plus rule fallback around the optional local client."""

    CONSENT_SCOPE = "local_ai"
    ENDPOINT_SETTING = "local_ai_endpoint"
    MODEL_SETTING = "local_ai_model"
    DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
    DEFAULT_MODEL = "llama3.2:3b"

    def __init__(self, repository, initially_enabled: bool = False, client: LocalLLMClient | None = None) -> None:
        self.repository = repository
        self._enabled = bool(initially_enabled)
        configured_endpoint = repository.get_setting(self.ENDPOINT_SETTING, self.DEFAULT_ENDPOINT)
        configured_model = repository.get_setting(self.MODEL_SETTING, self.DEFAULT_MODEL)
        if client is not None:
            self.client = client
        else:
            try:
                self.client = LocalLLMClient(
                    endpoint=configured_endpoint or self.DEFAULT_ENDPOINT,
                    model=configured_model or self.DEFAULT_MODEL,
                )
            except ValueError:
                self.client = LocalLLMClient()
        self.endpoint = getattr(self.client, "endpoint", self.DEFAULT_ENDPOINT)
        self.model = getattr(self.client, "model", self.DEFAULT_MODEL)
        from deskcare.ai.report_narrator import LocalReportNarrator

        self.report_narrator = LocalReportNarrator(self.client)
        self._listeners: list[Callable[[bool], None]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def subscribe(self, listener: Callable[[bool], None]) -> None:
        self._listeners.append(listener)
        listener(self._enabled)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self._enabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.repository.set_consent(self.CONSENT_SCOPE, self._enabled)
        self._notify()

    def configure(self, endpoint: str, model: str) -> None:
        candidate = LocalLLMClient(endpoint=endpoint.strip(), model=model.strip())
        self.client = candidate
        self.endpoint = candidate.endpoint
        self.model = candidate.model
        from deskcare.ai.report_narrator import LocalReportNarrator

        self.report_narrator = LocalReportNarrator(candidate)
        self.repository.set_setting(self.ENDPOINT_SETTING, self.endpoint)
        self.repository.set_setting(self.MODEL_SETTING, self.model)
        self._notify()

    def reset_configuration(self) -> None:
        self.client = LocalLLMClient()
        self.endpoint = self.client.endpoint
        self.model = self.client.model
        from deskcare.ai.report_narrator import LocalReportNarrator

        self.report_narrator = LocalReportNarrator(self.client)
        self.repository.delete_setting(self.ENDPOINT_SETTING)
        self.repository.delete_setting(self.MODEL_SETTING)
        self._notify()

    def parse_path(self, path) -> ImportResult:
        """Read only the path the user selected, and never persist its text."""

        rule_result = parse_selected_file(path)
        if not self._enabled:
            return rule_result
        try:
            content = Path(path).read_bytes()
            return self.client.parse(content, rule_result.source_name)
        except Exception as exc:
            warning = ImportIssue(
                "local_ai_fallback",
                "本机模型不可用或输出未通过校验，已保留规则解析结果；仍需人工确认。",
                fatal=False,
            )
            return ImportResult(rule_result.source_name, rule_result.drafts, rule_result.issues + (warning,))

    def probe_models(self, endpoint: str | None = None, model: str | None = None) -> tuple[str, ...]:
        """Inspect a user-requested loopback service without persisting edits."""

        if not self._enabled:
            raise LocalModelError("请先开启本地 AI 授权，再检测本机模型。")
        requested_endpoint = (self.endpoint if endpoint is None else endpoint).strip()
        requested_model = (self.model if model is None else model).strip()
        try:
            if requested_endpoint == self.endpoint and requested_model == self.model:
                client = self.client
            else:
                client = LocalLLMClient(
                    endpoint=requested_endpoint,
                    model=requested_model,
                    timeout_seconds=4.0,
                )
            models = client.list_models()
        except LocalModelError:
            raise
        except ValueError as exc:
            raise LocalModelError(str(exc)) from exc
        except Exception as exc:
            raise LocalModelError("本机模型检测失败；没有发送任务或报告数据。") from exc
        return tuple(models)

    def narrate_facts(self, facts, fallback_markdown: str) -> tuple[str, bool]:
        """Return model prose only when enabled and fully validated."""

        if not self._enabled:
            return fallback_markdown, False
        try:
            # Report AI is intentionally narrower than the full local report:
            # health check-ins and specific application names stay out of the
            # model payload even when the user separately enabled those logs.
            model_facts = dict(facts)
            model_facts["wellness"] = None
            model_facts["applications"] = None
            return self.report_narrator.narrate(model_facts), True
        except Exception:
            return fallback_markdown, False
