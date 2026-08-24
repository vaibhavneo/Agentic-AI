#!/bin/sh
# Runs as root (the container's default user, so this script CAN chown) so
# that a runtime volume mounted at /app/memory — which arrives with its own
# ownership, not the image's baked-in brain:brain — gets fixed up before the
# app ever tries to write to it. The image-build chown in the Dockerfile
# only covers the image's own filesystem layer; a volume mounted at that
# same path at container start shadows it entirely. Then drops to the
# unprivileged `brain` user for the actual server process — nothing
# app-level ever runs as root, same intent the Dockerfile's own USER
# directive used to express before a real Railway volume made that
# insufficient on its own.
set -e
chown -R brain:brain /app/memory
exec su brain -s /bin/sh -c "python3 server.py"
