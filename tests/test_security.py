import io
import unittest
import zipfile
from unittest.mock import patch
from urllib.request import Request
from defusedxml.common import DefusedXmlException
from policy_domino.api import LawAPI, ApiError
from policy_domino.annexes import extract_hwpx_text, extract_hwpx_cells
from policy_domino.http_security import open_official, validate_url


class SecurityTests(unittest.TestCase):
    def test_law_api_rejects_xml_entities(self):
        xml = b'<!DOCTYPE r [<!ENTITY payload "expanded">]><r>&payload;</r>'
        api = LawAPI('test', transport=lambda _: xml)
        with self.assertRaises(ApiError):
            api.request('lawSearch.do', 'law')

    def test_hwpx_rejects_entities_in_text_and_cells(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('Contents/section0.xml',
                '<!DOCTYPE r [<!ENTITY p "expanded">]><r><t>&p;</t></r>')
        for extract in (extract_hwpx_text, extract_hwpx_cells):
            with self.subTest(extract=extract.__name__), self.assertRaises(DefusedXmlException):
                extract(buffer.getvalue())

    def test_unapproved_urls_rejected_before_transport(self):
        for url in ('file:///etc/passwd', 'http://www.law.go.kr/',
                    'https://evil.example/', 'https://www.law.go.kr.evil.example/',
                    'https://user:password@www.law.go.kr/', 'https://www.law.go.kr:8443/'):
            with self.subTest(url=url), patch('policy_domino.http_security.build_opener') as opener:
                with self.assertRaises(ValueError):
                    open_official(Request(url), allowed_hosts={'www.law.go.kr'}, timeout=1)
                opener.assert_not_called()
        validate_url('https://www.law.go.kr/DRF/lawSearch.do', {'www.law.go.kr'})

    def test_redirect_is_checked_before_following(self):
        with patch('policy_domino.http_security.build_opener') as opener:
            request = Request('https://www.law.go.kr/DRF/lawSearch.do')
            open_official(request, allowed_hosts={'www.law.go.kr'}, timeout=1)
            redirect = opener.call_args.args[0]
            with self.assertRaises(ValueError):
                redirect.redirect_request(request, None, 302, 'Found', {}, 'https://evil.example/')
