#!/bin/sh
set -eu
# The base image declares /var/spool/asterisk and /var/log/asterisk as volumes, so
# directories created at build time are masked by whatever volume is mounted (and
# a volume carried over from an older container keeps its old contents). Create
# them here, every start: without them ARI bridge recording answers 500 and
# cdr_csv logs an error on every call.
mkdir -p /var/spool/asterisk/recording /var/log/asterisk/cdr-csv
chown -R asterisk:asterisk /var/spool/asterisk /var/log/asterisk 2>/dev/null || true

# Per-site config (softphones, trunk, credentials) comes from env; see render_config.py.
python3 /usr/local/bin/render_config.py /etc/asterisk
exec asterisk -f -vvv
