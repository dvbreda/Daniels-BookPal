# Claude Code in een container, om op de NAS aan BookPal te werken.
#
# Bewust een aparte container: dan hoef je niets op UGOS zelf te installeren en
# blijft alles opruimbaar met één `docker rm`.
FROM node:22-slim

# git en ripgrep gebruikt Claude Code zelf; de rest is nodig om BookPal in
# dezelfde container te kunnen draaien en testen.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        ripgrep \
        less \
        python3 \
        python3-venv \
        python3-pip \
        libarchive13 \
        libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

# De npm-installatie haalt hetzelfde binaire bestand op als het installatie-
# script; op een N100 (x86_64) is dat linux-x64.
RUN npm install -g @anthropic-ai/claude-code

# Niet als root werken. UID 1000 komt meestal overeen met de eerste UGOS-
# gebruiker, zodat bestanden die Claude aanmaakt van jou blijven.
ARG UID=1000
ARG GID=1000
RUN groupmod -g ${GID} node 2>/dev/null || true; \
    usermod -u ${UID} -g ${GID} node 2>/dev/null || true; \
    mkdir -p /home/node/.claude /workspace && chown -R ${UID}:${GID} /home/node /workspace
USER node

ENV HOME=/home/node
WORKDIR /workspace

# Blijft draaien zodat je er met `docker exec -it` in kunt.
CMD ["sleep", "infinity"]
