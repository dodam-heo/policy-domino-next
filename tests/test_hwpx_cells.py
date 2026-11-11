"""Prove NEXT retains HWPX row/column coordinates for amount comparisons."""
import io
import zipfile
import unittest
from policy_domino.annexes import extract_hwpx_cells

class StructuredHWPXTests(unittest.TestCase):
    def make(self,amount):
        xml=f'''<root xmlns:h="urn:h">
        <h:tbl>
          <h:tr><h:tc><h:t>가구</h:t></h:tc><h:tc><h:t>선정기준</h:t></h:tc></h:tr>
          <h:tr><h:tc><h:t>4인</h:t></h:tc><h:tc><h:t>{amount}</h:t></h:tc></h:tr>
        </h:tbl></root>'''
        data=io.BytesIO()
        with zipfile.ZipFile(data,"w") as z:
            z.writestr("Contents/section0.xml",xml)
        return data.getvalue()
    def test_matching_cells_are_stable_across_editions(self):
        old=extract_hwpx_cells(self.make("6,494,738"))
        new=extract_hwpx_cells(self.make("6,929,885"))
        key="표 1 · 4인 · 선정기준"
        self.assertEqual(old[key],"6,494,738")
        self.assertEqual(new[key],"6,929,885")
        self.assertEqual(set(old),set(new))
