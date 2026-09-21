"""Render the Asterisk config that depends on the deployment, from env.

The per-site facts live in env, not in committed ``.conf`` files: which softphones
exist, where the bank SBC is, the ARI and media-socket credentials. The same image
then serves the laptop softphone and a bank trunk, and a cutover is an env change.

Runs inside the Asterisk image (stdlib only) before ``asterisk -f``. ``render()`` is
pure so the tests can check the output without an Asterisk.

Env
---
Required:
  ASTERISK_ARI_USER, ASTERISK_ARI_PASSWORD      ARI account the controller uses.
  ASTERISK_WS_USER, ASTERISK_WS_PASSWORD        Basic auth on the media socket to voice.
Optional:
  ASTERISK_MEDIA_WS_URI       default ws://voice:7860/ws/asterisk
  ASTERISK_BOT_EXTENSION      what a softphone dials to reach the bot (default 1000)
  ASTERISK_SOFTPHONES         "1001:secret,1002:secret" -- endpoints named by extension
  ASTERISK_AGENT_EXTENSIONS   "1002" -- members of the collections-agents queue
  ASTERISK_EXTERNAL_IP        address phones on another network must send media to
  ASTERISK_LOCAL_NET          comma list of networks that reach this container
                              directly and so get its internal address; empty by
                              default (see _transport for why)
  ASTERISK_TRUNK_HOST         SBC address; no trunk is rendered without it
  ASTERISK_TRUNK_PORT         default 5060 (5061 for tls)
  ASTERISK_TRUNK_MATCH        comma list of source IPs/CIDRs allowed in; default the host
  ASTERISK_TRUNK_TRANSPORT    udp | tls (default udp)
  ASTERISK_TRUNK_SRTP         1 to require SDES-SRTP media
  ASTERISK_TLS_CERT, ASTERISK_TLS_KEY   TLS transport is rendered only when both exist
  ASTERISK_RTP_START, ASTERISK_RTP_END  default 10000-10050 (2 ports per call)
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

REQUIRED = ("ASTERISK_ARI_USER", "ASTERISK_ARI_PASSWORD", "ASTERISK_WS_USER", "ASTERISK_WS_PASSWORD")

#: The endpoint name the dial path uses for the carrier leg (``PJSIP/<n>@trunk``).
TRUNK_ENDPOINT = "trunk"


class ConfigError(ValueError):
    pass


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    return (env.get(key) or default).strip()


def _pairs(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in filter(None, (p.strip() for p in raw.split(","))):
        ext, sep, secret = item.partition(":")
        if not sep or not ext.isdigit() or not secret:
            raise ConfigError(f"ASTERISK_SOFTPHONES entry {item.split(':')[0]!r} must be <digits>:<password>")
        out.append((ext, secret))
    return out


def _list(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _transport(
    name: str, protocol: str, bind: str, external_ip: str, local_nets: list[str], extra: str = ""
) -> str:
    lines = [f"[{name}]", "type=transport", f"protocol={protocol}", f"bind={bind}"]
    if external_ip:
        # The address a peer outside this container must send to. Asterisk uses it
        # for every peer except those inside `local_net`, which is why local_net is
        # opt-in rather than "the RFC1918 ranges": on Docker Desktop a handset's SIP
        # arrives through the LAN relay and looks like it came from the Docker
        # gateway, so declaring 172.16.0.0/12 local made Asterisk advertise its own
        # container address (`c=IN IP4 172.19.x`) to a real phone. The phone then
        # sent its audio to an unroutable address and the bot heard silence while
        # its own audio arrived fine -- one-way audio that looks like a codec fault.
        lines += [
            f"external_media_address={external_ip}",
            f"external_signaling_address={external_ip}",
        ]
        lines += [f"local_net={net}" for net in local_nets]
    return "\n".join(lines) + extra + "\n"


def _pjsip(env: Mapping[str, str]) -> str:
    external_ip = _get(env, "ASTERISK_EXTERNAL_IP")
    local_nets = _list(_get(env, "ASTERISK_LOCAL_NET"))
    parts = [
        "; Rendered by render_config.py -- edit env, not this file.\n"
        "[global]\ntype=global\nuser_agent=Habibi-PBX\n"
        # ip is for the trunk only: softphone endpoints restrict identify_by below.
        "endpoint_identifier_order=username,auth_username,ip\n",
        _transport("transport-udp", "udp", "0.0.0.0:5060", external_ip, local_nets),
        _transport("transport-tcp", "tcp", "0.0.0.0:5060", external_ip, local_nets),
    ]
    cert, key = _get(env, "ASTERISK_TLS_CERT"), _get(env, "ASTERISK_TLS_KEY")
    tls = bool(cert and key and Path(cert).is_file() and Path(key).is_file())
    if tls:
        parts.append(
            _transport(
                "transport-tls",
                "tls",
                "0.0.0.0:5061",
                external_ip,
                local_nets,
                f"\ncert_file={cert}\npriv_key_file={key}\nmethod=tlsv1_2",
            )
        )

    for ext, secret in _pairs(_get(env, "ASTERISK_SOFTPHONES")):
        # Sections are named by the extension: the registrar looks up the AOR by
        # the To-user, and the username identifier matches the endpoint name.
        parts.append(
            f"[{ext}]\ntype=auth\nauth_type=userpass\nusername={ext}\npassword={secret}\n\n"
            f"[{ext}]\ntype=aor\nmax_contacts=1\nremove_existing=yes\nqualify_frequency=30\n\n"
            f"[{ext}]\ntype=endpoint\ncontext=from-internal\ndisallow=all\nallow=ulaw,alaw\n"
            f"auth={ext}\naors={ext}\nidentify_by=username,auth_username\ndirect_media=no\n"
            "rtp_symmetric=yes\nforce_rport=yes\nrewrite_contact=yes\ndtmf_mode=rfc4733\n"
        )

    host = _get(env, "ASTERISK_TRUNK_HOST")
    if host:
        transport = _get(env, "ASTERISK_TRUNK_TRANSPORT", "udp").lower()
        if transport not in ("udp", "tls"):
            raise ConfigError("ASTERISK_TRUNK_TRANSPORT must be udp or tls")
        if transport == "tls" and not tls:
            raise ConfigError("ASTERISK_TRUNK_TRANSPORT=tls needs ASTERISK_TLS_CERT and ASTERISK_TLS_KEY files")
        port = _get(env, "ASTERISK_TRUNK_PORT", "5061" if transport == "tls" else "5060")
        matches = _list(_get(env, "ASTERISK_TRUNK_MATCH")) or [host]
        if any(m.startswith("0.0.0.0") for m in matches):
            raise ConfigError("ASTERISK_TRUNK_MATCH must not allow 0.0.0.0/0")
        scheme = "sips" if transport == "tls" else "sip"
        endpoint = [
            f"[{TRUNK_ENDPOINT}]",
            "type=endpoint",
            f"transport=transport-{transport}",
            "context=from-trunk",
            "disallow=all",
            "allow=alaw,ulaw",
            f"aors={TRUNK_ENDPOINT}",
            "identify_by=ip",
            "direct_media=no",
            "rtp_symmetric=yes",
            "force_rport=yes",
            "rewrite_contact=yes",
            "dtmf_mode=rfc4733",
            # Caller ID from a number pool reaches the carrier as P-Asserted-Identity.
            "send_pai=yes",
            "trust_id_outbound=yes",
            "trust_id_inbound=yes",
        ]
        if _get(env, "ASTERISK_TRUNK_SRTP") in ("1", "true", "yes"):
            endpoint.append("media_encryption=sdes")
        parts.append("\n".join(endpoint) + "\n")
        parts.append(
            f"[{TRUNK_ENDPOINT}]\ntype=aor\ncontact={scheme}:{host}:{port}\nqualify_frequency=60\n"
        )
        parts.append(
            f"[{TRUNK_ENDPOINT}]\ntype=identify\nendpoint={TRUNK_ENDPOINT}\n"
            + "".join(f"match={m}\n" for m in matches)
        )
    return "\n".join(parts)


def _extensions(env: Mapping[str, str]) -> str:
    bot = _get(env, "ASTERISK_BOT_EXTENSION", "1000")
    if not bot.isdigit():
        raise ConfigError("ASTERISK_BOT_EXTENSION must be digits")
    # No Answer() here: the controller answers only once the bot's media socket is
    # up, so a caller never sits in answered silence.
    return (
        "; Rendered by render_config.py -- edit env, not this file.\n"
        "[from-internal]\n"
        f"exten => {bot},1,Stasis(habibi,inbound)\n"
        " same => n,Hangup()\n\n"
        "[from-trunk]\n"
        "exten => _X.,1,Stasis(habibi,inbound)\n"
        " same => n,Hangup()\n"
        "exten => _+X.,1,Stasis(habibi,inbound)\n"
        " same => n,Hangup()\n\n"
        "[agents]\n"
        "exten => collectors,1,Queue(collections-agents)\n"
        " same => n,Hangup()\n\n"
        "; The bot's media leg. The controller originates Local/bot@to-bot per call\n"
        "; and bridges it with the caller: a chan_websocket channel is not in ARI's\n"
        "; bridgeable channel registry, so only the dialplan can reach it. Dial comes\n"
        "; before any Answer, so this leg answering means the bot is on the socket --\n"
        "; which is when the controller answers the caller. HABIBI_CTX arrives as an\n"
        "; inherited (__) channel variable and reaches the bot in MEDIA_START.\n"
        "[to-bot]\n"
        "exten => bot,1,Dial(WebSocket/habibi_bot/c(slin16)f(json),30)\n"
        " same => n,Hangup()\n"
    )


def _queues(env: Mapping[str, str]) -> str:
    members = "".join(f"member => PJSIP/{ext}\n" for ext in _list(_get(env, "ASTERISK_AGENT_EXTENSIONS")))
    return (
        "[general]\npersistentmembers = no\n\n"
        "[collections-agents]\nstrategy = ringall\ntimeout = 25\nretry = 5\nwrapuptime = 10\n"
        # Never park a caller in a queue nobody can answer.
        "ringinuse = no\njoinempty = unavailable,invalid,unknown\nleavewhenempty = unavailable,invalid,unknown\n"
        + members
    )


def _ari(env: Mapping[str, str]) -> str:
    return (
        "[general]\nenabled = yes\npretty = no\n\n"
        f"[{_get(env, 'ASTERISK_ARI_USER')}]\ntype = user\nread_only = no\n"
        f"password = {_get(env, 'ASTERISK_ARI_PASSWORD')}\npassword_format = plain\n"
    )


def _websocket_client(env: Mapping[str, str]) -> str:
    uri = _get(env, "ASTERISK_MEDIA_WS_URI", "ws://voice:7860/ws/asterisk")
    return (
        "[habibi_bot]\ntype = websocket_client\n"
        f"uri = {uri}\n"
        # One socket per call, dialled with the per-call options ARI passes.
        "connection_type = per_call_config\n"
        "protocols = media\n"
        f"username = {_get(env, 'ASTERISK_WS_USER')}\n"
        f"password = {_get(env, 'ASTERISK_WS_PASSWORD')}\n"
        f"tls_enabled = {'yes' if uri.startswith('wss://') else 'no'}\n"
    )


def _rtp(env: Mapping[str, str]) -> str:
    start, end = _get(env, "ASTERISK_RTP_START", "10000"), _get(env, "ASTERISK_RTP_END", "10050")
    if not (start.isdigit() and end.isdigit() and int(start) < int(end)):
        raise ConfigError("ASTERISK_RTP_START must be below ASTERISK_RTP_END")
    return f"[general]\nrtpstart={start}\nrtpend={end}\nstrictrtp=yes\n"


def render(env: Mapping[str, str]) -> dict[str, str]:
    missing = [k for k in REQUIRED if not _get(env, k)]
    if missing:
        raise ConfigError("missing required env: " + ", ".join(missing))
    return {
        "pjsip.conf": _pjsip(env),
        "extensions.conf": _extensions(env),
        "queues.conf": _queues(env),
        "ari.conf": _ari(env),
        "websocket_client.conf": _websocket_client(env),
        "rtp.conf": _rtp(env),
    }


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/asterisk")
    try:
        files = render(os.environ)
    except ConfigError as exc:
        sys.exit(f"render_config: {exc}")
    for name, body in files.items():
        (target / name).write_text(body, encoding="utf-8")
    print("render_config: wrote " + ", ".join(sorted(files)), flush=True)


if __name__ == "__main__":
    main()
