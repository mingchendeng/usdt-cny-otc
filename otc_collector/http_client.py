import json
import time
import urllib.error
import urllib.request


class ApiError(RuntimeError):
    pass


class HttpClient:
    """访问交易所公开盘口。请求之间留出间隔，遇到限流就退避重试。"""

    def __init__(self, delay: float = 0.6, timeout: float = 20, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0

    def get_json(self, url: str, headers: dict | None = None):
        return self._request("GET", url, None, headers)

    def post_json(self, url: str, payload: dict, headers: dict | None = None):
        return self._request("POST", url, payload, headers)

    def _request(self, method: str, url: str, payload: dict | None, headers: dict | None):
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._wait()
            try:
                return self._once(method, url, payload, headers)
            except ApiError as exc:
                last_error = exc
                message = str(exc)
                retryable = any(code in message for code in ("429", "500", "502", "503", "504"))
                if not retryable or attempt == self.retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise ApiError(str(last_error))

    def _wait(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _once(self, method: str, url: str, payload: dict | None, headers: dict | None):
        header_map = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if headers:
            header_map.update(headers)
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            header_map["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=header_map, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                detail = ""
            raise ApiError(f"HTTP {exc.code} {url} {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"网络错误 {url}: {exc.reason}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(f"响应不是 JSON: {url}") from exc
