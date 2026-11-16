import unittest

from ifsc_feed import analyze

# Estrutura copiada do edital 05/2027 (tecnico integrado, por prova): deve ser ignorado.
INTEGRADO = """Edital ingresso nº 05
CURSOS TÉCNICOS
INTEGRADOS
EDITAL DE INGRESSO N° 05/DEING/2027/1
Câmpus Tubarão
Curso
Técnico Integrado em
Informática
Integral
(matutino)*
36 vagas totais
"""

# Edital misto hipotetico: um integrado e um subsequente no mesmo documento.
MISTO = """EDITAL DE INGRESSO N° 10/DEING/2027/1
cursos técnicos subsequentes e integrados
ANEXO I - QUADRO DE VAGAS
Câmpus Tubarão
Técnico Integrado em
Informática
Integral
36 vagas totais
Técnico Subsequente em
Desenvolvimento de Sistemas
Noturno
40 vagas totais
Câmpus Xanxerê
Técnico Subsequente em Informática
"""

# Edital FIC hipotetico no formato de tabela (Campus Curso Vagas Turno Carga).
FIC = """EDITAL DE INGRESSO N° 22/DEING/2027/1
Cursos de Qualificação Profissional (FIC)
Câmpus Curso Vagas Turno Carga horária Pré-requisitos
Criciúma Administração Financeira Básica 40 Noturno 60h
Criciúma Desenhista de Móveis 20 Noturno 80h 1º ano do ensino médio concluído, noções de informática e de AutoCAD
Criciúma Lógica de Programação com Python 30 Noturno 60h
Tubarão Introdução ao Desenvolvimento Web 25 Vespertino 80h
Xanxerê Controle de Versão de Software 20 Noturno 40h
4.2 A inscrição será feita pela internet. Quem não tiver acesso poderá usar os computadores do câmpus e Python.
"""

PESSOAL = """EDITAL N° 01/2027
Processo seletivo de tutores bolsistas para o curso de Informática
Câmpus Criciúma
Técnico em Informática
"""


class T(unittest.TestCase):
    def test_integrado_inteiro_ignorado(self):
        status, item = analyze("https://x/edital-05_2027_1_tecnico_integrado_prova", INTEGRADO)
        self.assertTrue(status.startswith("skip:integrado"))
        self.assertIsNone(item)

    def test_misto_ignora_integrado_mantem_subsequente(self):
        status, item = analyze("https://x/edital-10", MISTO)
        self.assertEqual(status, "match")
        d = item["description"]
        self.assertIn("Desenvolvimento de Sistemas", d)
        self.assertNotIn("Integrado em Informática", d)
        self.assertNotIn("Xanxerê", d)  # campus fora do alvo

    def test_fic_tabela(self):
        status, item = analyze("https://x/edital-22", FIC)
        self.assertEqual(status, "match")
        d = item["description"]
        self.assertIn("Python", d)
        self.assertIn("Desenvolvimento Web", d)
        self.assertNotIn("Desenhista", d)  # informatica so como pre-requisito
        self.assertNotIn("Financeira", d)
        self.assertNotIn("Controle de Versão", d)  # Xanxere nao interessa
        self.assertNotIn("computadores", d)  # clausula geral depois da tabela

    def test_selecao_de_pessoal_ignorada(self):
        status, _ = analyze("https://x/edital-01", PESSOAL)
        self.assertTrue(status.startswith("skip:"))


if __name__ == "__main__":
    unittest.main()
