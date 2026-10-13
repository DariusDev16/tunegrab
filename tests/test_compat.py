"""Guarda de compatibilidade de sintaxe.

Regressao real: o projeto anunciava suporte a Python 3.9+, mas usava escapes
ANSI dentro da parte de expressao de f-strings (ex.: bold('\\x1b[31mERRO')).
Isso so became SyntaxError no Python 3.12 (PEP 701), entao nunca apareceu em
desenvolvimento e o CI quebrou no primeiro push. Este teste pega a reincidencia
antes do push, sem precisar de um 3.9 instalado: ast.parse aceita
feature_version e aplica as regras de sintaxe daquela versao.
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tunegrab.py")

MIN_PYTHON = (3, 9)
SUPPORTED = [(3, 9), (3, 10), (3, 11), (3, 12), (3, 13)]


class TestSyntaxCompatibility(unittest.TestCase):
    def setUp(self):
        with open(SOURCE, encoding="utf-8") as fh:
            self.source = fh.read()

    def test_parses_on_every_supported_python(self):
        for version in SUPPORTED:
            with self.subTest(python=f"{version[0]}.{version[1]}"):
                ast.parse(self.source, feature_version=version)

    def test_no_backslash_inside_fstring_expressions(self):
        """Regra removida so no 3.12 (PEP 701): nao voltar a usa-la."""
        tree = ast.parse(self.source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            for value in node.values:
                if not isinstance(value, ast.FormattedValue):
                    continue
                for sub in ast.walk(value.value):
                    if (isinstance(sub, ast.Constant)
                            and isinstance(sub.value, str)
                            and ("\x1b" in sub.value or "\n" in sub.value)):
                        offenders.append(value.value.lineno)
        self.assertEqual(offenders, [],
                         f"escape dentro de f-string nas linhas {offenders}")

    def test_declares_minimum_python_consistently(self):
        """O numero announced no README/argparse bate com o testado aqui."""
        if sys.version_info < MIN_PYTHON:
            self.skipTest("rodando em Python abaixo do minimo suportado")
        self.assertIn(f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)