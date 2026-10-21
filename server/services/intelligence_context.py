"""Bounded conversational intent, never a store of canonical facts.

Only server-owned periods and a closed vocabulary of topics survive retrieval.
No historical prose, campaign ID, metric value or assistant instruction is sent
back to the model. Entity resolution remains the responsibility of read tools.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
import re
import unicodedata

MAX_MESSAGES = 6
MAX_HISTORY_CHARS = 1800
TOPICS = {
    "campanhas": r"\bcampanh\w*\b",
    "vendas": r"\b(vendas|receita|pedidos|faturamento)\b",
    "marketing": r"\b(marketing|anuncios|publicidade|trafego)\b",
    "estratégia": r"\b(estrategia|posicionamento|objetivos)\b",
    "operação": r"\b(operacao|estoque|logistica)\b",
}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))


@dataclass
class Context:
    question: str
    period: dict
    limitations: list[str]
    clarification: str | None = None
    topics: list[str] = field(default_factory=list)


def recover_context(question, period, existing, *, client_id, user_id, conversation_id):
    result = Context(question, dict(period), [])
    text = normalized(question)
    result.topics = [topic for topic, pattern in TOPICS.items() if re.search(pattern, text)]
    followup = bool(re.search(r"\b(anterior|anteriores|isso|aconteceu|compare com|dois periodos)\b", text)) or bool(re.fullmatch(r'qual campanha[?!. ]*', text))
    if not followup:
        return result
    if not existing:
        result.clarification = 'Informe o tema e o período: não há contexto anterior nesta conversa.'
        return result
    conversation = existing.get('conversation', {})
    if any(conversation.get(key) != value for key, value in
           [('id', conversation_id), ('client_id', client_id), ('user_id', user_id)]):
        raise RuntimeError('CONVERSATION_NOT_FOUND')
    budget, previous = MAX_HISTORY_CHARS, None
    for message in reversed(existing.get('messages', [])[-MAX_MESSAGES:]):
        if any(message.get(key) != value for key, value in
               [('conversation_id', conversation_id), ('client_id', client_id), ('user_id', user_id)]):
            continue
        if message.get('role') != 'user':
            continue
        content = message.get('content')
        prior = content.get('question', '') if isinstance(content, dict) else ''
        if not isinstance(prior, str) or not prior or len(prior) > min(600, budget):
            continue
        budget -= len(prior)
        topics = [topic for topic, pattern in TOPICS.items() if re.search(pattern, normalized(prior))]
        saved_topics = content.get('context_topics', [])
        if not topics and isinstance(saved_topics, list):
            topics = [topic for topic in TOPICS if topic in saved_topics]
        try:
            start, end = date.fromisoformat(message['period_start']), date.fromisoformat(message['period_end'])
            if not 0 <= (end - start).days <= 366:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        # Nearest authorized user turn only; older contradictory turns are not merged.
        previous = (topics, start, end, content.get("context_request_period"))
        break
    ambiguous = 'Indique o tema ou a campanha e o período desejados; a referência da conversa não é inequívoca.'
    if previous is None:
        result.clarification = ambiguous
        return result
    topics, prior_start, prior_end, prior_request = previous
    explicit_topics = [topic for topic, pattern in TOPICS.items() if re.search(pattern, text)]
    topics = explicit_topics or topics
    if not topics or (len(topics) > 1 and not explicit_topics):
        result.clarification = ambiguous
        return result
    result.topics = topics
    # A changed UI period takes precedence over historical metadata.
    anchor = date.fromisoformat(period['start'])
    finish = date.fromisoformat(period['end'])
    if period == prior_request or period == {'start': prior_start.isoformat(), 'end': prior_end.isoformat()}:
        anchor, finish = prior_start, prior_end
    if 'anterior' in text and not re.search(r'\b(mes|semana|periodo) anterior\b', text):
        result.clarification = 'Informe se deseja o mês, a semana ou o período anterior.'
        return result
    try:
        if re.search(r'\bmes anterior\b', text):
            finish = anchor.replace(day=1) - timedelta(days=1)
            anchor = finish.replace(day=1)
        elif re.search(r'\bsemana anterior\b', text):
            finish = anchor - timedelta(days=anchor.weekday() + 1)
            anchor = finish - timedelta(days=6)
        elif re.search(r'\bperiodo anterior\b', text):
            days = (finish - anchor).days + 1
            anchor, finish = anchor - timedelta(days=days), anchor - timedelta(days=1)
    except OverflowError:
        result.clarification = 'Não é possível consultar um período anterior ao calendário suportado.'
        return result
    result.period = {'start': anchor.isoformat(), 'end': finish.isoformat()}
    if re.search(r'\b(compare|comparar|dois periodos)\b', text):
        result.clarification = ('A comparação exige evidências dos dois períodos. Nesta entrega, consulte cada período '
                                'separadamente; respostas antigas não comprovam variações.')
        return result
    result.question = (f'{question}\nTema anterior recuperado: {", ".join(topics)}. '
                       'Consulte novamente as fontes autorizadas no período informado. '
                       'Não presuma identidade de campanha, causalidade ou comparação a partir do histórico.')
    result.limitations.append('O histórico orienta apenas o tema; fatos e métricas exigem nova consulta às fontes autorizadas.')
    if 'aconteceu' in text or re.search(r'\bpor que\b', text):
        result.limitations.append('Os indicadores disponíveis não comprovam causalidade; explicações possíveis são hipóteses.')
    return result
