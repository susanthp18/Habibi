# Asterisk 23.x: JSON control (`f(json)`) and chan_websocket. The andrius 22.x
# images omit chan_websocket, so this is 23.4.1. Digest pin; never :latest.
FROM andrius/asterisk:23.4.1_debian-trixie@sha256:dc68d293ee48f512516c5b968a2289465d9817a6851a00b1540d71847ea3f583

USER root
COPY asterisk/*.conf /etc/asterisk/
COPY render_config.py /usr/local/bin/render_config.py
COPY asterisk/entrypoint.sh /entrypoint.sh
# The spool and log directories are volumes in the base image, so their
# subdirectories are created by the entrypoint at start: a mkdir here would be
# masked by the mount (and by a volume carried over from an older container).
RUN chmod +x /entrypoint.sh \
    && sed -i 's/\r$//' /entrypoint.sh /usr/local/bin/render_config.py \
    && find /etc/asterisk -name '*.conf' -exec sed -i 's/\r$//' {} \; \
    && chown -R asterisk:asterisk /etc/asterisk

EXPOSE 5060/udp 5060/tcp 5061/tcp 10000-10050/udp
ENTRYPOINT ["/entrypoint.sh"]
