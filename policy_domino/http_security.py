"""HTTPS requests restricted to caller-owned official hosts, including redirects."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


def validate_url(url, allowed_hosts):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ValueError("URL is not an approved HTTPS endpoint")
    return url


def open_official(request, *, allowed_hosts, timeout):
    validate_url(request.full_url, allowed_hosts)

    class OfficialRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate_url(newurl, allowed_hosts)
            # Credentials and request bodies must not cross origins.
            if urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
                raise ValueError("Cross-host redirect is not permitted")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return build_opener(OfficialRedirect()).open(request, timeout=timeout)
