"""Read-only PDF export of immutable, tenant-scoped analysis snapshots."""
from io import BytesIO
from math import isfinite
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import json
from xml.sax.saxutils import escape
from .ig_supabase import sb_select
from .technical_text import humanize_analysis_row


async def load_report(client_id, analysis_id):
    rows = await sb_select('ai_analyses', filters={'client_id': f'eq.{client_id}', 'id': f'eq.{analysis_id}', 'status': 'eq.completed'}, limit=1)
    if not rows or rows[0].get('client_id') != client_id or rows[0].get('id') != analysis_id or rows[0].get('status') != 'completed' or not rows[0].get('analysis'):
        raise RuntimeError('REPORT_NOT_FOUND')
    humanize_analysis_row(rows[0])  # análises antigas podem ter IDs técnicos no texto
    frozen = (rows[0].get('data_quality') or {}).get('report_context') or {}
    if frozen.get('client_name') and frozen['client_name'] != 'Empresa ativa':
        return rows[0], frozen['client_name']
    clients = await sb_select('clients', select='id,name,trade_name', filters={'id': f'eq.{client_id}'}, limit=1)
    client = next((row for row in clients if row.get('id') == client_id), {})
    return rows[0], client.get('trade_name') or client.get('name') or client_id


def render_report(record, company, kind):
    start, end = date.fromisoformat(record['period_start']), date.fromisoformat(record['period_end'])
    if kind not in {'weekly', 'monthly'} or (kind == 'weekly' and (start.weekday() != 0 or end != start + timedelta(days=6))) or (kind == 'monthly' and (start.day != 1 or end != start.replace(day=calendar.monthrange(start.year,start.month)[1]))):
        raise RuntimeError('REPORT_PERIOD_INVALID')
    if len(json.dumps(record, ensure_ascii=False)) > 200000:
        raise RuntimeError('REPORT_SIZE_LIMIT')
    # Lazy import keeps startup cost out of the API and performs no network IO.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
    from reportlab.graphics.shapes import Drawing, Rect, String

    metrics = record.get('metrics_snapshot') or []
    insights = (record['analysis'].get('insights') or [])
    actions = (record['analysis'].get('actions') or [])
    if len(metrics) > 100 or len(insights) > 30 or len(actions) > 30:
        raise RuntimeError('REPORT_SIZE_LIMIT')
    by_id = {m['id']: m for m in metrics}
    labels = {s['id']: s.get('label') or s['id'] for s in record.get('sources') or []}
    states = {'confirmed':'confirmado','partial':'parcial','available':'disponível','unavailable':'indisponível','disconnected':'desconectado','no_data':'sem dados','error':'erro', 'now':'fazer agora','week':'nesta semana','monitor':'acompanhar','investigate':'investigar','opportunity':'oportunidade','risk':'risco','attention':'atenção','anomaly':'anomalia','positive':'fato observado','data_quality':'qualidade dos dados','high':'alta','medium':'média','low':'baixa'}
    def state_label(value): return states.get(value, value or 'não confirmado')
    def origin(value): return labels.get(value, value)
    def display_date(value):
        if not value: return 'não confirmada'
        try:
            if len(value) == 10: return date.fromisoformat(value).strftime('%d/%m/%Y')
            parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %Hh%M')
        except (TypeError, ValueError): return 'não confirmada'
    def supported(mid):
        m = by_id.get(mid, {})
        return m.get('status') in {'confirmed', 'partial'} and isinstance(m.get('value'), (int, float)) and isfinite(m['value'])
    def numeric(m):
        value = m.get('value')
        if not isinstance(value, (int, float)) or not isfinite(value):
            return 'Indisponível'
        number = f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
        return ('R$ ' + number if m.get('format') == 'currency' else number + ('%' if m.get('format') == 'percent' else 'x' if m.get('format') == 'decimal' else ''))
    def comparable(m):
        return m.get('status') == 'confirmed' and all(isinstance(m.get(k), (int, float)) and isfinite(m[k]) for k in ['value', 'previous_value', 'variation_percent'])
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='MugoTitle', fontName='Helvetica', fontSize=32, leading=38, textColor=colors.HexColor('#153f35'), spaceAfter=20))
    styles['BodyText'].leading = 15
    styles['BodyText'].spaceAfter = 9
    styles['Heading2'].textColor = colors.HexColor('#153f35')
    story = []
    def p(value, style='BodyText'):
        text = str(value or '')
        if len(text) > 12000:
            raise RuntimeError('REPORT_SIZE_LIMIT')
        return Paragraph(escape(text).replace('\n', '<br/>'), styles[style])
    def section(title):
        story.append(p(title, 'Heading2'))
    period = f"{display_date(record['period_start'])} a {display_date(record['period_end'])}"
    story += [Spacer(1, 26*mm), p('Mugoverso', 'MugoTitle'), p('INTELIGÊNCIA & RELATÓRIOS', 'Heading2'),
              p('Relatório semanal' if kind == 'weekly' else 'Relatório mensal', 'Heading1'), p(company, 'MugoTitle'), p(period),
              p('Análise estratégica de marketing e negócios. Evidências, hipóteses e decisões.'),
              p(f"Versão: {record['id']}\nGerado em: {display_date(record.get('completed_at') or record.get('created_at'))}\nDatas de referência: America/Sao_Paulo."), PageBreak()]
    section('Resumo executivo')
    executive = record['analysis'].get('executive') or {}
    story.append(p(executive.get('overall')))
    for label, key in [('Principal mudança', 'main_change'), ('Oportunidade', 'opportunity'), ('Atenção', 'attention')]:
        if executive.get(key): story += [p(label, 'Heading3'), p(executive[key])]
    section('Visão geral dos indicadores')
    rows = [[p('Indicador'), p('Atual / fonte'), p('Anterior / variação')]]
    for m in metrics:
        variation = f"{m['variation_percent']:+.2f}%".replace('.', ',') if comparable(m) else ''
        comparison = f"{numeric({**m, 'value': m['previous_value']})} / {variation}" if comparable(m) else 'Sem comparação validada'
        rows.append([p(m['label']), p(f"{numeric(m)}\n{origin(m.get('source'))} / {state_label(m.get('status'))}"), p(comparison)])
    if len(rows) > 1:
        table = Table(rows, colWidths=[58*mm, 62*mm, 54*mm], repeatRows=1, splitInRow=1, hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2ec')), ('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#d8ded8')), ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story.append(table)
    else: story.append(p('Não há indicadores disponíveis neste snapshot.'))
    section('Comparativos entre períodos equivalentes')
    story.append(p(f'Base anterior: {display_date((start-timedelta(days=(end-start).days+1)).isoformat())} a {display_date((start-timedelta(days=1)).isoformat())}. Janela de igual duração; não necessariamente o mês calendário anterior completo.'))
    chart_metrics = [m for m in metrics if comparable(m) and m['value'] >= 0 and m['previous_value'] >= 0][:8]
    for m in chart_metrics:
        story.append(p(f"{m['label']} - {origin(m.get('source'))}", 'Heading3'))
        drawing = Drawing(480, 70)
        scale = max(m['value'], m['previous_value'], 1)
        for i, (label, value, color) in enumerate([('Anterior', m['previous_value'], '#a8b8ab'), ('Atual', m['value'], '#153f35')]):
            y = 42-i*28
            drawing.add(String(0,y,label,fontSize=9))
            drawing.add(Rect(65,y-3,280*value/scale,13,fillColor=colors.HexColor(color),strokeColor=None))
            drawing.add(String(355,y,numeric({**m,'value':value}),fontSize=9))
        story.append(drawing)
    if not chart_metrics: story.append(p('Não há comparação temporal validada disponível. Nenhuma tendência foi estimada.'))
    section('Desempenho por canal')
    for source in dict.fromkeys(m.get('source','') for m in metrics):
        story.append(p(origin(source), 'Heading3'))
        for m in metrics:
            if m.get('source') == source: story.append(p(f"{m['label']}: {numeric(m)} ({state_label(m.get('status'))})."))
    section('Diagnóstico estratégico, oportunidades e riscos')
    for item in insights:
        ids = item.get('metric_ids') or []
        if not ids or not all(supported(mid) for mid in ids): continue
        story += [p(item.get('title'), 'Heading3'), p(f"{state_label(item.get('category'))} / confiança {state_label(item.get('confidence'))}."),
                  p('Evidência: ' + '; '.join(f"{by_id[mid]['label']}: {numeric(by_id[mid])} ({origin(by_id[mid]['source'])})" for mid in ids)),
                  p(item.get('interpretation')), p('Ação recomendada: ' + str(item.get('action') or 'Medição adicional necessária.'))]
    story.append(p('Hipóteses explicativas não comprovam causalidade. Etapas do funil, metas e tendências só podem ser avaliadas quando constam das evidências validadas; lacunas exigem instrumentação adicional.'))
    for crossing in ((record.get('data_quality') or {}).get('report_context') or {}).get('crossings') or []:
        funnel = crossing.get('funnel') or {}
        if crossing.get('status') != 'available' or funnel.get('status') != 'confirmed': continue
        story.append(p(crossing.get('label'), 'Heading3'))
        for key, label in [('sessions','Sessões'),('view_item','Visualizações de produto'),('add_to_cart','Carrinhos'),('begin_checkout','Checkouts'),('purchase','Compras')]:
            value = funnel.get(key)
            if isinstance(value, (int,float)) and isfinite(value): story.append(p(f'{label}: {value} (eventos GA4, sem atribuir receita da loja).'))
    section('Recomendações priorizadas e plano de ação')
    priorities = ['now','week','monitor','investigate']
    actions = sorted([a for a in actions if supported(a.get('metric_id'))], key=lambda a: priorities.index(a['priority']) if a.get('priority') in priorities else 4)[:3]
    for item in actions:
        m = by_id[item['metric_id']]
        story += [p(item.get('recommendation'), 'Heading3'), p(item.get('justification')),
                  p(f"Prioridade: {state_label(item.get('priority'))}. Indicador de acompanhamento: {m['label']} ({origin(m['source'])}). Evidência: {numeric(m)} no período {period}."),
                  p('Impacto esperado (hipótese): ' + str(item.get('impact_expected') or 'A medir.'))]
    if not actions: story.append(p('Não há ações sustentadas suficientes. Priorize completar a medição das fontes ausentes.'))
    section('Fontes, atualização e observações metodológicas')
    story.append(p((record.get('data_quality') or {}).get('message')))
    for source in record.get('sources') or []:
        story.append(p(f"{source.get('label',source.get('id'))}: {state_label(source.get('status'))}. Dias cobertos: {source.get('covered_days')}. Atualização: {display_date(source.get('last_sync_at'))}."))
    story.append(p('Snapshot histórico da análise identificada na capa, sem recalcular números com dados atuais. Receita atribuída por plataforma não é receita deduplicada. Fontes parciais não representam zero. Comparações usam somente valores anteriores e variações fornecidos pelo pipeline canônico.'))
    output = BytesIO()
    def footer(canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica',8); canvas.setFillColor(colors.HexColor('#52625a'))
        canvas.drawString(18*mm,12*mm,'Mugoverso | '+record['period_start']+' - '+record['period_end'])
        canvas.drawRightString(A4[0]-18*mm,12*mm,f'Página {doc.page}'); canvas.restoreState()
    SimpleDocTemplate(output,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=22*mm,title=f'Mugô - {company} - {period}',author='Mugoverso').build(story,onFirstPage=footer,onLaterPages=footer)
    data = output.getvalue()
    if len(data) > 2_000_000: raise RuntimeError('REPORT_SIZE_LIMIT')
    return data
