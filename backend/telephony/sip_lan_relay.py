"""Forward SIP on the Windows LAN/hotspot into Docker's localhost publish.

Docker Desktop does not deliver LAN SIP into the container, so the Asterisk
overlay publishes 5060 on localhost only and this process binds 0.0.0.0:5060 and
relays UDP/TCP to it. Laptop staging only; a bank VM runs Asterisk on the host
network and needs none of this.

    python telephony/sip_lan_relay.py

Windows Firewall must allow inbound UDP 5060 for this python.exe on the profile
the phone's network uses (a hotspot is usually Public, office Wi-Fi Private).
See telephony/README.md.
"""

from __future__ import annotations

import asyncio
import socket
import sys

UPSTREAM = ("127.0.0.1", 15060)
LISTEN_PORT = 5060

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _tcp_pipe(a: asyncio.StreamReader, b: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await a.read(65536)
            if not data:
                break
            b.write(data)
            await b.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            b.close()
        except Exception:
            pass


async def _tcp_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    peer = writer.get_extra_info("peername")
    print(f"sip-relay tcp from {peer}", flush=True)
    try:
        up_reader, up_writer = await asyncio.open_connection(*UPSTREAM)
    except Exception as exc:
        print(f"sip-relay tcp upstream failed: {exc}", flush=True)
        writer.close()
        return
    t1 = asyncio.create_task(_tcp_pipe(reader, up_writer))
    t2 = asyncio.create_task(_tcp_pipe(up_reader, writer))
    await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    t1.cancel()
    t2.cancel()


class _UdpProtocol(asyncio.DatagramProtocol):
    """Forward each phone's SIP through its own upstream socket.

    One socket for everyone meant Asterisk's replies went to whichever phone had
    sent last: a second handset silently stole the first one's registration and
    calls. Asterisk sees one source port per phone, which is also what makes its
    rewritten Contact route back correctly.
    """

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        #: client address -> socket this relay talks to Asterisk with for it
        self._upstream: dict[tuple[str, int], socket.socket] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def _socket_for(self, client: tuple[str, int]) -> socket.socket:
        sock = self._upstream.get(client)
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            sock.setblocking(False)
            self._upstream[client] = sock
            asyncio.get_running_loop().add_reader(
                sock.fileno(), lambda s=sock, c=client: self._on_upstream(s, c)
            )
            print(f"sip-relay udp: new phone {client[0]}:{client[1]}", flush=True)
        return sock

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] == "0.0.0.0":
            return
        self._socket_for(addr).sendto(data, UPSTREAM)

    def _on_upstream(self, sock: socket.socket, client: tuple[str, int]) -> None:
        if self.transport is None:
            return
        try:
            data, _from = sock.recvfrom(65535)
        except BlockingIOError:
            return
        self.transport.sendto(data, client)


def _host_addresses() -> list[str]:
    """The addresses a phone could register to, so the operator can pick one."""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    except OSError:
        return []


async def main() -> None:
    loop = asyncio.get_running_loop()
    tcp = await asyncio.start_server(_tcp_client, "0.0.0.0", LISTEN_PORT)
    await loop.create_datagram_endpoint(_UdpProtocol, local_addr=("0.0.0.0", LISTEN_PORT))
    print(
        f"sip-relay listening 0.0.0.0:{LISTEN_PORT} -> {UPSTREAM[0]}:{UPSTREAM[1]}\n"
        f"  point the softphone at one of: {', '.join(_host_addresses()) or 'this host'}\n"
        "  and set ASTERISK_EXTERNAL_IP to the same address",
        flush=True,
    )
    async with tcp:
        await tcp.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
