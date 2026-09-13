#!/bin/sh
set -eu

# The project-owned Scout contract is immutable image content. Replace any
# stale or agent-modified home copy before the gateway starts, then remove the
# general-purpose base skills that are outside Scout's product scope.
mkdir -p /var/lib/hermes/skills
rm -rf \
  /var/lib/hermes/skills/scout \
  /var/lib/hermes/skills/growth \
  /var/lib/hermes/skills/productivity
cp -a /opt/hermes/skills/scout /var/lib/hermes/skills/scout
