import copy
from io import BytesIO
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI, HTTPException
from pypdf import PdfReader
from services import intelligence_reports as service
from routes import intelligence as routes

ID = '00000000-0000-0000-0000-000000000009'


def record():
    return {'id': ID, 'client_id': 'tenant-a', 'status': 'completed', 'period_start': '2026-09-01', 'period_end': '2026-09-30',
        'created_at': '2026-10-01T09:00:00Z', 'completed_at': '2026-10-01T09:00:00Z',
        'metrics_snapshot': [{'id': 'spend', 'label': 'Investimento', 'value': 100, 'previous_value': 80, 'variation_percent': 25,
                             'status': 'confirmed', 'source': 'meta', 'format': 'currency'}],
        'sources': [{'id':'meta','label':'Meta Ads','status':'partial','covered_days':20,'last_sync_at':'2026-10-01'}],
        'data_quality': {'status': 'partial', 'message': 'Cobertura parcial.'},
        'analysis': {'executive': {'overall': 'Investimento observado; receita não comprovada.', 'main_change': 'Mudança observada.'},
            'insights': [{'title': 'Revisar distribuição', 'metric_ids': ['spend'], 'interpretation': 'Hipótese a investigar.', 'category': 'opportunity', 'confidence': 'medium', 'action': 'Revisar distribuição.'}],
            'actions': [{'metric_id': 'spend', 'recommendation': 'Revisar distribuição.', 'justification': 'Investimento observado.', 'priority': 'now', 'impact_expected': 'A medir.'}]}}


class PdfTests(unittest.TestCase):
    def test_valid_a4_multipage_pdf_contains_only_snapshot_values_and_version(self):
        data = service.render_report(record(), 'Empresa sintética', 'monthly')
        self.assertTrue(data.startswith(b'%PDF-'))
        pdf = PdfReader(BytesIO(data)); self.assertGreaterEqual(len(pdf.pages), 3)
        for page in pdf.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 595.28, places=1)
            self.assertAlmostEqual(float(page.mediabox.height), 841.89, places=1)
        text = '\n'.join(page.extract_text() for page in pdf.pages)
        for expected in ['Empresa sintética', '100,00', '80,00', '25,00%', ID, 'Meta Ads', 'Cobertura parcial', 'Indicador de acompanhamento']:
            self.assertIn(expected, text)
        self.assertNotIn('999999', text)

    def test_weekly_period_and_mismatched_format(self):
        row = record(); row.update(period_start='2026-09-07', period_end='2026-09-13')
        self.assertTrue(service.render_report(row, 'Empresa', 'weekly').startswith(b'%PDF-'))
        for kind in ['monthly', 'invalid']:
            with self.assertRaisesRegex(RuntimeError, 'REPORT_PERIOD_INVALID'): service.render_report(row, 'Empresa', kind)

    def test_partial_metrics_do_not_claim_comparison_and_unknown_recommendation_is_omitted(self):
        row = record(); row['metrics_snapshot'][0]['status'] = 'partial'
        row['analysis']['actions'][0].update(metric_id='foreign', recommendation='FORBIDDEN')
        text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(service.render_report(row, 'Empresa', 'monthly'))).pages)
        self.assertNotIn('FORBIDDEN', text); self.assertNotIn('25,00%', text)
        self.assertIn('Sem comparação validada', text)

    def test_extensive_report_paginates_and_escapes_markup(self):
        row = record()
        row['metrics_snapshot'] = [{**row['metrics_snapshot'][0], 'id':f'm{i}', 'label':f'Indicador {i} <script>'} for i in range(75)]
        row['analysis']['insights'] = []; row['analysis']['actions'] = []
        pdf = PdfReader(BytesIO(service.render_report(row, 'Empresa & parceiros', 'monthly')))
        self.assertGreater(len(pdf.pages), 5)
        text = '\n'.join(p.extract_text() for p in pdf.pages)
        self.assertIn('Indicador 74 <script>', text)
        self.assertIn('Empresa & parceiros', text)

    def test_snapshot_is_not_mutated_and_budget_is_bounded(self):
        row = record(); before = copy.deepcopy(row)
        service.render_report(row, 'Empresa', 'monthly'); self.assertEqual(row, before)
        row['metrics_snapshot'] *= 101
        with self.assertRaisesRegex(RuntimeError, 'REPORT_SIZE_LIMIT'): service.render_report(row, 'Empresa', 'monthly')


class ReportAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_query_is_scoped_and_foreign_record_is_denied(self):
        for rows in [[], [{**record(), 'client_id':'tenant-b'}], [{**record(), 'id':'foreign'}], [{**record(), 'status':'failed'}]]:
            with patch.object(service,'sb_select',AsyncMock(return_value=rows)) as select:
                with self.assertRaisesRegex(RuntimeError,'REPORT_NOT_FOUND'): await service.load_report('tenant-a',ID)
                self.assertEqual(select.await_args.kwargs['filters'], {'client_id':'eq.tenant-a','id':f'eq.{ID}','status':'eq.completed'})
                self.assertEqual(select.await_count,1)

    async def test_frozen_company_and_snapshot_need_no_current_metrics(self):
        row = record(); row['data_quality']['report_context']={'client_name':'Nome versionado'}
        with patch.object(service,'sb_select',AsyncMock(return_value=[row])) as select:
            loaded, company = await service.load_report('tenant-a',ID)
        self.assertEqual(company,'Nome versionado'); self.assertEqual(loaded,row); self.assertEqual(select.await_count,1)

    async def test_permission_denied_before_pdf_or_database_and_safe_read_download(self):
        app=FastAPI();app.include_router(routes.router)
        with patch.object(routes,'_context',AsyncMock(side_effect=HTTPException(403))), patch.object(service,'load_report',AsyncMock()) as load:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
                response=await client.get(f'/api/intelligence/reports/{ID}/pdf')
            self.assertEqual(response.status_code,403);load.assert_not_awaited()
        with patch.object(routes,'_context',AsyncMock(return_value=('tenant-a','user-a'))),patch.object(service,'load_report',AsyncMock(return_value=(record(),'Empresa'))) as load:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
                response=await client.get(f'/api/intelligence/reports/{ID}/pdf?kind=monthly')
                invalid=await client.get('/api/intelligence/reports/not-a-uuid/pdf')
            self.assertEqual(response.status_code,200);self.assertEqual(invalid.status_code,422)
            self.assertEqual(response.headers['content-type'],'application/pdf')
            self.assertEqual(response.headers['cache-control'],'private, no-store')
            self.assertIn('attachment;',response.headers['content-disposition'])
            self.assertTrue(response.content.startswith(b'%PDF-'));load.assert_awaited_once_with('tenant-a',ID)
