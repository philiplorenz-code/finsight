"""Regression: Decimal must start at the XML numeric lexeme, not a float."""
import io
from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook


@pytest.mark.parametrize("lexeme", ["123456789012345.67", "9999999.12345678", "-123456789012345.67"])
def test_exact_numeric_xml_money(lexeme):
    from app.importer import parse_workbook

    workbook = Workbook()
    workbook.active.append(["Buchungstag", "Referenzkonto", "Betrag", "Kontostand", "Waehrung", "Buchungs-ID"])
    workbook.active.append([datetime(2025, 1, 1), "TEST-ACCOUNT", 1, 1, "EUR", "TEST-BOOKING"])
    original = io.BytesIO()
    workbook.save(original)
    patched = io.BytesIO()
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(original) as source, ZipFile(patched, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(data)
                for coordinate in ("C2", "D2"):
                    root.find(f'.//s:c[@r="{coordinate}"]/s:v', namespace).text = lexeme
                data = ElementTree.tostring(root)
            target.writestr(item.filename, data)
    rows, *_ = parse_workbook(patched.getvalue())
    assert rows[0]["amount"] == Decimal(lexeme)
    assert rows[0]["balance"] == Decimal(lexeme)
    assert str(rows[0]["source"]["columns"]["Betrag"]) == lexeme
