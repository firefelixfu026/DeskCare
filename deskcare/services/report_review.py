"""User-requested report review: allowlisted aggregates, no activity trail or health data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import secrets

from deskcare.ai.reminder_advisor import ReminderAIAdvisor
from deskcare.ai.structured_transport import request_model_json
from deskcare.services.reminder_advice import AdviceError


SYSTEM_PROMPT = (
    "你是 DeskCare 的日报/周报复盘助手。目标是帮助用户决定接下来先看什么、做什么，"
    "不是润色全文，也不是健康诊断。只提供了这一次报告的数量汇总，没有任务内容、应用名或健康记录。"
    "不能推断任务难度、拖延、疲劳、休息效果、工作效率或因果关系。"
    "活跃分钟是电脑操作估计，任务完成是用户标记，现在休息是意愿，不是实际休息证明。"
    "推迟、跳过和明确时机不合适必须分开；单次推迟不能证明频率不合理。"
    "data_is_demo 为 true 时都是虚构演示，不能当作真实用户行为。"
    "请根据 aggregates 的事实，从 candidates 中选择最值得优先回看的最多三个项目，"
    "再选择最多两个不同的下一步入口。优先关注未完成事项、反复推迟或明确不合适；"
    "数据不足时优先提示记录覆盖不足，而不是作趋势判断。不要机械重复所有数字。"
    "严格返回 JSON，仅有 focus 和 next_steps 两个字段。focus 是不重复的候选 id 数组，"
    "至少一项最多三项；next_steps 是不重复的 action 数组，最多两项，"
    "只能来自 focus 对应候选的非空 action。不增加说明或数字。程序按真实记录生成文字，"
    "操作只是跳转，不会修改任务或提醒。"
)


@dataclass(frozen=True)
class ReviewCard:
    key: str
    title: str
    detail: str
    action: str | None = None


@dataclass(frozen=True)
class ReviewSnapshot:
    payload: bytes
    cards: tuple[ReviewCard, ...]
    captured_at: datetime

    @property
    def data(self):
        return json.loads(self.payload)

    def human_preview(self):
        data = self.data
        use, tasks, reminders = data['usage'], data['tasks'], data['reminders']
        quality = data['coverage']
        return "\n".join([
            f"报告范围：{data['period']['start']} 至 {data['period']['end']}",
            f"快照时间：{self.captured_at:%m月%d日 %H:%M}",
            "来源：虚构演示数据" if data['data_is_demo'] else "来源：本机记录汇总",
            f"覆盖：{quality['days_with_activity']}/{quality['period_days']} 天有活动记录，约 {quality['covered_minutes_estimate']:g} 分钟",
            f"电脑活跃估计 {use['active_minutes_estimate']:g} 分钟；空闲 {use['idle_minutes_estimate']:g} 分钟；未知 {use['unknown_minutes_estimate']:g} 分钟",
            f"任务：共 {tasks['confirmed_total']} 项，标记完成 {tasks['completed_by_user']} 项，未完成 {tasks['open']} 项",
            f"提醒：显示 {reminders['shown']} 次；选择现在休息 {reminders['break_intent_confirmed']} 次；推迟 {reminders['snoozed']} 次；跳过 {reminders['skipped']} 次；明确不合适 {reminders['bad_timing']} 次",
            "以及 DeskCare 根据这些数字生成的回顾候选与跳转入口。",
            "", "不发送应用名、应用类别、小时轨迹、任务名称与备注、状态打卡、健康记录或检验单。",
            "AI 只帮助挑选复盘重点，不会代你完成任务、改变提醒，也不能据此判断健康或效率。",
        ])


@dataclass(frozen=True)
class ReviewRequest:
    token: str
    provider: str
    endpoint: str
    model: str
    snapshot: ReviewSnapshot
    body: bytes
    epoch: int


ACTION_LABELS = {'tasks': '查看待完成任务', 'reminders': '检查提醒安排', 'usage': '查看使用统计'}


class ReportReviewService:
    CONSENT_SCOPE = 'report_review_ai'

    def __init__(self, repository, local_ai=None, cloud_ai=None, *, request_fn=None, clock=None):
        self.repository = repository
        self.gateway = ReminderAIAdvisor(None, local_ai, cloud_ai)
        self.cloud_ai = cloud_ai
        self.request_fn = request_fn
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.epoch = 0
        self._pending = {}

    @property
    def enabled(self):
        return self.repository.get_consent(self.CONSENT_SCOPE) is True

    def invalidate(self):
        self.epoch += 1
        self._pending.clear()

    def set_enabled(self, enabled):
        self.repository.set_consent(self.CONSENT_SCOPE, bool(enabled))
        self.invalidate()

    def snapshot(self, facts):
        # Explicit allowlist: never copy the full report, even to a local model.
        def number(value, integer=False):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise AdviceError('报告中的数量无效，请刷新报告。')
            return int(value) if integer else round(value, 1)

        quality = facts['data_quality']
        data = {
            'period': {key: facts['period'][key] for key in ('type', 'start', 'end')},
            'data_is_demo': bool(quality.get('demo_data') or quality.get('demo_scenario')),
            'coverage': {key: number(quality[key], key != 'covered_minutes_estimate') for key in
                         ('covered_minutes_estimate', 'days_with_activity', 'period_days')},
            'usage': {key: number(facts['usage'][key]) for key in
                      ('active_minutes_estimate', 'idle_minutes_estimate', 'unknown_minutes_estimate')},
            'tasks': {key: number(facts['tasks'][key], True) for key in ('confirmed_total', 'completed_by_user', 'open')},
            'reminders': {key: number(facts['reminders'].get(key, 0), True) for key in
                          ('shown', 'break_intent_confirmed', 'snoozed', 'skipped', 'bad_timing')},
        }
        use, tasks, reminders = data['usage'], data['tasks'], data['reminders']
        cards = []
        if tasks['open']:
            cards.append(ReviewCard('open_tasks', f"还有 {tasks['open']} 项未标记完成",
                                    '先确认哪些还要继续、哪些需要改期。不必把清单上的所有事都挤进今天。', 'tasks'))
        if reminders['bad_timing']:
            cards.append(ReviewCard('bad_timing', f"有 {reminders['bad_timing']} 次明确反馈时机不合适",
                                    '可以回看提醒安排；是否调整间隔，由你决定。这不等于身体状态不好。', 'reminders'))
        if reminders['snoozed'] >= 3:
            cards.append(ReviewCard('repeated_snooze', f"提醒被推迟了 {reminders['snoozed']} 次",
                                    '若你也觉得经常被打断，可以检查间隔与情境设置。推迟不算作“时机不合适”。', 'reminders'))
        coverage = data['coverage']
        if coverage['days_with_activity'] < coverage['period_days'] or coverage['covered_minutes_estimate'] == 0:
            cards.append(ReviewCard('coverage', '这份记录没有覆盖整个时段',
                                    f"{coverage['period_days']} 天中有 {coverage['days_with_activity']} 天有活动记录。空白不等于没用电脑，暂不据此比较习惯。", 'usage'))
        cards.append(ReviewCard('usage', f"电脑活跃估计约 {use['active_minutes_estimate']:g} 分钟",
                                '想找适合留出休息空档的时段，可以回看使用统计。这不是实际工作量或健康评分。', 'usage'))
        if tasks['completed_by_user']:
            cards.append(ReviewCard('completed', f"你标记完成了 {tasks['completed_by_user']} 项任务",
                                    '这是你的完成记录，不是自动检测结果。可以把注意力留给还想推进的事项。', 'tasks'))
        if reminders['break_intent_confirmed']:
            cards.append(ReviewCard('break_intent', f"你有 {reminders['break_intent_confirmed']} 次选择现在休息",
                                    '记录的是当时的选择，不能据此确认实际休息了多久，也不能判断恢复效果。'))
        return ReviewSnapshot(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8'), tuple(cards), self.clock())

    def _body(self, provider, endpoint, model, snapshot):
        from urllib.parse import urlparse
        content = {'aggregates': snapshot.data, 'candidates': [
            {'id': card.key, 'title': card.title, 'detail': card.detail, 'action': card.action} for card in snapshot.cards]}
        body = {'model': model, 'stream': False, 'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps(content, ensure_ascii=False, sort_keys=True)}]}
        if provider == 'local':
            body.update(format='json', options={'num_predict': 512})
        else:
            body.update(response_format={'type': 'json_object'}, max_tokens=512)
            if urlparse(endpoint).hostname == 'api.deepseek.com':
                body['thinking'] = {'type': 'disabled'}
        return json.dumps(body, ensure_ascii=False, sort_keys=True).encode('utf-8')

    def prepare(self, snapshot, provider):
        endpoint, model = self.gateway._configuration(provider)
        self.invalidate()  # One outstanding, one-use preview; preparing never reads a key.
        request = ReviewRequest(secrets.token_hex(16), provider, endpoint, model, snapshot,
                                self._body(provider, endpoint, model, snapshot), self.epoch)
        self._pending[request.token] = request
        return request

    def is_current(self, request):
        age = (self.clock() - request.snapshot.captured_at).total_seconds()
        return (self.enabled and request.epoch == self.epoch and 0 <= age <= 300
                and self.gateway._configuration(request.provider) == (request.endpoint, request.model)
                and request.body == self._body(request.provider, request.endpoint, request.model, request.snapshot))

    def analyze(self, request, *, confirmed=False):
        if not confirmed:
            raise AdviceError('请先查看本次发送内容，再确认分析。')
        pending = self._pending.pop(request.token, None)
        if pending != request or not self.is_current(request):
            raise AdviceError('授权、服务或预览已改变，请重新预览。')
        raw = request_model_json(request.provider, request.endpoint, request.body,
                                 credentials=self.cloud_ai.credentials if request.provider == 'cloud' else None,
                                 request_fn=self.request_fn)
        result = self.validate(raw, request.snapshot)
        if not self.is_current(request):
            raise AdviceError('授权或服务已改变，已丢弃结果；已发送的内容无法撤回。')
        return result

    @staticmethod
    def validate(raw, snapshot):
        if not isinstance(raw, dict) or set(raw) != {'focus', 'next_steps'}:
            raise AdviceError('AI 回复不符合复盘格式，保留本机回顾。')
        focus, actions = raw['focus'], raw['next_steps']
        available = {card.key: card for card in snapshot.cards}
        if (not isinstance(focus, list) or not 1 <= len(focus) <= 3
                or not all(isinstance(key, str) and key in available for key in focus)
                or len(set(focus)) != len(focus)):
            raise AdviceError('AI 引用了这份报告中不存在的重点，保留本机回顾。')
        allowed_actions = {available[key].action for key in focus} - {None}
        if (not isinstance(actions, list) or len(actions) > 2
                or not all(isinstance(key, str) and key in allowed_actions for key in actions)
                or len(set(actions)) != len(actions)):
            raise AdviceError('AI 建议的入口无效，保留本机回顾。')
        return tuple(available[key] for key in focus), tuple(actions)
