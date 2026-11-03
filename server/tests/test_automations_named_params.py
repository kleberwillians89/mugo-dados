"""Templates aprovados com variáveis nomeadas ({{nome}}): a Meta exige parameter_name e os mesmos nomes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest

from services import automations as au
from services import google_calendar as gc

REUNIAO = {"name": "mugo_reuniao_interna", "language": "pt_BR", "status": "APPROVED", "category": "UTILITY", "header_format": None,
           "button_url_dynamic": False,
           "components": [{"type": "BODY", "text": "Olá, {{nome}}! Você tem uma reunião agendada no Mugô Dados. Reunião: {{reuniao}} "
                                                   "Data: {{data}} Horário: {{horario}} Participantes: {{participantes}} Equipe Mugô"}]}
MAP = ["nome", "reuniao", "data", "horario", "participantes"]


class NamedTemplateTests(unittest.TestCase):
    def test_parse_counts_named_variables(self):
        parsed = au.parse_template({**REUNIAO, "status": "approved"})
        self.assertEqual(parsed["body_param_count"], 5)
        self.assertEqual(au.body_names(parsed), MAP)

    def test_components_carry_parameter_name(self):
        comps = au.build_components(REUNIAO, ["Ana", "Alinhamento", "04/11", "15:00", "Ana e Kleber"], None, MAP)
        self.assertEqual([p["parameter_name"] for p in comps[0]["parameters"]], MAP)
        self.assertEqual(comps[0]["parameters"][3]["text"], "15:00")

    def test_wrong_names_are_blocked_before_meta(self):
        self.assertFalse(au.variables_match(REUNIAO, ["nome", "titulo", "data", "hora"]))
        with self.assertRaises(au.AutomationError):
            au.build_components(REUNIAO, ["a", "b", "c", "d"], None, ["nome", "titulo", "data", "hora"])

    def test_preview_fills_names(self):
        text = au.render_text(REUNIAO, ["Ana", "Alinhamento", "04/11", "15:00", "Ana e Kleber"], MAP)
        self.assertIn("Reunião: Alinhamento", text)
        self.assertNotIn("{{", text)

    def test_positional_templates_unchanged(self):
        tpl = {"body_param_count": 2, "components": [{"type": "BODY", "text": "Oi {{1}}, {{2}}"}]}
        comps = au.build_components(tpl, ["a", "b"], None, ["x", "y"])
        self.assertNotIn("parameter_name", comps[0]["parameters"][0])


class ParticipantsTests(unittest.TestCase):
    def test_first_names_from_directory_never_email(self):
        attending = [{"email": "k@x.com", "name": None}, {"email": "ana@cli.com", "name": "Ana Paula"},
                     {"email": "sala@x.com", "resource": True}, {"email": "semnome@x.com", "name": None}]
        team = {"k@x.com": {"name": "Kleber Willians"}}
        self.assertEqual(gc._participants(attending, {}, team), "Kleber e Ana")


if __name__ == "__main__":
    unittest.main()
