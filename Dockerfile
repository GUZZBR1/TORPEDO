# Current immutable Plow Hermes base. The tag names the source commit and the
# digest prevents registry-side substitution.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-8710797b6409c77df560c6198407765d138ea617@sha256:b9627febe57e34ec0df373709ad91a27a7fda68093e76d519678cac1012614f9

# plow-init composes this variant persona after the protected base persona on
# every boot. Never copy identity into the mutable Hermes home.
COPY --chown=0:0 runtime/persona.md /opt/hermes/plow-seed/persona.md
RUN chmod 0644 /opt/hermes/plow-seed/persona.md

# Keep the immutable bundled source outside the writable Hermes home. The base
# reconciles it into an empty or unmodified persistent home on boot.
COPY --chown=0:0 skills/scout/ /opt/hermes/skills/scout/
RUN find /opt/hermes/skills/scout -type d -exec chmod 0755 {} + \
 && find /opt/hermes/skills/scout -type f -name '*.py' -exec chmod 0755 {} + \
 && find /opt/hermes/skills/scout -type f ! -name '*.py' -exec chmod 0644 {} + \
 && /opt/hermes/.venv/bin/python3 -m compileall -q /opt/hermes/skills/scout/scripts

# The base image includes general-purpose productivity skills. Scout is a
# reconnaissance-only agent, so remove them from both the initial home and the
# bundled reconciliation source; Latch browser tools remain supplied by Hermes.
RUN rm -rf /var/lib/hermes/skills/growth /var/lib/hermes/skills/productivity \
 && rm -rf /opt/hermes/skills/growth /opt/hermes/skills/productivity

# Fetch the official Agent Index Client at a reviewed commit and verify the
# exact bytes before installing the root-owned unattended copy.
COPY vendor/client.pin /opt/plow/agent-index-client.pin
RUN set -eu; \
    sha="$(sed -n 's/^sha=//p' /opt/plow/agent-index-client.pin)"; \
    want="$(sed -n 's/^sha256=//p' /opt/plow/agent-index-client.pin)"; \
    path="$(sed -n 's/^path=//p' /opt/plow/agent-index-client.pin)"; \
    echo "$sha" | grep -Eq '^[0-9a-f]{40}$'; \
    curl -fsS --max-time 60 -o /opt/plow/agent-index-client.py \
      "https://raw.githubusercontent.com/plow-pbc/agent-index-client/${sha}/${path}"; \
    got="$(sha256sum /opt/plow/agent-index-client.py | cut -d' ' -f1)"; \
    [ "$got" = "$want" ] || { echo "agent-index client is $got, pin says $want" >&2; exit 1; }; \
    chmod 0644 /opt/plow/agent-index-client.py

COPY image/s6-overlay/ /etc/s6-overlay/
