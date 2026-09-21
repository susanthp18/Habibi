"""pjsip.conf for the e2e test phones, from the PBX's own ASTERISK_SOFTPHONES.

Each extension registers to the PBX under test with the credentials the PBX was
rendered with, so the harness cannot drift from the site config. Calls the PBX
places to any of them arrive on one ``pbx-in`` endpoint (identified by the PBX's
address) and the dialplan dispatches on the dialled extension.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

pbx = os.environ.get("PHONES_PBX_HOST", "asterisk")
pbx_ip = socket.gethostbyname(pbx)
extensions = [
    item.split(":", 1) for item in (p.strip() for p in os.environ["ASTERISK_SOFTPHONES"].split(",")) if item
]

out = [
    "[global]\ntype=global\nuser_agent=Habibi-E2E-Phone\n",
    "[t-udp]\ntype=transport\nprotocol=udp\nbind=0.0.0.0:5060\n",
    f"[pbx-in]\ntype=endpoint\ntransport=t-udp\ncontext=incoming\ndisallow=all\nallow=ulaw\n"
    "direct_media=no\nrtp_symmetric=yes\ndtmf_mode=rfc4733\n",
    f"[pbx-in]\ntype=identify\nendpoint=pbx-in\nmatch={pbx_ip}\n",
]
for ext, secret in extensions:
    out.append(
        f"[{ext}-auth]\ntype=auth\nauth_type=userpass\nusername={ext}\npassword={secret}\n\n"
        f"[pbx-{ext}]\ntype=aor\ncontact=sip:{pbx_ip}:5060\n\n"
        f"[pbx-{ext}]\ntype=endpoint\ntransport=t-udp\ncontext=incoming\ndisallow=all\nallow=ulaw\n"
        f"outbound_auth={ext}-auth\naors=pbx-{ext}\nfrom_user={ext}\ncallerid=\"{ext}\" <{ext}>\n"
        "direct_media=no\nrtp_symmetric=yes\ndtmf_mode=rfc4733\nidentify_by=username\n\n"
        f"[reg-{ext}]\ntype=registration\ntransport=t-udp\noutbound_auth={ext}-auth\n"
        f"server_uri=sip:{pbx_ip}:5060\nclient_uri=sip:{ext}@{pbx_ip}:5060\ncontact_user={ext}\n"
        "retry_interval=5\nexpiration=120\n"
    )
Path("/etc/asterisk/pjsip.conf").write_text("\n".join(out))
print("render_phones: " + ", ".join(ext for ext, _ in extensions), flush=True)
