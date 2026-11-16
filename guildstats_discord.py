import json
import re
from html import unescape

import requests


WEBHOOK_URL_PATTERN = re.compile(
    r"https?://discord(?:app)?\.com/api/webhooks/\d+/[^\s\"'<>]+",
    re.IGNORECASE,
)


def _safe_response_detail(response_body):
    text = response_body.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]*>", " ", text)
    text = unescape(text)
    text = WEBHOOK_URL_PATTERN.sub("[webhook URL ukryty]", text)
    text = " ".join(text.split())
    return text[:240]


def post_report(report, webhook_url):
    try:
        response = requests.post(
            webhook_url,
            json={"content": report, "allowed_mentions": {"parse": []}},
            timeout=15,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            f"Nie udalo sie polaczyc z Discordem ({type(error).__name__}). "
            "URL webhooka nie zostal wyswietlony."
        ) from None

    if response.status_code in (200, 204):
        return

    response_body = response.content
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None

    detail = ""
    if isinstance(payload, dict):
        message = payload.get("message")
        code = payload.get("code")
        if isinstance(message, str):
            detail = message
        if isinstance(code, int):
            detail = f"{detail} (kod Discorda: {code})".strip()

    if not detail:
        content_type = response.headers.get("Content-Type", "brak")
        server = response.headers.get("Server", "nieznany")
        body_detail = _safe_response_detail(response_body)
        detail = (
            f"odpowiedz nie zawiera kodu bledu Discorda; "
            f"serwer={server}, Content-Type={content_type}"
        )
        if body_detail:
            detail += f"; odpowiedz={body_detail}"

    if response.status_code == 403 and "error code: 1010" in response_body.decode(
        "utf-8", errors="replace"
    ).lower():
        hint = (
            "Cloudflare odrzuca to polaczenie sieciowe (kod 1010); "
            "to nie wskazuje na bledny token webhooka. Sprobuj bez VPN "
            "lub proxy albo z innej sieci. Jesli problem wystepuje w "
            "roznych sieciach, skontaktuj sie z pomoca Discorda."
        )
    elif response.status_code == 403:
        hint = (
            "Sprawdz szczegol odpowiedzi. Jesli serwer korzysta z "
            "Cloudflare, problem moze dotyczyc sieci lub klienta, a "
            "nie samego webhooka."
        )
    elif response.status_code in (401, 404):
        hint = (
            "Sprawdz, czy wklejono caly URL aktywnego webhooka; "
            "usuniety webhook trzeba utworzyc ponownie."
        )
    else:
        hint = "Discord odrzucil wysylke raportu."

    description = f"Discord odrzucil webhook (HTTP {response.status_code}"
    if detail:
        description += f": {detail}"
    description += f"). {hint}"
    raise RuntimeError(description)
